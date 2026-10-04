# ⚖️ Thai Legal AI
### ถาม-ตอบกฎหมายจากตัวบทจริง และคลังตัวบทประมวลกฎหมายแพ่งและพาณิชย์

แอปมี 2 ส่วน:

1. **ถาม-ตอบกฎหมาย** — ค้นตัวบทที่เกี่ยวข้อง แล้วให้ AI ตอบโดยยกข้อความจากตัวบทจริง (`POST /api/ask`)
   หรือค้นหาตัวบทอย่างเดียวโดยไม่ใช้ AI (`POST /api/search`)
   - คำถามที่มีคำว่า **สรุป / อธิบาย / ขยายความ** จะตอบแบบสรุป; ถ้ามี **สั้น / ย่อ / กระชับ** จะสรุปแบบสั้น
2. **คลังตัวบทกฎหมาย** — เปิดดูและค้นหาได้ทุกมาตรา (`GET /api/statutes`)

---

## 📚 ข้อมูลตัวบท

- ฐานข้อมูล `data/legal_ai.db` มี **1,872 มาตรา** — ประมวลกฎหมายแพ่งและพาณิชย์ฉบับเต็ม
  (มาตรา 1–1,755, มาตราย่อยแบบ "/" 116 มาตรา, มาตราที่ถูกยกเลิก 37 มาตรา)
- นำเข้าจาก `code_lawyer.pdf` ด้วย `ingest_pdf.py` — ทุกมาตรามาจากเอกสารต้นฉบับ ไม่มีข้อมูลสมมติ
- ข้อความตัวบทใช้เลขไทยตามต้นฉบับ (เช่น "ตามมาตรา ๓๕"); การค้นหาและการตรวจอ้างอิงถือว่า ๐-๙ กับ 0-9 เป็นตัวเดียวกัน
- ยังไม่มีประมวลกฎหมายอาญา, พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล หรือกฎหมายแรงงาน

## 🛡️ การป้องกันคำตอบที่แต่งขึ้น (`legal_engine/qa.py`)

- **ค้นตัวบท:** BM25 + ตัดคำด้วย PyThaiNLP + จับเลขมาตรา (`มาตรา 420`, `ม.420, 425`, เลขไทย) และเติมมาตราต้นเรื่อง/มาตราข้างเคียงในหมวดเดียวกัน
- **ตรวจอ้างอิงทุกข้อ:** ข้อความที่ AI ยกมาต้องมีอยู่จริงในมาตราที่อ้าง และมาตราต้องอยู่ในชุดที่ส่งให้ AI
- **ตรวจความครบถ้วน:** ถ้าคำตอบตกหล่นระยะเวลา จำนวนเงิน หรือร้อยละที่อยู่ในมาตราที่อ้าง จะให้ AI ตอบใหม่
- **ถามซ้ำ 1 ครั้งแล้วงดตอบ:** ตรวจไม่ผ่านจะให้ AI แก้หนึ่งครั้ง ถ้ายังไม่ผ่านจะงดตอบ (`ABSTAIN`) — ไม่แสดงคำตอบที่ตรวจไม่ผ่าน

> สถานะ "ตรวจอ้างอิงผ่าน" ยืนยันว่าข้อความที่ยกมามีอยู่จริงในตัวบท แต่ไม่ได้ยืนยันว่าข้อสรุปถูกต้องครบถ้วน
> ผู้ใช้ควรอ่านตัวบทที่แนบมาประกอบทุกครั้ง และไม่ควรใช้แทนคำปรึกษาจากนักกฎหมาย

## 🤖 โมเดล AI

| เงื่อนไข | โมเดลที่ใช้ |
|---|---|
| มี `ANTHROPIC_API_KEY` (หรือ `ANTHROPIC_AUTH_TOKEN`) | Claude API — `claude-opus-5-5` |
| ไม่มี key | Ollama ในเครื่อง — `qwen2.5:7b` ที่ `http://localhost:11434` |

บังคับเลือกได้ด้วย `LEGAL_AI_LLM_PROVIDER=auto|anthropic|ollama`

**ห้ามใส่ API key ในไฟล์ใด ๆ ในโฟลเดอร์นี้** (โฟลเดอร์ซิงก์กับ OneDrive) — ตั้งเป็นตัวแปร environment เท่านั้น

---

## 🚀 รันบนเครื่อง

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

เปิด <http://127.0.0.1:8000>

ใช้ Claude API: `setx ANTHROPIC_API_KEY "sk-ant-..."` แล้วเปิด terminal ใหม่
ใช้ Ollama: `ollama pull qwen2.5:7b` — เครื่องต้องมี RAM/VRAM พอโหลดโมเดล (ถ้าไม่พอจะเห็น `LLM_OUT_OF_MEMORY`)

## ☁️ Deploy บน Vercel

Vercel ตรวจพบ FastAPI เองและเริ่มแอปจาก `app.py` — ไฟล์ที่เกี่ยวข้อง: `vercel.json` (ตั้ง `maxDuration`), `.vercelignore`

1. ตั้ง Environment Variables ใน Vercel → Project → Settings → Environment Variables
   - `ANTHROPIC_API_KEY` — **จำเป็น** (Vercel ไม่มี Ollama)
   - `LEGAL_AI_LLM_PROVIDER` = `anthropic` — ให้ขึ้นข้อความ "ยังไม่ได้ตั้งค่า key" แทนการพยายามต่อ Ollama ถ้าลืมตั้ง key
2. Deploy: `npx vercel` (ทดสอบ) แล้ว `npx vercel --prod`
3. ตรวจหลัง deploy: เปิดหน้าเว็บ, `GET /api/status` ต้องได้ `"provider": "anthropic", "configured": true`, ลองถามหนึ่งคำถาม

ข้อควรรู้เมื่อรันบน Vercel:

- **ฐานข้อมูลเป็นแบบอ่านอย่างเดียว** — คัดลอก `data/legal_ai.db` ไปที่ `/tmp` ของแต่ละ instance ตอนเริ่ม
  (ล้างประวัติคำถามจากเครื่องพัฒนาออก) การแก้ตัวบท (`POST/PUT/DELETE /api/statutes`) และประวัติ (`/api/history`)
  จะตอบ `403` เพราะเว็บสาธารณะไม่มีระบบล็อกอิน และข้อมูลใน `/tmp` หายเมื่อ instance ปิด
- **ค่าใช้จ่าย:** ทุกคนที่มีลิงก์ถามได้ และแต่ละคำถามเรียก Claude Opus 1–2 ครั้ง — แนะนำเปิด
  Vercel Deployment Protection หรือแชร์ลิงก์เฉพาะคนที่ต้องการ และตั้งวงเงินใน Anthropic Console
- **เวลาตอบ:** ตั้ง `maxDuration` ไว้ 300 วินาที (คำถามที่ต้องถามซ้ำอาจใช้เวลาเกิน 60 วินาที)
  ถ้าแผน Vercel ของคุณจำกัดต่ำกว่านี้ ให้ลดค่าใน `vercel.json` หรือ `LEGAL_AI_CLAUDE_EFFORT=medium`

## ⚙️ ตัวแปร environment

| ตัวแปร | ค่าเริ่มต้น | ใช้ทำอะไร |
|---|---|---|
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | — | ใช้ Claude API |
| `LEGAL_AI_LLM_PROVIDER` | `auto` | `auto` / `anthropic` / `ollama` |
| `LEGAL_AI_CLAUDE_MODEL` | `claude-opus-5-5` | โมเดล Claude (โหมดตอบคำถาม) |
| `LEGAL_AI_CLAUDE_MODEL_SUMMARY` | ค่าเดียวกับ `LEGAL_AI_CLAUDE_MODEL` | โมเดล Claude โหมดสรุป/อธิบาย |
| `LEGAL_AI_CLAUDE_EFFORT` | `high` | ระดับ effort ของ Claude (โหมดตอบคำถาม) |
| `LEGAL_AI_CLAUDE_EFFORT_SUMMARY` | ค่าเดียวกับ `LEGAL_AI_CLAUDE_EFFORT` | ระดับ effort โหมดสรุป/อธิบาย |
| `LEGAL_AI_LLM_BASE_URL` | `http://localhost:11434/v1` | ที่อยู่ Ollama |
| `LEGAL_AI_LLM_MODEL` | `qwen2.5:7b` | โมเดล Ollama |
| `LEGAL_AI_LLM_TIMEOUT` | `180` | timeout (วินาที) ของ Ollama |
| `LEGAL_AI_DB` | `data/legal_ai.db` | ที่อยู่ฐานข้อมูล |
| `LEGAL_AI_DEBUG` | — | `1` = แสดงรายละเอียด error ของ AI ในผลลัพธ์ |

## 🧪 ทดสอบ

```powershell
.\.venv\Scripts\python -m unittest discover -s tests   # ใช้สำเนาฐานข้อมูลชั่วคราว
.\.venv\Scripts\python tools/verify_sections.py        # ต้องจบด้วย exit code 0
```

## 📁 โครงสร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | FastAPI — ทุก endpoint, ให้บริการหน้าเว็บ และเป็นจุดเริ่มแอปบน Vercel |
| `legal_engine/qa.py` | ถาม-ตอบ ตรวจอ้างอิงและความครบถ้วน |
| `legal_engine/claude_llm.py` | เชื่อมต่อ Claude API |
| `legal_engine/hybrid_retriever.py` | ค้นหาตัวบท |
| `legal_engine/database.py` | ฐานข้อมูล SQLite |
| `ingest_pdf.py`, `legal_engine/pdf_extract.py` | นำเข้าตัวบทจาก PDF |
| `static/` | หน้าเว็บ |
| `tests/`, `tools/verify_sections.py` | ชุดทดสอบและตรวจความครบของมาตรา |
