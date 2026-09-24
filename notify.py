from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from calculator import quote_lot

log = logging.getLogger("copart")

TELEGRAM_API = "https://api.telegram.org"

_DISMANTLE_LABEL = {
    "sedan": "Седан",
    "suv": "Внедорожник",
    "sprinter": "Спринтер / бус",
    "pickup": "Пикап / X7 / LR",
}


def _gbp(value) -> str:
    if value is None:
        return "—"
    return f"£{float(value):,.2f}"


def _usd(value) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def prepare_lot_notify(store, lot: dict) -> dict:
    """Карточка как в CRM: контакты поиска, фильтры, расчёт с курсом."""
    payload = dict(lot)
    payload["search_contacts"] = store.search_contacts_for_lot(payload)
    source = str(payload.get("source") or "").strip().lower()
    url = str(payload.get("url") or "").lower()
    if source == "bidcars" or "bid.cars" in url:
        payload["source"] = "bidcars"
        payload["quote"] = None
        return payload
    fx = None
    try:
        fx = store.get_fx_rate()
    except Exception:
        fx = None
    payload["quote"] = quote_lot(
        bid=payload.get("bid"),
        location=payload.get("location"),
        category=payload.get("category"),
        title=payload.get("title") or "",
        body_style=payload.get("body_style"),
        vat_on_sale=payload.get("vat_on_sale"),
        fx_rate=fx,
    )
    return payload


def format_lot(lot: dict) -> str:
    title = lot.get("title") or f"Lot {lot.get('lot_id')}"
    source = str(lot.get("source") or "").strip().lower()
    is_bidcars = source == "bidcars" or "bid.cars" in str(lot.get("url") or "").lower()
    head = "Повторный аукцион" if lot.get("event") == "relist" else "Новое авто"
    if is_bidcars:
        head = f"{head} · Bid.cars"
    lines = [f"<b>{_esc(head)}</b>", f"<b>{_esc(str(title))}</b>", ""]

    names = [str(x) for x in (lot.get("search_names") or []) if x]
    if names:
        lines.append(f"Поиск: {_esc(', '.join(names))}")

    contacts = lot.get("search_contacts") or []
    for contact in contacts:
        search = str(contact.get("search") or "").strip()
        if search and (len(contacts) > 1 or search not in names):
            lines.append(f"Поиск: {_esc(search)}")
        if contact.get("owner_name"):
            lines.append(f"Менеджер: {_esc(str(contact['owner_name']))}")
        if contact.get("telegram"):
            lines.append(f"Кому (Telegram): {_esc(str(contact['telegram']))}")
        if contact.get("phone"):
            lines.append(f"Телефон: {_esc(str(contact['phone']))}")
        if contact.get("comment"):
            lines.append(f"Комментарий: {_esc(str(contact['comment']))}")
        params = contact.get("params") or []
        if params:
            bits = [f"{p.get('label')}: {p.get('value')}" for p in params if p.get("label") and p.get("value")]
            if bits:
                lines.append("Фильтры: " + _esc(" · ".join(bits)))

    lines.append("")
    lot_id = str(lot.get("display_lot_id") or lot.get("lot_id") or "")
    if lot_id.lower().startswith("bc-"):
        lot_id = lot_id[3:]
    if lot_id:
        lines.append(f"Lot: <code>{_esc(lot_id)}</code>")
    if lot.get("vin"):
        lines.append(f"VIN: <code>{_esc(str(lot['vin']))}</code>")
    if lot.get("year"):
        lines.append(f"Год: {_esc(str(lot['year']))}")
    if lot.get("make") or lot.get("model"):
        lines.append("Марка/модель: " + _esc(" ".join(str(x) for x in (lot.get("make"), lot.get("model")) if x)))
    if lot.get("body_style"):
        lines.append(f"Кузов: {_esc(str(lot['body_style']))}")
    if lot.get("location"):
        lines.append(f"Площадка: {_esc(str(lot['location']))}")
    if lot.get("category"):
        lines.append(f"Категория: {_esc(str(lot['category']))}")
    if lot.get("odometer") is not None:
        try:
            lines.append(f"Пробег: {int(float(lot['odometer'])):,}".replace(",", " "))
        except (TypeError, ValueError):
            lines.append(f"Пробег: {_esc(str(lot['odometer']))}")
    if lot.get("sale_date"):
        lines.append(f"Аукцион: {_esc(str(lot['sale_date']))}")
    if lot.get("previous_sale_date"):
        lines.append(f"Прошлая дата: {_esc(str(lot['previous_sale_date']))}")

    quote = lot.get("quote")
    if not is_bidcars and quote is None:
        quote = quote_lot(
            bid=lot.get("bid"),
            location=lot.get("location"),
            category=lot.get("category"),
            title=lot.get("title") or "",
            body_style=lot.get("body_style"),
            vat_on_sale=lot.get("vat_on_sale"),
        )
    lines.append("")
    if is_bidcars:
        if lot.get("bid") is not None:
            lines.append(f"Ставка: {_usd(lot.get('bid'))}")
        else:
            lines.append("Нет ставки — появится, когда Bid.cars отдаст current bid.")
        if lot.get("primary_damage"):
            lines.append(f"Повреждение: {_esc(str(lot['primary_damage']))}")
    elif quote:
        copart = quote["copart"]
        delivery = quote["delivery"]
        if delivery.get("manual"):
            note = f"{delivery['region_key']}, {delivery['label']} (вручную)"
        elif delivery.get("sedan_as_jeep"):
            note = f"{delivery['region_key']}, седан как джип (Cat B)"
        else:
            note = f"{delivery['region_key']}, {delivery['label']}"
        dtype = _DISMANTLE_LABEL.get(str(quote.get("dismantle_type") or ""), str(quote.get("dismantle_type") or ""))
        lines.append("<b>Расчёт</b>")
        lines.append(f"Ставка: {_gbp(copart.get('bid', lot.get('bid')))}")
        try:
            auction_fee = float(copart.get("copart_total") or 0) - float(copart.get("bid") or 0)
        except (TypeError, ValueError):
            auction_fee = None
        if auction_fee is not None:
            lines.append(f"Аукционный сбор: {_gbp(auction_fee)}")
        lines.append(f"Copart Total: <b>{_gbp(copart.get('copart_total'))}</b>")
        lines.append(f"Доставка: {_gbp(delivery.get('amount'))} ({_esc(note)})")
        lines.append(f"Комиссия за перевод 3%: {_gbp(quote.get('transfer_fee'))}")
        lines.append(f"Итого UK: <b>{_gbp(quote.get('total_uk'))}</b>")
        if quote.get("fx_rate"):
            lines.append(f"Курс GBP→USD: {quote['fx_rate']}")
            lines.append(f"Расходы Англии: {_usd(quote.get('england_usd'))}")
        if quote.get("dismantle_mode") == "weight" and quote.get("dismantle_kg"):
            lines.append(
                f"Разбор: {_usd(quote.get('dismantle_usd'))} "
                f"(850 + 1.4 × {quote['dismantle_kg']:g} кг)"
            )
        else:
            lines.append(f"Разбор: {_usd(quote.get('dismantle_usd'))} ({_esc(dtype)})")
        if quote.get("grand_usd") is not None:
            lines.append(f"Итого с разбором: <b>{_usd(quote.get('grand_usd'))}</b>")
    else:
        if lot.get("bid") is not None:
            lines.append(f"Ставка: {_gbp(lot.get('bid'))}")
        lines.append("Нет ставки — полный расчёт появится, когда Copart отдаст current bid.")

    if lot.get("url"):
        lines.append("")
        site = "Bid.cars" if is_bidcars else "Copart"
        lines.append(f'<a href="{_esc(str(lot["url"]))}">Открыть на {site}</a>')
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "…"
    return text


def send_message(token: str, chat_id: str, text: str) -> None:
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
    ).encode()
    req = urllib.request.Request(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if not body.get("ok"):
            raise RuntimeError(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        log.error("Telegram HTTP %s: %s", exc.code, detail)
        raise


def send_message_safe(token: str, chat_id: str, text: str) -> bool:
    try:
        send_message(token, chat_id, text)
        return True
    except Exception:
        log.exception("Telegram: не отправил в чат %s", chat_id)
        return False


def telegram_call(
    token: str,
    method: str,
    payload: dict | None = None,
    *,
    timeout: int = 30,
) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        log.error("Telegram %s HTTP %s: %s", method, exc.code, detail)
        raise


def telegram_get(token: str, method: str, params: dict | None = None, timeout: int = 30) -> dict:
    return telegram_call(token, method, params, timeout=timeout)


def get_bot_username(token: str) -> str | None:
    try:
        body = telegram_get(token, "getMe")
    except Exception:
        log.exception("Telegram getMe")
        return None
    if not body.get("ok"):
        log.error("Telegram getMe: %s", body)
        return None
    return (body.get("result") or {}).get("username")


def notify_lot(token: str, chat_ids: list[str], lot: dict) -> int:
    if not token or not chat_ids:
        return 0
    text = format_lot(lot)
    sent = 0
    seen: set[str] = set()
    for chat_id in chat_ids:
        key = str(chat_id).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if send_message_safe(token, key, text):
            sent += 1
    return sent


def discover_chat_id(token: str) -> str | None:
    try:
        body = telegram_get(token, "getUpdates", {"limit": 50, "timeout": 0})
    except Exception:
        log.exception("Не удалось получить чаты Telegram")
        return None
    if not body.get("ok"):
        log.error("Telegram getUpdates: %s", body)
        return None
    for update in reversed(body.get("result") or []):
        for key in ("message", "edited_message", "my_chat_member", "channel_post"):
            chat = (update.get(key) or {}).get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is not None:
                return str(chat_id)
    return None


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
