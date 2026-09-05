from __future__ import annotations

import argparse
import logging
import sys

from config import load_settings
from notify import notify_lot, prepare_lot_notify
from scraper import CopartBlockedError, stop_scrape_service
from store import LotStore
from worker import run_cycle_safe, sleep_until_next

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("copart")


def main() -> None:
    parser = argparse.ArgumentParser(description="Монитор Copart UK")
    parser.add_argument("--once", action="store_true", help="Один проход без цикла")
    args = parser.parse_args()

    settings = load_settings(require_telegram=False)
    store = LotStore()
    store.import_searches(list(settings.searches))

    def telegram_notify(token: str, chat_id: str, lot: dict) -> None:
        payload = prepare_lot_notify(store, lot)
        chats = store.search_notify_chats_for_lot(payload)
        extra = (chat_id or "").strip()
        if extra and extra not in chats:
            chats.append(extra)
        if not chats:
            log.info("Новый лот %s — нет получателей Telegram", lot.get("lot_id"))
            return
        notify_lot(token, chats, payload)

    notify = telegram_notify if settings.telegram_token else None
    if not notify:
        log.info("Telegram не задан — результат только в консоли и в базе CRM")
    log.info(
        "Старт. Проверка каждые %s мин. Поиски: %s",
        settings.poll_interval_minutes,
        ", ".join(item.name for item in store.enabled_searches()),
    )

    try:
        while True:
            try:
                run_cycle_safe(settings, store, notify=notify)
            except CopartBlockedError:
                log.exception("Сайт временно недоступен")
            except Exception:
                log.exception("Ошибка цикла")
            if args.once:
                break
            sleep_until_next(settings)
    except KeyboardInterrupt:
        log.info("Остановлен")
    finally:
        stop_scrape_service()
        store.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
