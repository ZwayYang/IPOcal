from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup


HISTOCK_PUBLIC_URL = "https://histock.tw/stock/public.aspx"


@dataclass(frozen=True)
class HistockExtra:
    symbol: str
    market_price: float | None
    profit: int | None
    roi_pct: float | None
    total_qualified: str | None
    win_rate_pct: str | None


_SYMBOL_RE = re.compile(r"^\s*(\d{4,5})\s+")


def fetch_histock_public_table(client: httpx.Client | None = None) -> dict[str, HistockExtra]:
    """
    Scrape HiStock '公開申購/股票抽籤日程表' for extra columns:
    市價、獲利、報酬率(%)
    """
    close_client = False
    if client is None:
        client = httpx.Client(timeout=20, headers={"User-Agent": "IPOcal/0.1"})
        close_client = True
    try:
        r = client.get(HISTOCK_PUBLIC_URL)
        r.raise_for_status()
        html = r.text
    finally:
        if close_client:
            client.close()

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return {}

    # Map header name -> column index
    header = table.find("tr")
    if header is None:
        return {}
    ths = header.find_all(["th", "td"])
    headers = [t.get_text(strip=True) for t in ths]
    idx = {h: i for i, h in enumerate(headers)}

    # Expected headers (Chinese). Be defensive.
    sym_col = None
    for k in ("股票代號 名稱", "股票代號名稱", "股票代號"):
        if k in idx:
            sym_col = idx[k]
            break
    if sym_col is None:
        # fallback: second column in HiStock table is usually "股票代號 名稱"
        sym_col = 1

    def col(name: str) -> int | None:
        return idx.get(name)

    market_col = col("市價")
    profit_col = col("獲利")
    roi_col = col("報酬率(%)") or col("報酬率(％)")
    qualified_col = col("總合格件")
    win_rate_col = col("中籤率(%)") or col("中籤率(％)")

    out: dict[str, HistockExtra] = {}
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if not tds:
            continue

        sym_text = tds[sym_col].get_text(" ", strip=True) if sym_col < len(tds) else ""
        m = _SYMBOL_RE.match(sym_text)
        if not m:
            continue
        symbol = m.group(1)

        market_price = _to_float(_cell_text(tds, market_col))
        profit = _to_int(_cell_text(tds, profit_col))
        roi_pct = _to_float(_cell_text(tds, roi_col))
        total_qualified = _cell_text(tds, qualified_col) or None
        win_rate_pct = _cell_text(tds, win_rate_col) or None

        out[symbol] = HistockExtra(
            symbol=symbol,
            market_price=market_price,
            profit=profit,
            roi_pct=roi_pct,
            total_qualified=total_qualified,
            win_rate_pct=win_rate_pct,
        )
    return out


def _cell_text(tds, i: int | None) -> str:
    if i is None or i < 0 or i >= len(tds):
        return ""
    return tds[i].get_text(" ", strip=True)


def _to_float(s: str) -> float | None:
    s = (s or "").replace(",", "").strip()
    if not s or s in {"-", "—"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _to_int(s: str) -> int | None:
    s = (s or "").replace(",", "").strip()
    if not s or s in {"-", "—"}:
        return None
    try:
        return int(float(s))
    except Exception:
        return None

