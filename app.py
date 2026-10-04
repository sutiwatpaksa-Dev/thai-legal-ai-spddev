"""
FastAPI Server — Thai Legal AI
มีสองส่วน:
1. คลังตัวบทกฎหมายแห่งชาติ (Knowledge Base) — ตัวบทจริงจากฐานข้อมูล SQLite
2. ถาม-ตอบกฎหมาย — ให้ AI ตอบจากตัวบทจริง (/api/ask) หรือค้นหาตัวบทอย่างเดียว (/api/search)
"""

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import hmac
from collections import defaultdict, deque
from typing import Optional, List
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Vercel เขียนไฟล์ได้เฉพาะ /tmp — PyThaiNLP สร้างโฟลเดอร์ข้อมูลตั้งแต่ตอน import
# จึงต้องตั้งก่อน import legal_engine (Vercel เริ่มแอปจากไฟล์นี้โดยตรง)
if os.environ.get("VERCEL"):
    os.environ.setdefault("PYTHAINLP_DATA", "/tmp/pythainlp-data")

from legal_engine import claude_llm
from legal_engine import database as db
from legal_engine import feedback
from legal_engine import groq_llm
from legal_engine import qa as qa_module
from legal_engine.hybrid_retriever import HybridLegalRetriever
from legal_engine.qa import LegalQA

app = FastAPI(
    title="Thai Legal AI",
    description="คลังตัวบทกฎหมายแห่งชาติ และระบบถาม-ตอบที่อ้างอิงตัวบทจริง",
    version="2.0.0"
)

# รายละเอียด error ของ AI ถูกบันทึกลง log ฝั่ง server (ไม่ส่งให้ผู้ใช้)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ฐานข้อมูล SQLite เป็นแหล่งข้อมูลหลักของตัวบทกฎหมาย
db.init_db()
retriever = HybridLegalRetriever(db.list_statutes())
qa = LegalQA(retriever=retriever)


def _reindex() -> None:
    """สร้างดัชนีค้นหาใหม่หลังข้อมูลตัวบทเปลี่ยน"""
    retriever.reload(db.list_statutes())


def _require_local() -> None:
    """
    บน Vercel (เว็บสาธารณะ ไม่มีระบบล็อกอิน) ห้ามแก้ตัวบทและห้ามดูประวัติคำถามของผู้อื่น
    — ฐานข้อมูลอยู่ใน /tmp ของแต่ละ instance อยู่แล้ว การแก้ไขจึงไม่คงอยู่
    """
    if os.environ.get("VERCEL"):
        raise HTTPException(status_code=403, detail="ใช้ได้เฉพาะเมื่อรันบนเครื่อง (ไม่เปิดบนเว็บสาธารณะ)")

# Pydantic Schemas
class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = Field(10, ge=1, le=50)

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    # auto = สรุปเมื่อคำถามมีคำว่า สรุป/อธิบาย/ขยายความ, นอกนั้นตอบคำถาม
    mode: str = Field("auto", pattern=r"^(auto|answer|summary)$")
    # โมเดล Groq ที่ผู้ใช้เลือก (ใช้เมื่อ provider = groq; ว่าง = ค่าเริ่มต้น)
    model: Optional[str] = Field(None, max_length=64)

class StatuteCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    category: str = Field(..., min_length=1)
    book: str = ""
    title: str = Field(..., min_length=1)
    section: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    keywords: List[str] = []
    elements: List[str] = []
    status: str = Field("active", pattern=r"^(active|repealed)$")

class StatuteUpdate(BaseModel):
    category: Optional[str] = None
    book: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    content: Optional[str] = None
    keywords: Optional[List[str]] = None
    elements: Optional[List[str]] = None
    status: Optional[str] = Field(None, pattern=r"^(active|repealed)$")

# ---------------- ถาม-ตอบ / ค้นหาตัวบท ----------------

@app.post("/api/ask")
def ask_question(req: AskRequest):
    """
    ถาม-ตอบกฎหมายจริง: ค้นตัวบทจากฐานข้อมูล → LLM ในเครื่อง (Ollama) → ตรวจอ้างอิงกับตัวบทจริง
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="กรุณาระบุคำถาม")
    if req.model and qa_module.active_provider() == "groq" and req.model not in groq_llm.GROQ_MODELS:
        raise HTTPException(status_code=400, detail="โมเดลนี้ไม่อยู่ในรายการที่เลือกได้")
    result = qa.ask(question, mode=req.mode, model=req.model or "")
    # ผลการเรียกจริงคือสัญญาณสุขภาพที่เชื่อถือได้ที่สุด — แต่ปัญหาเฉพาะคำถาม/โมเดล
    # (ตอบยาวเกิน, เกินโควตาชั่วคราว ฯลฯ) ไม่ได้แปลว่า AI ทั้งระบบใช้งานไม่ได้
    if result["status"] == "LLM_ERROR":
        if result.get("error_code") in SERVICE_DOWN_CODES:
            _set_health(False, result.get("error_code"), result.get("error", ""), source="ask")
    elif result.get("guardrails"):   # มีผลตรวจ = โมเดลตอบกลับมาจริง
        _set_health(True, source="ask")
    result["llm_health"] = dict(_llm_health)
    checks = result.get("guardrails") or {}
    total = len(result["citations"]) + len(checks.get("rejected_citations", []))
    # สัดส่วนอ้างอิงของโมเดลที่ยกข้อความตรงกับตัวบทจริง (ไม่มีอ้างอิง = 0)
    result["faithfulness_score"] = round(100.0 * len(result["citations"]) / total, 1) if total else 0.0
    result["analysis_id"] = db.save_analysis(
        facts=question, provider=f"{result.get('provider', 'ollama')}-qa", model=result.get("model"), result=result,
        statutes_cited=[c["section"] for c in result["citations"]],
        faithfulness_score=result["faithfulness_score"],
    )
    return result

@app.post("/api/search")
def search_statutes(req: SearchRequest):
    """
    ค้นหาตัวบทกฎหมายที่เกี่ยวข้องกับคำถาม (ไม่ใช้ AI) เรียงตามคะแนนความเกี่ยวข้อง
    """
    if not req.query.strip():
        return {"results": []}
    results = retriever.retrieve(req.query, top_k=req.top_k, min_score_threshold=0.1)
    return {"results": results}

# ---------------- สถานะ AI (health) ----------------
# อัปเดตจากผลการเรียกจริง (/api/ask) และจากการ probe โมเดล — ไม่ใช่แค่ดูว่า server เปิดอยู่

HEALTH_TTL_SECONDS = 60
# รหัส error ที่แปลว่า AI ใช้ไม่ได้ทั้งระบบ (ไม่ขึ้นกับคำถามหรือโมเดลที่เลือก)
SERVICE_DOWN_CODES = {"LLM_AUTH", "LLM_UNREACHABLE", "LLM_OUT_OF_MEMORY"}
PROBE_TIMEOUT_SECONDS = 120   # ครั้งแรกต้องโหลดโมเดลเข้าหน่วยความจำ
_health_lock = threading.Lock()
_llm_health = {"ok": None, "error_code": None, "message": "ยังไม่ได้ตรวจ", "checked_at": None, "source": None}


def _set_health(ok: bool, error_code: Optional[str] = None, message: str = "", source: str = "ask") -> None:
    _llm_health.update(ok=ok, error_code=error_code, message=message, checked_at=time.time(), source=source)


def _ollama_base() -> str:
    return qa_module.LLM_BASE_URL.rstrip("/").removesuffix("/v1")


def _probe_ollama() -> None:
    """สั่งโมเดลสร้าง 1 token — บังคับให้โหลดโมเดลจริง (จุดที่ CUDA/RAM ไม่พอจะล้ม)"""
    body = json.dumps({"model": qa_module.LLM_MODEL, "prompt": "ok", "stream": False,
                       "options": {"num_predict": 1}}).encode()
    req = urllib.request.Request(f"{_ollama_base()}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT_SECONDS):
            pass
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise ConnectionError(str(e.reason)) from None


@app.get("/api/status")
def get_status(probe: bool = Query(False, description="ทดสอบโมเดลจริง (อาจใช้เวลาโหลดโมเดล)")):
    """สถานะจริงของระบบ: จำนวนตัวบทในคลัง และสุขภาพของโมเดล AI"""
    provider = qa_module.active_provider()
    llm = {"provider": provider, "model": qa_module.active_model()}

    if provider == "anthropic":
        # ไม่ probe Claude (เสียค่าใช้จ่าย) — สุขภาพมาจากผลการถามจริงครั้งล่าสุด
        llm["configured"] = claude_llm.credentials_configured()
        if not llm["configured"]:
            _set_health(False, "LLM_AUTH", qa_module.LLM_ERROR_MESSAGES["LLM_AUTH"], source="config")
    elif provider == "groq":
        # ไม่ probe (กินโควตาฟรี) — สุขภาพมาจากผลการถามจริงครั้งล่าสุด
        llm["configured"] = groq_llm.credentials_configured()
        llm["models"] = groq_llm.model_options()
        if not llm["configured"]:
            _set_health(False, "LLM_AUTH", qa_module.LLM_ERROR_MESSAGES["LLM_AUTH"], source="config")
    else:
        stale = _llm_health["checked_at"] is None or time.time() - _llm_health["checked_at"] > HEALTH_TTL_SECONDS
        if probe and stale:
            with _health_lock:
                try:
                    _probe_ollama()
                    _set_health(True, source="probe")
                except Exception as e:
                    _set_health(False, **_error_code_and_message(e), source="probe")

    llm["health"] = dict(_llm_health)
    llm["reachable"] = bool(_llm_health["ok"])
    return {"statutes": len(retriever.statutes), "categories": db.list_categories(), "llm": llm,
            "feedback": {"enabled": feedback.enabled()}}


def _error_code_and_message(e: Exception) -> dict:
    fields = qa_module.llm_error_fields(e)   # บันทึกรายละเอียดลง log
    return {"error_code": fields["error_code"], "message": fields["error"]}

# ---------------- Statutes CRUD (คลังตัวบท) ----------------

@app.get("/api/statutes")
def get_all_statutes(
    category: Optional[str] = Query(None, description="กรองตามหมวดกฎหมาย"),
    q: Optional[str] = Query(None, description="ค้นหาข้อความในเลขมาตรา/ชื่อ/เนื้อหา/คำสำคัญ"),
):
    """
    ดึงรายการตัวบทกฎหมายจากฐานข้อมูล (กรองตามหมวดหรือข้อความได้)
    """
    statutes = db.list_statutes(category=category, q=q)
    return {"total": len(statutes), "statutes": statutes}

@app.get("/api/statutes/{statute_id}")
def get_statute(statute_id: str):
    statute = db.get_statute(statute_id)
    if not statute:
        raise HTTPException(status_code=404, detail="ไม่พบตัวบทกฎหมาย")
    return statute

@app.post("/api/statutes", status_code=201, dependencies=[Depends(_require_local)])
def create_statute(body: StatuteCreate):
    try:
        statute = db.create_statute(body.model_dump())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"มีตัวบทรหัส {body.id} อยู่แล้ว")
    _reindex()
    return statute

@app.put("/api/statutes/{statute_id}", dependencies=[Depends(_require_local)])
def update_statute(statute_id: str, body: StatuteUpdate):
    statute = db.update_statute(statute_id, body.model_dump(exclude_unset=True))
    if not statute:
        raise HTTPException(status_code=404, detail="ไม่พบตัวบทกฎหมาย")
    _reindex()
    return statute

@app.delete("/api/statutes/{statute_id}", status_code=204, dependencies=[Depends(_require_local)])
def delete_statute(statute_id: str):
    if not db.delete_statute(statute_id):
        raise HTTPException(status_code=404, detail="ไม่พบตัวบทกฎหมาย")
    _reindex()

@app.get("/api/categories")
def get_categories():
    """รายการหมวดกฎหมายพร้อมจำนวนมาตรา"""
    return {"categories": db.list_categories()}

# ---------------- ประวัติการถาม-ตอบ ----------------

@app.get("/api/history", dependencies=[Depends(_require_local)])
def get_history(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return db.list_analyses(limit=limit, offset=offset)

@app.get("/api/history/{analysis_id}", dependencies=[Depends(_require_local)])
def get_history_item(analysis_id: int):
    item = db.get_analysis(analysis_id)
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบประวัติ")
    return item

@app.delete("/api/history/{analysis_id}", status_code=204, dependencies=[Depends(_require_local)])
def delete_history_item(analysis_id: int):
    if not db.delete_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="ไม่พบประวัติ")

# ---------------- ความคิดเห็นผู้ใช้ (ให้คะแนนคำตอบ / รีวิวเว็บไซต์ / แจ้งตัวบทผิด) ----------------

class FeedbackRequest(BaseModel):
    type: str = Field(..., pattern=r"^(answer|site|statute)$")
    rating: Optional[int] = None
    comment: str = Field("", max_length=1000)
    nickname: str = Field("", max_length=40)
    question: str = Field("", max_length=2000)
    model: str = Field("", max_length=64)
    answer_status: str = Field("", max_length=32)
    section: str = Field("", max_length=64)
    website: str = ""   # กับดักบอท: ช่องที่ซ่อนจากผู้ใช้ — ถ้ามีค่าแสดงว่าเป็นสแปม


# จำกัดจำนวนครั้งต่อ IP ในหน่วยความจำของแต่ละ instance (ไม่บันทึก IP ลงที่ใด)
FEEDBACK_LIMIT, FEEDBACK_WINDOW = 10, 600
ADMIN_FAIL_LIMIT, ADMIN_FAIL_WINDOW = 5, 600
_recent = defaultdict(deque)
_recent_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "")


def _too_many(key: str, limit: int, window: int, record: bool = True) -> bool:
    now = time.time()
    with _recent_lock:
        q = _recent[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return True
        if record:
            q.append(now)
    return False


@app.post("/api/feedback", status_code=201)
def submit_feedback(req: FeedbackRequest, request: Request):
    """รับความคิดเห็น — ไม่เก็บ IP อีเมล หรือเบอร์โทร ชื่อเล่นไม่บังคับ"""
    if not feedback.enabled():
        raise HTTPException(status_code=503, detail="ระบบความคิดเห็นยังไม่เปิดใช้งาน")
    if req.website:
        return {"ok": True}   # สแปม: ตอบเหมือนสำเร็จแต่ไม่บันทึก
    if req.type == "answer" and req.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="คะแนนคำตอบต้องเป็น 1 หรือ -1")
    if req.type == "site" and req.rating not in (1, 2, 3, 4, 5):
        raise HTTPException(status_code=422, detail="กรุณาให้ดาว 1-5 ดวง")
    if req.type == "statute" and not (req.section.strip() and req.comment.strip()):
        raise HTTPException(status_code=422, detail="กรุณาระบุมาตราและอธิบายว่าผิดตรงไหน")
    if _too_many("fb:" + _client_ip(request), FEEDBACK_LIMIT, FEEDBACK_WINDOW):
        raise HTTPException(status_code=429, detail="ส่งความคิดเห็นถี่เกินไป กรุณารอสักครู่")
    entry = req.model_dump(exclude={"website"})
    if req.type == "statute":
        entry["rating"] = None
    try:
        row = feedback.save(entry)
    except feedback.FeedbackError as e:
        logging.getLogger("legal_ai.feedback").error("save failed: %s", e)
        raise HTTPException(status_code=502, detail="บันทึกความคิดเห็นไม่สำเร็จ กรุณาลองใหม่") from None
    return {"ok": True, "id": row["id"]}


def _require_admin(request: Request, x_admin_password: str = Header("")) -> None:
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งรหัสผ่านผู้ดูแล (ADMIN_PASSWORD)")
    key = "admin:" + _client_ip(request)
    if _too_many(key, ADMIN_FAIL_LIMIT, ADMIN_FAIL_WINDOW, record=False):
        raise HTTPException(status_code=429, detail="ใส่รหัสผิดหลายครั้ง กรุณารอ 10 นาที")
    if not hmac.compare_digest(x_admin_password.encode("utf-8"), expected.encode("utf-8")):
        _too_many(key, ADMIN_FAIL_LIMIT, ADMIN_FAIL_WINDOW)   # นับครั้งที่ผิด
        raise HTTPException(status_code=401, detail="รหัสผ่านไม่ถูกต้อง")


@app.get("/api/admin/feedback", dependencies=[Depends(_require_admin)])
def admin_feedback(limit: int = Query(500, ge=1, le=2000)):
    try:
        rows = feedback.list_entries(limit)
    except feedback.FeedbackError as e:
        logging.getLogger("legal_ai.feedback").error("list failed: %s", e)
        raise HTTPException(status_code=502, detail="อ่านข้อมูลจากที่เก็บไม่สำเร็จ") from None
    return {"backend": feedback.backend(), "stats": feedback.stats(rows), "rows": rows}


# ให้บริการไฟล์ static (Frontend)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Legal AI Backend is running."}

@app.get("/admin")
async def serve_admin():
    """หน้าผู้ดูแล — ข้อมูลจริงต้องใส่รหัสผ่าน (ตรวจที่ /api/admin/feedback)"""
    return FileResponse(os.path.join(static_dir, "admin.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
