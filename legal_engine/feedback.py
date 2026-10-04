"""
ความคิดเห็นของผู้ใช้: ให้คะแนนคำตอบ AI, รีวิวเว็บไซต์, แจ้งตัวบทผิด

ที่เก็บ:
- Google Sheet ผ่าน Google Apps Script (tools/feedback_apps_script.gs) เมื่อตั้ง FEEDBACK_SCRIPT_URL และ
  FEEDBACK_SECRET — ใช้บน Vercel เพราะฐานข้อมูลใน /tmp หายเมื่อ instance ปิด
- ตาราง feedback ใน SQLite เมื่อรันบนเครื่องและยังไม่ได้ตั้งค่า Sheet
- บน Vercel ที่ยังไม่ได้ตั้งค่า Sheet: ปิดระบบ (ไม่รับข้อมูลที่จะหายไป)

ความเป็นส่วนตัว: เก็บเฉพาะคะแนน ความคิดเห็น ชื่อเล่น/นามแฝง (ไม่บังคับ) และคำถาม/คำตอบที่ถูกให้คะแนน
ไม่เก็บ IP อีเมล หรือเบอร์โทร
"""

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import database as db
from .claude_llm import _windows_user_env

SHEET_TIMEOUT = 15
FIELD_LIMITS = {"comment": 1000, "nickname": 40, "question": 2000, "model": 64, "answer_status": 32, "section": 64}
ANONYMOUS = "ไม่ระบุชื่อ"

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FeedbackError(RuntimeError):
    """บันทึก/อ่านความคิดเห็นไม่สำเร็จ"""


def _setting(name: str) -> str:
    return os.environ.get(name) or _windows_user_env(name)


def backend() -> str:
    """"sheet" / "local" / "" (ปิด)"""
    if _setting("FEEDBACK_SCRIPT_URL") and _setting("FEEDBACK_SECRET"):
        return "sheet"
    return "" if os.environ.get("VERCEL") else "local"


def enabled() -> bool:
    return bool(backend())


def clean_text(value: Any, limit: int) -> str:
    """ตัดอักขระควบคุม/ช่องว่างหัวท้าย และจำกัดความยาว"""
    return _CONTROL_RE.sub("", str(value or "")).strip()[:limit]


def sheet_safe(value: Any) -> Any:
    """กันสูตร (formula injection) เมื่อข้อความขึ้นต้นด้วย = + - @ — Google Sheet/Excel จะไม่คำนวณ"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def make_row(entry: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: clean_text(entry.get(k), n) for k, n in FIELD_LIMITS.items()}
    row["nickname"] = row["nickname"] or ANONYMOUS
    row.update(id=uuid.uuid4().hex[:12], created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               type=entry["type"], rating=entry.get("rating"))
    return row


def _call_sheet(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps({"secret": _setting("FEEDBACK_SECRET"), **payload}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(_setting("FEEDBACK_SCRIPT_URL"), data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        # Apps Script ตอบ 302 ไปยัง URL ผลลัพธ์ — urllib ตามไปด้วย GET ให้เอง
        with urllib.request.urlopen(req, timeout=SHEET_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise FeedbackError(f"Google Sheet: {type(e).__name__}: {e}") from None
    if not data.get("ok"):
        raise FeedbackError(f"Google Sheet: {data.get('error', 'unknown error')}")
    return data


def save(entry: Dict[str, Any]) -> Dict[str, Any]:
    row = make_row(entry)
    where = backend()
    if where == "sheet":
        _call_sheet({"action": "add", "row": {k: sheet_safe(v) for k, v in row.items()}})
    elif where == "local":
        db.save_feedback(row)
    else:
        raise FeedbackError("ระบบความคิดเห็นยังไม่ได้ตั้งค่า")
    return row


def list_entries(limit: int = 500) -> List[Dict[str, Any]]:
    """ล่าสุดก่อน"""
    where = backend()
    if where == "sheet":
        rows = _call_sheet({"action": "list", "limit": limit}).get("rows", [])
    elif where == "local":
        rows = db.list_feedback(limit)
    else:
        raise FeedbackError("ระบบความคิดเห็นยังไม่ได้ตั้งค่า")
    for r in rows:   # ค่าจาก Sheet อาจเป็นข้อความ — ทำให้ rating เป็นตัวเลขเสมอ
        try:
            r["rating"] = int(r["rating"]) if r.get("rating") not in (None, "") else None
        except (TypeError, ValueError):
            r["rating"] = None
    return rows


def stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """สรุปสำหรับหน้า admin: จำนวนแต่ละประเภท, ดาวเฉลี่ยของรีวิว, 👍/👎 แยกตามโมเดล"""
    site = [r["rating"] for r in rows if r.get("type") == "site" and r.get("rating")]
    per_model: Dict[str, Dict[str, int]] = {}
    for r in rows:
        if r.get("type") == "answer" and r.get("rating") in (1, -1):
            m = per_model.setdefault(r.get("model") or "ไม่ระบุ", {"up": 0, "down": 0})
            m["up" if r["rating"] == 1 else "down"] += 1
    return {
        "total": len(rows),
        "by_type": {t: sum(1 for r in rows if r.get("type") == t) for t in ("answer", "site", "statute")},
        "site_average": round(sum(site) / len(site), 2) if site else None,
        "site_count": len(site),
        "answer_by_model": per_model,
    }
