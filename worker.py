from __future__ import annotations

import logging
import random
import time

from config import Search
from scraper import CopartBlockedError, CopartScraper, get_scrape_service
from store import LotStore

log = logging.getLogger("copart")


def lot_allowed(lot: dict, settings) -> bool:
    make = (lot.get("make") or "").upper()
    title = (lot.get("title") or "").upper()
    if settings.make_filter:
        if not any(m in make or m in title for m in settings.make_filter):
            return False
    year = lot.get("year")
    if settings.year_from is not None and year is not None and year < settings.year_from:
        return False
    if settings.year_to is not None and year is not None and year > settings.year_to:
        return False
    if settings.max_bid is not None and lot.get("bid") is not None and lot["bid"] > settings.max_bid:
        return False
    return True


def classify(lot: dict, store: LotStore) -> str | None:
    prev = store.get(lot["lot_id"])
    if prev is None:
        if lot.get("vin") and store.vin_known(lot["vin"], lot["lot_id"]):
            lot["event"] = "relist"
            return "relist"
        lot["event"] = "new"
        return "new"
    prev_sale = prev.get("sale_date")
    new_sale = lot.get("sale_date")
    if prev_sale and new_sale and prev_sale != new_sale:
        lot["event"] = "relist"
        lot["previous_sale_date"] = prev_sale
        return "relist"
    return None


def fetch_search_lots(row: dict, settings) -> list[dict]:
    platform = str(row.get("platform") or "copart").strip().lower() or "copart"
    search = Search(name=row["name"], url=row["url"])
    if platform == "bidcars":
        page_limit = settings.max_pages if settings.max_pages > 0 else 8
        found = get_scrape_service(settings.headless).fetch_bidcars_search(
            [(search.name, search.url)],
            page_limit,
        )
        for lot in found:
            lot["source"] = "bidcars"
            if search.name not in (lot.get("search_names") or []):
                names = list(lot.get("search_names") or [])
                names.append(search.name)
                lot["search_names"] = names
        return found
    scraper = CopartScraper(
        urls=[search],
        max_pages=settings.max_pages,
        headless=settings.headless,
    )
    found = scraper.fetch_lots()
    for lot in found:
        lot["source"] = lot.get("source") or "copart"
    return found


def run_cycle(settings, store: LotStore, *, notify=None, platform: str | None = None) -> dict:
    platforms = [platform] if platform in {"copart", "bidcars"} else ["copart", "bidcars"]
    first = store.is_first_run()
    total_in_search = 0
    total_new = 0
    total_relist = 0
    notified = 0
    notified_ids: set[str] = set()
    succeeded = 0
    blocked: CopartBlockedError | None = None
    lots_by_id: dict[str, dict] = {}
    scanned_platforms: list[str] = []

    for plat in platforms:
        groups = store.searches_by_manager(platform=plat)
        if not groups:
            continue
        seen_ids: list[str] = []
        scraped_keys: set[str] = set()
        plat_ok = 0
        for owner_label, searches in groups:
            log.info(
                "Менеджер «%s»: %s поиск(ов) %s по очереди",
                owner_label,
                len(searches),
                "Bid.cars" if plat == "bidcars" else "Copart",
            )
            for row in searches:
                search = Search(name=row["name"], url=row["url"])
                seed_this = first or not row.get("seeded_at")
                try:
                    found = fetch_search_lots(row, settings)
                except CopartBlockedError as exc:
                    blocked = exc
                    log.warning(
                        "Поиск «%s» пропущен: %s временно недоступен",
                        search.name,
                        "Bid.cars" if plat == "bidcars" else "Copart",
                    )
                    continue
                except Exception as exc:
                    log.warning("Поиск «%s» пропущен: %s", search.name, exc)
                    continue
                if plat != "bidcars":
                    found = [lot for lot in found if lot_allowed(lot, settings)]
                new_here = 0
                relist_here = 0
                for lot in found:
                    CopartScraper._merge(lots_by_id, [lot])
                    seen_ids.append(lot["lot_id"])
                    if seed_this:
                        continue
                    event = classify(lot, store)
                    if event == "new":
                        new_here += 1
                    elif event == "relist":
                        relist_here += 1
                    if event and notify and settings.telegram_token and lot["lot_id"] not in notified_ids:
                        try:
                            notify(settings.telegram_token, settings.telegram_chat_id, lot)
                            notified += 1
                            notified_ids.add(lot["lot_id"])
                            log.info("%s: %s %s", event, lot["lot_id"], lot.get("title"))
                        except Exception:
                            log.exception("Telegram: не отправил лот %s", lot["lot_id"])
                        time.sleep(0.4)
                store.set_search_scan_stats(row["id"], in_search=len(found), new_count=new_here)
                store.apply_scan(found, mark_missing=False, seed=seed_this)
                if not row.get("seeded_at"):
                    store.mark_search_seeded(row["id"])
                scraped_keys |= store._search_keys(row)
                total_in_search += len(found)
                total_new += new_here
                total_relist += relist_here
                succeeded += 1
                plat_ok += 1
                log.info(
                    "«%s»: %s авто в поиске, новых %s",
                    search.name,
                    len(found),
                    new_here,
                )
        if plat_ok:
            store.mark_missing_for_keys(seen_ids, scraped_keys, source=plat)
            scanned_platforms.append(plat)

    if succeeded == 0:
        if blocked:
            raise blocked
        log.info("Нет включённых поисков")
        return {"found": 0, "new": 0, "relist": 0, "notified": 0}

    if first:
        store.mark_seeded()
        for plat in scanned_platforms:
            store.mark_all_searches_seeded(platform=plat)
        log.info(
            "Первый запуск: сохранил %s лотов в CRM (без пометки «новое»)",
            len(lots_by_id),
        )
        return {
            "found": total_in_search,
            "new": 0,
            "relist": 0,
            "notified": 0,
            "first_run": True,
        }

    if not notify or not settings.telegram_token:
        log.info(
            "В поиске: %s, новых: %s, повторных: %s (Telegram выключен)",
            total_in_search,
            total_new,
            total_relist,
        )
    return {
        "found": total_in_search,
        "new": total_new,
        "relist": total_relist,
        "notified": notified,
        "first_run": False,
    }


def seed_search(settings, store: LotStore, search_id: int) -> dict:
    row = store.get_search(search_id)
    if not row:
        return {"found": 0, "seeded": 0}
    if row.get("seeded_at"):
        return {"found": 0, "seeded": 0, "already_seeded": True}
    search = Search(name=row["name"], url=row["url"])
    platform = str(row.get("platform") or "copart").strip().lower() or "copart"
    log.info("Первичная загрузка поиска «%s»", search.name)
    lots = fetch_search_lots(row, settings)
    if platform != "bidcars":
        lots = [lot for lot in lots if lot_allowed(lot, settings)]
    log.info("«%s»: сохраняю %s текущих лотов без пометки «новое»", search.name, len(lots))
    stats = store.apply_scan(lots, mark_missing=False, seed=True)
    store.mark_search_seeded(search_id)
    store.set_search_scan_stats(search_id, in_search=len(lots), new_count=0)
    return stats


def seed_search_safe(settings, store: LotStore, search_id: int) -> dict:
    run_id = store.start_sync()
    try:
        result = seed_search(settings, store, search_id)
        store.finish_sync(
            run_id,
            lots_found=result.get("found", 0),
            new_count=0,
        )
        return result
    except CopartBlockedError as exc:
        store.finish_sync(run_id, error=str(exc))
        raise
    except Exception as exc:
        store.finish_sync(run_id, error=str(exc))
        raise


def run_cycle_safe(settings, store: LotStore, *, notify=None, platform: str | None = None) -> dict:
    run_id = store.start_sync()
    try:
        result = run_cycle(settings, store, notify=notify, platform=platform)
        store.finish_sync(
            run_id,
            lots_found=result.get("found", 0),
            new_count=result.get("new", 0),
        )
        return result
    except CopartBlockedError as exc:
        store.finish_sync(run_id, error=str(exc))
        raise
    except Exception as exc:
        store.finish_sync(run_id, error=str(exc))
        raise


def sleep_until_next(settings) -> None:
    base = settings.poll_interval_minutes * 60
    extra = random.randint(3, max(8, min(20, base // 4)))
    seconds = base + extra
    log.info("Следующая проверка через %.1f мин", seconds / 60)
    time.sleep(seconds)
