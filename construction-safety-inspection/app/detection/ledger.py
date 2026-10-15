"""违规台账：SQLite 持久化 + 统计查询。

表结构 violation(id, ts, source, helmet_off, helmet_on, conf_min, severity)
所有写操作带参数化 SQL，接口线程安全（SQLite 连接按调用创建）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.detection.rules import Violation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS violation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    source     TEXT    NOT NULL,
    helmet_off INTEGER NOT NULL,
    helmet_on  INTEGER NOT NULL,
    conf_min   REAL    NOT NULL,
    severity   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_violation_ts ON violation(ts);
"""


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else config.LEDGER_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """初始化表结构（幂等）。"""
    conn = _connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def insert_violation(v: Violation, db_path: Optional[Path] = None) -> int:
    """写入一条违规记录，返回自增 id。"""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO violation(ts, source, helmet_off, helmet_on, conf_min, severity) "
            "VALUES(?,?,?,?,?,?)",
            v.to_row(),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_violations(limit: int = 200, db_path: Optional[Path] = None) -> list[dict]:
    """按时间倒序列出违规记录。"""
    conn = _connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM violation ORDER BY ts DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats(db_path: Optional[Path] = None) -> dict:
    """台账统计：总次数、总人次、严重次数、最近一次时间。"""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) cnt, IFNULL(SUM(helmet_off),0) persons, "
            "SUM(CASE WHEN severity='严重' THEN 1 ELSE 0 END) severe, "
            "MAX(ts) latest FROM violation"
        ).fetchone()
        return {
            "count": row[0] or 0,
            "persons": row[1] or 0,
            "severe": row[2] or 0,
            "latest": row[3],
        }
    finally:
        conn.close()


def clear(db_path: Optional[Path] = None) -> int:
    """清空台账（演示前重置用），返回删除条数。"""
    conn = _connect(db_path)
    try:
        cur = conn.execute("DELETE FROM violation")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
