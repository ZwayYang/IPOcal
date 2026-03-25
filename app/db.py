from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class OfferRow:
    source: str
    year: int  # ROC year in source (e.g. 115)
    seq: int
    draw_date: str
    name: str
    symbol: str
    market: str
    sub_start: str
    sub_end: str
    underwritten_price: str
    actual_price: str
    allot_date: str
    lead_broker: str
    sub_shares: str
    total_qualified: str
    win_rate_pct: str
    cancelled: str
    market_price: float | None
    profit: int | None
    roi_pct: float | None
    raw_json: str
    fetched_at_iso: str


def db_path() -> Path:
    import os

    override = os.getenv("IPOCAL_DB_PATH")
    if override:
        p = Path(override).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    return Path(__file__).resolve().parents[1] / "data.sqlite3"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS offers (
              source TEXT NOT NULL,
              year INTEGER NOT NULL,
              seq INTEGER NOT NULL,
              draw_date TEXT NOT NULL,
              name TEXT NOT NULL,
              symbol TEXT NOT NULL,
              market TEXT NOT NULL,
              sub_start TEXT NOT NULL,
              sub_end TEXT NOT NULL,
              underwritten_price TEXT NOT NULL,
              actual_price TEXT NOT NULL,
              allot_date TEXT NOT NULL,
              lead_broker TEXT NOT NULL,
              sub_shares TEXT NOT NULL,
              total_qualified TEXT NOT NULL,
              win_rate_pct TEXT NOT NULL,
              cancelled TEXT NOT NULL,
              market_price REAL,
              profit INTEGER,
              roi_pct REAL,
              raw_json TEXT NOT NULL,
              fetched_at_iso TEXT NOT NULL,
              PRIMARY KEY (source, year, seq)
            );
            """
        )
        _ensure_columns(con)


def _ensure_columns(con: sqlite3.Connection) -> None:
    cols = {row["name"] for row in con.execute("PRAGMA table_info(offers)")}
    wanted = {
        "market_price": "REAL",
        "profit": "INTEGER",
        "roi_pct": "REAL",
    }
    for name, typ in wanted.items():
        if name in cols:
            continue
        con.execute(f"ALTER TABLE offers ADD COLUMN {name} {typ}")


def upsert_offers(rows: Iterable[OfferRow]) -> int:
    sql = """
    INSERT INTO offers (
      source, year, seq, draw_date, name, symbol, market, sub_start, sub_end,
      underwritten_price, actual_price, allot_date, lead_broker, sub_shares,
      total_qualified, win_rate_pct, cancelled, market_price, profit, roi_pct, raw_json, fetched_at_iso
    ) VALUES (
      :source, :year, :seq, :draw_date, :name, :symbol, :market, :sub_start, :sub_end,
      :underwritten_price, :actual_price, :allot_date, :lead_broker, :sub_shares,
      :total_qualified, :win_rate_pct, :cancelled, :market_price, :profit, :roi_pct, :raw_json, :fetched_at_iso
    )
    ON CONFLICT(source, year, seq) DO UPDATE SET
      draw_date=excluded.draw_date,
      name=excluded.name,
      symbol=excluded.symbol,
      market=excluded.market,
      sub_start=excluded.sub_start,
      sub_end=excluded.sub_end,
      underwritten_price=excluded.underwritten_price,
      actual_price=excluded.actual_price,
      allot_date=excluded.allot_date,
      lead_broker=excluded.lead_broker,
      sub_shares=excluded.sub_shares,
      total_qualified=excluded.total_qualified,
      win_rate_pct=excluded.win_rate_pct,
      cancelled=excluded.cancelled,
      market_price=COALESCE(excluded.market_price, offers.market_price),
      profit=COALESCE(excluded.profit, offers.profit),
      roi_pct=COALESCE(excluded.roi_pct, offers.roi_pct),
      raw_json=excluded.raw_json,
      fetched_at_iso=excluded.fetched_at_iso
    ;
    """
    with connect() as con:
        cur = con.executemany(sql, [r.__dict__ for r in rows])
        return cur.rowcount


def update_histock_extras(extras: dict[str, tuple[float | None, int | None, float | None]]) -> int:
    """
    extras: symbol -> (market_price, profit, roi_pct)
    Update all rows matching symbol.
    """
    sql = """
    UPDATE offers
    SET market_price = :market_price,
        profit = :profit,
        roi_pct = :roi_pct
    WHERE symbol = :symbol
    """
    payload = [
        {
            "symbol": sym,
            "market_price": mp,
            "profit": pf,
            "roi_pct": roi,
        }
        for sym, (mp, pf, roi) in extras.items()
    ]
    if not payload:
        return 0
    with connect() as con:
        cur = con.executemany(sql, payload)
        return cur.rowcount


def update_histock_stats(extras: dict[str, tuple[str | None, str | None]]) -> int:
    """
    extras: symbol -> (total_qualified, win_rate_pct)
    Store as-is (strings), because upstream may include commas or decimals.
    """
    sql = """
    UPDATE offers
    SET total_qualified = COALESCE(:total_qualified, total_qualified),
        win_rate_pct = COALESCE(:win_rate_pct, win_rate_pct)
    WHERE symbol = :symbol
    """
    payload = [
        {"symbol": sym, "total_qualified": tq, "win_rate_pct": wr}
        for sym, (tq, wr) in extras.items()
        if tq is not None or wr is not None
    ]
    if not payload:
        return 0
    with connect() as con:
        cur = con.executemany(sql, payload)
        return cur.rowcount


def list_offers() -> list[sqlite3.Row]:
    with connect() as con:
        return list(
            con.execute(
                """
                SELECT *
                FROM offers
                ORDER BY year DESC, draw_date DESC, seq ASC
                """
            )
        )

