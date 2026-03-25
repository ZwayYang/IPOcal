from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MoneyWindow:
    symbol: str
    name: str
    start: date
    end: date
    amount: int
    kind: str  # "apply" or "win"


def parse_roc_date(s: str) -> date | None:
    """
    "115/03/24" -> date(2026, 3, 24)
    """
    s = (s or "").strip()
    if not s or "/" not in s:
        return None
    try:
        y, m, d = s.split("/", 2)
        y = int(y) + 1911
        m = int(m)
        d = int(d)
        return date(y, m, d)
    except Exception:
        return None


def add_business_days(d: date, days: int) -> date:
    step = 1 if days >= 0 else -1
    remaining = abs(days)
    cur = d
    while remaining:
        cur = cur + timedelta(days=step)
        if cur.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return cur


def parse_int_like(s: str) -> int | None:
    try:
        return int(str(s).replace(",", "").strip())
    except Exception:
        return None


def parse_price(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None


def parse_pct(s: str) -> float | None:
    """
    "8.02" -> 8.02
    "8.02%" -> 8.02
    """
    try:
        return float(str(s).replace("%", "").replace("％", "").replace(",", "").strip())
    except Exception:
        return None


def required_amount(price: float | None, shares: int | None) -> int | None:
    if price is None or shares is None:
        return None
    # Many cases are 1,000 shares. Round to integer dollars.
    return int(round(price * shares))


def refund_date_estimate(draw_date: date) -> date:
    # MVP: next business day after draw date.
    return add_business_days(draw_date, 1)


def available_date_after_refund(refund_date: date) -> date:
    """
    User rule: debit happens before open; refund happens after open.
    Therefore, money refunded on day D cannot be used for a debit that also
    occurs on day D (pre-open). Model this as cash becoming available starting
    the next business day.
    """
    return add_business_days(refund_date, 1)


def money_windows_for_offer(
    *,
    symbol: str,
    name: str,
    lock_start: date,
    draw_date: date,
    refund_date: date,
    allot_date: date | None,
    amount: int,
) -> list[MoneyWindow]:
    # "apply": from lock_start to refund_date (non-winning). Refund is after open,
    # so on refund day it is still considered locked for pre-open debits.
    windows = [
        MoneyWindow(symbol=symbol, name=name, start=lock_start, end=refund_date, amount=amount, kind="apply")
    ]
    # "win": from sub_start to allot_date (winning)
    if allot_date is not None and allot_date >= lock_start:
        windows.append(MoneyWindow(symbol=symbol, name=name, start=lock_start, end=allot_date, amount=amount, kind="win"))
    return windows


def daily_required_amount(windows: list[MoneyWindow], start: date, end: date, kind: str) -> list[tuple[date, int]]:
    cur = start
    out: list[tuple[date, int]] = []
    while cur <= end:
        total = 0
        for w in windows:
            if w.kind != kind:
                continue
            if w.start <= cur <= w.end:
                total += w.amount
        out.append((cur, total))
        cur = cur + timedelta(days=1)
    return out

