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

ใช้เฉพาะโมเดลฟรี (ไม่เสียค่าใช้จ่าย):

| เงื่อนไข | โมเดลที่ใช้ |
|---|---|
| มี `GROQ_API_KEY` | Groq (แผน Free) — ผู้ใช้เลือกโมเดลบนหน้าเว็บ: `openai/gpt-oss-120b` (ค่าเริ่มต้น), `openai/gpt-oss-20b`, `qwen/qwen3.8-27b` |
| ไม่มี key | Ollama ในเครื่อง — `qwen2.5:7b` ที่ `http://localhost:11434` |

บังคับเลือกได้ด้วย `LEGAL_AI_LLM_PROVIDER=auto|groq|ollama`
แผน Free ของ Groq จำกัด 30 คำขอ/นาที, 1,000 คำขอ/วัน, 8K tokens/นาที และ 200K tokens/วัน ต่อโมเดล
(เกินโควตาจะเห็น `LLM_RATE_LIMIT` — รอสักครู่หรือเลือกโมเดลอื่น)
Claude API (`anthropic`) เสียค่าใช้จ่าย จึงไม่ถูกเลือกอัตโนมัติ — ใช้ได้เฉพาะเมื่อตั้ง `LEGAL_AI_LLM_PROVIDER=anthropic` ตรงๆ

**ห้ามใส่ API key ในไฟล์ใด ๆ ในโฟลเดอร์นี้** (โฟลเดอร์ซิงก์กับ OneDrive) — ตั้งเป็นตัวแปร environment เท่านั้น

---

## 🚀 รันบนเครื่อง

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

เปิด <http://127.0.0.1:8000>

ใช้ Groq: สร้าง key ฟรีที่ <https://console.groq.com/keys> แล้ว `setx GROQ_API_KEY "gsk_..."` และเปิด terminal ใหม่
ใช้ Ollama: `ollama pull qwen2.5:7b` — เครื่องต้องมี RAM/VRAM พอโหลดโมเดล (ถ้าไม่พอจะเห็น `LLM_OUT_OF_MEMORY`)

## ☁️ Deploy บน Vercel

Vercel ตรวจพบ FastAPI เองและเริ่มแอปจาก `app.py` — ไฟล์ที่เกี่ยวข้อง: `vercel.json` (ตั้ง `maxDuration`), `.vercelignore`

1. ตั้ง Environment Variables ใน Vercel → Project → Settings → Environment Variables
   - `GROQ_API_KEY` — **จำเป็น** (Vercel ไม่มี Ollama)
   - `LEGAL_AI_LLM_PROVIDER` = `groq` — ให้ขึ้นข้อความ "ยังไม่ได้ตั้งค่า key" แทนการพยายามต่อ Ollama ถ้าลืมตั้ง key
2. Deploy: `npx vercel` (ทดสอบ) แล้ว `npx vercel --prod`
3. ตรวจหลัง deploy: เปิดหน้าเว็บ, `GET /api/status` ต้องได้ `"provider": "groq", "configured": true`, ลองถามหนึ่งคำถาม

ข้อควรรู้เมื่อรันบน Vercel:

- **ฐานข้อมูลเป็นแบบอ่านอย่างเดียว** — คัดลอก `data/legal_ai.db` ไปที่ `/tmp` ของแต่ละ instance ตอนเริ่ม
  (ล้างประวัติคำถามจากเครื่องพัฒนาออก) การแก้ตัวบท (`POST/PUT/DELETE /api/statutes`) และประวัติ (`/api/history`)
  จะตอบ `403` เพราะเว็บสาธารณะไม่มีระบบล็อกอิน และข้อมูลใน `/tmp` หายเมื่อ instance ปิด
- **โควตา:** ทุกคนที่มีลิงก์ถามได้ และแต่ละคำถามเรียก Groq 1–2 ครั้ง ใช้โควตาฟรีร่วมกันทั้งเว็บ —
  ถ้าคนใช้มากจะเจอ `LLM_RATE_LIMIT` บ่อย แนะนำแชร์ลิงก์เฉพาะคนที่ต้องการ
- **เวลาตอบ:** ตั้ง `maxDuration` ไว้ 300 วินาที (คำถามที่ต้องถามซ้ำอาจใช้เวลาเกิน 60 วินาที)
  ถ้าแผน Vercel ของคุณจำกัดต่ำกว่านี้ ให้ลดค่าใน `vercel.json`

## 💬 ความคิดเห็นผู้ใช้ (v2)

ผู้ใช้ให้คะแนนคำตอบ (👍/👎 + ความคิดเห็น), รีวิวเว็บไซต์ (1–5 ดาว) และแจ้งตัวบทผิด (ปุ่มบนการ์ดมาตรา) ได้
โดยใส่ชื่อเล่น/นามแฝงหรือไม่ระบุชื่อก็ได้ — **ไม่เก็บ IP อีเมล หรือเบอร์โทร** มีกับดักสแปมและจำกัด 10 ครั้ง/10 นาทีต่อ IP

ที่เก็บ: Google Sheet (บน Vercel) หรือตาราง `feedback` ใน SQLite (บนเครื่อง ถ้ายังไม่ได้ตั้งค่า Sheet)
บน Vercel ถ้ายังไม่ตั้งค่า Sheet ระบบจะปิดและซ่อนปุ่มทั้งหมด (ไม่รับข้อมูลที่จะหายไปกับ `/tmp`)

ตั้งค่า Google Sheet (ครั้งเดียว):
1. สร้าง Google Sheet → ส่วนขยาย → Apps Script → วางโค้ดจาก `tools/feedback_apps_script.gs`
   แล้วแก้ `SECRET` เป็นรหัสลับยาวๆ ของคุณ
2. Deploy → New deployment → Web app · Execute as: **Me** · Who has access: **Anyone** → คัดลอก Web app URL
3. ใน Vercel ตั้ง `FEEDBACK_SCRIPT_URL` (URL จากข้อ 2), `FEEDBACK_SECRET` (ค่าเดียวกับ `SECRET`)
   และ `ADMIN_PASSWORD` (รหัสเข้าหน้าผู้ดูแล) — ห้ามใส่ค่าเหล่านี้ในไฟล์ใดในโฟลเดอร์นี้

หน้าผู้ดูแล: `/admin` — ใส่ `ADMIN_PASSWORD` เพื่อดูสรุป (จำนวน, ดาวเฉลี่ย, 👍/👎 แยกตามโมเดล), รายการ และดาวน์โหลด CSV
(ใส่รหัสผิด 5 ครั้งจะถูกพัก 10 นาที)

## ⚙️ ตัวแปร environment

| ตัวแปร | ค่าเริ่มต้น | ใช้ทำอะไร |
|---|---|---|
| `GROQ_API_KEY` | — | ใช้ Groq (ฟรีภายใต้โควตา) |
| `LEGAL_AI_LLM_PROVIDER` | `auto` | `auto` / `groq` / `ollama` (`anthropic` = Claude แบบเสียเงิน ต้องตั้งเอง) |
| `LEGAL_AI_GROQ_MODEL` | `openai/gpt-oss-120b` | โมเดล Groq เริ่มต้น |
| `LEGAL_AI_GROQ_MAX_TOKENS` | `8000` | เพดาน tokens (การคิด + คำตอบ) ของ Groq |
| `LEGAL_AI_CLAUDE_MODEL` | `claude-opus-5-5` | โมเดล Claude (โหมดตอบคำถาม) |
| `LEGAL_AI_CLAUDE_MODEL_SUMMARY` | ค่าเดียวกับ `LEGAL_AI_CLAUDE_MODEL` | โมเดล Claude โหมดสรุป/อธิบาย |
| `LEGAL_AI_CLAUDE_EFFORT` | `high` | ระดับ effort ของ Claude (โหมดตอบคำถาม) |
| `LEGAL_AI_CLAUDE_EFFORT_SUMMARY` | ค่าเดียวกับ `LEGAL_AI_CLAUDE_EFFORT` | ระดับ effort โหมดสรุป/อธิบาย |
| `LEGAL_AI_LLM_BASE_URL` | `http://localhost:11434/v1` | ที่อยู่ Ollama |
| `LEGAL_AI_LLM_MODEL` | `qwen2.5:7b` | โมเดล Ollama |
| `LEGAL_AI_LLM_TIMEOUT` | `180` | timeout (วินาที) ของ Ollama |
| `FEEDBACK_SCRIPT_URL` | — | URL ของ Apps Script ที่บันทึกความคิดเห็นลง Google Sheet |
| `FEEDBACK_SECRET` | — | รหัสลับเดียวกับ `SECRET` ใน Apps Script |
| `ADMIN_PASSWORD` | — | รหัสเข้าหน้า `/admin` (ไม่ตั้ง = ปิดหน้าผู้ดูแล) |
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
| `legal_engine/feedback.py`, `tools/feedback_apps_script.gs` | ความคิดเห็นผู้ใช้ และสคริปต์ Google Sheet |
| `static/admin.html` | หน้าผู้ดูแล (ดูความคิดเห็น) |
| `legal_engine/groq_llm.py` | เชื่อมต่อ Groq และรายการโมเดลที่เลือกได้ |
| `legal_engine/claude_llm.py` | เชื่อมต่อ Claude API (เสียเงิน ไม่ใช้โดยอัตโนมัติ) และ JSON schema ของคำตอบ |
| `legal_engine/hybrid_retriever.py` | ค้นหาตัวบท |
| `legal_engine/database.py` | ฐานข้อมูล SQLite |
| `ingest_pdf.py`, `legal_engine/pdf_extract.py` | นำเข้าตัวบทจาก PDF |
| `static/` | หน้าเว็บ |
| `tests/`, `tools/verify_sections.py` | ชุดทดสอบและตรวจความครบของมาตรา |
