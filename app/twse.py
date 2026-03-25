from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .db import OfferRow


TWSE_PUBLIC_FORM_URL = "https://www.twse.com.tw/announcement/publicForm"


@dataclass(frozen=True)
class TwsePublicForm:
    year: int
    fields: list[str]
    data: list[list[str]]


def fetch_twse_public_form(yy: int, client: httpx.Client | None = None) -> TwsePublicForm:
    params = {"response": "json", "yy": str(yy)}
    close_client = False
    if client is None:
        client = httpx.Client(timeout=20, follow_redirects=True)
        close_client = True
    try:
        try:
            payload = _get_json_following_redirects(
                client,
                TWSE_PUBLIC_FORM_URL,
                params=params,
                headers={"User-Agent": "IPOcal/0.1"},
            )
        except httpx.ConnectError as e:
            # Some Windows/Python builds may fail to validate TWSE's TLS chain.
            # Fallback to insecure TLS to keep the app usable; data is public.
            insecure = httpx.Client(timeout=20, verify=False, follow_redirects=True)
            try:
                payload = _get_json_following_redirects(
                    insecure,
                    TWSE_PUBLIC_FORM_URL,
                    params=params,
                    headers={"User-Agent": "IPOcal/0.1"},
                )
            finally:
                insecure.close()
            _ = e
    finally:
        if close_client:
            client.close()

    if payload.get("stat") != "OK":
        raise RuntimeError(f"TWSE returned non-OK stat: {payload.get('stat')!r}")

    fields = payload.get("fields") or []
    data = payload.get("data") or []
    src_year = int(payload.get("date") or 0)  # not critical; keep yy as requested
    return TwsePublicForm(year=src_year or yy, fields=fields, data=data)


def _get_json_following_redirects(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str],
    max_hops: int = 5,
) -> dict:
    """
    Render (and some network paths) may return 307 from TWSE even when a client
    is configured to follow redirects. Be extra defensive:
    - force follow_redirects=True on request
    - if still receiving 3xx, manually follow Location
    """
    cur_url = url
    cur_params = params
    for _ in range(max_hops):
        r = client.get(
            cur_url,
            params=cur_params,
            headers={
                **headers,
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.twse.com.tw/",
            },
            follow_redirects=True,
        )

        # Some environments return 3xx but still include the JSON body.
        if 300 <= r.status_code < 400:
            try:
                maybe = r.json()
                if isinstance(maybe, dict) and maybe.get("stat") == "OK":
                    return maybe
            except Exception:
                pass

            loc = r.headers.get("location")
            if loc:
                # TWSE may redirect to a fully-qualified URL that already includes query params.
                cur_url = str(httpx.URL(cur_url).join(loc))
                cur_params = {}  # prevent duplicating query params
                continue

            # No Location and not JSON; fall through to raise with context.
            raise httpx.HTTPStatusError(
                f"Redirect without Location from TWSE: {r.status_code} {r.reason_phrase}",
                request=r.request,
                response=r,
            )

        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Too many redirects when fetching TWSE publicForm: {url}")


def to_offer_rows(form: TwsePublicForm, fetched_at: datetime | None = None) -> list[OfferRow]:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    fetched_at_iso = fetched_at.isoformat()

    # Field positions from TWSE (stable ordering).
    # ["序號","抽籤日期","證券名稱","證券代號","發行市場","申購開始日","申購結束日", ...,
    #  "承銷價(元)","實際承銷價(元)","撥券日期(上市、上櫃日期)", ...,"申購股數", ...,"總合格件","中籤率(%)", ...]
    rows: list[OfferRow] = []
    for record in form.data:
        if not record or len(record) < 18:
            continue
        raw_json = json.dumps({"fields": form.fields, "record": record}, ensure_ascii=False)
        rows.append(
            OfferRow(
                source="twse_publicForm",
                year=_roc_year_of(record[1]) or form.year,
                seq=int(_safe_int(record[0]) or 0),
                draw_date=record[1].strip(),
                name=record[2].strip(),
                symbol=record[3].strip(),
                market=record[4].strip(),
                sub_start=record[5].strip(),
                sub_end=record[6].strip(),
                underwritten_price=record[9].strip(),
                actual_price=record[10].strip(),
                allot_date=record[11].strip(),
                lead_broker=record[12].strip(),
                sub_shares=record[13].strip(),
                total_qualified=record[15].strip(),
                win_rate_pct=record[16].strip(),
                cancelled=record[17].strip() if len(record) > 17 else "",
                market_price=None,
                profit=None,
                roi_pct=None,
                raw_json=raw_json,
                fetched_at_iso=fetched_at_iso,
            )
        )
    return rows


def _safe_int(s: str) -> int | None:
    try:
        return int(str(s).replace(",", "").strip())
    except Exception:
        return None


def _roc_year_of(roc_date: str) -> int | None:
    # "115/03/24" -> 115
    try:
        return int(roc_date.split("/")[0])
    except Exception:
        return None

