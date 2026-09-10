from __future__ import annotations

import logging
import time
import urllib.error

from notify import get_bot_username, send_message_safe, telegram_call
from store import LotStore

log = logging.getLogger("copart")

HELP_TEXT = (
    "MG Group CRM\n\n"
    "Новые авто Copart приходят сюда.\n"
    "Чтобы открыть CRM, на сайте нажмите «Войти через Telegram».\n\n"
    "/notify — вкл/выкл уведомления"
)

LOGIN_OK = "Вход выполнен. Вернитесь в браузер — CRM откроется сам."
LOGIN_EXPIRED = (
    "Ссылка для входа устарела. Откройте CRM и нажмите «Войти через Telegram» ещё раз."
)
DISABLED = "Доступ отключён. Напишите администратору."


def _from_user(message: dict) -> dict:
    return message.get("from") or {}


def _chat_id(message: dict) -> str | None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    return str(chat_id) if chat_id is not None else None


def handle_message(store: LotStore, token: str, message: dict) -> None:
    from_user = _from_user(message)
    telegram_id = from_user.get("id")
    chat_id = _chat_id(message)
    if telegram_id is None or not chat_id:
        return
    if (message.get("chat") or {}).get("type") not in {None, "private"}:
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return
    user = store.upsert_telegram_user(
        telegram_id=int(telegram_id),
        username=from_user.get("username"),
        first_name=from_user.get("first_name"),
        last_name=from_user.get("last_name"),
    )
    text = (message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
    payload = text.split(maxsplit=1)[1].strip() if " " in text else ""

    if command == "/start":
        if not user["enabled"]:
            send_message_safe(token, chat_id, DISABLED)
            return
        if payload:
            session = store.complete_login_token(payload, user["id"])
            if session:
                role = "Вы администратор." if user["role"] == "admin" else "Можно открывать CRM."
                send_message_safe(token, chat_id, f"{LOGIN_OK}\n{role}")
                return
            send_message_safe(token, chat_id, LOGIN_EXPIRED)
            return
        extra = " Первый вход — вы администратор." if user["role"] == "admin" else ""
        send_message_safe(token, chat_id, HELP_TEXT + extra)
        return

    if command in {"/notify", "/stop", "/startnotify"}:
        if not user["enabled"]:
            send_message_safe(token, chat_id, DISABLED)
            return
        if command == "/stop":
            enabled = False
        elif command == "/startnotify":
            enabled = True
        else:
            enabled = not user["notify"]
        store.set_user_notify(user["id"], enabled)
        if enabled:
            send_message_safe(token, chat_id, "Уведомления о новых авто включены.")
        else:
            send_message_safe(token, chat_id, "Уведомления выключены. /notify — включить снова.")
        return

    if command in {"/help", "/crm"}:
        send_message_safe(token, chat_id, HELP_TEXT)
        return

    if text.startswith("/"):
        send_message_safe(token, chat_id, HELP_TEXT)


def _skip_old_updates(store: LotStore, token: str) -> None:
    if store.get_meta("telegram_offset") is not None:
        return
    try:
        body = telegram_call(
            token,
            "getUpdates",
            {"timeout": 0, "limit": 100, "allowed_updates": ["message"]},
            timeout=20,
        )
    except Exception:
        log.exception("Telegram: не удалось пропустить старые обновления")
        store.set_meta("telegram_offset", "0")
        return
    results = body.get("result") or []
    if results:
        store.set_meta("telegram_offset", str(int(results[-1]["update_id"]) + 1))
    else:
        store.set_meta("telegram_offset", "0")


def poll_telegram(store: LotStore, get_token) -> None:
    time.sleep(1)
    announced = False
    while True:
        token = (get_token() or "").strip()
        if not token:
            if not announced:
                log.info("Telegram-бот: нет TELEGRAM_BOT_TOKEN — вход и уведомления выключены")
                announced = True
            time.sleep(8)
            continue
        announced = False
        _skip_old_updates(store, token)
        raw_offset = store.get_meta("telegram_offset") or "0"
        try:
            offset = int(raw_offset)
        except ValueError:
            offset = 0
        try:
            body = telegram_call(
                token,
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 25,
                    "limit": 50,
                    "allowed_updates": ["message"],
                },
                timeout=40,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                store.set_meta("telegram_poll_ok", "0")
                store.set_meta(
                    "telegram_poll_error",
                    "Конфликт: тот же бот уже слушает getUpdates на другом компьютере/процессе. "
                    "Оставьте один app.py или перевыпустите токен у @BotFather.",
                )
                log.warning(
                    "Telegram: уже крутится другой getUpdates (второй app.py?). "
                    "Оставьте один бэкенд — вход/уведомления работают только у него."
                )
                time.sleep(8)
                continue
            log.exception("Telegram getUpdates HTTP %s", exc.code)
            time.sleep(4)
            continue
        except Exception:
            log.exception("Telegram getUpdates")
            time.sleep(4)
            continue
        if not body.get("ok"):
            log.error("Telegram getUpdates: %s", body)
            time.sleep(4)
            continue
        store.set_meta("telegram_poll_ok", "1")
        store.set_meta("telegram_poll_error", "")
        for update in body.get("result") or []:
            update_id = int(update["update_id"])
            store.set_meta("telegram_offset", str(update_id + 1))
            message = update.get("message") or update.get("edited_message")
            if message:
                try:
                    handle_message(store, token, message)
                except Exception:
                    log.exception("Telegram: ошибка обработки сообщения")


def resolve_bot_username(token: str) -> str | None:
    if not token:
        return None
    return get_bot_username(token)
