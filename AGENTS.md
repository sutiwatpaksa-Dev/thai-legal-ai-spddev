# Agent Guide — Thai Legal AI

Two AI agents work in this folder: **Claude (Claude Code)** and **Gemini (Antigravity)**.
Each agent edits **only the files in its own scope**. To get a change in the other agent's
files, add an item under **Requests** at the bottom. The user's decisions below override
everything else in this file.

_Last updated: 2026-10-04 by Claude._

## What the app is

Two sections only (user decision, 2026-10-04):

1. **ถาม-ตอบกฎหมาย** — AI answer from real statute text (`POST /api/ask`), or search without AI
   (`POST /api/search`). Questions containing สรุป / อธิบาย / ขยายความ switch to summary mode;
   สั้น / ย่อ / กระชับ asks for a short summary.
2. **คลังตัวบทกฎหมาย** (Knowledge Base) — browse and search every section (`GET /api/statutes`).

Removed at the user's request and **must not come back**: the FIRAC analysis tab (`/api/analyze`),
the Check Q&A tab (`/api/check-qa`, `/api/qa`), the guardrails explainer tab, the LLM settings tab.

## User decisions (binding)

| Date | Decision |
|---|---|
| 2026-10-04 | Only the two sections above. |
| 2026-10-04 | **No mock data.** Statute text comes only from a source document; answers only from the real Q&A pipeline; no hard-coded verdicts, scores or answers. |
| 2026-10-04 | **Strict abstention & Neighboring context**: If any quote fails verification or a section is invented, AI is retried once with feedback; if it still fails, it must strictly ABSTAIN and not display any hallucinated answer (no yellow partial warning banner with false content). Retrieved statutes are enriched with the foundational section (e.g. ม.341 for หักกลบลบหนี้) and neighboring sections of the same chapter/part. Quotes are deduplicated before scoring. |
| 2026-10-04 | **Free models only — the user does not want to pay.** Q&A uses **Groq** (free plan) when `GROQ_API_KEY` is set, otherwise Ollama `qwen2.5:7b`. Users pick the Groq model in the web UI: `openai/gpt-oss-120b` (default), `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`, each shown with a description. The paid Claude API is never chosen automatically (only with an explicit `LEGAL_AI_LLM_PROVIDER=anthropic`). Override with `LEGAL_AI_LLM_PROVIDER=auto\|groq\|ollama`. Supersedes the earlier Claude-first decision. |
| 2026-10-04 | Fixes from the user's UI test report (error handling, health badge, mobile layout, search, accessibility) are implemented; the Knowledge Base tab is named **คลังตัวบทกฎหมาย** because only the civil code is complete. |

## Current state

- **Database** `data/legal_ai.db`: 1,872 sections — the complete ประมวลกฎหมายแพ่งและพาณิชย์ from
  `code_lawyer.pdf` (sections 1–1,755, 116 slash sections, 37 repealed). The 8 hand-written
  criminal/PDPA/labour sections (no source document) were removed at 5:34–5:39 PM, so every
  section now comes from a source document.
- **API key:** never put an API key in any file in this folder (it is synced to OneDrive and read
  by both agents). The app reads `GROQ_API_KEY` (and the opt-in `ANTHROPIC_API_KEY`) from the environment only.
- **Q&A safety checks** (`legal_engine/qa.py`): every quote must exist in the cited section;
  sections not provided are rejected; answers that drop a time limit, amount or percentage from a
  cited section are retried once, then flagged; failures return `ABSTAIN`.
- **AI health**: `GET /api/status?probe=true` makes the local model generate 1 token (forces a real
  load); every `/api/ask` result also updates health. Raw errors go to the server log only
  (`LEGAL_AI_DEBUG=1` shows them to admins).
- **Vercel**: auto-detects FastAPI and starts from `app.py` (no `api/` entrypoint, no rewrites); `app.py`
  points PyThaiNLP at `/tmp` before importing `legal_engine`. Needs `GROQ_API_KEY` and `LEGAL_AI_LLM_PROVIDER=groq` (no Ollama there). The DB is copied to `/tmp` with history cleared;
  statute writes and `/api/history` return 403 when `VERCEL` is set (public site, no login).
- **Known environment issue**: this PC often lacks RAM/VRAM to load `qwen2.5:7b`
  (`LLM_OUT_OF_MEMORY`). Not a code bug — free memory, restart Ollama, or use Groq.

## Scope: Claude — data, backend, Q&A, web UI, tests

| Area | Files |
|---|---|
| PDF extraction and import | `legal_engine/pdf_extract.py`, `ingest_pdf.py` |
| Section verification | `tools/verify_sections.py` |
| Database layer and schema | `legal_engine/database.py`, `data/legal_ai.db` |
| API (all endpoints) and Vercel deploy | `app.py`, `vercel.json`, `.vercelignore` |
| Q&A pipeline, citation and completeness checks | `legal_engine/qa.py`, `legal_engine/quantities.py` |
| Groq and Claude API connections | `legal_engine/groq_llm.py`, `legal_engine/claude_llm.py` |
| Web UI (owned by Claude since the user's 2026-10-04 request) | `static/**` |
| Test suite | `tests/**` |

## Scope: Gemini (Antigravity) — search quality

| Area | Files |
|---|---|
| Search ranking and abstention threshold | `legal_engine/hybrid_retriever.py` |
| Hand-written statutes outside the civil code | `legal_engine/knowledge_base.py` |

**No longer used by the app** (kept only because the folder has no git history; delete on the
user's go-ahead): `legal_engine/legal_reasoner.py`, `legal_engine/guardrails.py`,
`legal_engine/llm_connector.py`, `test_engine.py`.

## Data contract (both agents rely on this)

- **Source of truth:** the SQLite `statutes` table via `legal_engine/database.py`
  (`db.list_statutes()`). The retriever is built from that list.
- **Statute fields:** `id, category, book, title, section, content, keywords[], elements[],
  status ("active" | "repealed"), source, source_page`. `title` is the real heading path from
  the PDF, e.g. `ลักษณะ 5 ละเมิด › หมวด 1 ความรับผิดเพื่อละเมิด`.
- **`content` keeps the PDF's Thai digits** ("ตามมาตรา ๓๕"); `section` uses Arabic digits
  (`มาตรา 35`). All search and citation code must treat ๐-๙ and 0-9 as the same.
- **IDs:** `CCC-<number>`; a slash becomes a hyphen (`มาตรา 1264/1` → `CCC-1264-1`); ทวิ → `-bis`.
- Hand-written `keywords`/`elements` are kept for 420, 425, 437, 149, 150, 653; all other civil-code
  sections have empty lists. Never fill them with placeholders.
- **UI numbers:** Arabic digits in labels, buttons and counts; statute text keeps Thai digits.

## Working rules

1. Don't edit files outside your scope. Need a change there? Add a Request below.
2. Scratch and debug scripts go in your own temp directory, never the project root.
3. Don't change the data contract or a user decision without the user.
4. Before saying work is done, run:
   - `python -m unittest discover -s tests` (126 tests; uses a temporary copy of the DB; live-AI
     tests skip themselves with a reason when the model can't load)
   - `python tools/verify_sections.py` (must exit 0)

## Requests

### Open

- **Claude → user:** the มาตรา 252 text ends with the sub-heading "๑. บุริมสิทธิสามัญ" (a heading of
  the form "๑. …" merged into the previous section). Fix in `ingest_pdf.py` on the user's go-ahead.
- **Claude → Gemini (`hybrid_retriever.py`):** off-topic questions still retrieve statutes above
  `MIN_SCORE` 0.8 — e.g. "สูตรทำขนมเค้กช็อกโกแลต" returned contract/agency/privilege/will sections, so the
  AI was called and had to abstain itself. On the free Groq plan (200K tokens/day per model) each such
  call wastes ~4K tokens of the shared quota. Please make the retriever return no hits for questions with
  no legal terms, so `qa.ask` abstains before calling the AI. `tests/` cover the in-scope questions.

### Done

- Strict abstention on quote failure (no yellow partial warning on hallucinated text), retry loop with feedback, quote deduplication, neighboring statutes enrichment (ดึงมาตราต้นหมวดและมาตราข้างเคียง 2-3 มาตรา), and anti-reverse inference prompt updated (Gemini).
- Section extraction in `hybrid_retriever.py` requires มาตรา/ม. prefix (or standalone number queries), supports Thai digits and multi-section lists (เช่น `ม.420, 425`), and prevents amounts like "โอนเงิน 45,000 บาท" from matching section 45 (Gemini).
- The 8 hand-written statutes without a source document removed (Gemini, 5:34–5:39 PM).
- Scratch files removed from the project root (Gemini).
- `statutes_ccc.json` and its loader removed; placeholder-elements bonus removed (Gemini).
- PDF import complete and verified (Claude).
- Mock `/api/qa` and fixed-score `/api/check-qa` removed; real Q&A at `/api/ask` (Claude).
