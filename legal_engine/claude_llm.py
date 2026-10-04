"""
เรียก Claude API (Anthropic SDK) สำหรับระบบถาม-ตอบกฎหมาย

- ใช้ structured outputs (output_config.format) ให้ได้ JSON ตามรูปแบบเดียวกับที่ qa.py ตรวจอ้างอิง
- ใช้ fallbacks "default" (server-side) — ถ้าตัวกรองความปลอดภัยปฏิเสธ จะส่งต่อให้โมเดลสำรองอัตโนมัติ
- ไม่เก็บ/ไม่รับ API key ในโค้ด: SDK อ่านจาก ANTHROPIC_API_KEY หรือ ANTHROPIC_AUTH_TOKEN เอง

หมายเหตุความเป็นส่วนตัว: คำถามและตัวบทที่เกี่ยวข้องจะถูกส่งไปประมวลผลที่ Anthropic
"""

import json
import os
from typing import Any, Dict

import anthropic

CLAUDE_MODEL = os.environ.get("LEGAL_AI_CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.environ.get("LEGAL_AI_CLAUDE_EFFORT", "high")
CLAUDE_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_CITATION = {
    "type": "object",
    "properties": {"section": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["section", "quote"],
    "additionalProperties": False,
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": _CITATION},
        "insufficient": {"type": "boolean"},
    },
    "required": ["answer", "citations", "insufficient"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "heading": {"type": "string"}, "explanation": {"type": "string"},
                "section": {"type": "string"}, "quote": {"type": "string"},
            },
            "required": ["heading", "explanation", "section", "quote"],
            "additionalProperties": False,
        }},
        "example": {"type": "string"},
        "notes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "point": {"type": "string"}, "section": {"type": "string"}, "quote": {"type": "string"},
            },
            "required": ["point", "section", "quote"],
            "additionalProperties": False,
        }},
        "insufficient": {"type": "boolean"},
    },
    "required": ["title", "summary", "key_points", "example", "notes", "insufficient"],
    "additionalProperties": False,
}


class ClaudeRefusal(RuntimeError):
    """Claude (และโมเดลสำรอง) ปฏิเสธคำขอ"""


def _windows_user_env(name: str) -> str:
    """
    อ่านตัวแปรระดับผู้ใช้ของ Windows (ที่ตั้งด้วย setx) จาก registry
    จำเป็นเพราะ terminal ใน IDE ที่เปิดก่อนรัน setx จะไม่ได้รับตัวแปรใหม่ใน environment ของ process
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value or "")
    except OSError:
        return ""


def _api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or _windows_user_env("ANTHROPIC_API_KEY")


def credentials_configured() -> bool:
    """มี credential หรือไม่ (ตรวจว่ามีค่า — ไม่บันทึกหรือแสดงค่า key)"""
    return bool(_api_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = _api_key()
        # ส่ง key ให้ SDK โดยตรงเมื่ออ่านจาก registry; ถ้าอยู่ใน environment อยู่แล้ว SDK อ่านเองได้
        _client = anthropic.Anthropic(api_key=key) if key and not os.environ.get("ANTHROPIC_API_KEY") else anthropic.Anthropic()
    return _client


def call_claude(system_prompt: str, user_content: str, summary: bool) -> Dict[str, Any]:
    response = _get_client().beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={
            "effort": CLAUDE_EFFORT,
            "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA if summary else ANSWER_SCHEMA},
        },
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise ClaudeRefusal(f"Claude ปฏิเสธคำขอ (category: {category})")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("คำตอบยาวเกินขีดจำกัด max_tokens")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)
