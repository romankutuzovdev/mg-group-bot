#!/usr/bin/env python3
"""Полный каталог Copart UK → JSON для сайта.

Не использует поиски бота/CRM. Обходит «все авто» на Copart,
оставляет по 1–3 лота на каждую пару марка+модель,
к каждому — 1–3 CDN-ссылки на фото (без скачивания на диск).

Примеры:
  python export_copart_cdn.py
  python export_copart_cdn.py --per-model 3 --max-images 3
  python export_copart_cdn.py --details              # дотянуть фото со страницы лота
  python export_copart_cdn.py --max-pages 50         # ограничить обход
  python export_copart_cdn.py --all-lots             # без схлопывания по модели
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

log = logging.getLogger("export_copart_cdn")

# «Все авто» на Copart UK — без фильтров бота
CATALOG_CRITERIA = {
    "query": ["*"],
    "filter": {},
    "searchName": "",
    "watchListOnly": False,
    "freeFormSearch": False,
}
CATALOG_URL = (
    "https://www.copart.co.uk/lotSearchResults?free=true&query="
    f"&searchCriteria={quote(json.dumps(CATALOG_CRITERIA, separators=(',', ':')), safe='')}"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cdn_urls(urls: list[Any] | None, *, limit: int) -> list[str]:
    from scraper import _uniq_images

    preferred: list[str] = []
    for raw in urls or []:
        src = str(raw or "").strip()
        if not src or src.startswith("/api/media/"):
            continue
        preferred.append(src.replace("_thb.", "_ful."))
    return _uniq_images(preferred)[: max(1, limit)]


def _model_key(lot: dict) -> str:
    make = str(lot.get("make") or "").strip().upper() or "?"
    model = str(lot.get("model") or "").strip().upper() or "?"
    # Убираем лишний шум вроде комплектации из model, если слишком длинный
    if len(model) > 40:
        model = model.split()[0]
    return f"{make}|{model}"


def pick_per_model(lots: list[dict], *, per_model: int) -> list[dict]:
    """До per_model лотов на каждую марку+модель (разнообразие по году)."""
    if per_model <= 0:
        return lots
    groups: dict[str, list[dict]] = {}
    for lot in lots:
        key = _model_key(lot)
        groups.setdefault(key, []).append(lot)

    picked: list[dict] = []
    for key, items in sorted(groups.items()):
        items.sort(
            key=lambda x: (
                -(int(x.get("year") or 0)),
                str(x.get("sale_date") or ""),
                str(x.get("lot_id") or ""),
            )
        )
        # Разносим по годам, если можно
        chosen: list[dict] = []
        seen_years: set[int] = set()
        for lot in items:
            year = int(lot.get("year") or 0)
            if year and year in seen_years and len(chosen) < per_model:
                continue
            chosen.append(lot)
            if year:
                seen_years.add(year)
            if len(chosen) >= per_model:
                break
        if len(chosen) < per_model:
            for lot in items:
                if lot in chosen:
                    continue
                chosen.append(lot)
                if len(chosen) >= per_model:
                    break
        picked.extend(chosen)
        log.debug("%s → %s лот(ов)", key, len(chosen))
    log.info(
        "После отбора по модели: %s авто (было %s, ≤%s на марку+модель)",
        len(picked),
        len(lots),
        per_model,
    )
    return picked


def scrape_catalog(*, max_pages: int) -> list[dict]:
    from config import load_settings
    from scraper import get_scrape_service

    settings = load_settings(require_telegram=False, require_searches=False)
    service = get_scrape_service(settings.headless)
    pages = max_pages if max_pages > 0 else 300
    log.info("Каталог Copart UK: до %s стр. поиска", pages)
    log.info("URL: %s", CATALOG_URL[:120] + "…")
    # Каталог долгий — стандартный timeout=600 у fetch слишком мал
    found = service._run_job(
        {
            "kind": "search",
            "searches": [("Каталог Copart UK", CATALOG_URL)],
            "page_limit": pages,
        },
        timeout=max(1800, pages * 25),
    ) or []
    for lot in found:
        lot["source"] = "copart"
        lot["search_names"] = ["catalog"]
    log.info("С каталога снято уникальных лотов: %s", len(found))
    # чекпоинт, чтобы не потерять список при сбое на --details
    checkpoint = DATA_DIR / "copart_catalog_raw.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        json.dumps({"generated_at": _now(), "count": len(found), "lots": found}, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Чекпоинт: %s", checkpoint)
    return found


def enrich_details(
    lots: list[dict],
    *,
    min_images: int,
    max_images: int,
    limit: int | None,
    pause: float,
) -> list[dict]:
    os.environ["LOT_KEEP_CDN_IMAGES"] = "1"
    from config import load_settings
    from scraper import get_scrape_service, parse_lot_id

    settings = load_settings(require_telegram=False, require_searches=False)
    service = get_scrape_service(settings.headless)
    total = len(lots) if limit is None else min(limit, len(lots))
    out: list[dict] = []
    for index, lot in enumerate(lots[:total], start=1):
        lot_id = str(lot.get("lot_id") or parse_lot_id(str(lot.get("url") or "")) or "")
        url = str(lot.get("url") or f"https://www.copart.co.uk/lot/{lot_id}")
        log.info("[%s/%s] детали %s", index, total, lot_id)
        try:
            details = service.fetch_lot(url) or {}
            merged = {**lot, **{k: v for k, v in details.items() if v not in (None, "", [])}}
            images = _cdn_urls(merged.get("images"), limit=max_images)
            merged["images"] = images
            if len(images) < min_images:
                log.warning("лот %s: %s фото (нужно ≥%s)", lot_id, len(images), min_images)
            else:
                log.info("лот %s: %s CDN-фото", lot_id, len(images))
            out.append(merged)
        except Exception as exc:
            log.warning("лот %s: %s", lot_id, exc)
            lot = dict(lot)
            lot["images"] = _cdn_urls(lot.get("images"), limit=max_images)
            out.append(lot)
        time.sleep(pause)
    if limit is not None:
        out.extend(lots[total:])
    return out


def to_site(lot: dict, *, max_images: int) -> dict:
    images = _cdn_urls(lot.get("images"), limit=max_images)
    return {
        "lot_id": str(lot.get("lot_id") or ""),
        "title": lot.get("title"),
        "year": lot.get("year"),
        "make": lot.get("make"),
        "model": lot.get("model"),
        "bid": lot.get("bid"),
        "currency": "GBP",
        "location": lot.get("location"),
        "category": lot.get("category"),
        "odometer": lot.get("odometer"),
        "sale_date": lot.get("sale_date"),
        "vin": lot.get("vin"),
        "url": lot.get("url") or f"https://www.copart.co.uk/lot/{lot.get('lot_id')}",
        "body_style": lot.get("body_style"),
        "color": lot.get("color"),
        "engine": lot.get("engine"),
        "transmission": lot.get("transmission"),
        "drive": lot.get("drive"),
        "fuel": lot.get("fuel"),
        "primary_damage": lot.get("primary_damage"),
        "secondary_damage": lot.get("secondary_damage"),
        "keys": lot.get("keys"),
        "images": images,
        "images_count": len(images),
    }


def write_json(path: Path, lots: list[dict], *, max_images: int, meta: dict) -> None:
    site = [to_site(lot, max_images=max_images) for lot in lots]
    payload = {
        "generated_at": _now(),
        "source": "copart",
        "catalog": True,
        "images_mode": "cdn",
        "count": len(site),
        "with_images": sum(1 for x in site if x["images_count"] > 0),
        **meta,
        "lots": site,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("Записал %s авто → %s (с фото: %s)", len(site), path, payload["with_images"])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Полный каталог Copart UK → JSON + CDN-фото")
    p.add_argument("--per-model", type=int, default=3, help="Сколько лотов на марку+модель (0 = все)")
    p.add_argument("--all-lots", action="store_true", help="Не схлопывать по модели (все лоты каталога)")
    p.add_argument("--max-images", type=int, default=3, help="CDN-фото на авто (1–3)")
    p.add_argument("--min-images", type=int, default=1, help="Минимум фото (для --details)")
    p.add_argument("--max-pages", type=int, default=200, help="Макс. страниц поиска каталога")
    p.add_argument("--from-checkpoint", action="store_true", help="Взять список из data/copart_catalog_raw.json")
    p.add_argument("--details", action="store_true", help="Открыть каждый отобранный лот для фото/полей")
    p.add_argument("--details-limit", type=int, default=None, help="Лимит лотов для --details")
    p.add_argument("--pause", type=float, default=0.35)
    p.add_argument("-o", "--output", type=Path, default=DATA_DIR / "copart_catalog.json")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    os.environ.setdefault("LOT_KEEP_CDN_IMAGES", "1")

    if args.from_checkpoint:
        raw_path = DATA_DIR / "copart_catalog_raw.json"
        if not raw_path.exists():
            raise SystemExit(f"Нет чекпоинта {raw_path}")
        raw = list(json.loads(raw_path.read_text(encoding="utf-8")).get("lots") or [])
        log.info("Из чекпоинта: %s лотов", len(raw))
    else:
        raw = scrape_catalog(max_pages=args.max_pages)
    if not raw:
        raise SystemExit("Каталог пуст — проверьте Chrome / капчу Copart")

    per_model = 0 if args.all_lots else max(0, args.per_model)
    lots = pick_per_model(raw, per_model=per_model) if per_model else raw

    max_images = max(1, min(12, args.max_images))
    if args.details:
        lots = enrich_details(
            lots,
            min_images=max(1, args.min_images),
            max_images=max_images,
            limit=args.details_limit,
            pause=max(0.0, args.pause),
        )
        if args.details_limit is not None:
            lots = lots[: args.details_limit]
    else:
        for lot in lots:
            lot["images"] = _cdn_urls(lot.get("images"), limit=max_images)

    out = args.output if args.output.is_absolute() else ROOT / args.output
    write_json(
        out,
        lots,
        max_images=max_images,
        meta={
            "per_model": per_model,
            "max_pages": args.max_pages,
            "with_details": bool(args.details),
            "catalog_url": CATALOG_URL,
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nОстановлено", file=sys.stderr)
        raise SystemExit(130)
