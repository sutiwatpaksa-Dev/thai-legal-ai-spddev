"""
ตั้งค่าร่วมของชุดทดสอบ — ต้อง import โมดูลนี้ก่อน legal_engine / app เสมอ

ทดสอบกับ "สำเนา" ของ data/legal_ai.db ในโฟลเดอร์ชั่วคราว
เพื่อไม่ให้การทดสอบ (เช่น เพิ่ม/ลบตัวบท) แก้ไขฐานข้อมูลจริง
"""

import atexit
import json
import os
import shutil
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(ROOT, "data", "legal_ai.db")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# การทดสอบต้องไม่เรียก Claude API จริง (เสียเงิน) — ใช้ Ollama เว้นแต่ test ระบุผู้ให้บริการเอง
os.environ["LEGAL_AI_LLM_PROVIDER"] = "ollama"

if "LEGAL_AI_DB" not in os.environ:
    if not os.path.exists(REAL_DB):
        raise RuntimeError("ไม่พบ data/legal_ai.db — รัน `python ingest_pdf.py` ก่อนทดสอบ")
    _tmp = tempfile.mkdtemp(prefix="legal_ai_test_")
    os.environ["LEGAL_AI_DB"] = os.path.join(_tmp, "legal_ai.db")
    shutil.copy(REAL_DB, os.environ["LEGAL_AI_DB"])
    atexit.register(shutil.rmtree, _tmp, ignore_errors=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


_ollama_state = None


def ollama_ready() -> bool:
    """
    Ollama รันอยู่ มีโมเดล และ "โหลดโมเดลได้จริง" (สร้าง 1 token สำเร็จ)
    ถ้าโหลดไม่ได้ (เช่น RAM/VRAM ไม่พอ) ให้ข้ามการทดสอบกับโมเดลจริง — เป็นปัญหาของเครื่อง ไม่ใช่ของโค้ด
    """
    global _ollama_state
    if _ollama_state is not None:
        return _ollama_state[0]
    from legal_engine import qa
    base = qa.LLM_BASE_URL.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as r:
            names = [m.get("name") for m in json.load(r).get("models", [])]
        if qa.LLM_MODEL not in names:
            _ollama_state = (False, f"ยังไม่ได้ติดตั้ง {qa.LLM_MODEL}")
            return False
        body = json.dumps({"model": qa.LLM_MODEL, "prompt": "ok", "stream": False,
                           "options": {"num_predict": 1}}).encode()
        req = urllib.request.Request(f"{base}/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120):
            pass
        _ollama_state = (True, "")
    except Exception as e:
        _ollama_state = (False, f"โหลดโมเดลไม่ได้: {type(e).__name__}")
    return _ollama_state[0]


def ollama_skip_reason() -> str:
    ollama_ready()
    return _ollama_state[1] or "Ollama ไม่ได้รัน"
