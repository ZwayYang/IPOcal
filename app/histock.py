from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
import json

import httpx
from bs4 import BeautifulSoup

from .db import OfferRow


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


def fetch_histock_offers(client: httpx.Client | None = None) -> list[OfferRow]:
    """
    Primary datasource for cloud deployment (TWSE may block some datacenter IPs).
    Builds OfferRow list from HiStock table.
    """
    close_client = False
    if client is None:
        client = httpx.Client(timeout=20, headers={"User-Agent": "IPOcal/0.1"})
        close_client = True
    try:
        r = client.get(HISTOCK_PUBLIC_URL, follow_redirects=True)
        r.raise_for_status()
        html = r.text
    finally:
        if close_client:
            client.close()

    soup = BeautifulSoup(html, "html.parser")
    table = _find_public_table(soup)
    if table is None:
        return []

    header = table.find("tr")
    if header is None:
        return []
    ths = header.find_all(["th", "td"])
    headers = [t.get_text(strip=True) for t in ths]
    idx = {h: i for i, h in enumerate(headers)}

    def col(*names: str) -> int | None:
        for n in names:
            if n in idx:
                return idx[n]
        return None

    fetched_at_iso = datetime.now(timezone.utc).isoformat()

    draw_col = col("抽籤日期")
    sym_col = col("股票代號 名稱", "股票代號名稱", "股票代號") or 1
    market_col = col("發行市場")
    period_col = col("申購期間")
    allot_col = col("撥券日期")
    under_lots_col = col("承銷張數")
    under_price_col = col("承銷價")
    market_price_col = col("市價")
    profit_col = col("獲利")
    roi_col = col("報酬率(%)", "報酬率(％)")
    sub_lots_col = col("申購張數")
    qualified_col = col("總合格件")
    win_rate_col = col("中籤率(%)", "中籤率(％)")
    remark_col = col("備註")

    rows: list[OfferRow] = []
    seq = 0
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if not tds:
            continue

        sym_text = _cell_text(tds, sym_col)
        m = _SYMBOL_RE.match(sym_text)
        if not m:
            continue
        symbol = m.group(1)
        name = sym_text.split(None, 1)[1].strip() if len(sym_text.split(None, 1)) > 1 else sym_text.strip()

        draw_date_iso = _to_iso_date(_cell_text(tds, draw_col))
        if not draw_date_iso:
            continue
        draw_year = int(draw_date_iso.split("-", 1)[0])

        sub_start_iso, sub_end_iso = _parse_period(_cell_text(tds, period_col), draw_year, draw_date_iso)
        allot_date_iso = _parse_md(_cell_text(tds, allot_col), draw_year, draw_date_iso) or ""

        under_lots = _cell_text(tds, under_lots_col)
        under_price = _cell_text(tds, under_price_col)
        market_price = _to_float(_cell_text(tds, market_price_col))
        profit = _to_int(_cell_text(tds, profit_col))
        roi_pct = _to_float(_cell_text(tds, roi_col))
        sub_lots = _to_int(_cell_text(tds, sub_lots_col))
        sub_shares = f"{(sub_lots or 1) * 1000:,}"

        total_qualified = _cell_text(tds, qualified_col) or "0"
        win_rate_pct = (_cell_text(tds, win_rate_col) or "0").replace("%", "").replace("％", "").strip()
        market = _cell_text(tds, market_col) or ""
        remark = _cell_text(tds, remark_col) or ""

        seq += 1
        raw_json = json.dumps(
            {
                "source": "histock",
                "underwritten_lots": under_lots.strip(),
                "remark": remark,
            },
            ensure_ascii=False,
        )

        rows.append(
            OfferRow(
                source="histock",
                year=draw_year,
                seq=seq,
                draw_date=draw_date_iso,
                name=name,
                symbol=symbol,
                market=market,
                sub_start=sub_start_iso or draw_date_iso,
                sub_end=sub_end_iso or draw_date_iso,
                underwritten_price=under_price.strip() or "未訂出",
                actual_price=under_price.strip() or "未訂出",
                allot_date=allot_date_iso,
                lead_broker="",
                sub_shares=sub_shares,
                total_qualified=total_qualified,
                win_rate_pct=win_rate_pct,
                cancelled="",
                market_price=market_price,
                profit=profit,
                roi_pct=roi_pct,
                raw_json=raw_json,
                fetched_at_iso=fetched_at_iso,
            )
        )

    return rows


def _find_public_table(soup: BeautifulSoup):
    # Find the table that contains the "公開申購/股票抽籤日程表" columns.
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        hs = [t.get_text(strip=True) for t in header.find_all(["th", "td"])]
        if "抽籤日期" in hs and ("股票代號 名稱" in hs or "股票代號名稱" in hs) and "承銷價" in hs:
            return table
    return soup.find("table")


def _to_iso_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    s = s.replace(".", "/").replace("-", "/")
    parts = s.split("/")
    if len(parts) != 3:
        return None
    y, m, d = parts
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def _parse_md(md: str, year: int, draw_iso: str) -> str | None:
    md = (md or "").strip()
    if not md or md in {"-", "—"}:
        return None
    md = md.replace(".", "/").replace("-", "/")
    if "/" not in md:
        return None
    m, d = md.split("/", 1)
    try:
        m_i = int(m)
        d_i = int(d)
    except Exception:
        return None
    # handle year boundary (Jan draw, Dec md)
    draw_month = int(draw_iso.split("-", 2)[1])
    y = year - 1 if (draw_month == 1 and m_i == 12) else year
    return f"{y:04d}-{m_i:02d}-{d_i:02d}"


def _parse_period(period: str, year: int, draw_iso: str) -> tuple[str | None, str | None]:
    """
    "03/18~03/20" -> (YYYY-03-18, YYYY-03-20)
    Handles Dec->Jan boundary.
    """
    period = (period or "").strip()
    if not period or "~" not in period:
        return (None, None)
    left, right = [p.strip() for p in period.split("~", 1)]
    start = _parse_md(left, year, draw_iso)
    end = _parse_md(right, year, draw_iso)
    return (start, end)


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

