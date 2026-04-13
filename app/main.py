from __future__ import annotations

from datetime import date, datetime
import html as html_std
from pathlib import Path
import threading
from typing import Any, Sequence
import traceback

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED

from . import calc
from .db import init_db, list_offers, upsert_offers
from .histock import fetch_histock_offers


app = FastAPI(title="IPOcal", version="0.1")


def _templates_dir() -> str:
    # .../app/main.py -> .../templates
    return str(Path(__file__).resolve().parents[1] / "templates")


templates = Jinja2Templates(directory=_templates_dir())
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parents[1] / "static")), name="static")

def _render(request: Request, name: str, context: dict[str, Any]) -> HTMLResponse:
    """
    Starlette's Jinja2Templates.TemplateResponse signature differs by version:
    - Newer: TemplateResponse(name, context)
    - Older: TemplateResponse(request, name, context)
    We support both for local + Render runtime compatibility.
    """
    try:
        return templates.TemplateResponse(name, context)  # type: ignore[arg-type]
    except TypeError:
        return templates.TemplateResponse(request, name, context)  # type: ignore[misc]


def _env(name: str) -> str | None:
    import os

    v = os.getenv(name)
    return v.strip() if v and v.strip() else None


class OptionalBasicAuthMiddleware(BaseHTTPMiddleware):
    """
    If IPOCAL_USERNAME/IPOCAL_PASSWORD are set, protect all routes with Basic Auth.
    If not set, do nothing (public).
    """

    async def dispatch(self, request: Request, call_next):
        user = _env("IPOCAL_USERNAME")
        pwd = _env("IPOCAL_PASSWORD")
        if not user or not pwd:
            return await call_next(request)

        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("basic "):
            import base64

            try:
                raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
                u, p = raw.split(":", 1)
                if u == user and p == pwd:
                    return await call_next(request)
            except Exception:
                pass

        headers = {"WWW-Authenticate": 'Basic realm="IPOcal"'}
        return PlainTextResponse("Unauthorized", status_code=HTTP_401_UNAUTHORIZED, headers=headers)


app.add_middleware(OptionalBasicAuthMiddleware)

_refresh_lock = threading.Lock()


def refresh_cache() -> dict[str, Any]:
    now = datetime.now()
    rows = fetch_histock_offers()
    total = upsert_offers(rows)
    return {"ok": True, "source": "histock", "rows_upserted": total, "refreshed_at": now.isoformat()}


def schedule_refresh(background: bool = True) -> None:
    """
    Trigger a refresh and record status in app.state.
    If background=True, run in a daemon thread.
    """

    def _run() -> None:
        if not _refresh_lock.acquire(blocking=False):
            app.state.refresh_status = "running"
            return
        try:
            app.state.refresh_status = "running"
            app.state.last_refresh_started_at = datetime.now().isoformat()
            result = refresh_cache()
            app.state.last_refresh_result = result
            app.state.last_refresh_error = None
            app.state.refresh_status = "ok"
        except Exception as e:
            app.state.last_refresh_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            app.state.refresh_status = "error"
        finally:
            _refresh_lock.release()

    if background:
        threading.Thread(target=_run, daemon=True).start()
    else:
        _run()


@app.on_event("startup")
def _startup() -> None:
    init_db()
    # IMPORTANT: never block startup on network fetches in production hosting.
    # Render (and similar platforms) can mark the service unhealthy if startup is slow.
    app.state.refresh_status = "idle"
    app.state.last_refresh_started_at = None
    app.state.last_refresh_result = None
    app.state.last_refresh_error = None
    schedule_refresh(background=True)

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(lambda: schedule_refresh(background=False), "cron", hour=6, minute=5)  # local time
    scheduler.start()
    app.state.scheduler = scheduler


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "ipocal"}

@app.head("/health")
def health_head() -> Response:
    return Response(status_code=200)

@app.get("/api/refresh_status")
def refresh_status() -> dict[str, Any]:
    return {
        "status": getattr(app.state, "refresh_status", "unknown"),
        "last_refresh_started_at": getattr(app.state, "last_refresh_started_at", None),
        "last_refresh_result": getattr(app.state, "last_refresh_result", None),
        "last_refresh_error": getattr(app.state, "last_refresh_error", None),
    }

@app.head("/api/refresh_status")
def refresh_status_head() -> Response:
    return Response(status_code=200)


@app.get("/refresh")
def refresh() -> RedirectResponse:
    schedule_refresh(background=True)
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/offers")
def api_offers() -> JSONResponse:
    rows = list_offers()
    return JSONResponse([dict(r) for r in rows])


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    horizon_days: int = 14,
    capital: int = 0,
    symbols: list[str] = Query(default=[]),
) -> HTMLResponse:
    today = date.today()
    horizon_days = max(7, min(int(horizon_days), 365))
    horizon_end = today.fromordinal(today.toordinal() + horizon_days)

    offers = []
    windows: list[calc.MoneyWindow] = []

    selected_set = set(symbols) if symbols else None  # None -> default all selected

    for r in list_offers():
        try:
            raw_json = r["raw_json"]
        except Exception:
            raw_json = ""
        extra = _extra_from_raw_json(raw_json or "")
        sub_start = calc.parse_date(r["sub_start"])
        sub_end = calc.parse_date(r["sub_end"])
        draw_date = calc.parse_date(r["draw_date"])
        allot_date = calc.parse_date(r["allot_date"])

        if not sub_start or not sub_end or not draw_date:
            continue
        if sub_end < today:
            continue
        if sub_start > horizon_end and draw_date > horizon_end:
            continue

        refund_date = calc.refund_date_estimate(draw_date)
        debit_date = calc.debit_date_after_subscription_end(sub_end)
        wire_by_date = calc.funding_wire_by_date(sub_end)
        loan_apply_by_date = calc.loan_apply_by_date(sub_end)

        price = calc.parse_price(r["actual_price"]) or calc.parse_price(r["underwritten_price"])
        shares = calc.parse_int_like(r["sub_shares"])
        amount = calc.required_amount(price, shares)

        refund_available_date = calc.available_date_after_refund(refund_date)
        status = _status(today, sub_start, sub_end)
        selected = selected_set is None or r["symbol"] in selected_set

        if selected and amount is not None:
            windows.extend(
                calc.money_windows_for_offer(
                    symbol=r["symbol"],
                    name=r["name"],
                    lock_start=debit_date,
                    draw_date=draw_date,
                    refund_date=refund_date,
                    allot_date=allot_date,
                    amount=amount,
                )
            )

        offers.append(
            {
                "symbol": r["symbol"],
                "name": r["name"],
                "market": r["market"],
                "sub_start": sub_start,
                "sub_end": sub_end,
                "draw_date": draw_date,
                "allot_date": allot_date,
                "refund_date": refund_date,
                "refund_available_date": refund_available_date,
                "wire_by_date": wire_by_date,
                "loan_apply_by_date": loan_apply_by_date,
                "lock_start": debit_date,
                "price": price,
                "market_price": r["market_price"],
                "profit": r["profit"],
                "roi_pct": r["roi_pct"],
                "underwritten_shares": extra.get("underwritten_shares"),
                "underwritten_lots": extra.get("underwritten_lots"),
                "shares": shares,
                "amount": amount,
                "win_rate_pct": r["win_rate_pct"],
                "total_qualified": r["total_qualified"],
                "lead_broker": r["lead_broker"],
                "status": status,
                "selected": selected,
                "expected_value": _expected_value(r["profit"], r["win_rate_pct"]),
            }
        )

    offers.sort(key=lambda o: (o["sub_start"], o["draw_date"], o["symbol"]))

    daily_apply = calc.daily_required_amount(windows, today, horizon_end, "apply")
    max_apply = max((amt for _, amt in daily_apply), default=0)
    capital = max(0, int(capital))
    daily_shortfall = [(d, max(0, amt - capital)) for d, amt in daily_apply]
    max_borrow = max((sf for _, sf in daily_shortfall), default=0)
    offers_for_detail = [o for o in offers if o["selected"] and o["amount"] is not None]
    daily_rows = []
    for d, amt in daily_apply:
        sf = max(0, amt - capital)
        daily_rows.append(
            {
                "date": d,
                "required": amt,
                "shortfall": sf,
                "detail": _daily_detail_line(d, offers_for_detail, sf),
            }
        )
    selected_count = sum(1 for o in offers if o["selected"])

    return _render(
        request,
        "index.html",
        {
            "request": request,
            "today": today,
            "horizon_days": horizon_days,
            "offers": offers,
            "daily_rows": daily_rows,
            "max_apply": max_apply,
            "capital": capital,
            "max_borrow": max_borrow,
            "selected_count": selected_count,
        },
    )


@app.head("/")
def index_head() -> Response:
    # Render health check probes HEAD /
    return Response(status_code=200)


def _md_slash(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}"


def _esc_detail(s: Any) -> str:
    return html_std.escape(str(s), quote=False)


_WIRE_LBL = (
    '<span class="rounded bg-amber-100 px-1.5 py-0.5 text-sm font-semibold text-amber-900">匯撥期限</span>'
)
_LOAN_LBL = (
    '<span class="rounded bg-violet-100 px-1.5 py-0.5 text-sm font-semibold text-violet-900">借款申請</span>'
)


def _daily_detail_line(day: date, offers_for_detail: Sequence[dict[str, Any]], shortfall: int) -> str:
    """與 static/app.js 一致：標籤高亮、多筆分行、日期僅月/日。"""
    frags: list[str] = []
    wire_hints = sorted([o for o in offers_for_detail if o["wire_by_date"] == day], key=lambda o: str(o["symbol"]))
    loan_hints = sorted([o for o in offers_for_detail if o["loan_apply_by_date"] == day], key=lambda o: str(o["symbol"]))
    for o in wire_hints:
        frags.append(f"{_WIRE_LBL} {_esc_detail(o['symbol'])} {_esc_detail(o['name'])}")
    for o in loan_hints:
        frags.append(f"{_LOAN_LBL} {_esc_detail(o['symbol'])} {_esc_detail(o['name'])}")

    debits = sorted([o for o in offers_for_detail if o["lock_start"] == day], key=lambda o: str(o["symbol"]))
    refunds = sorted([o for o in offers_for_detail if o["refund_date"] == day], key=lambda o: str(o["symbol"]))

    if debits:
        frags.append("扣款(開盤前)：")
        for o in debits:
            w, l = o["wire_by_date"], o["loan_apply_by_date"]
            frags.append(
                f"{_esc_detail(o['symbol'])} {_esc_detail(o['name'])}（{o['amount']:,}）；"
                f"匯撥不晚於 {_md_slash(w)}；借款不晚於 {_md_slash(l)}"
            )
    if refunds:
        frags.append("退款入帳(開盤後)：")
        for o in refunds:
            frags.append(f"{_esc_detail(o['symbol'])} {_esc_detail(o['name'])}（{o['amount']:,}）")

    if not frags:
        return "—"
    out = "<br>".join(frags)
    if shortfall > 0 and debits:
        out += (
            '<br><span class="text-rose-700 font-medium">'
            "【本日有資金缺口】請於上列各檔期限前備妥款項。</span>"
        )
    return out


def _status(today: date, sub_start: date, sub_end: date) -> str:
    if sub_start <= today <= sub_end:
        return "申購中"
    if today < sub_start:
        return "未開始"
    return "已截止"


def _extra_from_raw_json(raw_json: str) -> dict[str, Any]:
    """
    TWSE record indices (based on their JSON fields order):
    7: 承銷股數, 8: 實際承銷股數, 14: 總承銷金額(元)
    """
    import json

    try:
        payload = json.loads(raw_json)
        if isinstance(payload, dict) and payload.get("source") == "histock":
            return {
                "underwritten_shares": "",
                "underwritten_lots": str(payload.get("underwritten_lots") or "").strip(),
            }
        record = payload.get("record") or []
        # TWSE "實際承銷股數" is shares. HiStock shows "承銷張數" (lots).
        underwritten_shares = record[8] if len(record) > 8 else ""
        underwritten_lots = ""
        try:
            underwritten_lots = str(int(int(str(underwritten_shares).replace(",", "").strip()) / 1000))
        except Exception:
            underwritten_lots = ""
        return {
            "underwritten_shares": underwritten_shares,
            "underwritten_lots": underwritten_lots,
        }
    except Exception:
        return {"underwritten_shares": "", "underwritten_lots": ""}


def _expected_value(profit: int | None, win_rate_pct: str) -> float | None:
    """
    User requested EV formula:
      EV = profit * (win_rate_pct/100) - 20

    This treats 20 as a fixed per-try cost.
    """
    if profit is None:
        return None
    p = calc.parse_pct(win_rate_pct)
    if p is None:
        return None
    return (profit * (p / 100.0)) - 20.0

