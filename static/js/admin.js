/**
 * หน้าผู้ดูแล: อ่านความคิดเห็นผู้ใช้ (ต้องใส่ ADMIN_PASSWORD ที่ตั้งไว้บน server)
 * รหัสผ่านเก็บใน sessionStorage เท่านั้น (หายเมื่อปิดแท็บ)
 */

const TYPE_LABEL = { answer: "ให้คะแนนคำตอบ", site: "รีวิวเว็บไซต์", statute: "แจ้งตัวบทผิด" };
const CSV_COLUMNS = ["created_at", "type", "rating", "nickname", "comment", "question", "model", "answer_status", "section", "id"];
let allRows = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function getPassword() {
  try { return sessionStorage.getItem("legalAiAdmin") || ""; } catch (_) { return ""; }
}

function setPassword(pw) {
  try { pw ? sessionStorage.setItem("legalAiAdmin", pw) : sessionStorage.removeItem("legalAiAdmin"); } catch (_) { /* ใช้ได้เฉพาะรอบนี้ */ }
}

let memoryPassword = "";

async function load(password) {
  const res = await fetch("/api/admin/feedback?limit=2000", { headers: { "X-Admin-Password": password } });
  let data = {};
  try { data = await res.json(); } catch (_) { /* ไม่ใช่ JSON */ }
  if (!res.ok) {
    const err = new Error(data.detail || "โหลดข้อมูลไม่สำเร็จ");
    err.status = res.status;
    throw err;
  }
  return data;
}

function fmtDate(iso) {
  const d = new Date(iso);
  return isNaN(d) ? String(iso || "") : d.toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" });
}

function ratingText(r) {
  if (r.type === "answer") return r.rating === 1 ? "👍" : r.rating === -1 ? "👎" : "";
  if (r.type === "site") return r.rating ? "★".repeat(r.rating) + "☆".repeat(5 - r.rating) : "";
  return "";
}

function renderStats(stats) {
  const card = (label, value, sub = "") => `
    <div class="glass-panel stat-card">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ""}
    </div>`;
  const t = stats.by_type || {};
  document.getElementById("statCards").innerHTML =
    card("ทั้งหมด", stats.total) +
    card("ให้คะแนนคำตอบ", t.answer || 0) +
    card("รีวิวเว็บไซต์", stats.site_average ?? "–", `ดาวเฉลี่ยจาก ${stats.site_count} รีวิว`) +
    card("แจ้งตัวบทผิด", t.statute || 0);

  const models = Object.entries(stats.answer_by_model || {});
  document.getElementById("modelTable").innerHTML = models.length ? `
    <table class="admin-table">
      <thead><tr><th>โมเดล</th><th>👍</th><th>👎</th><th>มีประโยชน์</th></tr></thead>
      <tbody>${models.map(([m, c]) => {
        const total = c.up + c.down;
        return `<tr><td>${escapeHtml(m)}</td><td class="num">${c.up}</td><td class="num">${c.down}</td>
          <td class="num">${total ? Math.round((100 * c.up) / total) : 0}%</td></tr>`;
      }).join("")}</tbody>
    </table>` : `<p class="fb-empty">ยังไม่มีการให้คะแนนคำตอบ</p>`;
}

function renderRows() {
  const type = document.getElementById("typeFilter").value;
  const rows = type === "all" ? allRows : allRows.filter(r => r.type === type);
  document.getElementById("rowCount").textContent = `${rows.length} รายการ`;
  document.getElementById("rows").innerHTML = rows.length ? rows.map(r => `
    <div class="fb-row">
      <div class="fb-row-head">
        <span class="fb-type ${escapeHtml(r.type)}">${escapeHtml(TYPE_LABEL[r.type] || r.type)}</span>
        <span class="fb-rating">${ratingText(r)}</span>
        <span>${escapeHtml(r.nickname || "ไม่ระบุชื่อ")}</span>
        <span>· ${escapeHtml(fmtDate(r.created_at))}</span>
        ${r.model ? `<span>· ${escapeHtml(r.model)}</span>` : ""}
        ${r.section ? `<span>· ${escapeHtml(r.section)}</span>` : ""}
      </div>
      ${r.comment ? `<div class="fb-comment">${escapeHtml(r.comment)}</div>` : ""}
      ${r.question ? `<div class="fb-context">คำถาม: ${escapeHtml(r.question)}${r.answer_status ? ` (${escapeHtml(r.answer_status)})` : ""}</div>` : ""}
    </div>`).join("") : `<p class="fb-empty">ยังไม่มีข้อมูล</p>`;
}

/** CSV: ใส่ ' นำหน้าค่าที่ขึ้นต้นด้วย = + - @ กัน Excel คำนวณเป็นสูตร */
function toCsv(rows) {
  const cell = v => {
    let s = String(v ?? "");
    if (/^[=+\-@]/.test(s) && !/^-?\d+$/.test(s)) s = "'" + s;
    return `"${s.replace(/"/g, '""')}"`;
  };
  return "﻿" + [CSV_COLUMNS.join(","), ...rows.map(r => CSV_COLUMNS.map(c => cell(r[c])).join(","))].join("\r\n");
}

function downloadCsv() {
  const type = document.getElementById("typeFilter").value;
  const rows = type === "all" ? allRows : allRows.filter(r => r.type === type);
  const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `feedback-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function showData(password) {
  const data = await load(password);
  allRows = data.rows || [];
  renderStats(data.stats || {});
  renderRows();
  document.getElementById("loginPanel").hidden = true;
  document.getElementById("dataPanel").hidden = false;
}

function logout() {
  setPassword(""); memoryPassword = "";
  allRows = [];
  document.getElementById("dataPanel").hidden = true;
  document.getElementById("loginPanel").hidden = false;
  document.getElementById("adminPassword").value = "";
}

document.addEventListener("DOMContentLoaded", () => {
  const msg = document.getElementById("loginMsg");

  document.getElementById("loginForm").addEventListener("submit", async e => {
    e.preventDefault();
    const pw = document.getElementById("adminPassword").value;
    msg.textContent = "กำลังตรวจสอบ..."; msg.className = "fb-msg";
    try {
      await showData(pw);
      memoryPassword = pw; setPassword(pw);
      msg.textContent = "";
    } catch (err) {
      msg.textContent = err.message; msg.className = "fb-msg error";
    }
  });

  document.getElementById("typeFilter").addEventListener("change", renderRows);
  document.getElementById("csvBtn").addEventListener("click", downloadCsv);
  document.getElementById("logoutBtn").addEventListener("click", logout);
  document.getElementById("refreshBtn").addEventListener("click", async () => {
    try { await showData(memoryPassword || getPassword()); }
    catch (err) {
      if (err.status === 401) logout();
      else document.getElementById("rowCount").textContent = err.message;
    }
  });

  const saved = getPassword();
  if (saved) showData(saved).then(() => { memoryPassword = saved; }).catch(() => setPassword(""));
});
