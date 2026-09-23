"""SQLite 写事务（`BEGIN IMMEDIATE`）——团体赛各写操作共用的唯一实现。

## 为什么需要它

SQLite 的"先 SELECT 判断、再无条件写入"不是原子操作：FastAPI 每个请求使用**独立连接**，
两个并发请求可以同时通过校验，然后依次写入，从而绕过"已经存在就不能再建"这类业务守卫。
`BEGIN IMMEDIATE` 会在事务开始时就取到**写锁**，因此：

1. 读-判断-写整体被放进同一个写事务 → 同一个 TeamTie 的并发请求被串行化；
2. 后来者拿到锁时读到的是前一个请求**已提交**的状态，业务守卫因此一定能命中；
3. 拿不到锁（另一个请求正在处理）时返回可读的 409，而不是把 SQLite 的错误漏成 500。

## 为什么是独立模块

原先 `team_runtime._write_tx`、`teams._roster_write_tx` 各自实现了一份同样的语义
（当时为了避免循环依赖而刻意重复）。本模块把这份语义收敛成**唯一实现**：
`team_runtime` 与 `team_ties` 都复用它，后来者不需要再抄第三份。

调用方通过 `busy_message` 给出面向用户的文案（各业务措辞不同），异常类型由调用方
自己映射：本模块只抛 `TransactionBusyError`，不 import 任何业务异常，因此不会产生
`services` 包内的循环依赖。
"""

import sqlite3
from contextlib import contextmanager
from typing import Iterator
from uuid import uuid4

#: 锁等待超时的默认文案（调用方一般会传自己的 `busy_message`）。
DEFAULT_BUSY_MESSAGE = "该资源正在被另一个请求处理，请稍后重试"


class TransactionBusyError(RuntimeError):
    """写事务无法开始或提交：另一个请求正在处理同一资源。

    `code` 预置为 409（业务冲突），调用方转成自己的业务异常时保持这个语义，
    绝不能漏成 500。
    """

    def __init__(self, message: str, code: int = 409):
        super().__init__(message)
        self.code = code


@contextmanager
def write_transaction(
    conn: sqlite3.Connection,
    *,
    busy_message: str = DEFAULT_BUSY_MESSAGE,
    conflict_message: str | None = None,
) -> Iterator[None]:
    """把一次"读-判断-写"整体放进写事务。

    - 干净连接使用 `BEGIN IMMEDIATE` 立刻取写锁，把同一资源的并发请求串行化；
    - 已处于外部事务时改用 SAVEPOINT，保证内部失败可回滚且不替外部提前提交；
    - 事务体内任何异常都回滚到进入点（不留半成品状态）；
    - 提交失败同样 `rollback` 并按 409 冲突报告。
    """
    if conn.in_transaction:
        savepoint = f"d6a_write_{uuid4().hex}"
        conn.execute(f'SAVEPOINT "{savepoint}"')
        try:
            yield
        except BaseException:
            try:
                conn.execute(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
            finally:
                conn.execute(f'RELEASE SAVEPOINT "{savepoint}"')
            raise
        conn.execute(f'RELEASE SAVEPOINT "{savepoint}"')
        return

    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise TransactionBusyError(f"{busy_message}（{exc}）") from None
        # 例如表缺失、SQL 语法错误等属于真实内部错误，不能被伪装成业务冲突。
        raise

    try:
        yield
    except BaseException:
        conn.rollback()
        raise

    try:
        conn.commit()
    except sqlite3.OperationalError as exc:
        conn.rollback()
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            hint = conflict_message or busy_message
            raise TransactionBusyError(f"{hint}（{exc}）") from None
        # commit 阶段的非锁错误也必须回滚，但不应被调用方映射成 409。
        raise
