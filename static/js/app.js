/**
 * Thai Legal AI — คลังตัวบทกฎหมาย + ถาม-ตอบอ้างอิงตัวบทจริง
 *
 * หลักการแสดงตัวเลข: ส่วนติดต่อผู้ใช้ (ป้าย ปุ่ม จำนวน) ใช้เลขอารบิกทั้งหมด
 * ส่วนเนื้อหาตัวบทคงเลขไทยตามต้นฉบับ PDF
 */

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initAsk();
  initKnowledgeBase();
  initFeedback();
  loadSystemStatus();
});

// ---------- Utilities ----------

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const THAI_DIGITS = "๐๑๒๓๔๕๖๗๘๙";
const toArabic = s => s.replace(/[๐-๙]/g, d => String(THAI_DIGITS.indexOf(d)));
const toThai = s => s.replace(/[0-9]/g, d => THAI_DIGITS[Number(d)]);
const fmt = n => Number(n).toLocaleString("en-US");
const escapeRegExp = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function postJson(url, body) {
  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    throw new ApiError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้", 0);
  }
  if (!res.ok) {
    // ไม่แสดงรายละเอียดภายในของ server ให้ผู้ใช้
    throw new ApiError(res.status >= 500 ? "ระบบขัดข้องชั่วคราว กรุณาลองใหม่" : "คำขอไม่ถูกต้อง", res.status);
  }
  return res.json();
}

/** ไฮไลต์คำค้นในข้อความที่ escape แล้ว (คำค้นต้องผ่าน escape ด้วย) */
function highlight(escapedText, terms) {
  const usable = (terms || []).filter(t => t && t.length >= 2);
  if (!usable.length) return escapedText;
  const re = new RegExp(`(${usable.map(t => escapeRegExp(escapeHtml(t))).join("|")})`, "gi");
  return escapedText.replace(re, "<mark>$1</mark>");
}

function statuteMeta(s) {
  const parts = [];
  if (s.book) parts.push(escapeHtml(s.book));
  if (s.title && s.title !== s.book) parts.push(escapeHtml(s.title));
  return parts.join(" › ");
}

const REPEALED_ONLY = /^(?:มาตรา\s*[๐-๙0-9]+\s*ถึง\s*มาตรา\s*[๐-๙0-9]+\s*)?[\[(]?\s*ยกเลิก\s*[\])]?$/;

function formatStatuteContent(content, isRepealed = false, terms = []) {
  if (!content) return "";
  if (isRepealed && REPEALED_ONLY.test(content.trim())) {
    return `<div class="statute-repealed-notice"><span class="repealed-tag">${escapeHtml(content.trim())}</span> มาตรานี้ถูกยกเลิกแล้ว</div>`;
  }

  const lines = content.split("\n").map(l => l.trim()).filter(Boolean);
  if (lines.length === 0) return "";

  // อนุมาตรา: (๑), (1), (๔/๑) และ (ก), (a)
  const reClause1 = /^(\([0-9๐-๙]+(?:\/[0-9๐-๙]+)?\))\s*(.*)/;
  const reClause2 = /^(\([ก-ฮa-zA-Z]\))\s*(.*)/;
  const totalParas = lines.filter(l => !reClause1.test(l) && !reClause2.test(l)).length;
  const hl = text => highlight(escapeHtml(text), terms);

  let paraCount = 0;
  return lines.map(line => {
    const m1 = line.match(reClause1);
    const m2 = !m1 && line.match(reClause2);
    if (m1 || m2) {
      const m = m1 || m2;
      return `<div class="statute-subclause ${m1 ? "level-1" : "level-2"}">
          <span class="clause-num">${escapeHtml(m[1])}</span><span class="clause-body">${hl(m[2])}</span></div>`;
    }
    paraCount++;
    const label = totalParas > 1 ? ` data-para="วรรค ${paraCount}"` : "";
    return `<p class="statute-para"${label}>${hl(line)}</p>`;
  }).join("");
}

function copyStatuteText(id, btn) {
  const s = kb.byId.get(id);
  if (!s) return;
  const titleInfo = s.title ? ` (${s.title})` : (s.book ? ` (${s.book})` : "");
  navigator.clipboard.writeText(`${s.section}${titleInfo}\n\n${s.content}`).then(() => {
    const label = btn.querySelector("span");
    const orig = label.textContent;
    label.textContent = "คัดลอกแล้ว";
    btn.classList.add("copied");
    setTimeout(() => { label.textContent = orig; btn.classList.remove("copied"); }, 1800);
  }).catch(() => {});
}

const LONG_CONTENT = 420;   // ตัวบทยาวกว่านี้จะพับไว้ในรายการผลค้นหา

/**
 * การ์ดตัวบท
 * opts.extra: HTML ป้ายเพิ่มเติม, opts.terms: คำที่ไฮไลต์, opts.collapsible: พับตัวบทยาว
 */
function statuteCard(s, opts = {}) {
  const repealed = s.status === "repealed";
  const collapsible = opts.collapsible && (s.content || "").length > LONG_CONTENT;
  return `
    <article class="statute-card${repealed ? " repealed" : ""}">
      <div class="statute-card-top">
        <span class="statute-badge">${escapeHtml(s.category || "")}</span>
        ${repealed ? `<span class="repealed-badge">ยกเลิกแล้ว</span>` : ""}
        ${opts.extra || ""}
        <button type="button" class="copy-sec-btn report-btn fb-only" data-report="${escapeHtml(s.section)}" aria-label="แจ้งว่าข้อความ${escapeHtml(s.section)}ผิด">
          <span>แจ้งตัวบทผิด</span>
        </button>
        <button type="button" class="copy-sec-btn" data-copy="${escapeHtml(s.id)}" aria-label="คัดลอก${escapeHtml(s.section)}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          <span>คัดลอก</span>
        </button>
      </div>
      <h3 class="statute-sec">${escapeHtml(s.section)}</h3>
      <div class="statute-title">${statuteMeta(s)}</div>
      <div class="statute-content authentic-book-format${collapsible ? " collapsed" : ""}">${formatStatuteContent(s.content, repealed, opts.terms)}</div>
      ${collapsible ? `<button type="button" class="expand-btn" aria-expanded="false">อ่านทั้งมาตรา ▾</button>` : ""}
      <div class="statute-source">${s.source_page ? `ที่มา: ${escapeHtml(s.source || "")} หน้า ${s.source_page}` : `ที่มา: ${escapeHtml(s.source || "ไม่ระบุ")}`}</div>
    </article>`;
}

// ปุ่มในการ์ด (คัดลอก / ขยาย) ใช้ event delegation — ไม่ใช้ inline onclick
document.addEventListener("click", e => {
  const copyBtn = e.target.closest("[data-copy]");
  if (copyBtn) return copyStatuteText(copyBtn.dataset.copy, copyBtn);
  const expandBtn = e.target.closest(".expand-btn");
  if (expandBtn) {
    const content = expandBtn.previousElementSibling;
    const expanded = content.classList.toggle("collapsed") === false;
    expandBtn.setAttribute("aria-expanded", String(expanded));
    expandBtn.textContent = expanded ? "ย่อ ▴" : "อ่านทั้งมาตรา ▾";
  }
});

/** ป้ายความเกี่ยวข้องแทนคะแนนดิบ (เทียบกับผลอันดับ 1) */
function relevanceTag(score, topScore) {
  const ratio = topScore > 0 ? score / topScore : 0;
  const [cls, label] = ratio >= 0.6 ? ["high", "เกี่ยวข้องมาก"] : ratio >= 0.3 ? ["mid", "เกี่ยวข้องปานกลาง"] : ["low", "เกี่ยวข้องน้อย"];
  return `<span class="relevance-tag ${cls}">${label}</span>`;
}

// ---------- Tabs ----------

function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  const contents = document.querySelectorAll(".tab-content");
  // จำตำแหน่งเลื่อนของแต่ละแท็บ — เปิดแท็บครั้งแรกเริ่มที่ด้านบน ไม่ค้างตำแหน่งของแท็บก่อนหน้า
  const scrollByTab = {};
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const current = document.querySelector(".tab-btn.active");
      if (current === tab) return;
      if (current) scrollByTab[current.dataset.tab] = window.scrollY;
      tabs.forEach(t => { t.classList.remove("active"); t.setAttribute("aria-selected", "false"); });
      contents.forEach(c => c.classList.remove("active"));
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      document.getElementById(tab.dataset.tab)?.classList.add("active");
      window.scrollTo(0, scrollByTab[tab.dataset.tab] || 0);
    });
  });
}

// ---------- System status (สุขภาพ AI จากการเรียกจริง) ----------

let statuteTotal = null;

function setStatusBadge(state, text, title = "") {
  const badge = document.getElementById("systemStatus");
  badge.classList.remove("ok", "warn", "error", "checking");
  badge.classList.add(state);
  document.getElementById("systemStatusText").textContent =
    (statuteTotal !== null ? `${fmt(statuteTotal)} มาตรา · ` : "") + text;
  badge.title = title;
}

/** อัปเดตป้ายจากสุขภาพ AI ที่ server รายงาน */
function applyHealth(llm) {
  const h = llm.health || {};
  if (h.ok === true) setStatusBadge("ok", "AI พร้อม", `โมเดล: ${llm.model}`);
  else if (h.ok === false) setStatusBadge("error", "AI ใช้งานไม่ได้", `${h.message || ""} (ค้นหาตัวบทยังใช้ได้)`);
  else if (llm.provider === "anthropic" || llm.provider === "groq")
    // Claude/Groq ไม่ถูก probe (เสียค่าใช้จ่าย/กินโควตา) — ตั้งค่าแล้วแต่ยังไม่ได้ถามจริง
    setStatusBadge("checking", `${llm.provider === "groq" ? "Groq" : "Claude"} ตั้งค่าแล้ว · ทดสอบเมื่อถามครั้งแรก`, `โมเดล: ${llm.model}`);
  else setStatusBadge("checking", "กำลังตรวจ AI...", `โมเดล: ${llm.model}`);
}

/** ตัวเลือกโมเดล (แสดงเมื่อ server ส่งรายการโมเดลมา เช่น Groq) */
function initModelPicker(models) {
  const picker = document.getElementById("modelPicker");
  const select = document.getElementById("modelSelect");
  const desc = document.getElementById("modelDescription");
  if (!models || !models.length) { picker.hidden = true; return; }
  select.innerHTML = models.map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.label)}</option>`).join("");
  let saved = null;
  try { saved = localStorage.getItem("legalAiModel"); } catch (_) { /* ไม่มี storage ก็ใช้ค่าแรก */ }
  if (saved && models.some(m => m.id === saved)) select.value = saved;
  const sync = () => {
    const m = models.find(x => x.id === select.value);
    desc.textContent = m ? m.description : "";
    try { localStorage.setItem("legalAiModel", select.value); } catch (_) { /* ไม่จำค่าได้ก็ไม่เป็นไร */ }
  };
  select.onchange = sync;
  sync();
  picker.hidden = false;
}

function selectedModel() {
  const picker = document.getElementById("modelPicker");
  return picker.hidden ? undefined : document.getElementById("modelSelect").value;
}

async function loadSystemStatus() {
  try {
    const quick = await (await fetch("/api/status")).json();
    statuteTotal = quick.statutes;
    document.body.classList.toggle("feedback-on", !!(quick.feedback && quick.feedback.enabled));
    applyHealth(quick.llm);
    initModelPicker(quick.llm.models);
    if (quick.llm.provider === "ollama") {
      // ทดสอบโมเดลจริง (โหลดเข้าหน่วยความจำ) — อาจใช้เวลา
      const probed = await (await fetch("/api/status?probe=true")).json();
      applyHealth(probed.llm);
    }
  } catch (_) {
    setStatusBadge("error", "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้");
  }
}

// ---------- ถาม-ตอบ ----------

function initAsk() {
  const form = document.getElementById("askForm");
  const input = document.getElementById("questionInput");
  const askBtn = document.getElementById("askAiBtn");
  const searchBtn = document.getElementById("searchDocsBtn");
  const hint = document.getElementById("questionHint");

  // ปุ่มกดได้เมื่อพิมพ์คำถามแล้วเท่านั้น (validation ไม่ใช่ error ของระบบ)
  const syncButtons = () => {
    const empty = !input.value.trim();
    askBtn.disabled = searchBtn.disabled = empty || askBtn.dataset.busy === "1";
    if (!empty) hint.hidden = true;
  };
  input.addEventListener("input", syncButtons);
  syncButtons();

  document.querySelectorAll("#qaSampleChips .chip-btn").forEach(chip => {
    chip.addEventListener("click", () => {
      document.querySelectorAll("#qaSampleChips .chip-btn").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      input.value = chip.dataset.q;
      syncButtons();
      input.focus();
    });
  });

  const guard = () => {
    if (input.value.trim()) return true;
    hint.hidden = false;
    input.focus();
    return false;
  };

  form.addEventListener("submit", e => {
    e.preventDefault();
    if (guard()) runAsk(input.value.trim(), askBtn, searchBtn, syncButtons);
  });
  searchBtn.addEventListener("click", () => {
    if (guard()) runSearch(input.value.trim(), askBtn, searchBtn, syncButtons);
  });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });
}

function setBusy(btn, otherBtn, busyText, onDone) {
  const label = btn.querySelector("span");
  const original = label.textContent;
  const started = Date.now();
  btn.dataset.busy = "1";
  btn.disabled = otherBtn.disabled = true;
  const tick = () => { label.textContent = `${busyText} ${Math.round((Date.now() - started) / 1000)} วินาที`; };
  tick();
  const timer = setInterval(tick, 1000);
  return () => {
    clearInterval(timer);
    label.textContent = original;
    btn.dataset.busy = "0";
    onDone();
  };
}

function showResult(html) {
  const area = document.getElementById("askResult");
  area.innerHTML = html;
  area.hidden = false;
  area.scrollIntoView({ behavior: "smooth", block: "start" });
}

function banner(cls, icon, title, sub = "", right = "") {
  return `
    <div class="verification-banner ${cls}" role="status">
      <div class="banner-left"><span class="banner-icon" aria-hidden="true">${icon}</span>
        <div><div class="banner-title">${title}</div>${sub ? `<div class="banner-sub">${sub}</div>` : ""}</div>
      </div>${right}
    </div>`;
}

async function runAsk(question, askBtn, searchBtn, syncButtons) {
  const done = setBusy(askBtn, searchBtn, "AI กำลังอ่านตัวบท...", syncButtons);
  try {
    const data = await postJson("/api/ask", { question, model: selectedModel() });
    if (data.llm_health) applyHealth({ health: data.llm_health, model: data.model });
    lastAnswer = { question, model: data.model || (data.status === "DIRECT" ? "ฐานข้อมูลตัวบท" : ""),
                   answer_status: data.status || "" };
    showResult(renderAnswer(data) + (data.status !== "LLM_ERROR" ? answerFeedbackHtml() : ""));
  } catch (err) {
    if (err.status === 0 || err.status >= 500) setStatusBadge("error", "ระบบขัดข้อง", err.message);
    showResult(banner("banner-warning", "✕", escapeHtml(err.message)));
  } finally {
    done();
  }
}

const ANSWER_STATUS = {
  CITATIONS_VERIFIED: {
    cls: "banner-verified", icon: "✓",
    title: "ข้อความที่อ้างอิงตรงกับตัวบทจริงทุกข้อ",
    sub: "ระบบยืนยันว่าข้อความที่ยกมามีอยู่จริงในตัวบท แต่ไม่ได้ยืนยันว่าข้อสรุปของ AI ถูกต้องครบถ้วน โปรดอ่านตัวบทประกอบ",
  },
  CITATIONS_PARTIAL: {
    cls: "banner-abstain", icon: "!",
    title: "คำตอบผ่านการตรวจไม่ครบทุกข้อ",
    sub: "มีอ้างอิงที่ตรวจไม่ผ่าน หรือคำตอบอาจตกหล่นเงื่อนไขในตัวบท (ดูรายละเอียดด้านล่าง) โปรดอ่านตัวบทประกอบอย่างระมัดระวัง",
  },
  ABSTAIN: {
    cls: "banner-abstain", icon: "⚠",
    title: "ระบบไม่ตอบคำถามนี้",
    sub: "ตัวบทที่ค้นพบไม่เพียงพอ หรือ AI ยกข้อความที่ตรวจสอบกับตัวบทจริงไม่ได้ จึงไม่ตอบเพื่อป้องกันความคลาดเคลื่อน",
  },
};

/** รายการตัวบทแบบคอลัมน์เดียว (ผลค้นหา / ตัวบทที่ AI อ่าน) */
function statuteList(statutes, opts = {}) {
  return `<div class="statute-list">${statutes.map((s, i) =>
    statuteCard(s, { collapsible: true, extra: opts.extraFor ? opts.extraFor(s, i) : "" })).join("")}</div>`;
}

function renderAnswer(data) {
  const retrieved = data.retrieved_statutes || [];
  const missing = (data.missing_sections || []).map(escapeHtml).join(", ");
  const missingNote = missing && data.status !== "DIRECT"
    ? `<p class="hint">ไม่พบ ${missing} ในคลัง (มีเฉพาะประมวลกฎหมายแพ่งและพาณิชย์) — คำตอบด้านล่างอิงเฉพาะมาตราที่พบ</p>` : "";

  if (data.status === "DIRECT") {
    // ตอบจากฐานข้อมูลตรงๆ (ตัวบท / ตำแหน่งในประมวล / สถานะยกเลิก) — ไม่ผ่าน AI
    return `
      ${banner("banner-verified", "📖", "ตอบจากตัวบทในคลังโดยตรง (ไม่ใช้ AI)",
        "ข้อความและข้อมูลมาตรานำมาจากฐานข้อมูลตัวบทตรงตัว ไม่ได้ผ่านการตีความของ AI")}
      <article class="glass-panel result-block">
        <h2 class="result-label">คำตอบ <span class="model-tag">ฐานข้อมูลตัวบท</span></h2>
        <div class="answer-text">${escapeHtml(data.answer)}</div>
      </article>
      ${retrieved.length && data.lookup !== "text" ? `
      <details class="result-block">
        <summary class="result-label">ตัวบทเต็ม (${retrieved.length} มาตรา)</summary>
        ${statuteList(retrieved)}
      </details>` : ""}`;
  }

  if (data.status === "LLM_ERROR") {
    // AI ล้ม แต่การค้นหาตัวบทสำเร็จแล้ว — แสดงมาตราที่ค้นพบให้ผู้ใช้อ่านต่อได้ทันที
    return `
      ${banner("banner-warning", "✕", "AI ตอบไม่ได้ในขณะนี้", escapeHtml(data.error || "บริการ AI ขัดข้อง"))}
      ${data.debug_error ? `<details class="debug-detail"><summary>รายละเอียดสำหรับผู้ดูแลระบบ</summary><pre>${escapeHtml(data.debug_error)}</pre></details>` : ""}
      ${retrieved.length ? `
      <section class="result-block">
        <h2 class="result-label">มาตราที่ค้นพบสำหรับคำถามนี้ (${retrieved.length} มาตรา — ค้นหาโดยไม่ใช้ AI)</h2>
        ${statuteList(retrieved)}
      </section>` : ""}`;
  }

  const st = ANSWER_STATUS[data.status] || ANSWER_STATUS.ABSTAIN;
  const statutesById = Object.fromEntries(retrieved.map(s => [s.id, s]));
  const checks = data.guardrails || {};

  const citations = (data.citations || []).map(c => {
    const s = statutesById[c.id];
    return `
      <div class="citation-card">
        <div class="citation-head">
          <span class="citation-pill">✓ ${escapeHtml(c.section)}</span>
          ${c.status === "repealed" ? `<span class="repealed-badge">ยกเลิกแล้ว</span>` : ""}
          <span class="citation-page">${c.source_page ? `code_lawyer.pdf หน้า ${c.source_page}` : ""}</span>
        </div>
        <blockquote class="citation-quote">"${escapeHtml(c.quote)}"</blockquote>
        ${s ? `<details><summary>อ่านตัวบทเต็ม ${escapeHtml(s.section)}</summary><div class="statute-content authentic-book-format">${formatStatuteContent(s.content, s.status === "repealed")}</div></details>` : ""}
      </div>`;
  }).join("");

  const rejected = (checks.rejected_citations || []).map(c => `
    <li><strong>${escapeHtml(c.section || "?")}</strong>: ${escapeHtml(c.reason)}
      ${c.quote ? `<div class="rejected-quote">"${escapeHtml(c.quote)}"</div>` : ""}</li>`).join("");
  const unsupported = (checks.unsupported_sections_in_answer || []).map(escapeHtml).join(", ");
  const omitted = (checks.omitted_conditions || []).map(o =>
    `<li><strong>${escapeHtml(o.section)}</strong> ระบุ ${o.missing.map(escapeHtml).join(", ")} แต่คำตอบไม่ได้กล่าวถึง</li>`).join("");

  // ถ้า AI ไม่ตอบ ให้เปิดรายการตัวบทไว้เลย เพื่อให้ผู้ใช้อ่านเองได้
  const openList = data.status === "ABSTAIN" ? " open" : "";

  return `
    ${banner(st.cls, st.icon, st.title, st.sub,
      `<div class="score-pill" title="สัดส่วนอ้างอิงที่ยกข้อความตรงกับตัวบทจริง">${data.faithfulness_score ?? 0}%</div>`)}
    ${missingNote}

    ${data.answer ? `
    <article class="glass-panel result-block">
      <h2 class="result-label">คำตอบ ${data.model ? `<span class="model-tag">${escapeHtml(data.model)}</span>` : ""}</h2>
      <div class="answer-text">${escapeHtml(data.answer)}</div>
    </article>` : ""}

    ${omitted ? `
    <div class="result-block rejected-block">
      <h2 class="result-label">⚠ คำตอบอาจไม่ครบ — ตัวบทกำหนดเงื่อนไขมากกว่าที่ตอบ</h2>
      <ul>${omitted}</ul>
      <p>โปรดอ่านตัวบทเต็มด้านล่างประกอบ</p>
    </div>` : ""}

    ${citations ? `
    <div class="result-block">
      <h2 class="result-label">ข้อความที่ AI อ้างอิง (ตรวจแล้วว่ามีอยู่จริงในตัวบท)</h2>
      ${citations}
    </div>` : ""}

    ${rejected || unsupported ? `
    <div class="result-block rejected-block">
      <h2 class="result-label">อ้างอิงที่ถูกตัดออก</h2>
      ${rejected ? `<ul>${rejected}</ul>` : ""}
      ${unsupported ? `<p>คำตอบกล่าวถึงมาตราที่ไม่อยู่ในตัวบทที่ค้นพบ: ${unsupported}</p>` : ""}
    </div>` : ""}

    ${retrieved.length ? `
    <details class="result-block"${openList}>
      <summary class="result-label">ตัวบทที่ AI ได้อ่าน (${retrieved.length} มาตรา)</summary>
      ${statuteList(retrieved)}
    </details>` : ""}
  `;
}

async function runSearch(query, askBtn, searchBtn, syncButtons) {
  const done = setBusy(searchBtn, askBtn, "กำลังค้นหา...", syncButtons);
  try {
    const data = await postJson("/api/search", { query, top_k: 10 });
    const results = data.results || [];
    if (!results.length) {
      showResult(banner("banner-abstain", "⚠", "ไม่พบตัวบทที่เกี่ยวข้อง", "ลองใช้คำอื่น หรือระบุเลขมาตรา"));
      return;
    }
    const top = results[0].score;
    showResult(`
      <section class="result-block">
        <h2 class="result-label">ตัวบทที่เกี่ยวข้องที่สุด ${results.length} มาตรา (ค้นหาโดยไม่ใช้ AI)</h2>
        ${statuteList(results.map(r => r.statute), { extraFor: (s, i) => relevanceTag(results[i].score, top) })}
      </section>`);
  } catch (err) {
    showResult(banner("banner-warning", "✕", escapeHtml(err.message)));
  } finally {
    done();
  }
}

// ---------- คลังตัวบทกฎหมาย ----------

const STATUTE_BATCH_SIZE = 30;   // ใช้ค่าเดียวทั้งตอนเปิดหน้าและตอนค้นหา
const CCC = "ประมวลกฎหมายแพ่งและพาณิชย์";
const kb = {
  all: [], byId: new Map(), filtered: [], shown: 0, terms: [], note: "",
  law: "all", book: "all", query: "", statusFilter: "all",
  sortMode: "sec_asc", userSorted: false,
};

function sectionKey(s) {
  const m = toArabic(s.section || "").match(/(\d+)(?:\s*\/\s*(\d+))?/);
  return { main: m ? parseInt(m[1], 10) : 99999, sub: m && m[2] ? parseInt(m[2], 10) : 0 };
}

function bookWeight(s) {
  if (s.category !== CCC) return 100;
  if (s.book === "ข้อความเบื้องต้น") return 0;
  const m = (s.book || "").match(/บรรพ\s*(\d+)/);
  return m ? parseInt(m[1], 10) : 50;
}

function compareSection(a, b) {
  if (a.category !== b.category) return a.category === CCC ? -1 : b.category === CCC ? 1 : a.category.localeCompare(b.category, "th");
  const ka = sectionKey(a), kb_ = sectionKey(b);
  return ka.main - kb_.main || ka.sub - kb_.sub;
}

function sortStatutes(list, mode, scores) {
  const arr = list.slice();
  switch (mode) {
    case "relevance": return arr.sort((a, b) => (scores.get(b) || 0) - (scores.get(a) || 0) || compareSection(a, b));
    case "sec_desc": return arr.sort((a, b) => -compareSection(a, b));
    case "book_asc": return arr.sort((a, b) => bookWeight(a) - bookWeight(b) || compareSection(a, b));
    case "len_desc": return arr.sort((a, b) => (b.content || "").length - (a.content || "").length || compareSection(a, b));
    case "len_asc": return arr.sort((a, b) => (a.content || "").length - (b.content || "").length || compareSection(a, b));
    default: return arr.sort(compareSection);
  }
}

async function initKnowledgeBase() {
  const badge = document.getElementById("statuteCountBadge");
  try {
    const data = await (await fetch("/api/statutes")).json();
    kb.all = data.statutes || [];
    kb.byId = new Map(kb.all.map(s => [s.id, s]));
  } catch (_) {
    badge.textContent = "โหลดคลังตัวบทไม่สำเร็จ";
    return;
  }

  buildLawFilters();

  const searchInput = document.getElementById("statuteSearchInput");
  const clearBtn = document.getElementById("clearSearchBtn");
  const statusFilter = document.getElementById("statuteStatusFilter");
  const sortSelect = document.getElementById("statuteSortSelect");
  const resetBtn = document.getElementById("resetFiltersBtn");

  let timer;
  searchInput.addEventListener("input", e => {
    clearTimeout(timer);
    clearBtn.hidden = !e.target.value;
    timer = setTimeout(() => { kb.query = e.target.value.trim(); applyFilters(); }, 200);
  });
  clearBtn.addEventListener("click", () => {
    searchInput.value = "";
    clearBtn.hidden = true;
    kb.query = "";
    applyFilters();
    searchInput.focus();
  });
  statusFilter.addEventListener("change", e => { kb.statusFilter = e.target.value; applyFilters(); });
  sortSelect.addEventListener("change", e => { kb.sortMode = e.target.value; kb.userSorted = true; applyFilters(); });
  resetBtn.addEventListener("click", () => {
    Object.assign(kb, { query: "", law: "all", book: "all", statusFilter: "all", sortMode: "sec_asc", userSorted: false });
    searchInput.value = "";
    clearBtn.hidden = true;
    statusFilter.value = "all";
    buildLawFilters();
    applyFilters();
  });
  document.getElementById("loadMoreStatutesBtn").addEventListener("click", appendBatch);

  applyFilters();
}

function filterButton(group, value, label, active, note = "") {
  return `<button type="button" class="book-filter-btn${active ? " active" : ""}" data-${group}="${escapeHtml(value)}"
    aria-pressed="${active}">${escapeHtml(label)}${note ? ` <small>${escapeHtml(note)}</small>` : ""}</button>`;
}

/** ชั้นที่ 1: เลือกกฎหมาย · ชั้นที่ 2: เลือกบรรพ (เฉพาะ ป.พ.พ.) */
function buildLawFilters() {
  const laws = new Map();
  kb.all.forEach(s => laws.set(s.category, (laws.get(s.category) || 0) + 1));
  const lawOrder = [...laws.keys()].sort((a, b) => (a === CCC ? -1 : b === CCC ? 1 : a.localeCompare(b, "th")));

  // ความครบถ้วนของข้อมูล: ป.พ.พ. นำเข้าจาก PDF ครบทุกมาตรา ส่วนกฎหมายอื่นมีเพียงบางมาตรา
  const coverage = law => (kb.all.find(s => s.category === law)?.source || "").endsWith(".pdf") ? "ครบทั้งฉบับ" : "บางมาตรา";

  document.getElementById("statuteLawFilters").innerHTML =
    filterButton("law", "all", `ทุกกฎหมาย (${fmt(kb.all.length)})`, kb.law === "all") +
    lawOrder.map(law => filterButton("law", law, `${law} (${fmt(laws.get(law))})`, kb.law === law, coverage(law))).join("");

  const bookRow = document.getElementById("statuteBookFilters");
  if (kb.law !== CCC) {
    bookRow.hidden = true;
    bookRow.innerHTML = "";
  } else {
    const books = new Map();
    kb.all.filter(s => s.category === CCC).forEach(s => books.set(s.book, (books.get(s.book) || 0) + 1));
    const order = [...books.keys()].sort((a, b) => bookWeight({ category: CCC, book: a }) - bookWeight({ category: CCC, book: b }));
    bookRow.hidden = false;
    bookRow.innerHTML = filterButton("book", "all", "ทุกบรรพ", kb.book === "all") +
      order.map(b => filterButton("book", b, `${b} (${fmt(books.get(b))})`, kb.book === b)).join("");
  }

  document.querySelectorAll("[data-law]").forEach(btn => btn.addEventListener("click", () => {
    kb.law = btn.dataset.law;
    kb.book = "all";
    buildLawFilters();
    applyFilters();
  }));
  document.querySelectorAll("[data-book]").forEach(btn => btn.addEventListener("click", () => {
    kb.book = btn.dataset.book;
    buildLawFilters();
    applyFilters();
  }));
}

const NUMBER_QUERY = /^(?:มาตรา|ม\.?)?\s*([0-9๐-๙]+(?:\s*\/\s*[0-9๐-๙]+)?)$/;

/** มาตราอื่นที่อ้างถึงมาตรา num ในเนื้อหา (เลขทั้งตัว ไม่ใช่ส่วนหนึ่งของเลขอื่น) */
function citesSection(content, num) {
  const n = toArabic(num).replace("/", "\\s*/\\s*");
  return new RegExp(`มาตรา\\s*${n}(?![0-9/])`).test(toArabic(content || ""));
}

function applyFilters() {
  const q = kb.query.trim();
  const scores = new Map();
  kb.terms = [];
  kb.note = "";

  const base = kb.all.filter(s => {
    if (kb.statusFilter === "active" && s.status === "repealed") return false;
    if (kb.statusFilter === "repealed" && s.status !== "repealed") return false;
    if (kb.law !== "all" && s.category !== kb.law) return false;
    if (kb.book !== "all" && s.book !== kb.book) return false;
    return true;
  });

  let filtered = base;
  let mode = kb.sortMode;
  const numMatch = q.match(NUMBER_QUERY);

  if (numMatch) {
    // ค้นด้วยเลขมาตรา: มาตราที่เลขตรงเป๊ะก่อน (420 และ 420/1...) แล้วจึงมาตราที่อ้างถึง — ไม่เอา 1420
    const num = toArabic(numMatch[1].replace(/\s+/g, ""));
    const [main, sub] = num.split("/");
    const exact = base.filter(s => {
      const k = sectionKey(s);
      return String(k.main) === main && (sub === undefined || String(k.sub) === sub);
    });
    const refs = base.filter(s => !exact.includes(s) && citesSection(s.content, num));
    filtered = [...sortStatutes(exact, "sec_asc"), ...sortStatutes(refs, "sec_asc")];
    kb.note = `มาตรา ${num}: ตรงเลข ${exact.length} · มาตราที่อ้างถึง ${refs.length}`;
    mode = null;   // ลำดับถูกกำหนดแล้ว
  } else if (q) {
    // ค้นด้วยคำ: ให้คะแนนความเกี่ยวข้อง และไฮไลต์คำที่พบ
    const variants = [...new Set([q, toArabic(q), toThai(q)])].map(v => v.toLowerCase());
    kb.terms = variants;
    filtered = base.filter(s => {
      const content = (s.content || "").toLowerCase();
      const head = `${s.section} ${s.title} ${s.book}`.toLowerCase();
      const kw = (s.keywords || []).join(" ").toLowerCase();
      let score = 0;
      for (const v of variants) {
        score += content.split(v).length - 1;
        if (head.includes(v)) score += 5;
        if (kw.includes(v)) score += 3;
      }
      if (score) scores.set(s, score);
      return score > 0;
    });
    if (!kb.userSorted) mode = "relevance";
  }

  kb.filtered = mode ? sortStatutes(filtered, mode, scores) : filtered;

  const sortSelect = document.getElementById("statuteSortSelect");
  const relOption = sortSelect.querySelector('option[value="relevance"]');
  relOption.disabled = !q || !!numMatch;
  sortSelect.value = mode === "relevance" ? "relevance" : kb.sortMode;

  document.getElementById("resetFiltersBtn").hidden =
    !(q || kb.law !== "all" || kb.book !== "all" || kb.statusFilter !== "all" || kb.userSorted);

  document.getElementById("statuteGrid").innerHTML = "";
  kb.shown = 0;
  appendBatch();
}

function appendBatch() {
  const next = kb.filtered.slice(kb.shown, kb.shown + STATUTE_BATCH_SIZE);
  kb.shown += next.length;
  document.getElementById("statuteGrid").insertAdjacentHTML("beforeend",
    next.map(s => statuteCard(s, { terms: kb.terms })).join(""));
  const shownText = `แสดง ${fmt(kb.shown)} จาก ${fmt(kb.filtered.length)} มาตรา`;
  document.getElementById("statuteCountBadge").textContent = kb.note ? `${kb.note} · ${shownText}` : shownText;
  document.getElementById("loadMoreStatutesBtn").hidden = kb.shown >= kb.filtered.length;
}

// ---------- ความคิดเห็นผู้ใช้ (ให้คะแนนคำตอบ / รีวิวเว็บไซต์ / แจ้งตัวบทผิด) ----------
// แสดงเฉพาะเมื่อ server เปิดระบบ (body.feedback-on) — ไม่เก็บ IP อีเมล หรือเบอร์โทร

let lastAnswer = null;

function savedNickname() {
  try { return localStorage.getItem("legalAiNickname") || ""; } catch (_) { return ""; }
}

function rememberNickname(name) {
  try { localStorage.setItem("legalAiNickname", name); } catch (_) { /* ไม่จำก็ไม่เป็นไร */ }
}

function feedbackErrorText(err) {
  if (err.status === 429) return "ส่งถี่เกินไป กรุณารอสักครู่แล้วลองใหม่";
  if (err.status === 503) return "ระบบความคิดเห็นยังไม่เปิดใช้งาน";
  if (err.status === 422) return "ข้อมูลไม่ครบ กรุณาตรวจอีกครั้ง";
  return err.message || "ส่งไม่สำเร็จ กรุณาลองใหม่";
}

function answerFeedbackHtml() {
  return `
    <section class="glass-panel result-block feedback-box fb-only" aria-label="ให้คะแนนคำตอบ">
      <div class="fb-question">คำตอบนี้มีประโยชน์ไหม?</div>
      <div class="fb-votes">
        <button type="button" class="chip-btn fb-vote" data-vote="1" aria-pressed="false">👍 มีประโยชน์</button>
        <button type="button" class="chip-btn fb-vote" data-vote="-1" aria-pressed="false">👎 ไม่มีประโยชน์</button>
      </div>
      <form class="fb-answer-form feedback-form" hidden novalidate>
        <label class="form-label" for="fbAnswerComment">บอกเพิ่มเติม (ไม่บังคับ)</label>
        <textarea id="fbAnswerComment" class="legal-input fb-textarea" maxlength="1000" placeholder="เช่น ตอบผิดมาตรา ขาดเงื่อนไข หรืออ่านเข้าใจง่าย"></textarea>
        <label class="form-label" for="fbAnswerNickname">ชื่อเล่นหรือนามแฝง (ไม่บังคับ)</label>
        <input type="text" id="fbAnswerNickname" class="legal-input fb-input fb-nickname" maxlength="40" placeholder="เว้นว่าง = ไม่ระบุชื่อ" value="${escapeHtml(savedNickname())}">
        <input type="text" name="website" class="fb-trap" tabindex="-1" autocomplete="off" aria-hidden="true">
        <p class="fb-privacy">ระบบเก็บคะแนน ความคิดเห็น ชื่อเล่น (ถ้ามี) และคำถามนี้กับโมเดลที่ตอบ เพื่อปรับปรุงคำตอบ — ไม่เก็บ IP อีเมล หรือเบอร์โทร</p>
        <button type="submit" class="btn-primary"><span>ส่งความคิดเห็น</span></button>
      </form>
      <p class="fb-msg" role="status" aria-live="polite"></p>
    </section>`;
}

async function sendFeedback(body) {
  return postJson("/api/feedback", body);
}

function initFeedback() {
  const dialog = document.getElementById("feedbackDialog");
  const form = document.getElementById("feedbackDialogForm");
  const msg = document.getElementById("feedbackDialogMsg");
  const comment = document.getElementById("dialogComment");
  const nickname = document.getElementById("dialogNickname");
  const submitBtn = document.getElementById("feedbackDialogSubmit");
  let mode = "site", section = "";

  const open = (newMode, newSection = "") => {
    mode = newMode; section = newSection;
    form.reset();
    nickname.value = savedNickname();
    msg.textContent = ""; msg.className = "fb-msg";
    submitBtn.disabled = false;
    document.getElementById("starField").hidden = mode !== "site";
    const secLine = document.getElementById("feedbackDialogSection");
    secLine.hidden = mode !== "statute";
    secLine.textContent = mode === "statute" ? section : "";
    document.getElementById("feedbackDialogTitle").textContent = mode === "site" ? "รีวิวเว็บไซต์" : "แจ้งตัวบทผิด";
    document.getElementById("dialogCommentLabel").textContent =
      mode === "site" ? "ความคิดเห็น (ไม่บังคับ)" : "ข้อความที่ผิด และควรเป็นอย่างไร (จำเป็น)";
    comment.placeholder = mode === "site" ? "ชอบหรืออยากให้ปรับปรุงอะไร" : "เช่น ท้ายมาตรามีหัวข้อ \"๑. บุริมสิทธิสามัญ\" ติดมา";
    dialog.showModal();
    (mode === "site" ? document.getElementById("star5") : comment).focus();
  };

  document.getElementById("siteReviewBtn").addEventListener("click", () => open("site"));
  document.getElementById("feedbackDialogCancel").addEventListener("click", () => dialog.close());

  form.addEventListener("submit", async e => {
    e.preventDefault();
    const stars = form.querySelector('input[name="stars"]:checked');
    if (mode === "site" && !stars) { msg.textContent = "กรุณาเลือกจำนวนดาว"; msg.className = "fb-msg error"; return; }
    if (mode === "statute" && !comment.value.trim()) { msg.textContent = "กรุณาอธิบายว่าผิดตรงไหน"; msg.className = "fb-msg error"; comment.focus(); return; }
    submitBtn.disabled = true;
    msg.textContent = "กำลังส่ง..."; msg.className = "fb-msg";
    try {
      await sendFeedback({
        type: mode, rating: mode === "site" ? Number(stars.value) : null,
        comment: comment.value, nickname: nickname.value, section,
        website: form.querySelector(".fb-trap").value,
      });
      rememberNickname(nickname.value.trim());
      msg.textContent = "ขอบคุณสำหรับความคิดเห็น ✓"; msg.className = "fb-msg ok";
      setTimeout(() => dialog.close(), 1200);
    } catch (err) {
      msg.textContent = feedbackErrorText(err); msg.className = "fb-msg error";
      submitBtn.disabled = false;
    }
  });

  document.addEventListener("click", e => {
    const report = e.target.closest("[data-report]");
    if (report) return open("statute", report.dataset.report);

    const vote = e.target.closest(".fb-vote");
    if (vote) {
      const box = vote.closest(".feedback-box");
      box.dataset.vote = vote.dataset.vote;
      box.querySelectorAll(".fb-vote").forEach(b => {
        const on = b === vote;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", String(on));
      });
      const f = box.querySelector(".fb-answer-form");
      f.hidden = false;
      f.querySelector("textarea").focus();
    }
  });

  document.addEventListener("submit", async e => {
    const f = e.target.closest(".fb-answer-form");
    if (!f) return;
    e.preventDefault();
    const box = f.closest(".feedback-box");
    const out = box.querySelector(".fb-msg");
    const btn = f.querySelector("button[type=submit]");
    btn.disabled = true;
    out.textContent = "กำลังส่ง..."; out.className = "fb-msg";
    const nick = f.querySelector(".fb-nickname").value;
    try {
      await sendFeedback({
        type: "answer", rating: Number(box.dataset.vote),
        comment: f.querySelector("textarea").value, nickname: nick,
        ...(lastAnswer || {}), website: f.querySelector(".fb-trap").value,
      });
      rememberNickname(nick.trim());
      f.hidden = true;
      box.querySelector(".fb-votes").hidden = true;
      box.querySelector(".fb-question").textContent = "ขอบคุณสำหรับความคิดเห็น ✓";
      out.textContent = "";
    } catch (err) {
      out.textContent = feedbackErrorText(err); out.className = "fb-msg error";
      btn.disabled = false;
    }
  });
}
