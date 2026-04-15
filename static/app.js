function parseISODate(s) {
  // "2026-03-17" -> Date (local)；勿用 dataset（多段 hyphen 在部分環境不可靠），改由 getAttribute 讀取
  if (!s || typeof s !== "string") return null;
  const head = s.trim().slice(0, 10);
  const [y, m, d] = head.split("-").map((x) => parseInt(x, 10));
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

/** 從 <tr> 讀取 data-*（kebab-case），避免 dataset 對 data-wire-by 等屬性映射異常 */
function readRowDateAttr(row, kebab) {
  return parseISODate(row.getAttribute(`data-${kebab}`) || "");
}

function fmtNum(n) {
  return (n || 0).toLocaleString("en-US");
}

function iso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function addDays(d, days) {
  const x = new Date(d.getTime());
  x.setDate(x.getDate() + days);
  return x;
}

function fmtDateMd(d) {
  if (!d) return "—";
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${m}/${day}`;
}

function escHtml(s) {
  const el = document.createElement("div");
  el.textContent = s == null ? "" : String(s);
  return el.innerHTML;
}

const WIRE_LBL =
  '<span class="rounded bg-amber-100 px-1.5 py-0.5 text-sm font-semibold text-amber-900">匯撥期限</span>';
const LOAN_LBL =
  '<span class="rounded bg-violet-100 px-1.5 py-0.5 text-sm font-semibold text-violet-900">借款申請</span>';
const LOOKBACK_DAYS = 5;

function sameCalendarDay(a, b) {
  if (!a || !b) return false;
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function getHorizonDays() {
  const el = document.querySelector('input[name="horizon_days"]');
  const v = el ? parseInt(el.value || "30", 10) : 30;
  return Math.max(7, Math.min(365, isFinite(v) ? v : 30));
}

function getCapital() {
  const el = document.getElementById("capital-input");
  const v = el ? parseInt(el.value || "0", 10) : 0;
  return Math.max(0, isFinite(v) ? v : 0);
}

function selectedOffers() {
  const rows = Array.from(document.querySelectorAll(".offer-row"));
  const offers = [];
  for (const row of rows) {
    const check = row.querySelector(".offer-check");
    if (!check || !check.checked) continue;
    const amount = parseInt((row.getAttribute("data-amount") || "").replaceAll(",", ""), 10);
    if (!isFinite(amount) || amount <= 0) continue;
    const lockStart = readRowDateAttr(row, "lock-start");
    const refundDate = readRowDateAttr(row, "refund-date");
    const wireBy = readRowDateAttr(row, "wire-by");
    const loanBy = readRowDateAttr(row, "loan-by");
    if (!lockStart || !refundDate) continue;
    offers.push({
      symbol: row.getAttribute("data-symbol") || "",
      name: row.getAttribute("data-name") || "",
      amount,
      lockStart,
      refundDate,
      wireBy,
      loanBy,
    });
  }
  return offers;
}

function recompute() {
  const today = new Date();
  const today0 = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = addDays(today0, -LOOKBACK_DAYS);
  const horizonDays = getHorizonDays();
  const end = addDays(today0, horizonDays);
  const capital = getCapital();
  const offers = selectedOffers();

  // Precompute events by date.
  const debitByDate = new Map(); // iso -> [{symbol,name,amount}]
  const refundByDate = new Map(); // iso -> [{symbol,name,amount}]
  for (const o of offers) {
    const dk = iso(o.lockStart);
    if (!debitByDate.has(dk)) debitByDate.set(dk, []);
    debitByDate.get(dk).push(o);

    const rk = iso(o.refundDate);
    if (!refundByDate.has(rk)) refundByDate.set(rk, []);
    refundByDate.get(rk).push(o);
  }

  let maxApply = 0;
  let maxBorrow = 0;

  const rows = [];
  for (let d = start; d <= end; d = addDays(d, 1)) {
    let required = 0;
    for (const o of offers) {
      if (o.lockStart <= d && d <= o.refundDate) required += o.amount;
    }
    const shortfall = Math.max(0, required - capital);
    maxApply = Math.max(maxApply, required);
    maxBorrow = Math.max(maxBorrow, shortfall);

    const k = iso(d);
    const debits = debitByDate.get(k) || [];
    const refunds = refundByDate.get(k) || [];
    rows.push({ date: k, required, shortfall, debits, refunds });
  }

  const maxApplyEl = document.getElementById("max-apply");
  const maxBorrowEl = document.getElementById("max-borrow");
  const hintEl = document.getElementById("borrow-hint");
  if (maxApplyEl) maxApplyEl.textContent = fmtNum(maxApply);
  if (maxBorrowEl) maxBorrowEl.textContent = fmtNum(maxBorrow);
  if (hintEl) hintEl.textContent = `以你的現有資金 ${fmtNum(capital)} 去比每日需款的最大缺口`;

  const body = document.getElementById("daily-body");
  if (!body) return;
  body.innerHTML = "";

  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50";

    const tdDate = document.createElement("td");
    tdDate.className = "px-4 py-2 tabular-nums";
    tdDate.textContent = fmtDateMd(parseISODate(r.date));

    const tdReq = document.createElement("td");
    tdReq.className = "px-4 py-2 text-right tabular-nums";
    tdReq.textContent = fmtNum(r.required);

    const tdSf = document.createElement("td");
    const delta = capital - r.required;
    tdSf.className =
      "px-4 py-2 text-right tabular-nums " + (delta < 0 ? "text-emerald-700 font-semibold" : "text-rose-700 font-semibold");
    tdSf.textContent = delta < 0 ? `-${fmtNum(-delta)}` : `+${fmtNum(delta)}`;

    const tdDetail = document.createElement("td");
    tdDetail.className = "px-4 py-2 text-slate-700 text-sm leading-relaxed";

    const dayDate = parseISODate(r.date);
    const frags = [];
    const wireSorted = offers
      .filter((o) => o.wireBy && dayDate && sameCalendarDay(dayDate, o.wireBy))
      .sort((a, b) => a.symbol.localeCompare(b.symbol));
    const loanSorted = offers
      .filter((o) => o.loanBy && dayDate && sameCalendarDay(dayDate, o.loanBy))
      .sort((a, b) => a.symbol.localeCompare(b.symbol));
    for (const o of wireSorted) {
      frags.push(`${WIRE_LBL} ${escHtml(o.symbol)} ${escHtml(o.name)}`);
    }
    for (const o of loanSorted) {
      frags.push(`${LOAN_LBL} ${escHtml(o.symbol)} ${escHtml(o.name)}`);
    }

    const debSorted = r.debits.slice().sort((a, b) => a.symbol.localeCompare(b.symbol));
    if (debSorted.length) {
      frags.push("扣款(開盤前)：");
      for (const o of debSorted) {
        frags.push(`${escHtml(o.symbol)} ${escHtml(o.name)}（${fmtNum(o.amount)}）`);
      }
    }
    const refSorted = r.refunds.slice().sort((a, b) => a.symbol.localeCompare(b.symbol));
    if (refSorted.length) {
      frags.push("退款入帳(開盤後)：");
      for (const o of refSorted) {
        frags.push(`${escHtml(o.symbol)} ${escHtml(o.name)}（${fmtNum(o.amount)}）`);
      }
    }

    if (!frags.length) {
      tdDetail.textContent = "—";
    } else {
      tdDetail.innerHTML = frags.join("<br>");
    }

    tr.appendChild(tdDate);
    tr.appendChild(tdReq);
    tr.appendChild(tdSf);
    tr.appendChild(tdDetail);
    body.appendChild(tr);
  }
}

function wire() {
  const form = document.getElementById("calc-form");
  if (form) {
    // Prevent accidental submit when user just wants live updates.
    form.addEventListener("submit", () => {
      // allow normal submit (keeps URL shareable)
    });
  }
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!t) return;
    if (t.classList && t.classList.contains("offer-check")) recompute();
    if (t.id === "capital-input") recompute();
    if (t.name === "horizon_days") recompute();
  });
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (!t) return;
    if (t.id === "capital-input" || t.name === "horizon_days") recompute();
  });

  recompute();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", wire);
} else {
  wire();
}

