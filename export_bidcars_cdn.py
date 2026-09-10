#!/usr/bin/env python3
"""Каталог Bid.cars → JSON для сайта (ставки + CDN-фото).

Как export_copart_cdn.py, но для США/Bid.cars:
обходит поиск без фильтров бота, оставляет до N лотов на марку+модель,
пишет ставки (USD) и CDN-ссылки на фото.

Примеры:
  python export_bidcars_cdn.py
  python export_bidcars_cdn.py --per-model 3 --max-pages 80
  python export_bidcars_cdn.py --all-lots
  python export_bidcars_cdn.py --from-checkpoint --details
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

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

log = logging.getLogger("export_bidcars_cdn")

# Каталог автомобилей Bid.cars с пагинацией /page/N
CATALOG_URL = "https://bid.cars/en/automobile/page/1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cdn_urls(urls: list[Any] | None, *, limit: int) -> list[str]:
    seen: list[str] = []
    for raw in urls or []:
        src = str(raw or "").strip()
        if not src.startswith("http"):
            continue
        if src.startswith("/api/media/"):
            continue
        src = src.replace("_thb.", "_ful.")
        if src not in seen:
            seen.append(src)
        if len(seen) >= max(1, limit):
            break
    return seen


def _model_key(lot: dict) -> str:
    make = str(lot.get("make") or "").strip().upper() or "?"
    model = str(lot.get("model") or "").strip().upper() or "?"
    if len(model) > 40:
        model = model.split()[0]
    return f"{make}|{model}"


def pick_per_model(lots: list[dict], *, per_model: int) -> list[dict]:
    if per_model <= 0:
        return lots
    groups: dict[str, list[dict]] = {}
    for lot in lots:
        groups.setdefault(_model_key(lot), []).append(lot)

    picked: list[dict] = []
    for key, items in sorted(groups.items()):
        items.sort(
            key=lambda x: (
                -(float(x.get("bid") or 0)),
                -(int(x.get("year") or 0)),
                str(x.get("lot_id") or ""),
            )
        )
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
    pages = max_pages if max_pages > 0 else 100
    log.info("Каталог Bid.cars: до %s стр.", pages)
    log.info("URL: %s", CATALOG_URL)
    found = service._run_job(
        {
            "kind": "bidcars_search",
            "searches": [("Каталог Bid.cars", CATALOG_URL)],
            "page_limit": pages,
        },
        timeout=max(1800, pages * 30),
    ) or []
    for lot in found:
        lot["source"] = "bidcars"
        lot["search_names"] = ["catalog"]
    log.info("С каталога Bid.cars снято: %s", len(found))
    checkpoint = DATA_DIR / "bidcars_catalog_raw.json"
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
    max_images: int,
    limit: int | None,
    pause: float,
) -> list[dict]:
    from config import load_settings
    from scraper import get_scrape_service

    settings = load_settings(require_telegram=False, require_searches=False)
    service = get_scrape_service(settings.headless)
    total = len(lots) if limit is None else min(limit, len(lots))
    out: list[dict] = []
    for index, lot in enumerate(lots[:total], start=1):
        url = str(lot.get("url") or "")
        log.info("[%s/%s] детали %s", index, total, lot.get("lot_id"))
        try:
            details = service.fetch_bidcars_lot(url) or {}
            merged = {**lot, **{k: v for k, v in details.items() if v not in (None, "", [])}}
            images = _cdn_urls(list(merged.get("images") or []) + list(lot.get("images") or []), limit=max_images)
            merged["images"] = images
            log.info("лот %s: bid=%s, фото=%s", lot.get("lot_id"), merged.get("bid"), len(images))
            out.append(merged)
        except Exception as exc:
            log.warning("лот %s: %s", lot.get("lot_id"), exc)
            lot = dict(lot)
            lot["images"] = _cdn_urls(lot.get("images"), limit=max_images)
            out.append(lot)
        time.sleep(pause)
    if limit is not None:
        out.extend(lots[total:])
    return out


def to_site(lot: dict, *, max_images: int) -> dict:
    lot_id = str(lot.get("lot_id") or "")
    display = lot_id[3:] if lot_id.lower().startswith("bc-") else lot_id
    images = _cdn_urls(lot.get("images"), limit=max_images)
    return {
        "lot_id": lot_id,
        "display_lot_id": display,
        "title": lot.get("title"),
        "year": lot.get("year"),
        "make": lot.get("make"),
        "model": lot.get("model"),
        "bid": lot.get("bid"),
        "currency": "USD",
        "location": lot.get("location"),
        "ship_from": lot.get("ship_from"),
        "documents": lot.get("documents"),
        "odometer": lot.get("odometer"),
        "sale_date": lot.get("sale_date"),
        "vin": lot.get("vin"),
        "url": lot.get("url"),
        "body_style": lot.get("body_style"),
        "color": lot.get("color"),
        "engine": lot.get("engine"),
        "transmission": lot.get("transmission"),
        "drive": lot.get("drive"),
        "fuel": lot.get("fuel"),
        "primary_damage": lot.get("primary_damage"),
        "secondary_damage": lot.get("secondary_damage"),
        "keys": lot.get("keys"),
        "seller": lot.get("seller"),
        "images": images,
        "images_count": len(images),
        "source": "bidcars",
    }


def write_json(path: Path, lots: list[dict], *, max_images: int, meta: dict) -> None:
    site = [to_site(lot, max_images=max_images) for lot in lots]
    with_bids = sum(1 for x in site if x.get("bid") not in (None, ""))
    payload = {
        "generated_at": _now(),
        "source": "bidcars",
        "catalog": True,
        "images_mode": "cdn",
        "count": len(site),
        "with_bids": with_bids,
        "with_images": sum(1 for x in site if x["images_count"] > 0),
        **meta,
        "lots": site,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info(
        "Записал %s авто → %s (со ставкой: %s, с фото: %s)",
        len(site),
        path,
        with_bids,
        payload["with_images"],
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Каталог Bid.cars → JSON со ставками и CDN-фото")
    p.add_argument("--per-model", type=int, default=3, help="Лотов на марку+модель (0 = все)")
    p.add_argument("--all-lots", action="store_true", help="Не схлопывать по модели")
    p.add_argument("--max-images", type=int, default=3)
    p.add_argument("--max-pages", type=int, default=80)
    p.add_argument("--from-checkpoint", action="store_true")
    p.add_argument("--details", action="store_true", help="Открыть лоты для доп. полей/фото")
    p.add_argument("--details-limit", type=int, default=None)
    p.add_argument("--pause", type=float, default=0.35)
    p.add_argument("--only-with-bid", action="store_true", help="Оставить только лоты с числовой ставкой")
    p.add_argument("-o", "--output", type=Path, default=DATA_DIR / "bidcars_catalog.json")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.from_checkpoint:
        raw_path = DATA_DIR / "bidcars_catalog_raw.json"
        if not raw_path.exists():
            raise SystemExit(f"Нет чекпоинта {raw_path}")
        raw = list(json.loads(raw_path.read_text(encoding="utf-8")).get("lots") or [])
        log.info("Из чекпоинта: %s лотов", len(raw))
    else:
        raw = scrape_catalog(max_pages=args.max_pages)
    if not raw:
        raise SystemExit("Каталог Bid.cars пуст — проверьте Chrome / Cloudflare")

    if args.only_with_bid:
        before = len(raw)
        raw = [lot for lot in raw if lot.get("bid") not in (None, "")]
        log.info("С ставкой: %s из %s", len(raw), before)

    per_model = 0 if args.all_lots else max(0, args.per_model)
    lots = pick_per_model(raw, per_model=per_model) if per_model else raw

    max_images = max(1, min(12, args.max_images))
    if args.details:
        lots = enrich_details(
            lots,
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
