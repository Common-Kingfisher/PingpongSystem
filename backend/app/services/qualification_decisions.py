"""主裁判人工晋级裁定：只解决晋级线仍并列的剩余席位，并保留审计历史。"""

import json
import sqlite3

from .. import repository as repo
from . import rankings as rankings_service
from .transaction import TransactionBusyError, write_transaction


class QualificationDecisionError(Exception):
    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


def _ensure_group(conn: sqlite3.Connection, tournament_id: int, group_id: int) -> dict:
    tournament = repo.get_tournament(conn, tournament_id)
    group = repo.get_group(conn, group_id)
    if tournament is None or group is None or group["tournament_id"] != tournament_id:
        raise QualificationDecisionError("小组不存在", 404)
    return tournament


def _out(row: dict) -> dict:
    return {
        "id": row["id"],
        "tournament_id": row["tournament_id"],
        "group_id": row["group_id"],
        "selected_entry_ids": json.loads(row["selected_entry_ids"]),
        "reason": row["reason"],
        "operator_name": row["operator_name"],
        "created_at": row["created_at"],
        "invalidated_at": row["invalidated_at"],
        "invalidation_reason": row["invalidation_reason"],
        "active": row["invalidated_at"] is None,
    }


def _create_decision_locked(
    conn: sqlite3.Connection,
    tournament_id: int,
    group_id: int,
    selected_entry_ids: list[int],
    reason: str,
    operator_name: str,
) -> dict:
    tournament = _ensure_group(conn, tournament_id, group_id)
    if tournament["stage"] != "GROUP_STAGE":
        raise QualificationDecisionError("只有小组赛阶段可以进行人工晋级裁定")
    reason = reason.strip()
    operator_name = operator_name.strip()
    if len(reason) < 2 or not operator_name:
        raise QualificationDecisionError("请填写裁定理由和操作者姓名", 422)

    rankings = rankings_service.get_rankings(conn, tournament_id, include_decisions=False)
    group = next(item for item in rankings if item["group_id"] == group_id)
    if group["finished_matches"] < group["total_matches"]:
        raise QualificationDecisionError("小组赛尚未全部结束，不能人工指定晋级")
    if group["needs_point_scores"]:
        raise QualificationDecisionError("仍有相关小比分可以补录，请先完成小比分判定")
    if not group["ambiguous_qualification"]:
        raise QualificationDecisionError("当前晋级名单已经可以自动确定，无需人工裁定")

    selected = list(dict.fromkeys(selected_entry_ids))
    candidates = set(group["manual_candidate_entry_ids"])
    remaining = group["manual_slots_remaining"]
    if len(selected) != remaining:
        raise QualificationDecisionError(f"必须选择 {remaining} 个晋级参赛位", 422)
    if not set(selected).issubset(candidates):
        raise QualificationDecisionError("只能从晋级线并列的参赛位中选择", 422)

    repo.invalidate_qualification_decision(
        conn, group_id, f"由 {operator_name} 的新裁定替代"
    )
    row = repo.create_qualification_decision(
        conn,
        tournament_id,
        group_id,
        json.dumps(sorted(selected), separators=(",", ":")),
        rankings_service.qualification_snapshot(group),
        reason,
        operator_name,
    )
    return _out(row)


def _revoke_decision_locked(
    conn: sqlite3.Connection,
    tournament_id: int,
    group_id: int,
    reason: str,
    operator_name: str,
) -> dict:
    tournament = _ensure_group(conn, tournament_id, group_id)
    if tournament["stage"] != "GROUP_STAGE":
        raise QualificationDecisionError(
            "淘汰赛签表已经生成，当前版本不支持撤销该裁定；请在生成签表前完成更正，或联系管理员处理"
        )
    active = repo.get_active_qualification_decision(conn, group_id)
    if active is None:
        raise QualificationDecisionError("当前没有生效中的人工晋级裁定", 404)
    reason = reason.strip()
    operator_name = operator_name.strip()
    if len(reason) < 2 or not operator_name:
        raise QualificationDecisionError("请填写撤销理由和操作者姓名", 422)
    repo.invalidate_qualification_decision(
        conn, group_id, f"由 {operator_name} 撤销：{reason}"
    )
    return _out(repo.get_qualification_decision(conn, active["id"]))


def list_decisions(
    conn: sqlite3.Connection, tournament_id: int, group_id: int
) -> list[dict]:
    _ensure_group(conn, tournament_id, group_id)
    return [_out(row) for row in repo.list_qualification_decisions(conn, group_id)]

def create_decision(
    conn: sqlite3.Connection,
    tournament_id: int,
    group_id: int,
    selected_entry_ids: list[int],
    reason: str,
    operator_name: str,
) -> dict:
    """排名快照、旧裁定失效与新裁定写入使用同一写锁。"""
    try:
        with write_transaction(conn, busy_message="晋级裁定繁忙，请稍后重试"):
            return _create_decision_locked(
                conn,
                tournament_id,
                group_id,
                selected_entry_ids,
                reason,
                operator_name,
            )
    except TransactionBusyError as exc:
        raise QualificationDecisionError(str(exc), exc.code) from None


def revoke_decision(
    conn: sqlite3.Connection,
    tournament_id: int,
    group_id: int,
    reason: str,
    operator_name: str,
) -> dict:
    """重读生效裁定后原子撤销，避免重复撤销或覆盖新裁定。"""
    try:
        with write_transaction(conn, busy_message="撤销裁定繁忙，请稍后重试"):
            return _revoke_decision_locked(
                conn, tournament_id, group_id, reason, operator_name
            )
    except TransactionBusyError as exc:
        raise QualificationDecisionError(str(exc), exc.code) from None
