"""枚举定义测试：状态 code 明确、前后端一致、无中文字符串散落。"""

from app.models import (
    MatchStage,
    MatchStatus,
    TableStatus,
    TournamentStage,
)


def test_match_status_codes():
    assert MatchStatus.WAITING.value == "WAITING"
    assert MatchStatus.PLAYING.value == "PLAYING"
    assert MatchStatus.FINISHED.value == "FINISHED"
    # 三个状态互不相同
    assert len({s.value for s in MatchStatus}) == 3


def test_table_status_codes():
    assert TableStatus.FREE.value == "FREE"
    assert TableStatus.OCCUPIED.value == "OCCUPIED"


def test_tournament_stage_codes():
    assert TournamentStage.REGISTRATION.value == "REGISTRATION"
    assert TournamentStage.GROUP_STAGE.value == "GROUP_STAGE"
    assert TournamentStage.KNOCKOUT.value == "KNOCKOUT"
    assert TournamentStage.FINISHED.value == "FINISHED"


def test_match_stage_codes():
    assert MatchStage.GROUP.value == "GROUP"
    assert MatchStage.KNOCKOUT.value == "KNOCKOUT"


def test_enums_serialize_to_plain_strings():
    """FastAPI 返回 JSON 时，str-Enum 应序列化为普通字符串 code。"""
    for enum_cls in (MatchStatus, TableStatus, TournamentStage, MatchStage):
        for member in enum_cls:
            assert isinstance(member.value, str)
            assert member.value.isupper()
