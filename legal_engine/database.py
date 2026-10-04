"""
SQLite Database Layer (ฐานข้อมูลตัวบทกฎหมายและประวัติการวิเคราะห์)
- statutes: คลังตัวบทกฎหมาย (seed จาก knowledge_base.py ครั้งแรก)
- analyses: ประวัติผลการวิเคราะห์ข้อเท็จจริง
"""

import os
import re
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .knowledge_base import LEGAL_STATUTES

import shutil

_DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "legal_ai.db"
)

def _get_db_path() -> str:
    env_path = os.environ.get("LEGAL_AI_DB")
    if env_path:
        return env_path
    if os.environ.get("VERCEL"):
        tmp_db = "/tmp/legal_ai.db"
        if not os.path.exists(tmp_db) and os.path.exists(_DEFAULT_DB_PATH):
            shutil.copy2(_DEFAULT_DB_PATH, tmp_db)
            # ไม่นำประวัติคำถามจากเครื่องที่พัฒนาขึ้นไปกับ deploy
            with sqlite3.connect(tmp_db) as conn:
                conn.execute("DELETE FROM analyses")
        return tmp_db
    return _DEFAULT_DB_PATH

DB_PATH = _get_db_path()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS statutes (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    book        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL,
    section     TEXT NOT NULL,
    content     TEXT NOT NULL,
    keywords    TEXT NOT NULL DEFAULT '[]',
    elements    TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'active',   -- active | repealed
    source      TEXT NOT NULL DEFAULT 'manual',   -- ไฟล์ต้นทาง เช่น code_lawyer.pdf
    source_page INTEGER,
    sort_key    TEXT NOT NULL DEFAULT '',         -- ใช้เรียงลำดับมาตรา (รองรับ /1 และ ทวิ)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_statutes_category ON statutes(category);

CREATE TABLE IF NOT EXISTS analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    facts               TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT,
    status              TEXT NOT NULL,
    faithfulness_score  REAL,
    statutes_cited      TEXT NOT NULL DEFAULT '[]',
    result              TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at);

-- ความคิดเห็นผู้ใช้ (ใช้เมื่อรันบนเครื่อง; บน Vercel เก็บใน Google Sheet — ดู legal_engine/feedback.py)
CREATE TABLE IF NOT EXISTS feedback (
    id             TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    type           TEXT NOT NULL,          -- answer | site | statute
    rating         INTEGER,                -- answer: 1/-1, site: 1-5, statute: NULL
    comment        TEXT NOT NULL DEFAULT '',
    nickname       TEXT NOT NULL DEFAULT '',
    question       TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    answer_status  TEXT NOT NULL DEFAULT '',
    section        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);
"""

FEEDBACK_COLUMNS = ("id", "created_at", "type", "rating", "comment", "nickname",
                    "question", "model", "answer_status", "section")

_STATUTE_FIELDS = ("id", "category", "book", "title", "section", "content", "keywords", "elements", "status")

# คอลัมน์ที่เพิ่มภายหลัง: เติมให้ฐานข้อมูลเก่าที่สร้างก่อนมีคอลัมน์เหล่านี้
_ADDED_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "source": "TEXT NOT NULL DEFAULT 'manual'",
    "source_page": "INTEGER",
    "sort_key": "TEXT NOT NULL DEFAULT ''",
}


def section_sort_key(section: str) -> str:
    """'มาตรา 1264/1' -> '01264.0001.0' ให้เรียงแบบข้อความได้ถูกลำดับ (ทวิ/ตรี ต่อท้ายเป็นลำดับ)"""
    m = re.search(r"(\d+)(?:\s*/\s*(\d+))?\s*(ทวิ|ตรี|จัตวา|เบญจ|ฉ|สัตต|อัฏฐ|นว)?", section)
    if not m:
        return section
    suffix = ["", "ทวิ", "ตรี", "จัตวา", "เบญจ", "ฉ", "สัตต", "อัฏฐ", "นว"].index(m.group(3) or "")
    return f"{int(m.group(1)):05d}.{int(m.group(2) or 0):04d}.{suffix}"


def _curated_statutes() -> List[Dict[str, Any]]:
    """
    ตัวบทที่เขียนด้วยมือใน knowledge_base.py เท่านั้น
    (ไม่รวมรายการที่ knowledge_base.py โหลดต่อท้ายจาก statutes_ccc.json ซึ่งเลิกใช้แล้ว)
    """
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statutes_ccc.json")
    legacy = {}
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            legacy = {s["id"]: s for s in json.load(f)}
    return [s for s in LEGAL_STATUTES if legacy.get(s["id"]) != s]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """
    สร้างตาราง และ seed ตัวบทที่เขียนด้วยมือหากตารางยังว่าง
    ประมวลกฎหมายแพ่งฯ ฉบับเต็มนำเข้าจาก PDF ด้วย ingest_pdf.py
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(statutes)")}
        for col, ddl in _ADDED_COLUMNS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE statutes ADD COLUMN {col} {ddl}")
        for row in conn.execute("SELECT id, section FROM statutes WHERE sort_key = ''").fetchall():
            conn.execute("UPDATE statutes SET sort_key = ? WHERE id = ?", (section_sort_key(row["section"]), row["id"]))

        count = conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
        if count == 0:
            upsert_statutes(conn, [dict(s, source="manual (knowledge_base.py)") for s in _curated_statutes()])


def upsert_statutes(conn: sqlite3.Connection, statutes: List[Dict[str, Any]]) -> None:
    """เพิ่มหรือแทนที่ตัวบทหลายรายการในทรานแซกชันของผู้เรียก (คง created_at เดิมไว้)"""
    now = _now()
    conn.executemany(
        """INSERT INTO statutes (id, category, book, title, section, content, keywords, elements,
                                 status, source, source_page, sort_key, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               category = excluded.category, book = excluded.book, title = excluded.title,
               section = excluded.section, content = excluded.content, keywords = excluded.keywords,
               elements = excluded.elements, status = excluded.status, source = excluded.source,
               source_page = excluded.source_page, sort_key = excluded.sort_key,
               updated_at = excluded.updated_at""",
        [
            (
                s["id"], s["category"], s.get("book", ""), s["title"], s["section"], s["content"],
                json.dumps(s.get("keywords", []), ensure_ascii=False),
                json.dumps(s.get("elements", []), ensure_ascii=False),
                s.get("status", "active"), s.get("source", "manual"), s.get("source_page"),
                section_sort_key(s["section"]), now, now,
            )
            for s in statutes
        ],
    )


# ---------------- Statutes ----------------

def _row_to_statute(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["keywords"] = json.loads(d["keywords"])
    d["elements"] = json.loads(d["elements"])
    return d


def list_statutes(category: Optional[str] = None, q: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM statutes WHERE 1=1"
    params: List[Any] = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if q:
        like = f"%{q}%"
        sql += " AND (section LIKE ? OR title LIKE ? OR content LIKE ? OR keywords LIKE ?)"
        params.extend([like, like, like, like])
    sql += " ORDER BY category, sort_key"
    with get_conn() as conn:
        return [_row_to_statute(r) for r in conn.execute(sql, params).fetchall()]


def get_statute(statute_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM statutes WHERE id = ?", (statute_id,)).fetchone()
        return _row_to_statute(row) if row else None


def create_statute(data: Dict[str, Any]) -> Dict[str, Any]:
    """สร้างตัวบทใหม่ - raise sqlite3.IntegrityError หาก id ซ้ำ"""
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO statutes (id, category, book, title, section, content, keywords, elements,
                                     status, source, sort_key, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["id"], data["category"], data.get("book", ""), data["title"], data["section"], data["content"],
                json.dumps(data.get("keywords", []), ensure_ascii=False),
                json.dumps(data.get("elements", []), ensure_ascii=False),
                data.get("status", "active"), "manual (API)", section_sort_key(data["section"]),
                now, now,
            ),
        )
    return get_statute(data["id"])


def update_statute(statute_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """อัปเดตเฉพาะฟิลด์ที่ส่งมา (partial update)"""
    fields = {k: v for k, v in data.items() if k in _STATUTE_FIELDS and k != "id" and v is not None}
    if not fields:
        return get_statute(statute_id)
    for k in ("keywords", "elements"):
        if k in fields:
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    if "section" in fields:
        fields["sort_key"] = section_sort_key(fields["section"])
    set_clause = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = ?"
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE statutes SET {set_clause} WHERE id = ?",
            (*fields.values(), _now(), statute_id),
        )
        if cur.rowcount == 0:
            return None
    return get_statute(statute_id)


def delete_statute(statute_id: str) -> bool:
    with get_conn() as conn:
        return conn.execute("DELETE FROM statutes WHERE id = ?", (statute_id,)).rowcount > 0


def list_categories() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS total FROM statutes GROUP BY category ORDER BY category"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------- Analyses (History) ----------------

def save_analysis(facts: str, provider: str, model: Optional[str], result: Dict[str, Any],
                  statutes_cited: Optional[List[str]] = None,
                  faithfulness_score: Optional[float] = None) -> int:
    guardrails = result.get("guardrails") or {}
    firac = result.get("firac") or {}
    if statutes_cited is None:
        statutes_cited = firac.get("statutes_cited", [])
    if faithfulness_score is None:
        faithfulness_score = guardrails.get("faithfulness_score")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO analyses (facts, provider, model, status, faithfulness_score, statutes_cited, result, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                facts, provider, model, result.get("status", "UNKNOWN"),
                faithfulness_score,
                json.dumps(statutes_cited, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                _now(),
            ),
        )
        return cur.lastrowid


def list_analyses(limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        rows = conn.execute(
            """SELECT id, facts, provider, model, status, faithfulness_score, statutes_cited, created_at
               FROM analyses ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["statutes_cited"] = json.loads(d["statutes_cited"])
        items.append(d)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def get_analysis(analysis_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["statutes_cited"] = json.loads(d["statutes_cited"])
    d["result"] = json.loads(d["result"])
    return d


def delete_analysis(analysis_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,)).rowcount > 0


# ---------------- ความคิดเห็นผู้ใช้ ----------------

def save_feedback(row: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(f"INSERT INTO feedback ({', '.join(FEEDBACK_COLUMNS)}) VALUES ({', '.join('?' * len(FEEDBACK_COLUMNS))})",
                     tuple(row.get(c) for c in FEEDBACK_COLUMNS))


def list_feedback(limit: int = 500) -> List[Dict[str, Any]]:
    """ล่าสุดก่อน"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM feedback ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
