function parseISODate(s) {
  // "2026-03-17" -> Date (local)
  if (!s) return null;
  const [y, m, d] = s.split("-").map((x) => parseInt(x, 10));
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
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
    const amount = parseInt((row.dataset.amount || "").replaceAll(",", ""), 10);
    if (!isFinite(amount) || amount <= 0) continue;
    const lockStart = parseISODate(row.dataset.lockStart);
    const refundDate = parseISODate(row.dataset.refundDate);
    if (!lockStart || !refundDate) continue;
    offers.push({
      symbol: row.dataset.symbol || "",
      name: row.dataset.name || "",
      amount,
      lockStart,
      refundDate,
    });
  }
  return offers;
}

function recompute() {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const horizonDays = getHorizonDays();
  const end = addDays(start, horizonDays);
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
    tdDate.textContent = r.date;

    const tdReq = document.createElement("td");
    tdReq.className = "px-4 py-2 text-right tabular-nums";
    tdReq.textContent = fmtNum(r.required);

    const tdSf = document.createElement("td");
    tdSf.className =
      "px-4 py-2 text-right tabular-nums " + (r.shortfall > 0 ? "text-rose-700 font-semibold" : "text-slate-600");
    tdSf.textContent = fmtNum(r.shortfall);

    const tdDetail = document.createElement("td");
    tdDetail.className = "px-4 py-2 text-slate-700";

    const parts = [];
    if (r.debits.length) {
      const s = r.debits
        .slice()
        .sort((a, b) => a.symbol.localeCompare(b.symbol))
        .map((o) => `${o.symbol} ${o.name}（${fmtNum(o.amount)}）`)
        .join("、");
      parts.push(`扣款(開盤前)：${s}`);
    }
    if (r.refunds.length) {
      const s = r.refunds
        .slice()
        .sort((a, b) => a.symbol.localeCompare(b.symbol))
        .map((o) => `${o.symbol} ${o.name}（${fmtNum(o.amount)}）`)
        .join("、");
      parts.push(`退款入帳(開盤後)：${s}`);
    }
    tdDetail.textContent = parts.length ? parts.join("；") : "—";

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

