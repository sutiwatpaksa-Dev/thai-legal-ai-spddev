// ทดสอบตรรกะฝั่งหน้าเว็บ (ไม่ต้องเปิดเบราว์เซอร์): โหลด app.js ด้วย DOM จำลองแล้วเรียกฟังก์ชันตรงๆ
// รัน: node tests/frontend_logic.test.mjs   (test_frontend_logic.py เรียกให้อัตโนมัติ)
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const code = readFileSync(new URL("../static/js/app.js", import.meta.url), "utf8");
const ctx = { document: { addEventListener() {} }, console };
vm.createContext(ctx);
vm.runInContext(code + "\n;globalThis.__t = { citesSection, NUMBER_QUERY, relevanceTag, highlight, escapeHtml, formatStatuteContent, sortStatutes, statuteCard };", ctx);
const t = ctx.__t;
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log("ok -", name); };

test("เลข 420 ไม่ตรงกับ ม.1420 (ทั้งเลขไทยและอารบิก)", () => {
  assert.equal(t.citesSection("ตามมาตรา ๔๒๐ วรรคหนึ่ง", "420"), true);
  assert.equal(t.citesSection("ตามมาตรา ๑๔๒๐", "420"), false);
  assert.equal(t.citesSection("ตามมาตรา ๔๒๐/๑", "420"), false);
  assert.equal(t.citesSection("ตามมาตรา 193/30", "193/30"), true);
});

test("รูปแบบคำค้นที่เป็นเลขมาตรา", () => {
  for (const q of ["420", "๔๒๐", "มาตรา 420", "ม.420", "ม 420", "193/30"]) assert.ok(t.NUMBER_QUERY.test(q), q);
  for (const q of ["ลูกหนี้", "กู้ยืม 2000 บาท"]) assert.ok(!t.NUMBER_QUERY.test(q), q);
});

test("ป้ายความเกี่ยวข้องแทนคะแนนดิบ", () => {
  assert.match(t.relevanceTag(57.7, 57.7), /เกี่ยวข้องมาก/);
  assert.match(t.relevanceTag(25, 57.7), /ปานกลาง/);
  assert.match(t.relevanceTag(5, 57.7), /เกี่ยวข้องน้อย/);
  assert.doesNotMatch(t.relevanceTag(57.7, 57.7), /57/);
});

test("ไฮไลต์คำค้นโดยไม่เปิดช่อง XSS", () => {
  assert.equal(t.highlight(t.escapeHtml("ลูกหนี้ผิดนัด"), ["ลูกหนี้"]), "<mark>ลูกหนี้</mark>ผิดนัด");
  const out = t.highlight(t.escapeHtml("<b>x</b> ลูกหนี้"), ["<b>"]);
  assert.ok(!out.includes("<b>"), out);
});

test("ตัวบทที่ยกเลิกเป็นช่วงแสดงเป็นป้ายยกเลิก", () => {
  assert.match(t.formatStatuteContent("มาตรา ๑๒๗๔ ถึง มาตรา ๑๒๙๗ (ยกเลิก)", true), /ถูกยกเลิกแล้ว/);
  assert.match(t.formatStatuteContent("(ยกเลิก)", true), /ถูกยกเลิกแล้ว/);
});

test("เรียงตามความเกี่ยวข้องเมื่อค้นด้วยคำ", () => {
  const a = { category: "ประมวลกฎหมายแพ่งและพาณิชย์", section: "มาตรา 1" };
  const b = { category: "ประมวลกฎหมายแพ่งและพาณิชย์", section: "มาตรา 2" };
  const scores = new Map([[a, 1], [b, 9]]);
  assert.deepEqual(t.sortStatutes([a, b], "relevance", scores).map(s => s.section), ["มาตรา 2", "มาตรา 1"]);
  assert.deepEqual(t.sortStatutes([b, a], "sec_asc", scores).map(s => s.section), ["มาตรา 1", "มาตรา 2"]);
});

test("การ์ดตัวบทยาวพับได้ และ escape id", () => {
  const card = t.statuteCard({ id: "CCC-1\"x", category: "c", section: "มาตรา 1", content: "ก".repeat(500) }, { collapsible: true });
  assert.match(card, /collapsed/);
  assert.match(card, /expand-btn/);
  assert.ok(!card.includes('CCC-1"x'), "id ต้องถูก escape");
});

console.log(`\n${passed} frontend tests passed`);
