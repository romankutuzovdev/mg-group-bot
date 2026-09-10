#!/usr/bin/env python3
"""Собрать лоты аукционов в один понятный JSON для сайта.

По умолчанию читает текущие лоты из CRM (data/seen_lots.db),
оставляет по 1 записи на каждое авто (по lot_id, затем по VIN)
и пишет data/lots_for_site.json.

Примеры:
  python export_lots_json.py
  python export_lots_json.py --new-only
  python export_lots_json.py --scrape
  python export_lots_json.py --scrape --details
  python export_lots_json.py --scrape --platform bidcars -o data/usa_lots.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "seen_lots.db"

log = logging.getLogger("export_lots")

SITE_FIELDS = (
    "lot_id",
    "display_lot_id",
    "source",
    "title",
    "year",
    "make",
    "model",
    "bid",
    "currency",
    "location",
    "ship_from",
    "category",
    "documents",
    "odometer",
    "sale_date",
    "vin",
    "url",
    "body_style",
    "vehicle_type_raw",
    "vat_on_sale",
    "color",
    "engine",
    "transmission",
    "drive",
    "fuel",
    "primary_damage",
    "secondary_damage",
    "keys",
    "highlights",
    "estimated_value",
    "repair_cost",
    "seller",
    "images",
    "searches",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filled_score(lot: dict) -> int:
    score = 0
    for key in (
        "title",
        "year",
        "make",
        "model",
        "bid",
        "location",
        "category",
        "odometer",
        "sale_date",
        "vin",
        "body_style",
        "color",
        "engine",
        "transmission",
        "drive",
        "fuel",
        "primary_damage",
        "images",
    ):
        value = lot.get(key)
        if value in (None, "", [], {}):
            continue
        score += 3 if key == "images" and isinstance(value, list) and value else 1
    return score


def _merge_lot(prev: dict, incoming: dict) -> dict:
    out = dict(prev)
    for key, value in incoming.items():
        if key == "search_names":
            names = list(out.get("search_names") or [])
            for name in value or []:
                if name and name not in names:
                    names.append(name)
            out["search_names"] = names
            continue
        if key == "images":
            seen: list[str] = list(out.get("images") or [])
            for url in value or []:
                src = str(url or "").strip()
                if src and src not in seen:
                    seen.append(src)
            out["images"] = seen
            continue
        if out.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            out[key] = value
    if _filled_score(incoming) > _filled_score(out):
        names = out.get("search_names")
        images = out.get("images")
        out = {**out, **{k: v for k, v in incoming.items() if v not in (None, "", [], {})}}
        if names:
            out["search_names"] = names
        if images:
            out["images"] = images
    return out


def _dedupe_lots(lots: list[dict]) -> list[dict]:
    """Одна запись на авто: сначала по lot_id, потом схлопываем одинаковый VIN."""
    by_id: dict[str, dict] = {}
    for lot in lots:
        lot_id = str(lot.get("lot_id") or "").strip()
        if not lot_id:
            continue
        if lot_id in by_id:
            by_id[lot_id] = _merge_lot(by_id[lot_id], lot)
        else:
            by_id[lot_id] = dict(lot)

    by_vin: dict[str, str] = {}
    drop: set[str] = set()
    for lot_id, lot in by_id.items():
        vin = str(lot.get("vin") or "").strip().upper()
        if len(vin) < 11:
            continue
        if vin in by_vin:
            keep_id = by_vin[vin]
            by_id[keep_id] = _merge_lot(by_id[keep_id], lot)
            drop.add(lot_id)
        else:
            by_vin[vin] = lot_id

    unique = [lot for lot_id, lot in by_id.items() if lot_id not in drop]
    unique.sort(
        key=lambda item: (
            str(item.get("sale_date") or "9999"),
            str(item.get("make") or ""),
            str(item.get("model") or ""),
            str(item.get("lot_id") or ""),
        )
    )
    return unique


def _currency_for(source: str) -> str:
    return "USD" if source == "bidcars" else "GBP"


def _to_site_lot(lot: dict) -> dict:
    source = str(lot.get("source") or "copart").strip().lower() or "copart"
    if source not in {"copart", "bidcars"}:
        url = str(lot.get("url") or "").lower()
        source = "bidcars" if "bid.cars" in url else "copart"

    lot_id = str(lot.get("lot_id") or "")
    display = lot.get("display_lot_id")
    if not display:
        display = lot_id[3:] if source == "bidcars" and lot_id.lower().startswith("bc-") else lot_id

    images = [str(u).strip() for u in (lot.get("images") or []) if str(u or "").strip()]
    searches = [str(n).strip() for n in (lot.get("search_names") or []) if str(n or "").strip()]

    payload: dict[str, Any] = {
        "lot_id": lot_id,
        "display_lot_id": display,
        "source": source,
        "title": lot.get("title"),
        "year": lot.get("year"),
        "make": lot.get("make"),
        "model": lot.get("model"),
        "bid": lot.get("bid"),
        "currency": _currency_for(source),
        "location": lot.get("location"),
        "ship_from": lot.get("ship_from"),
        "category": lot.get("category") or lot.get("documents"),
        "documents": lot.get("documents"),
        "odometer": lot.get("odometer"),
        "sale_date": lot.get("sale_date"),
        "vin": lot.get("vin"),
        "url": lot.get("url"),
        "body_style": lot.get("body_style"),
        "vehicle_type_raw": lot.get("vehicle_type_raw"),
        "vat_on_sale": lot.get("vat_on_sale"),
        "color": lot.get("color"),
        "engine": lot.get("engine"),
        "transmission": lot.get("transmission"),
        "drive": lot.get("drive"),
        "fuel": lot.get("fuel"),
        "primary_damage": lot.get("primary_damage"),
        "secondary_damage": lot.get("secondary_damage"),
        "keys": lot.get("keys"),
        "highlights": lot.get("highlights"),
        "estimated_value": lot.get("estimated_value"),
        "repair_cost": lot.get("repair_cost"),
        "seller": lot.get("seller"),
        "images": images,
        "searches": searches,
    }
    return {key: payload.get(key) for key in SITE_FIELDS}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def load_lots_from_db(
    *,
    new_only: bool,
    platform: str | None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    if not db_path.exists():
        raise SystemExit(f"Нет базы {db_path}. Сначала запустите CRM / синхронизацию.")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = _table_columns(conn, "lots")

    sql = "SELECT * FROM lots WHERE in_stock = 1"
    params: list[Any] = []
    if new_only:
        sql += " AND status = 'new'"
    if platform and "source" in cols:
        sql += " AND COALESCE(source, 'copart') = ?"
        params.append(platform)
    sql += " ORDER BY last_seen DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    lots: list[dict] = []
    for row in rows:
        data = dict(row)
        names = data.get("search_names") or "[]"
        try:
            data["search_names"] = json.loads(names) if isinstance(names, str) else list(names or [])
        except json.JSONDecodeError:
            data["search_names"] = [names] if names else []
        vat = data.get("vat_on_sale")
        if vat is not None:
            data["vat_on_sale"] = bool(vat)
        url = str(data.get("url") or "").lower()
        source = str(data.get("source") or "").strip().lower()
        if not source or source not in {"copart", "bidcars"}:
            source = "bidcars" if "bid.cars" in url else "copart"
        data["source"] = source
        data.setdefault("images", [])
        lots.append(data)
    return lots


def load_lots_from_scrape(*, platform: str | None) -> list[dict]:
    from config import collect_file_searches, load_settings
    from scraper import CopartBlockedError
    from store import LotStore
    from worker import fetch_search_lots, lot_allowed

    settings = load_settings(require_telegram=False, require_searches=False)
    store = LotStore()
    platforms = [platform] if platform in {"copart", "bidcars"} else ["copart", "bidcars"]
    collected: list[dict] = []

    for plat in platforms:
        rows = [
            row
            for row in store.list_searches(with_counts=False, platform=plat)
            if row.get("enabled")
        ]
        if not rows and plat == "copart":
            file_searches = collect_file_searches()
            rows = [
                {"id": 0, "name": item.name, "url": item.url, "platform": "copart", "enabled": 1}
                for item in file_searches
            ]
        if not rows:
            log.info("Нет включённых поисков для %s", plat)
            continue
        log.info("Сканирую %s поиск(ов) %s", len(rows), plat)
        for row in rows:
            name = row["name"]
            try:
                found = fetch_search_lots(row, settings)
            except CopartBlockedError as exc:
                log.warning("«%s» пропущен (блок): %s", name, exc)
                continue
            except Exception as exc:
                log.warning("«%s» пропущен: %s", name, exc)
                continue
            if plat != "bidcars":
                found = [lot for lot in found if lot_allowed(lot, settings)]
            log.info("«%s»: %s лотов", name, len(found))
            collected.extend(found)
            time.sleep(0.3)
    return collected


def enrich_details(
    lots: list[dict],
    *,
    limit: int | None = None,
    keep_cdn_images: bool = True,
) -> list[dict]:
    import os

    from config import load_settings
    from scraper import get_scrape_service

    if keep_cdn_images:
        os.environ["LOT_KEEP_CDN_IMAGES"] = "1"
    else:
        os.environ.pop("LOT_KEEP_CDN_IMAGES", None)

    settings = load_settings(require_telegram=False, require_searches=False)
    service = get_scrape_service(settings.headless)
    out: list[dict] = []
    total = len(lots) if limit is None else min(limit, len(lots))
    for index, lot in enumerate(lots[:total], start=1):
        url = str(lot.get("url") or "")
        source = str(lot.get("source") or "copart").lower()
        log.info("[%s/%s] детали %s", index, total, lot.get("lot_id"))
        try:
            if source == "bidcars" or "bid.cars" in url.lower():
                details = service.fetch_bidcars_lot(url)
            else:
                details = service.fetch_lot(url)
            out.append(_merge_lot(lot, details or {}))
        except Exception as exc:
            log.warning("Не удалось догрузить %s: %s", lot.get("lot_id"), exc)
            out.append(lot)
        time.sleep(0.4)
    if limit is not None and len(lots) > total:
        out.extend(lots[total:])
    return out


def write_json(path: Path, lots: list[dict], *, meta: dict | None = None) -> None:
    site_lots = [_to_site_lot(lot) for lot in lots]
    payload = {
        "generated_at": _now(),
        "count": len(site_lots),
        **(meta or {}),
        "lots": site_lots,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("Записал %s лотов → %s", len(site_lots), path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспорт лотов аукционов в JSON для сайта")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--from-db",
        action="store_true",
        help="Взять текущие лоты из CRM (по умолчанию)",
    )
    mode.add_argument(
        "--scrape",
        action="store_true",
        help="Заново обойти поиски Copart / Bid.cars",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Открыть страницу каждого лота и дотянуть все поля/фото",
    )
    parser.add_argument(
        "--download-images",
        action="store_true",
        help="Скачать фото на диск (по умолчанию в JSON только CDN-ссылки Copart)",
    )
    parser.add_argument(
        "--details-limit",
        type=int,
        default=None,
        help="Сколько лотов максимум догружать с --details",
    )
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Только статус «new» (для --from-db)",
    )
    parser.add_argument(
        "--platform",
        choices=("copart", "bidcars", "all"),
        default="all",
        help="Какой аукцион собирать",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DATA_DIR / "lots_for_site.json",
        help="Путь к JSON-файлу",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    use_db = not args.scrape
    platform = None if args.platform == "all" else args.platform

    if use_db:
        log.info("Читаю лоты из CRM%s", " (только new)" if args.new_only else "")
        raw = load_lots_from_db(new_only=args.new_only, platform=platform)
        source_mode = "db"
    else:
        log.info("Сканирую аукционы через браузер")
        raw = load_lots_from_scrape(platform=platform)
        source_mode = "scrape"

    unique = _dedupe_lots(raw)
    log.info("Уникальных авто: %s (было %s записей)", len(unique), len(raw))

    if args.details:
        unique = enrich_details(
            unique,
            limit=args.details_limit,
            keep_cdn_images=not args.download_images,
        )

    out_path = args.output if args.output.is_absolute() else ROOT / args.output
    write_json(
        out_path,
        unique,
        meta={
            "source_mode": source_mode,
            "platform": args.platform,
            "new_only": bool(args.new_only),
            "with_details": bool(args.details),
            "images": "download" if args.download_images else "cdn",
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nОстановлено", file=sys.stderr)
        raise SystemExit(130)
