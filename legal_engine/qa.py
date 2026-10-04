"""
Legal Q&A (ถาม-ตอบกฎหมายจริง จากตัวบทในฐานข้อมูล)

ขั้นตอน:
1. ค้นหาตัวบทที่เกี่ยวข้อง (Hybrid Retriever) + ดึงมาตราที่ผู้ใช้ระบุเลขมาโดยตรง
2. ส่งตัวบทจริง (ข้อความจาก PDF) ให้ LLM ในเครื่องผ่าน Ollama (OpenAI-compatible API)
3. LLM ต้องตอบเป็น JSON พร้อมอ้างอิงมาตราและ "ยกข้อความ" จากตัวบท
4. ตรวจอ้างอิงทุกข้อ: มาตราต้องอยู่ในชุดที่ส่งให้ และข้อความที่ยกมาต้องมีอยู่จริงในตัวบทนั้น
   อ้างอิงที่ตรวจไม่ผ่านจะถูกตัดออกและแจ้งเตือน หากไม่มีอ้างอิงใดผ่านเลยจะไม่ตอบ (ABSTAIN)

ข้อจำกัด: สถานะ CITATIONS_VERIFIED ยืนยันว่าข้อความที่อ้างมีอยู่จริงในตัวบท
แต่ไม่ได้ยืนยันว่าข้อสรุปของโมเดลถูกต้องครบถ้วน ผู้ใช้ต้องอ่านตัวบทที่แนบมาประกอบเสมอ
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple

from . import claude_llm
from . import database as db
from . import quantities
from .hybrid_retriever import HybridLegalRetriever

# ผู้ให้บริการโมเดล: "anthropic" (Claude API), "ollama" (โมเดลในเครื่อง)
# หรือ "auto" = ใช้ Claude เมื่อตั้งค่า ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN แล้ว มิฉะนั้นใช้ Ollama
LLM_PROVIDER = os.environ.get("LEGAL_AI_LLM_PROVIDER", "auto")
LLM_BASE_URL = os.environ.get("LEGAL_AI_LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LEGAL_AI_LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.environ.get("LEGAL_AI_LLM_API_KEY", "ollama")  # Ollama ไม่ตรวจ key
LLM_TIMEOUT = float(os.environ.get("LEGAL_AI_LLM_TIMEOUT", "180"))

logger = logging.getLogger("legal_ai.qa")

# แสดงข้อความ error ดิบให้ผู้ใช้เห็นเฉพาะเมื่อเปิดโหมดดีบัก (ห้ามเปิดใน production)
DEBUG_ERRORS = os.environ.get("LEGAL_AI_DEBUG") == "1"

TOP_K = 6
MIN_SCORE = 0.8

# รหัสข้อผิดพลาดของ AI -> ข้อความสำหรับผู้ใช้ (ไม่เปิดเผยรายละเอียดภายในระบบ)
LLM_ERROR_MESSAGES = {
    "LLM_OUT_OF_MEMORY": "หน่วยความจำของเครื่องไม่พอสำหรับโหลดโมเดล AI — ปิดโปรแกรมอื่นแล้วลองใหม่",
    "LLM_UNREACHABLE": "เชื่อมต่อบริการ AI ไม่ได้",
    "LLM_AUTH": "ยืนยันตัวตนกับบริการ AI ไม่ผ่าน — ตรวจการตั้งค่า API key",
    "LLM_REFUSED": "บริการ AI ปฏิเสธคำขอนี้",
    "LLM_TIMEOUT": "บริการ AI ตอบช้าเกินกำหนด",
    "LLM_BAD_OUTPUT": "AI ตอบกลับในรูปแบบที่ระบบอ่านไม่ได้",
    "LLM_FAILED": "บริการ AI ขัดข้อง",
}


def classify_llm_error(e: Exception) -> Tuple[str, str]:
    """แปลง exception จาก Ollama/Claude เป็น (รหัส, ข้อความสำหรับผู้ใช้)"""
    name, text = type(e).__name__, str(e).lower()
    if isinstance(e, claude_llm.ClaudeRefusal):
        code = "LLM_REFUSED"
    elif any(k in text for k in ("cuda", "out of memory", "unable to allocate", "failed to allocate", "insufficient memory")):
        code = "LLM_OUT_OF_MEMORY"
    elif "authentication" in name.lower() or "permissiondenied" in name.lower() or "401" in text:
        code = "LLM_AUTH"
    elif "timeout" in name.lower() or "timed out" in text:
        code = "LLM_TIMEOUT"
    elif "connection" in name.lower() or isinstance(e, ConnectionError):
        code = "LLM_UNREACHABLE"
    elif isinstance(e, (json.JSONDecodeError, StopIteration)):
        code = "LLM_BAD_OUTPUT"
    else:
        code = "LLM_FAILED"
    return code, LLM_ERROR_MESSAGES[code]


def llm_error_fields(e: Exception) -> Dict[str, Any]:
    """ฟิลด์ error สำหรับผลลัพธ์: บันทึกรายละเอียดลง log ฝั่ง server แทนการส่งให้ผู้ใช้"""
    code, message = classify_llm_error(e)
    logger.error("LLM call failed (%s): %s: %s", code, type(e).__name__, e)
    fields = {"error_code": code, "error": message}
    if DEBUG_ERRORS:
        fields["debug_error"] = f"{type(e).__name__}: {e}"
    return fields
MIN_QUOTE_CHARS = 8

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_SECTION_RE = re.compile(r"(?:มาตรา|ม\.|บท)\s*([0-9๐-๙]+(?:\s*/\s*[0-9๐-๙]+)?)")

SYSTEM_PROMPT = """คุณคือผู้ช่วยตอบคำถามกฎหมายไทย ตอบได้เฉพาะจาก "ตัวบทที่ให้มา" เท่านั้น

กฎ:
1. ใช้เฉพาะตัวบทในส่วน [ตัวบท] ห้ามใช้ความรู้อื่น ห้ามอ้างมาตราที่ไม่อยู่ในรายการ
2. ทุกข้อสรุปต้องอ้างมาตรา และยกข้อความจากตัวบทนั้นแบบคำต่อคำ (คัดลอกตรงตัว ไม่ถอดความ)
   โดยยกทั้งประโยคที่เกี่ยวข้อง ไม่ตัดกลางประโยค
3. ห้ามตัดเงื่อนไขทิ้ง: ถ้าตัวบทกำหนดระยะเวลา จำนวนเงิน หรือเงื่อนไขไว้หลายกรณี
   (เช่น "...ปีหนึ่งนับแต่... หรือเมื่อพ้นสิบปี...") ต้องระบุครบทุกกรณีในคำตอบ
4. ถ้าตัวบทที่ให้มาไม่พอจะตอบคำถาม ให้ตั้ง "insufficient": true และอธิบายสั้นๆ ว่าขาดอะไร
5. ตอบเป็นภาษาไทย ชัดเจน

ตอบเป็น JSON เท่านั้น ตามรูปแบบนี้:
{
  "answer": "คำตอบ",
  "citations": [{"section": "มาตรา 420", "quote": "ข้อความที่คัดลอกตรงตัวจากตัวบท"}],
  "insufficient": false
}"""


SUMMARY_PROMPT = """คุณคือผู้เชี่ยวชาญด้านกฎหมายไทยที่สรุปและอธิบายตัวบทกฎหมายให้คนทั่วไปเข้าใจง่าย ชัดเจน และเห็นภาพ โดยใช้เฉพาะ "ตัวบทที่ให้มา" เท่านั้น

แนวทางการอธิบาย (สไตล์ติวเตอร์กฎหมาย):
1. "summary": อธิบายเจตนารมณ์ของตัวบทด้วยภาษาง่ายๆ ชัดเจน
2. "key_points" 2-4 ข้อ: แจกแจงประเด็นสำคัญของมาตราออกเป็นข้อๆ อธิบายสั้นกระชับเข้าใจง่าย พร้อมระบุ quote จากตัวบทที่ตรงกับประเด็นนั้น
3. "example": เรื่องสมมติที่มีตัวละครและสถานการณ์ที่ทำให้เห็นผลของกฎหมายชัดเจน ถูกต้องตามหลักกฎหมาย
4. "notes" 1-2 ข้อ: จุดที่มักออกสอบ หรือข้อสังเกตสำคัญ เช่น ความแตกต่างกับนิติกรรมหรือสัญญาอื่น

กฎเหล็ก (Strict Rules):
1. ใช้เฉพาะตัวบทในส่วน [ตัวบท] ห้ามอ้างเลขมาตราที่ไม่อยู่ในรายการตัวบท
2. ห้ามอนุมานกรณีกลับด้านที่ตัวบทไม่ได้เขียนไว้: เช่น หากตัวบทระบุว่า "ถ้าหนี้เกิดแต่การอันมิชอบด้วยกฎหมาย ท่านว่าลูกหนี้จะยกเอาการหักกลบลบหนี้ขึ้นเป็นข้อต่อสู้หาได้ไม่" ห้ามสรุปอนุมานเองว่าหนี้ที่ชอบด้วยกฎหมายจะหักกลบได้โดยอัตโนมัติ เพราะกรณีปกติยังมีเงื่อนไขตามมาตราอื่น ให้สรุปเฉพาะสิ่งที่ตัวบทบัญญัติไว้จริงเท่านั้น
3. ทุกข้อใน key_points และ notes ต้องอ้างมาตราและยก quote ข้อความจากตัวบทแบบคำต่อคำ (คัดลอกตรงตัว 100% ห้ามดัดแปลง ห้ามตัดต่อ ห้ามแต่งข้อความขึ้นเองแม้แต่คำเดียว)
4. โครงสร้างตัวอย่างต้องถูกต้องตามหลักกฎหมาย: เช่น เรื่องการหักกลบลบหนี้ ต้องเป็นหนี้ที่บุคคลสองฝ่ายต่างผูกพันเป็นลูกหนี้และเจ้าหนี้ซึ่งกันและกัน (นาย ก. ติดหนี้นาย ข. และนาย ข. ก็ติดหนี้นาย ก.) ไม่ใช่หนี้สองก้อนของลูกหนี้คนเดียว
5. ห้ามตัดเงื่อนไขที่ตัวบทกำหนด (เช่น ระยะเวลา จำนวนเงิน ข้อยกเว้น)
6. ถ้าตัวบทที่ให้มาไม่พอ ให้ตั้ง "insufficient": true

ตอบเป็น JSON เท่านั้น ตามรูปแบบนี้:
{
  "title": "สรุปมาตรา 251 (บุริมสิทธิ)",
  "summary": "เจ้าหนี้บางคนมี \\"สิทธิได้เงินก่อน\\" จากทรัพย์สินของลูกหนี้ ก่อนเจ้าหนี้คนอื่น ๆ แต่สิทธินี้จะมีได้ก็ต่อเมื่อกฎหมายกำหนดไว้เท่านั้น",
  "key_points": [
    {"heading": "ผู้ทรงบุริมสิทธิ", "explanation": "คือเจ้าหนี้ที่กฎหมายให้สิทธิพิเศษ", "section": "มาตรา 251", "quote": "ผู้ทรงบุริมสิทธิย่อมทรงไว้ซึ่งสิทธิเหนือทรัพย์สินของลูกหนี้ในการที่จะได้รับชำระหนี้อันค้างชำระแก่ตนจากทรัพย์สินนั้นก่อนเจ้าหนี้อื่น ๆ"},
    {"heading": "ต้องมีกฎหมายรองรับ", "explanation": "ตกลงกันเองตามสัญญาไม่ได้ ต้องเป็นไปตาม ป.พ.พ. หรือกฎหมายอื่น", "section": "มาตรา 251", "quote": "โดยนัยดังบัญญัติไว้ในประมวลกฎหมายนี้หรือบทกฎหมายอื่น"}
  ],
  "example": "ลูกหนี้มีบ้าน 1 หลัง มูลค่า 1 ล้าน แต่มีหนี้รวม 3 ล้าน ถ้าในกลุ่มเจ้าหนี้มีคนที่มีบุริมสิทธิ เช่น ค่าจ้างแรงงาน จะได้รับเงินก่อน ส่วนที่เหลือค่อยแบ่งให้เจ้าหนี้สามัญ",
  "notes": [
    {"point": "บุริมสิทธิเกิดขึ้นโดยผลของกฎหมาย ไม่ต้องจดทะเบียนหรือส่งมอบทรัพย์ ซึ่งต่างจากจำนองและจำนำ", "section": "มาตรา 251", "quote": "โดยนัยดังบัญญัติไว้ในประมวลกฎหมายนี้หรือบทกฎหมายอื่น"}
  ],
  "insufficient": false
}"""

_SUMMARY_RE = re.compile(r"สรุป|อธิบาย|ขยายความ")
SUMMARY_CONTEXT = 8


def _norm(text: str) -> str:
    """เทียบข้อความแบบไม่สนช่องว่าง/ขึ้นบรรทัด และเลขไทย-อารบิก"""
    return re.sub(r"\s+", "", text.translate(_THAI_DIGITS))


def _norm_section(label: str) -> str:
    m = _SECTION_RE.search(label)
    return re.sub(r"\s+", "", m.group(1).translate(_THAI_DIGITS)) if m else ""


# รับรูปแบบที่ผู้ใช้พิมพ์จริง รวมถึงพิมพ์ตก เช่น "มาตร 251"
_QUESTION_SECTION_RE = re.compile(r"(?:มาตรา?|ม\.|ม\s|บท)\s*([0-9๐-๙]+(?:\s*/\s*[0-9๐-๙]+)?)")
_SHORT_RE = re.compile(r"สั้น|ย่อ|กระชับ|สรุปๆ")
SHORT_SUMMARY_FEEDBACK = ("ผู้ใช้ขอแบบสั้น: summary ไม่เกิน 2 ประโยค, key_points 2-3 ข้อ (อธิบายข้อละ 1 ประโยค), "
                          "example ไม่เกิน 2 ประโยค, notes ไม่เกิน 1 ข้อ")


def _explicit_sections(question: str) -> List[Dict[str, Any]]:
    """มาตราที่ผู้ถามระบุเลขมา เช่น '345', 'มาตรา 420', 'ม.193/30', 'บท 251' (ป.พ.พ.)"""
    found = []
    seen_ids = set()

    def add_num(raw_num: str):
        num = re.sub(r"\s+", "", raw_num.translate(_THAI_DIGITS)).replace("/", "-")
        st = db.get_statute(f"CCC-{num}")
        if st and st["id"] not in seen_ids:
            seen_ids.add(st["id"])
            found.append(st)

    for m in _QUESTION_SECTION_RE.finditer(question):
        add_num(m.group(1))

    # เลขเดี่ยวๆ ที่ขึ้นต้นคำถาม เช่น "345 สรุปให้สั้น"
    lead = re.match(r"^\s*([0-9๐-๙]+(?:\s*/\s*[0-9๐-๙]+)?)(?:\s|$|,|และ|ถึง|-)", question)
    if lead:
        add_num(lead.group(1))

    return found


def _context(statutes: List[Dict[str, Any]]) -> str:
    blocks = []
    for s in statutes:
        status = " (ยกเลิกแล้ว)" if s.get("status") == "repealed" else ""
        blocks.append(f"### {s['category']} {s['section']}{status}\n[{s.get('title', '')}]\n{s['content']}")
    return "\n\n".join(blocks)


def _summary_context(explicit: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    บริบทสำหรับสรุปมาตรา: ตัวมาตราเอง + มาตราต้นหมวด (หลักทั่วไป) + มาตราข้างเคียงในส่วนเดียวกัน
    + มาตราที่ตัวบทอ้างถึง เพื่อให้ตัวอย่างและข้อสังเกตอิงตัวบทจริงได้
    """
    if not explicit:
        return []
    out = list(explicit)
    for main in explicit:
        same_part = [s for s in db.list_statutes(category=main["category"]) if s["title"] == main["title"]]
        if same_part:
            # ดึงมาตราแรกของหมวด/ส่วนเสมอ (มักเป็นบทนิยามหรือหลักทั่วไป เช่น ม.341 สำหรับหักกลบลบหนี้)
            if same_part[0]["id"] != main["id"]:
                out.append(same_part[0])
            idx = next((i for i, s in enumerate(same_part) if s["id"] == main["id"]), None)
            if idx is not None:
                # ดึงมาตราก่อนหน้าและถัดไปในหมวดเดียวกัน 2-3 มาตรา
                start_i = max(0, idx - 1)
                end_i = min(len(same_part), idx + 3)
                out.extend(same_part[start_i:end_i])
        for m in _SECTION_RE.finditer(main["content"]):
            ref = db.get_statute("CCC-" + _norm_section(m.group(0)).replace("/", "-"))
            if ref:
                out.append(ref)
    uniq = list({s["id"]: s for s in out}.values())
    first = [s for s in uniq if s["id"] in {e["id"] for e in explicit}]
    return (first + [s for s in uniq if s not in first])[:SUMMARY_CONTEXT]


def _summary_to_check(out: Dict[str, Any]) -> Dict[str, Any]:
    """แปลงผลสรุปเป็นรูปแบบที่ _verify ตรวจได้ (คำตอบรวมตัวอย่าง เพื่อจับมาตราที่แต่งขึ้น)"""
    points = [p for p in (out.get("key_points") or []) + (out.get("notes") or []) if isinstance(p, dict)]
    text = "\n".join([str(out.get("summary", ""))]
                     + [f"{p.get('heading', '')} {p.get('explanation', '')} {p.get('point', '')}" for p in points])
    return {
        "answer": text + "\n" + str(out.get("example", "")),
        "answer_without_example": text,
        "citations": [{"section": p.get("section", ""), "quote": p.get("quote", "")} for p in points],
        "insufficient": out.get("insufficient"),
    }


def _keep_verified_points(points, verified) -> List[Dict[str, Any]]:
    """เก็บเฉพาะประเด็นที่ยก quote ตรงกับตัวบทจริงเท่านั้น (ไม่เก็บประเด็นที่ quote หลุดหรือแต่งขึ้น)"""
    ok = {(_norm_section(c["section"]), _norm(c["quote"])) for c in verified}
    kept = []
    for p in points or []:
        if not isinstance(p, dict):
            continue
        sec_norm = _norm_section(str(p.get("section", "")))
        q_norm = _norm(str(p.get("quote", "")))
        if (sec_norm, q_norm) in ok:
            st = next(c for c in verified if _norm_section(c["section"]) == sec_norm and _norm(c["quote"]) == q_norm)
            kept.append({**p, "section": st["section"], "id": st["id"], "source_page": st.get("source_page")})
    return kept


def _compose_summary_text(s: Dict[str, Any]) -> str:
    lines = [s["title"], "", s["summary"]]
    if s["key_points"]:
        lines += ["", "ประเด็นหลัก"]
        for p in s["key_points"]:
            heading = str(p.get("heading", "")).strip()
            exp = str(p.get("explanation", "")).strip()
            if heading and exp:
                lines.append(f"• {heading}: {exp}")
            elif exp:
                lines.append(f"• {exp}")
            elif heading:
                lines.append(f"• {heading}")
    if s["example"]:
        lines += ["", "ตัวอย่างให้เห็นภาพ", s["example"]]
    if s["notes"]:
        lines += ["", "จุดที่มักออกสอบ / ข้อสังเกตสำคัญ"]
        for p in s["notes"]:
            lines.append(f"• {str(p.get('point', '')).strip()}")
    return "\n".join(lines).strip()


def active_provider() -> str:
    if LLM_PROVIDER == "auto":
        return "anthropic" if claude_llm.credentials_configured() else "ollama"
    return LLM_PROVIDER


def active_model(mode: str = "answer") -> str:
    if active_provider() != "anthropic":
        return LLM_MODEL
    return claude_llm.CLAUDE_MODEL_SUMMARY if mode == "summary" else claude_llm.CLAUDE_MODEL


def _call_llm(question: str, statutes: List[Dict[str, Any]], feedback: str = "",
              system_prompt: str = SYSTEM_PROMPT) -> Dict[str, Any]:
    user = f"[ตัวบท]\n{_context(statutes)}\n\n[คำถาม]\n{question}"
    if feedback:
        user += f"\n\n[ข้อแก้ไข]\n{feedback}"
    if active_provider() == "anthropic":
        return claude_llm.call_claude(system_prompt, user, summary=system_prompt is SUMMARY_PROMPT)

    from openai import OpenAI

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=LLM_TIMEOUT)
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
    )
    return json.loads(resp.choices[0].message.content)


def _omitted_conditions(answer: str, verified: List[Dict[str, Any]],
                        statutes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """เงื่อนไขเชิงปริมาณ (ระยะเวลา/จำนวนเงิน/ร้อยละ) ในมาตราที่อ้าง ซึ่งคำตอบตกหล่น"""
    by_id = {s["id"]: s for s in statutes}
    out = []
    for sid in dict.fromkeys(c["id"] for c in verified):
        missing = quantities.omitted(answer, by_id[sid]["content"])
        if missing:
            out.append({"section": by_id[sid]["section"],
                        "missing": [quantities.describe(q) for q in sorted(missing, key=lambda q: (q[1], q[0]))]})
    return out


def _verify(llm_out: Dict[str, Any], statutes: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_section = {_norm_section(s["section"]): s for s in statutes}
    verified, rejected = [], []
    seen_citations = set()

    for c in llm_out.get("citations") or []:
        if not isinstance(c, dict):
            continue
        sec, quote = str(c.get("section", "")), str(c.get("quote", "")).strip()
        sec_n = _norm_section(sec)
        q_n = _norm(quote)
        if not sec_n and not q_n:
            continue
        pair_key = (sec_n, q_n)
        if pair_key in seen_citations:
            continue
        seen_citations.add(pair_key)

        st = by_section.get(sec_n)
        if st is None:
            rejected.append({"section": sec, "quote": quote, "reason": "มาตรานี้ไม่อยู่ในตัวบทที่ค้นพบ"})
        elif len(q_n) < MIN_QUOTE_CHARS or q_n not in _norm(st["content"]):
            rejected.append({"section": sec, "quote": quote, "reason": "ข้อความที่ยกมาไม่ตรงกับตัวบทจริง"})
        else:
            verified.append({"id": st["id"], "section": st["section"], "quote": quote,
                             "source_page": st.get("source_page"), "status": st.get("status", "active")})

    answer = str(llm_out.get("answer", ""))
    # มาตราที่ตัวบทที่ยกมาอ้างถึงเอง (เช่น ม.224 "ตามมาตรา ๗") ถือว่ามีที่มาในตัวบท
    allowed = set(by_section)
    for st in statutes:
        allowed |= {_norm_section(m.group(0)) for m in _SECTION_RE.finditer(st["content"])}
    unsupported = sorted({f"มาตรา {n}" for n in (_norm_section(m.group(0)) for m in _SECTION_RE.finditer(answer))
                          if n and n not in allowed})
    return {"verified_citations": verified, "rejected_citations": rejected,
            "unsupported_sections_in_answer": unsupported}


class LegalQA:
    def __init__(self, retriever: HybridLegalRetriever):
        self.retriever = retriever

    def ask(self, question: str, mode: str = "auto") -> Dict[str, Any]:
        """
        mode: "answer" ตอบคำถาม, "summary" สรุป/อธิบายมาตรา,
              "auto" เลือกสรุปเมื่อคำถามมีคำว่า สรุป/อธิบาย/ขยายความ
        """
        if mode == "auto":
            mode = "summary" if _SUMMARY_RE.search(question) else "answer"
        explicit = _explicit_sections(question)
        hits = self.retriever.retrieve(question, top_k=TOP_K, min_score_threshold=MIN_SCORE)
        statutes, seen = [], set()
        pool_main = _summary_context(explicit) if explicit else []
        if not pool_main and hits and mode == "summary":
            pool_main = _summary_context([hits[0]["statute"]])
        pool = (pool_main if pool_main else explicit) + [h["statute"] for h in hits]
        for s in pool:
            if s["id"] not in seen:
                seen.add(s["id"]); statutes.append(s)
        statutes = statutes[:SUMMARY_CONTEXT if mode == "summary" else TOP_K]

        base = {"question": question, "mode": mode, "provider": active_provider(), "model": active_model(mode),
                "retrieved_statutes": statutes}
        if not statutes:
            return {**base, "status": "ABSTAIN", "answer": "ไม่พบตัวบทที่เกี่ยวข้องในฐานข้อมูล จึงไม่ตอบเพื่อป้องกันความคลาดเคลื่อน",
                    "citations": [], "guardrails": {}}

        prompt = SUMMARY_PROMPT if mode == "summary" else SYSTEM_PROMPT
        length_hint = SHORT_SUMMARY_FEEDBACK if mode == "summary" and _SHORT_RE.search(question) else ""
        to_check = _summary_to_check if mode == "summary" else (lambda o: o)

        try:
            raw = _call_llm(question, statutes, length_hint, system_prompt=prompt)
        except Exception as e:  # โหลดโมเดลไม่ได้ / เชื่อมต่อไม่ได้ / โมเดลตอบไม่ใช่ JSON
            # การค้นตัวบททำงานสำเร็จแล้ว — ส่ง retrieved_statutes กลับไปให้ผู้ใช้อ่านเองได้
            return {**base, "status": "LLM_ERROR", "answer": "", "citations": [],
                    "guardrails": {}, **llm_error_fields(e)}

        llm_out = to_check(raw)
        checks = _verify(llm_out, statutes)
        verified = checks["verified_citations"]

        # ตรวจความครบของเงื่อนไข และตรวจว่ามี quote ผิดหรือมาตรานอกบริบทหรือไม่
        def omissions(out, ver):
            return _omitted_conditions(str(out.get("answer_without_example", out.get("answer", ""))), ver, statutes)

        omitted = omissions(llm_out, verified)
        needs_retry = bool(checks["rejected_citations"] or checks["unsupported_sections_in_answer"] or omitted)
        if needs_retry and not llm_out.get("insufficient"):
            issues = []
            if checks["rejected_citations"]:
                rej_items = [f"{r['section']} ข้อความ '{r['quote']}' ({r['reason']})" for r in checks["rejected_citations"]]
                issues.append("ข้อความอ้างอิงต่อไปนี้ตรวจไม่ผ่าน (ไม่มีในตัวบทจริงหรือดัดแปลงข้อความ): " + "; ".join(rej_items) +
                              " ห้ามแต่งหรือดัดแปลงข้อความ ห้ามอนุมานกรณีกลับด้านที่ตัวบทไม่ได้บัญญัติไว้ ให้ยกข้อความตรงตัวตามตัวบทที่ให้มาเท่านั้น")
            if checks["unsupported_sections_in_answer"]:
                issues.append("คำตอบอ้างถึงมาตราที่ไม่อยู่ในรายการตัวบท: " + ", ".join(checks["unsupported_sections_in_answer"]))
            if omitted:
                issues.append("คำตอบตกหล่นเงื่อนไขที่ตัวบทกำหนด: " + "; ".join(
                    f"{o['section']} ระบุ {', '.join(o['missing'])}" for o in omitted
                ) + " ให้ระบุเงื่อนไขทุกกรณีให้ครบ และยกข้อความจากตัวบทตรงตัว")

            feedback = " ".join(issues)
            try:
                retry_raw = _call_llm(question, statutes, " ".join(filter(None, [length_hint, feedback])),
                                      system_prompt=prompt)
                retry = to_check(retry_raw)
                retry_checks = _verify(retry, statutes)
                raw, llm_out, checks = retry_raw, retry, retry_checks
                verified = checks["verified_citations"]
                omitted = omissions(llm_out, verified)
            except Exception:
                pass
            checks["retried"] = True
        checks["omitted_conditions"] = omitted

        result = {**base, "citations": verified, "guardrails": checks}
        if mode == "summary":
            summary = {
                "title": str(raw.get("title") or "สรุปตัวบท"),
                "summary": str(raw.get("summary") or ""),
                "key_points": _keep_verified_points(raw.get("key_points"), verified),
                "example": str(raw.get("example") or ""),
                "notes": _keep_verified_points(raw.get("notes"), verified),
            }
            if summary["key_points"]:
                result["summary"] = summary
            verified_ok = bool(summary["key_points"])
        else:
            verified_ok = bool(verified)

        # เกณฑ์เข้มงวด: หากมี quote ที่ตรวจไม่ผ่าน หรืออ้างมาตรานอกบริบท ห้ามแสดงคำตอบ (ABSTAIN)
        has_rejected = bool(checks["rejected_citations"] or checks["unsupported_sections_in_answer"])
        if llm_out.get("insufficient") or not verified_ok or has_rejected:
            status = "ABSTAIN"
            if llm_out.get("insufficient"):
                answer = str(raw.get("answer") or raw.get("summary") or "ตัวบทที่ค้นพบไม่เพียงพอสำหรับตอบคำถามนี้")
            elif has_rejected:
                answer = "ระบบตรวจพบว่าคำตอบมีข้อความอ้างอิงที่ไม่ตรงกับตัวบทจริง จึงไม่แสดงคำตอบเพื่อป้องกันความคลาดเคลื่อน กรุณาศึกษาจากตัวบทเต็มด้านล่าง"
            else:
                answer = "ไม่สามารถยืนยันอ้างอิงกับตัวบทจริงได้ จึงไม่แสดงคำตอบเพื่อป้องกันความคลาดเคลื่อน กรุณาศึกษาจากตัวบทเต็มด้านล่าง"
            result.pop("summary", None)
            result["citations"] = []
        else:
            clean = (not checks["omitted_conditions"])
            status = "CITATIONS_VERIFIED" if clean else "CITATIONS_PARTIAL"
            answer = _compose_summary_text(result["summary"]) if mode == "summary" else str(raw.get("answer", ""))

        return {**result, "status": status, "answer": answer}
