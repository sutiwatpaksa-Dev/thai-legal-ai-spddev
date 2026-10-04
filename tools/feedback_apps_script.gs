/**
 * Thai Legal AI — รับความคิดเห็นจากเว็บไซต์ลง Google Sheet
 *
 * วิธีติดตั้ง (ทำครั้งเดียว):
 * 1. สร้าง Google Sheet ใหม่ → เมนู ส่วนขยาย (Extensions) → Apps Script
 * 2. ลบโค้ดเดิม วางไฟล์นี้ทั้งไฟล์ แล้วแก้ SECRET ด้านล่างเป็นรหัสลับยาวๆ ของคุณเอง
 *    (ค่าเดียวกับ FEEDBACK_SECRET ที่ตั้งใน Vercel — ห้ามใส่ในไฟล์ใดในโฟลเดอร์โปรเจกต์)
 * 3. Deploy → New deployment → ประเภท Web app
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 4. คัดลอก Web app URL (https://script.google.com/macros/s/.../exec) ไปตั้งเป็น FEEDBACK_SCRIPT_URL ใน Vercel
 *
 * แก้โค้ดภายหลัง: Deploy → Manage deployments → แก้ไข (ไอคอนดินสอ) → Version: New version
 * (URL เดิมใช้ต่อได้)
 */

const SECRET = 'เปลี่ยนเป็นรหัสลับของคุณ';
const SHEET_NAME = 'Feedback';
const COLUMNS = ['id', 'created_at', 'type', 'rating', 'comment', 'nickname',
                 'question', 'model', 'answer_status', 'section'];

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ ok: false, error: 'bad json' });
  }
  if (SECRET === 'เปลี่ยนเป็นรหัสลับของคุณ' || body.secret !== SECRET) {
    return reply({ ok: false, error: 'forbidden' });
  }

  const sheet = getSheet();
  if (body.action === 'add') {
    const lock = LockService.getScriptLock();
    lock.waitLock(10000);
    try {
      sheet.appendRow(COLUMNS.map(c => safe((body.row || {})[c])));
    } finally {
      lock.releaseLock();
    }
    return reply({ ok: true });
  }
  if (body.action === 'list') {
    const limit = Math.min(Number(body.limit) || 500, 2000);
    const values = sheet.getDataRange().getValues().slice(1);
    const rows = values.slice(-limit).reverse().map(r => {
      const row = {};
      COLUMNS.forEach((c, i) => {
        const v = r[i];
        row[c] = v instanceof Date ? v.toISOString() : v;
      });
      return row;
    });
    return reply({ ok: true, rows: rows });
  }
  return reply({ ok: false, error: 'unknown action' });
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(COLUMNS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/** กันสูตร: ข้อความที่ขึ้นต้นด้วย = + - @ จะถูกเก็บเป็นข้อความ ไม่ถูกคำนวณ */
function safe(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'number') return v;
  v = String(v);
  return /^[=+\-@]/.test(v) ? "'" + v : v;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
