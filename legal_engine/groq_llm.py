"""
เรียก Groq (OpenAI-compatible API) สำหรับระบบถาม-ตอบกฎหมาย — ใช้ฟรีได้ภายใต้โควตาของแผน Free

- ใช้ structured outputs แบบ strict (json_schema) ด้วย schema เดียวกับ Claude ให้ qa.py ตรวจอ้างอิงได้เหมือนเดิม
- ผู้ใช้เลือกโมเดลได้ทีละคำถามจาก GROQ_MODELS เท่านั้น
- ไม่เก็บ/ไม่รับ API key ในโค้ด: อ่านจาก GROQ_API_KEY (environment หรือตัวแปรผู้ใช้ของ Windows)

หมายเหตุความเป็นส่วนตัว: คำถามและตัวบทที่เกี่ยวข้องจะถูกส่งไปประมวลผลที่ Groq
"""

import json
import os
from typing import Any, Dict

from .claude_llm import ANSWER_SCHEMA, SUMMARY_SCHEMA, _windows_user_env

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TIMEOUT = float(os.environ.get("LEGAL_AI_GROQ_TIMEOUT", "120"))
# เพดานรวม "การคิด" + คำตอบ (โควตาฟรีนับเฉพาะ tokens ที่ใช้จริง ไม่นับเพดานนี้)
GROQ_MAX_TOKENS = int(os.environ.get("LEGAL_AI_GROQ_MAX_TOKENS", "8000"))

# โมเดลที่เลือกได้ (แผน Free: 30 คำขอ/นาที, 1,000 คำขอ/วัน, 8K tokens/นาที, 200K tokens/วัน ต่อโมเดล)
GROQ_MODELS = {
    "openai/gpt-oss-120b": {
        "label": "GPT-OSS 120B",
        "description": "แม่นยำที่สุดในสามตัว (120B) คิดวิเคราะห์ก่อนตอบ ~500 tokens/วินาที — แนะนำ",
        # "การคิด" ระดับ medium (ค่าเริ่มต้น) กิน tokens จนสรุปมาตรายาวๆ ไม่จบ — low ใช้ ~1,500 tokens
        "reasoning_effort": "low",
    },
    "openai/gpt-oss-20b": {
        "label": "GPT-OSS 20B",
        "description": "เร็วที่สุด (~1,000 tokens/วินาที) แต่เล็กกว่า อาจพลาดในคำถามที่ซับซ้อน",
        "reasoning_effort": "low",
    },
    "qwen/qwen3.8-27b": {
        "label": "Qwen 3.8 27B",
        "description": "โมเดลจาก Alibaba (27B) ถนัดภาษาเอเชีย ~450 tokens/วินาที",
    },
}
DEFAULT_MODEL = os.environ.get("LEGAL_AI_GROQ_MODEL", "openai/gpt-oss-120b")
if DEFAULT_MODEL not in GROQ_MODELS:
    raise ValueError(f"LEGAL_AI_GROQ_MODEL ต้องเป็นหนึ่งใน {', '.join(GROQ_MODELS)}")


class GroqKeyMissing(RuntimeError):
    """ยังไม่ได้ตั้งค่า GROQ_API_KEY"""


def _api_key() -> str:
    return os.environ.get("GROQ_API_KEY") or _windows_user_env("GROQ_API_KEY")


def credentials_configured() -> bool:
    """มี key หรือไม่ (ตรวจว่ามีค่า — ไม่บันทึกหรือแสดงค่า key)"""
    return bool(_api_key())


def model_options() -> list:
    return [{"id": mid, "label": info["label"], "description": info["description"]} for mid, info in GROQ_MODELS.items()]


_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=GROQ_BASE_URL, api_key=_api_key(), timeout=GROQ_TIMEOUT)
    return _client


def call_groq(system_prompt: str, user_content: str, summary: bool, model: str = "") -> Dict[str, Any]:
    model = model or DEFAULT_MODEL
    if model not in GROQ_MODELS:
        raise ValueError(f"โมเดล {model} ไม่อยู่ในรายการที่อนุญาต")
    if not credentials_configured():
        raise GroqKeyMissing("ยังไม่ได้ตั้งค่า GROQ_API_KEY")
    extra = {}
    if "reasoning_effort" in GROQ_MODELS[model]:
        extra["reasoning_effort"] = GROQ_MODELS[model]["reasoning_effort"]
    resp = _get_client().chat.completions.create(
        **extra,
        model=model,
        max_completion_tokens=GROQ_MAX_TOKENS,
        temperature=0.0,
        response_format={"type": "json_schema", "json_schema": {
            "name": "legal_summary" if summary else "legal_answer",
            "strict": True,
            "schema": SUMMARY_SCHEMA if summary else ANSWER_SCHEMA,
        }},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError("คำตอบยาวเกินขีดจำกัด max_completion_tokens")
    return json.loads(choice.message.content)
