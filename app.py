from __future__ import annotations

import hashlib
import logging
import sys
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from calculator import classify_vehicle, format_quote_text, quote_lot
from iaai import format_iaai_quote_text, quote_iaai
from bamper import cancel_job as bamper_cancel_job
from bamper import get_job as bamper_get_job
from bamper import load_parts_catalog
from bamper import start_search_job as bamper_start_search
from bidcars import (
    is_bidcars_search_url,
    is_bidcars_url,
    normalize_bidcars_search_url,
    normalize_bidcars_url,
    ocean_default,
    parse_bidcars_lot_id,
)
from config import DATA_DIR, ROOT, Search, load_settings, write_searches_file
from fx_rate import ensure_fx_rate
from notify import notify_lot, prepare_lot_notify, send_message
from scraper import CopartBlockedError, _is_lot_image, get_scrape_service, parse_lot_id
from store import LotStore
from telegram_bot import poll_telegram, resolve_bot_username
from worker import run_cycle_safe, seed_search_safe, sleep_until_next

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("copart")

settings = load_settings(require_telegram=False, require_searches=False)
store = LotStore()
store.import_searches(list(settings.searches))

DIST = ROOT / "frontend" / "dist"
SYNC_LOCK = threading.Lock()
_fx_cache: float | None = None
_fx_source_cache: str | None = None

app = FastAPI(title="Copart CRM")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|(\d{1,3}\.){3}\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_COOKIE = "crm_session"
SESSION_MAX_AGE = 30 * 24 * 3600
_bot_username: str | None = None


class SearchIn(BaseModel):
    name: str = ""
    url: str
    comment: str = ""
    client_telegram: str = ""
    client_phone: str = ""
    platform: str | None = None
    kind: str | None = None


class SearchPatch(BaseModel):
    name: str | None = None
    comment: str | None = None
    client_telegram: str | None = None
    client_phone: str | None = None


def normalize_search_url(url: str, *, platform: str | None = None) -> tuple[str, str]:
    cleaned = (url or "").strip()
    want = (platform or "").strip().lower()
    if want not in {"copart", "bidcars"}:
        # Авто: по URL, если площадку не задали (вкладка «Восстановление»)
        if is_bidcars_url(cleaned) or is_bidcars_search_url(cleaned):
            want = "bidcars"
        else:
            want = "copart"
    if want == "bidcars":
        if not cleaned:
            raise HTTPException(400, "Вставьте URL поиска с Bid.cars")
        try:
            return normalize_bidcars_search_url(cleaned), "bidcars"
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if not cleaned:
        raise HTTPException(400, "Вставьте URL поиска с Copart")
    if is_bidcars_url(cleaned) or is_bidcars_search_url(cleaned):
        raise HTTPException(400, "Это ссылка Bid.cars — добавьте её во вкладке Bid.cars или «Восстановление»")
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned, "copart"
    if cleaned.startswith("www."):
        return f"https://{cleaned}", "copart"
    if "copart.co.uk" in cleaned.lower() or "copart.com" in cleaned.lower():
        return f"https://{cleaned.lstrip('/')}", "copart"
    raise HTTPException(400, "Нужен полный URL с Copart (https://www.copart.co.uk/…)")


class LotPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class EnabledIn(BaseModel):
    enabled: bool


class LookupIn(BaseModel):
    url: str


class QuoteIn(BaseModel):
    bid: float
    location: str | None = None
    category: str | None = None
    title: str = ""
    body_style: str | None = None
    vat_on_sale: bool | None = None
    dismantle_type: str | None = None
    dismantle_kg: float | None = None
    delivery_column: str | None = None
    fx_rate: float | None = None
    url: str | None = None
    history_id: int | None = None
    lot_id: str | None = None


class IaaiQuoteIn(BaseModel):
    bid: float
    title: str = ""
    body_style: str | None = None
    dismantle_type: str | None = None
    dismantle_kg: float | None = None
    bid_method: str = "live"
    volume: str = "standard"
    url: str | None = None
    include_america_delivery: bool = False
    inland_usd: float | None = None
    inland_miles: float | None = None
    ocean_usd: float | None = None
    bidcars_fee_usd: float | None = None
    destination_port: str | None = "rotterdam"
    ship_from: str | None = None
    location: str | None = None
    us_port: str | None = None
    us_port_label: str | None = None
    miles_to_new_jersey: float | None = None
    miles_to_houston: float | None = None
    distance_source: str | None = None
    history_id: int | None = None
    lot_id: str | None = None
    vin: str | None = None
    odometer: float | None = None
    primary_damage: str | None = None
    documents: str | None = None
    images: list[str] | None = None
    purpose: str | None = None
    vehicle_size: str | None = None
    auction_platform: str | None = None
    ocean_destination: str | None = None
    title_code: str | None = None
    is_sublot: bool | None = None
    sublot_location: str | None = None
    auction_fees_usd: float | None = None


class SublotCheckIn(BaseModel):
    auction_url: str | None = None
    auction_platform: str | None = None
    lot_id: str | None = None


class BidcarsLookupIn(BaseModel):
    url: str


class CustomsByIn(BaseModel):
    price_usd: float | None = None
    price_eur: float | None = None
    engine_cc: int | None = None
    year: int | None = None
    age_band: str | None = None
    engine_type: str | None = None
    fuel: str | None = None
    engine: str | None = None
    title: str | None = None
    person: str = "individual"
    benefit_50: bool = False
    include_epts: bool = True
    eur_byn: float | None = None
    usd_byn: float | None = None
    rates_auto: bool = True


class FxRateIn(BaseModel):
    fx_rate: float


class BynRatesIn(BaseModel):
    eur_byn: float | None = None
    usd_byn: float | None = None
    auto: bool = False


class BamperSearchIn(BaseModel):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    title: str | None = None
    engine: str | None = None
    fuel: str | None = None
    transmission: str | None = None
    body_style: str | None = None
    scrape: bool = True
    mode: str = "full"


class TelegramMessagesIn(BaseModel):
    messages: list[str]


class MePatch(BaseModel):
    notify: bool | None = None


class UserPatch(BaseModel):
    notify: bool | None = None
    enabled: bool | None = None
    role: str | None = None


def _public_api(method: str, path: str) -> bool:
    if path == "/api/auth/config":
        return True
    if path == "/api/auth/login" and method == "POST":
        return True
    if path.startswith("/api/auth/login/") and method == "GET":
        return True
    if path == "/api/auth/logout" and method == "POST":
        return True
    return False


def _set_session_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_MAX_AGE,
        path="/",
    )


def _clear_session_cookie(response: Response, *, secure: bool = False) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, samesite="lax")


def _cookie_secure(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


def _request_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Нужна авторизация через Telegram")
    return user


def _require_admin(request: Request) -> dict:
    user = _request_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Только администратор")
    return user


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    user = store.get_session_user(request.cookies.get(SESSION_COOKIE))
    request.state.user = user
    path = request.url.path
    if path.startswith("/api/") and not _public_api(request.method, path) and not user:
        origin = request.headers.get("origin") or ""
        headers = {}
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            {"detail": "Нужна авторизация через Telegram"},
            status_code=401,
            headers=headers,
        )
    return await call_next(request)


def refresh_fx_cache() -> float:
    global _fx_cache, _fx_source_cache
    rate = store.get_fx_rate()
    if not rate:
        rate = ensure_fx_rate(store)
    _fx_cache = rate
    _fx_source_cache = store.get_meta("fx_rate_source")
    return rate


def current_fx_rate() -> float:
    if _fx_cache and _fx_cache > 0:
        return _fx_cache
    return refresh_fx_cache()


def with_quote(lot: dict, bid: float | None = None, extra: dict | None = None) -> dict:
    payload = extra or {}
    classified = classify_vehicle(
        " ".join(part for part in (lot.get("body_style"), lot.get("vehicle_type_raw"), lot.get("title")) if part)
    )
    lot["dismantle_type"] = payload.get("dismantle_type") or classified["dismantle_type"]
    fx = payload.get("fx_rate")
    if fx is None:
        fx = current_fx_rate()
    quote = quote_lot(
        bid=bid if bid is not None else lot.get("bid"),
        location=payload.get("location", lot.get("location")),
        category=payload.get("category", lot.get("category")),
        title=payload.get("title") or lot.get("title") or "",
        body_style=payload.get("body_style") or lot.get("body_style") or lot.get("vehicle_type_raw"),
        vat_on_sale=payload.get("vat_on_sale", lot.get("vat_on_sale")),
        dismantle_type=payload.get("dismantle_type"),
        dismantle_kg=payload.get("dismantle_kg"),
        delivery_column=payload.get("delivery_column"),
        fx_rate=fx,
    )
    lot["quote"] = quote
    lot["quote_text"] = format_quote_text(lot, quote) if quote else None
    return lot


def _persist_calc_history(lot: dict, history_id: int | None = None) -> int | None:
    entry = dict(lot)
    if not entry.get("auction"):
        url = str(entry.get("url") or "").lower()
        quote = entry.get("quote") if isinstance(entry.get("quote"), dict) else {}
        if (
            entry.get("source") == "bidcars"
            or quote.get("auction") == "iaai"
            or "bid.cars" in url
        ):
            entry["auction"] = "iaai"
        else:
            entry["auction"] = "copart"
    if history_id:
        updated = store.update_calc_history(history_id, entry)
        return updated["id"] if updated else None
    saved = store.save_calc_history(entry)
    return saved["id"]


def current_settings():
    return load_settings(require_telegram=False, require_searches=False)


def bot_username() -> str | None:
    global _bot_username
    token = current_settings().telegram_token
    if not token:
        _bot_username = None
        return None
    if _bot_username:
        return _bot_username
    name = resolve_bot_username(token)
    if name:
        _bot_username = name
    return _bot_username


def notify_chat_ids(extra: str = "") -> list[str]:
    chats = store.notify_chat_ids()
    extra = (extra or "").strip()
    if extra and extra not in chats:
        chats.append(extra)
    return chats


def telegram_notify(token: str, chat_id: str, lot: dict) -> None:
    payload = prepare_lot_notify(store, lot)
    chats = store.search_notify_chats_for_lot(payload)
    extra = (chat_id or "").strip()
    if extra and extra not in chats:
        chats.append(extra)
    if not chats:
        log.info("Новый лот %s — нет получателей Telegram (включите уведомления в боте /notify)", lot.get("lot_id"))
        return
    sent = notify_lot(token, chats, payload)
    log.info("Telegram: лот %s → %s чат(ов)", lot.get("lot_id"), sent)


def persist_searches() -> None:
    items = [
        Search(name=row["name"], url=row["url"])
        for row in store.list_searches(platform="copart", kind="client")
        if row["enabled"]
    ]
    try:
        write_searches_file(items)
    except OSError as exc:
        log.warning("Не удалось записать searches.txt: %s", exc)


def _seed_search_background(search_id: int) -> None:
    time.sleep(0.5)
    if not SYNC_LOCK.acquire(blocking=True, timeout=900):
        log.error("Не удалось запустить первичную загрузку поиска %s", search_id)
        return
    try:
        row = store.get_search(search_id)
        if not row or row.get("seeded_at"):
            return
        cfg = current_settings()
        result = seed_search_safe(cfg, store, search_id)
        log.info(
            "Поиск «%s»: первично сохранено %s лотов",
            row["name"],
            result.get("found", 0),
        )
    except CopartBlockedError:
        log.exception("Copart временно недоступен при первичной загрузке поиска %s", search_id)
    except Exception:
        log.exception("Ошибка первичной загрузки поиска %s", search_id)
    finally:
        SYNC_LOCK.release()


def worker_loop() -> None:
    time.sleep(3)
    while True:
        cfg = current_settings()
        try:
            with SYNC_LOCK:
                notify = telegram_notify if cfg.telegram_token else None
                run_cycle_safe(cfg, store, notify=notify)
        except CopartBlockedError:
            log.exception("Copart временно недоступен")
        except Exception:
            log.exception("Ошибка синхронизации")
        sleep_until_next(cfg)


@app.on_event("startup")
def startup() -> None:
    refresh_fx_cache()
    cfg = current_settings()
    username = bot_username()
    if cfg.telegram_token and username:
        log.info("Telegram-бот: @%s — вход в CRM и уведомления о новых авто", username)
    elif cfg.telegram_token:
        log.warning("TELEGRAM_BOT_TOKEN задан, но getMe не удался — проверьте токен")
    else:
        log.warning("Задайте TELEGRAM_BOT_TOKEN в .env — без него вход в CRM недоступен")
    threading.Thread(target=worker_loop, name="copart-sync", daemon=True).start()
    threading.Thread(
        target=poll_telegram,
        args=(store, lambda: current_settings().telegram_token),
        name="telegram-bot",
        daemon=True,
    ).start()
    log.info("API: http://127.0.0.1:%s  UI: http://127.0.0.1:5173", cfg.crm_port)


@app.get("/")
def index():
    built = DIST / "index.html"
    if built.exists():
        return FileResponse(built)
    return {
        "ok": True,
        "api": "Copart CRM backend",
        "ui": "http://127.0.0.1:5173",
        "hint": "Запустите frontend: cd frontend && npm run dev",
    }


@app.get("/api/auth/config")
def auth_config(request: Request) -> dict:
    username = bot_username()
    user = getattr(request.state, "user", None)
    poll_ok = store.get_meta("telegram_poll_ok")
    poll_error = store.get_meta("telegram_poll_error") or ""
    return {
        "configured": bool(current_settings().telegram_token and username),
        "bot_username": username,
        "user": user,
        "telegram_poll_ok": None if poll_ok is None else poll_ok == "1",
        "telegram_poll_error": poll_error or None,
    }


@app.post("/api/auth/login")
def auth_login() -> dict:
    cfg = current_settings()
    username = bot_username()
    if not cfg.telegram_token or not username:
        raise HTTPException(503, "Задайте TELEGRAM_BOT_TOKEN в .env и перезапустите сервер")
    token = store.create_login_token()
    return {
        "token": token,
        "bot_username": username,
        "bot_url": f"https://t.me/{username}?start={token}",
    }


@app.get("/api/auth/login/{token}")
def auth_poll(token: str, request: Request, response: Response) -> dict:
    row = store.get_login_token(token)
    if not row:
        raise HTTPException(404, "Сессия входа не найдена")
    if row.get("session_token"):
        user = store.get_user(row["user_id"])
        if not user or not user["enabled"]:
            return {"status": "denied"}
        _set_session_cookie(response, row["session_token"], secure=_cookie_secure(request))
        return {"status": "ok", "user": user}
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        return {"status": "expired"}
    return {"status": "pending"}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    store.delete_session(request.cookies.get(SESSION_COOKIE))
    _clear_session_cookie(response, secure=_cookie_secure(request))
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    return _request_user(request)


@app.patch("/api/auth/me")
def auth_patch_me(request: Request, body: MePatch) -> dict:
    user = _request_user(request)
    if body.notify is not None:
        user = store.set_user_notify(user["id"], body.notify) or user
    return user


@app.get("/api/users")
def list_users(request: Request) -> list[dict]:
    _require_admin(request)
    return store.list_users()


@app.patch("/api/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request) -> dict:
    _require_admin(request)
    user = store.get_user(user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    try:
        if body.notify is not None:
            user = store.set_user_notify(user_id, body.notify) or user
        if body.enabled is not None:
            user = store.set_user_enabled(user_id, body.enabled) or user
        if body.role is not None:
            user = store.set_user_role(user_id, body.role) or user
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return user


@app.get("/api/state")
def state(request: Request, platform: str | None = None, kind: str | None = None) -> dict:
    search_kind = (kind or "client").strip().lower()
    if search_kind not in {"client", "restoration"}:
        search_kind = "client"
    plat = (platform or "").strip().lower() or None
    if search_kind == "client":
        if plat not in {"copart", "bidcars"}:
            plat = "copart"
    else:
        plat = None
    return {
        "stats": store.stats(platform=plat, kind=search_kind),
        "sync": store.sync_status(),
        "searches": store.list_searches(platform=plat, kind=search_kind),
        "platform": plat or "restoration",
        "kind": search_kind,
        "interval_minutes": current_settings().poll_interval_minutes,
        "telegram": bool(current_settings().telegram_token),
        "notify_count": len(store.notify_chat_ids()),
        "me": getattr(request.state, "user", None),
        "fx_rate": current_fx_rate(),
        "fx_source": _fx_source_cache or store.get_meta("fx_rate_source"),
        "eur_byn": store.get_byn_rates().get("eur_byn"),
        "usd_byn": store.get_byn_rates().get("usd_byn"),
        "byn_rates_source": store.get_byn_rates().get("source"),
    }


@app.post("/api/settings/fx-rate")
def set_fx_rate(body: FxRateIn) -> dict:
    global _fx_cache, _fx_source_cache
    if body.fx_rate <= 0:
        raise HTTPException(400, "Курс должен быть больше 0")
    rate = store.set_fx_rate(body.fx_rate, source="manual")
    _fx_cache = rate
    _fx_source_cache = "manual"
    return {"fx_rate": rate, "fx_source": "manual"}


@app.post("/api/settings/byn-rates")
def set_byn_rates(body: BynRatesIn) -> dict:
    if body.auto:
        from customs_by import fetch_nbrb_rates

        rates = fetch_nbrb_rates(force=True)
        saved = store.set_byn_rates(
            eur_byn=float(rates.get("EUR") or 0) or None,
            usd_byn=float(rates.get("USD") or 0) or None,
            source="auto",
        )
        return {
            "eur_byn": saved.get("eur_byn"),
            "usd_byn": saved.get("usd_byn"),
            "source": saved.get("source"),
        }
    if (body.eur_byn is None or body.eur_byn <= 0) and (body.usd_byn is None or body.usd_byn <= 0):
        raise HTTPException(400, "Укажите курсы EUR и/или USD больше 0")
    saved = store.set_byn_rates(
        eur_byn=body.eur_byn,
        usd_byn=body.usd_byn,
        source="manual",
    )
    return {
        "eur_byn": saved.get("eur_byn"),
        "usd_byn": saved.get("usd_byn"),
        "source": saved.get("source"),
    }


@app.get("/api/lots")
def lots(
    status: str | None = None,
    search: str | None = None,
    q: str | None = None,
    stock: str = "in",
    feed: bool = False,
    source: str | None = None,
    kind: str | None = None,
) -> list[dict]:
    in_stock: bool | None
    if stock == "all":
        in_stock = None
    elif stock == "out":
        in_stock = False
    else:
        in_stock = True
    search_kind = (kind or "client").strip().lower()
    if search_kind not in {"client", "restoration"}:
        search_kind = "client"
    src = (source or "").strip().lower() or None
    if search_kind == "client":
        if src not in {"copart", "bidcars"}:
            src = "copart"
    else:
        # Восстановление: лоты с обеих площадок
        src = src if src in {"copart", "bidcars"} else None
    return store.list_lots(
        status=status or None,
        search=search or None,
        q=q or None,
        in_stock=in_stock,
        feed=feed,
        source=src,
        kind=search_kind,
    )


@app.patch("/api/lots/{lot_id}")
def patch_lot(lot_id: str, body: LotPatch) -> dict:
    allowed = {"new", "watching", "bid", "skip", "won", "lost"}
    if body.status is not None and body.status not in allowed:
        raise HTTPException(400, "Неизвестный статус")
    lot = store.update_lot(lot_id, status=body.status, notes=body.notes)
    if not lot:
        raise HTTPException(404, "Лот не найден")
    return lot


@app.post("/api/searches")
def add_search(body: SearchIn, request: Request) -> dict:
    user = _request_user(request)
    search_kind = (body.kind or "client").strip().lower()
    if search_kind not in {"client", "restoration"}:
        search_kind = "client"
    # Для восстановления площадку берём из URL; для клиентских вкладок — из platform
    plat_hint = None if search_kind == "restoration" else body.platform
    url, platform = normalize_search_url(body.url, platform=plat_hint)
    name = body.name.strip()
    row = store.add_search(
        name,
        url,
        comment=body.comment,
        client_telegram=body.client_telegram,
        client_phone=body.client_phone,
        owner_user_id=user.get("id"),
        platform=platform,
        kind=search_kind,
    )
    persist_searches()
    if row.get("id") and not row.get("seeded_at"):
        threading.Thread(
            target=_seed_search_background,
            args=(row["id"],),
            name=f"seed-search-{row['id']}",
            daemon=True,
        ).start()
        row = {**row, "seeding": True}
    return row


@app.post("/api/searches/{search_id}/enabled")
def enable_search(search_id: int, body: EnabledIn) -> dict:
    store.set_search_enabled(search_id, body.enabled)
    persist_searches()
    return {"ok": True}


@app.patch("/api/searches/{search_id}")
def patch_search(search_id: int, body: SearchPatch) -> dict:
    row = store.update_search(
        search_id,
        name=body.name,
        comment=body.comment,
        client_telegram=body.client_telegram,
        client_phone=body.client_phone,
    )
    if not row:
        raise HTTPException(404, "Поиск не найден")
    persist_searches()
    return row


@app.delete("/api/searches/{search_id}")
def remove_search(search_id: int) -> dict:
    store.delete_search(search_id)
    persist_searches()
    return {"ok": True}


@app.post("/api/sync")
def sync_now(platform: str | None = None, kind: str | None = None) -> dict:
    plat = (platform or "").strip().lower() or None
    search_kind = (kind or "").strip().lower() or None
    if plat not in {None, "copart", "bidcars"}:
        plat = None
    if search_kind not in {None, "client", "restoration"}:
        search_kind = None
    if search_kind == "restoration":
        plat = None
    elif plat in {"copart", "bidcars"} and not search_kind:
        search_kind = "client"
    if not SYNC_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Синхронизация уже идёт")
    try:
        result = run_cycle_safe(
            current_settings(),
            store,
            notify=telegram_notify,
            platform=plat,
            kind=search_kind,
        )
        return result
    except CopartBlockedError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    finally:
        SYNC_LOCK.release()


@app.post("/api/calc/lookup")
def calc_lookup(body: LookupIn) -> dict:
    raw = (body.url or "").strip()
    if "lotSearchResults" in raw and "/lot/" not in raw:
        raise HTTPException(400, "Нужна ссылка на конкретный лот Copart, не на поиск")
    lot_id = parse_lot_id(raw)
    if not lot_id:
        raise HTTPException(400, "Вставьте ссылку на лот, например https://www.copart.co.uk/lot/12345678")
    log.info("Калькулятор: открываю лот %s", lot_id)
    try:
        details = get_scrape_service(settings.headless).fetch_lot(raw)
        details["cached"] = False
        details["auction"] = "copart"
        result = with_quote(details)
        result["history_id"] = _persist_calc_history(result)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except CopartBlockedError as exc:
        cached = store.get(lot_id)
        if cached and cached.get("title"):
            cached["cached"] = True
            cached["auction"] = "copart"
            cached.setdefault("images", [])
            return with_quote(cached)
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        cached = store.get(lot_id)
        if cached and cached.get("title"):
            cached["cached"] = True
            cached["auction"] = "copart"
            cached.setdefault("images", [])
            return with_quote(cached)
        raise HTTPException(500, f"Не удалось открыть лот: {exc}") from exc


@app.post("/api/calc/quote")
def calc_quote(body: QuoteIn) -> dict:
    if body.bid is None or body.bid < 0:
        raise HTTPException(400, "Укажите ставку")
    lot = {
        "lot_id": body.lot_id,
        "title": body.title,
        "url": body.url,
        "location": body.location,
        "category": body.category,
        "body_style": body.body_style,
        "bid": body.bid,
        "vat_on_sale": body.vat_on_sale,
    }
    result = with_quote(
        lot,
        bid=body.bid,
        extra={
            "location": body.location,
            "category": body.category,
            "title": body.title,
            "body_style": body.body_style,
            "vat_on_sale": body.vat_on_sale,
            "dismantle_type": body.dismantle_type,
            "dismantle_kg": body.dismantle_kg,
            "delivery_column": body.delivery_column,
            "fx_rate": body.fx_rate,
        },
    )
    if body.history_id:
        prev = store.get_calc_history(body.history_id)
        if prev:
            payload = prev.get("payload") if isinstance(prev.get("payload"), dict) else {}
            payload.update(result)
            payload["bid"] = body.bid
            result["history_id"] = _persist_calc_history(payload, body.history_id)
    return result


@app.get("/api/bamper/parts")
def bamper_parts_catalog(refresh: bool = False) -> dict:
    items = load_parts_catalog(refresh=refresh)
    return {"count": len(items), "items": items}


@app.post("/api/bamper/search")
def bamper_search(body: BamperSearchIn) -> dict:
    try:
        job = bamper_start_search(
            make=body.make,
            model=body.model,
            year=body.year,
            title=body.title,
            engine=body.engine,
            fuel=body.fuel,
            transmission=body.transmission,
            body_style=body.body_style,
            scrape=bool(body.scrape),
            mode=body.mode or "full",
        )
        return job
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Bamper: {exc}") from exc


@app.get("/api/bamper/jobs/{job_id}")
def bamper_job(job_id: str) -> dict:
    job = bamper_get_job(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job


@app.post("/api/bamper/jobs/{job_id}/cancel")
def bamper_job_cancel(job_id: str) -> dict:
    job = bamper_cancel_job(job_id)
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return job


@app.post("/api/telegram/send")
def telegram_send_me(body: TelegramMessagesIn, request: Request) -> dict:
    user = _request_user(request)
    token = current_settings().telegram_token
    if not token:
        raise HTTPException(400, "Telegram-бот не настроен")
    chat_id = str(user.get("telegram_id") or "")
    if not chat_id:
        raise HTTPException(400, "Нет Telegram ID у пользователя")
    texts = [str(x).strip() for x in (body.messages or []) if str(x).strip()]
    if not texts or len(texts) > 8:
        raise HTTPException(400, "Нужно от 1 до 8 сообщений")
    for text in texts:
        if len(text) > 4096:
            raise HTTPException(400, "Сообщение длиннее лимита Telegram (4096)")
        try:
            send_message(token, chat_id, text)
        except Exception as exc:
            raise HTTPException(502, f"Telegram не принял сообщение: {exc}") from exc
    return {"ok": True, "sent": len(texts)}


@app.get("/api/calc/title-tariffs")
def title_tariffs() -> dict:
    from usa_title import list_title_tariffs

    return {"items": list_title_tariffs()}


@app.post("/api/calc/customs-by")
def calc_customs_by(body: CustomsByIn) -> dict:
    from customs_by import calculate_customs_by, fetch_nbrb_rates

    rates = None
    if body.rates_auto:
        fetched = fetch_nbrb_rates()
        rates = {
            "EUR": float(fetched.get("EUR") or 0) or 3.45,
            "USD": float(fetched.get("USD") or 0) or 3.2,
            "_usd_eur": float(fetched.get("_usd_eur") or 0) or 0.92,
        }
        # обновить сохранённые авто-курсы (тихо)
        try:
            store.set_byn_rates(
                eur_byn=rates["EUR"],
                usd_byn=rates["USD"],
                source="auto",
            )
        except Exception:
            pass
    else:
        saved = store.get_byn_rates()
        eur = body.eur_byn if body.eur_byn and body.eur_byn > 0 else saved.get("eur_byn")
        usd = body.usd_byn if body.usd_byn and body.usd_byn > 0 else saved.get("usd_byn")
        if not eur or not usd:
            fetched = fetch_nbrb_rates()
            eur = eur or float(fetched.get("EUR") or 3.45)
            usd = usd or float(fetched.get("USD") or 3.2)
        rates = {
            "EUR": float(eur),
            "USD": float(usd),
            "_usd_eur": float(usd) / float(eur) if eur else 0.92,
        }

    result = calculate_customs_by(
        price_usd=body.price_usd,
        price_eur=body.price_eur,
        engine_cc=body.engine_cc,
        year=body.year,
        age_band=body.age_band,
        engine_type=body.engine_type,
        fuel=body.fuel,
        engine=body.engine,
        title=body.title,
        person=body.person or "individual",
        benefit_50=bool(body.benefit_50),
        include_epts=bool(body.include_epts),
        rates=rates,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Не удалось посчитать растаможку")
    if result.get("rates"):
        result["rates"]["source"] = "auto" if body.rates_auto else "manual"
    return result


@app.post("/api/calc/iaai")
def calc_iaai(body: IaaiQuoteIn) -> dict:
    if body.bid is None or body.bid < 0:
        raise HTTPException(400, "Укажите ставку")
    method = "proxy" if str(body.bid_method or "").lower() == "proxy" else "live"
    volume = "high" if str(body.volume or "").lower() == "high" else "standard"
    purpose = "restoration" if str(body.purpose or "").lower() == "restoration" else "iaai"
    quote = quote_iaai(
        bid=body.bid,
        title=body.title,
        body_style=body.body_style,
        dismantle_type=body.dismantle_type,
        dismantle_kg=body.dismantle_kg,
        bid_method=method,
        volume=volume,
        inland_usd=body.inland_usd,
        inland_miles=body.inland_miles,
        ocean_usd=body.ocean_usd,
        bidcars_fee_usd=body.bidcars_fee_usd,
        destination_port=body.destination_port,
        ship_from=body.ship_from,
        location=body.location,
        us_port=body.us_port,
        us_port_label=body.us_port_label,
        miles_to_new_jersey=body.miles_to_new_jersey,
        miles_to_houston=body.miles_to_houston,
        distance_source=body.distance_source,
        include_america_delivery=bool(body.include_america_delivery),
        purpose=purpose,
        vehicle_size=body.vehicle_size,
        auction_platform=body.auction_platform,
        ocean_destination=body.ocean_destination,
        documents=body.documents,
        title_code=body.title_code or body.documents,
        is_sublot=body.is_sublot,
        sublot_location=body.sublot_location,
        auction_fees_usd=body.auction_fees_usd,
    )
    if not quote:
        raise HTTPException(400, "Не удалось посчитать")
    lot_id = body.lot_id or parse_bidcars_lot_id(body.url or "") or ""
    lot = {
        "auction": "iaai",
        "source": "bidcars",
        "lot_id": lot_id,
        "title": body.title,
        "url": body.url,
        "location": body.location,
        "ship_from": body.ship_from,
        "vin": body.vin,
        "odometer": body.odometer,
        "body_style": body.body_style,
        "primary_damage": body.primary_damage,
        "documents": body.documents,
        "images": body.images or [],
        "bid": body.bid,
        "inland_usd": body.inland_usd,
        "inland_miles": body.inland_miles,
        "us_port": body.us_port,
        "us_port_label": body.us_port_label,
        "miles_to_new_jersey": body.miles_to_new_jersey,
        "miles_to_houston": body.miles_to_houston,
        "distance_source": body.distance_source,
        "dismantle_type": quote["dismantle_type"],
        "quote": quote,
    }
    quote_text = format_iaai_quote_text(lot, quote)
    lot["quote_text"] = quote_text
    history_id = _persist_calc_history(lot, body.history_id)
    return {
        "quote": quote,
        "quote_text": quote_text,
        "dismantle_type": quote["dismantle_type"],
        "history_id": history_id,
    }


@app.post("/api/calc/bidcars/lookup")
@app.post("/api/calc/usa-lookup")
def calc_bidcars_lookup(body: BidcarsLookupIn) -> dict:
    raw = (body.url or "").strip()
    from usa_auction import detect_usa_source

    source = detect_usa_source(raw)
    if not source:
        # lot id only → try bid.cars as before
        try:
            from bidcars import normalize_bidcars_url

            normalize_bidcars_url(raw)
            source = "bidcars"
        except Exception:
            raise HTTPException(
                400,
                "Нужна ссылка Copart.com, IAAI.com или Bid.cars на лот",
            ) from None

    log.info("Калькулятор USA: %s → %s", source, raw[:120])
    try:
        details = get_scrape_service(settings.headless).fetch_usa_lot(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except CopartBlockedError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Не удалось открыть лот ({source}): {exc}") from exc

    classified = classify_vehicle(
        " ".join(part for part in (details.get("body_style"), details.get("title")) if part)
    )
    details["dismantle_type"] = classified["dismantle_type"]
    port = "rotterdam"
    ocean = (details.get("ocean_usd_by_port") or {}).get(port)
    if ocean is None:
        ocean = ocean_default(port)
    auction_platform = str(details.get("auction_platform") or ("copart" if source == "copart" else "iaai"))
    bid = details.get("bid")
    quote = None
    quote_text = None
    if bid is not None and float(bid) >= 0:
        quote = quote_iaai(
            bid=float(bid),
            title=details.get("title") or "",
            body_style=details.get("body_style"),
            dismantle_type=details["dismantle_type"],
            bid_method="live",
            volume="standard",
            inland_usd=details.get("inland_usd"),
            inland_miles=details.get("inland_miles"),
            ocean_usd=ocean,
            bidcars_fee_usd=details.get("bidcars_fee_usd") or 0,
            destination_port=port,
            ship_from=details.get("ship_from"),
            location=details.get("location"),
            us_port=details.get("us_port"),
            us_port_label=details.get("us_port_label"),
            miles_to_new_jersey=details.get("miles_to_new_jersey"),
            miles_to_houston=details.get("miles_to_houston"),
            distance_source=details.get("distance_source"),
            include_america_delivery=True,
            purpose="iaai",
            auction_platform=auction_platform,
            documents=details.get("documents") or details.get("title_code"),
            title_code=details.get("title_code") or details.get("documents"),
            is_sublot=bool(details.get("is_sublot")),
            sublot_location=details.get("sublot_location"),
        )
        if quote:
            quote_text = format_iaai_quote_text(details, quote)
    details["auction"] = auction_platform
    details["source"] = details.get("source") or source
    details["quote"] = quote
    details["quote_text"] = quote_text
    details["history_id"] = _persist_calc_history(details)
    return details


@app.post("/api/calc/check-sublot")
def calc_check_sublot(body: SublotCheckIn) -> dict:
    """После показа цены: открыть Copart/IAAI и проверить Sublot/Offsite (+$100)."""
    try:
        result = get_scrape_service(settings.headless).check_usa_sublot(
            auction_url=body.auction_url,
            auction_platform=body.auction_platform,
            lot_id=body.lot_id,
        )
    except CopartBlockedError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Не удалось проверить Sublot/Offsite: {exc}") from exc
    return result


@app.get("/api/calc/history")
def calc_history(limit: int = 40) -> dict:
    return {"items": store.list_calc_history(limit=min(max(limit, 1), 100))}


@app.get("/api/calc/history/{history_id}")
def calc_history_item(history_id: int) -> dict:
    item = store.get_calc_history(history_id)
    if not item:
        raise HTTPException(404, "Запись не найдена")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    if not payload:
        payload = {
            "lot_id": item.get("lot_id"),
            "title": item.get("title"),
            "url": item.get("url"),
            "bid": item.get("bid"),
            "location": item.get("location"),
            "category": item.get("category"),
            "images": [item["image"]] if item.get("image") else [],
        }
    payload["history_id"] = item["id"]
    payload["auction"] = item.get("auction") or payload.get("auction") or "copart"
    if item.get("image") and not payload.get("images"):
        payload["images"] = [item["image"]]
    return payload


@app.get("/api/media/lot/{lot_id}/{index}")
def media_lot_image(lot_id: str, index: int):
    if not lot_id.isdigit() or index < 0 or index > 7:
        raise HTTPException(404, "Нет фото")
    path = DATA_DIR / "lot-images" / f"{lot_id}_{index}.jpg"
    if not path.is_file():
        raise HTTPException(404, "Фото ещё не сохранено — подтяните лот снова")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/media/usa/{lot_id}/{index}")
def media_usa_image(lot_id: str, index: int):
    if not lot_id.isdigit() or index < 0 or index > 7:
        raise HTTPException(404, "Нет фото")
    path = DATA_DIR / "lot-images" / f"usa_{lot_id}_{index}.jpg"
    if not path.is_file():
        raise HTTPException(404, "Фото ещё не сохранено — подтяните лот снова")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/media/copart")
def media_copart_proxy(u: str = Query(..., min_length=12)):
    """Прокси CDN Copart через сессию Chrome (прямые ссылки дают 403)."""
    url = (u or "").strip()
    if url.startswith("/api/media/lot/"):
        parts = url.strip("/").split("/")
        if len(parts) >= 4:
            return media_lot_image(parts[3], int(parts[4]))
    if url.startswith("/api/media/usa/"):
        parts = url.strip("/").split("/")
        if len(parts) >= 4:
            return media_usa_image(parts[3], int(parts[4]))
    if not _is_lot_image(url):
        raise HTTPException(400, "Нужна ссылка на фото Copart")
    cache_dir = DATA_DIR / "lot-images" / "proxy"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    cached = cache_dir / f"{digest}.jpg"
    if cached.is_file() and cached.stat().st_size > 800:
        return FileResponse(cached, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    try:
        body = get_scrape_service(settings.headless).fetch_image(url)
    except CopartBlockedError:
        raise HTTPException(404, "Фото недоступно") from None
    except Exception:
        raise HTTPException(404, "Фото недоступно") from None
    if not body:
        raise HTTPException(404, "Фото недоступно")
    cached.write_bytes(body)
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(404, "Not found")
    built_file = DIST / full_path
    if built_file.is_file():
        return FileResponse(built_file)
    index_file = DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "ok": True,
        "api": "MG Group CRM backend",
        "ui": "http://127.0.0.1:5173",
        "hint": "Запустите frontend: cd frontend && npm run dev",
    }


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=settings.crm_host,
        port=settings.crm_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
