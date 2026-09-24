from __future__ import annotations

import logging
import os
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

log = logging.getLogger("copart")

LOT_ID_RE = re.compile(r"/lot/(\d{6,12})\b", re.I)
BID_RE = re.compile(r"(?:Current bid|Bid)[:\s]*£\s*([\d,]+(?:\.\d+)?)", re.I)
ODO_RE = re.compile(r"Odometer\s+([\d,]+)", re.I)
CAT_RE = re.compile(r"Category\s+([A-Z0-9]+)", re.I)
VAT_YES_RE = re.compile(
    r"vat\s*(?:applies|to be added\s*yes)|\+?\s*20%\s*vat",
    re.I,
)

LOT_ID_KEYS = ("ln", "lotNumber", "lotNbr", "lotId", "lot_id", "lot_number")
YEAR_KEYS = ("lcy", "year", "lotYear", "lot_year")
MAKE_KEYS = ("mkn", "make", "lotMake", "lot_make", "lotMakeDesc")
MODEL_KEYS = ("lmod", "lm", "lmg", "model", "lotModel", "lot_model", "ldd", "lotModelDesc")
TITLE_KEYS = ("ld", "lotDesc", "lot_desc", "title", "description", "lotDescription")
BID_KEYS = ("hb", "currentBid", "bid", "highBid", "current_bid", "buyTodayBid")
LOC_KEYS = ("yn", "loc", "yardName", "location", "facilityName", "aname")
CAT_KEYS = (
    "tdc", "titleCode", "lotTitleCode", "slg", "category", "titleType",
    "saleTitleType", "titleDescription", "titleGroupDescription", "titleGroupCode",
)
ODO_KEYS = ("orr", "od", "odometer", "odo", "odometerReading")
BODY_KEYS = ("lfc", "bs", "bdt", "bodyStyle", "vehicleType", "lotBodyStyle", "vehTypDesc", "ldd")
VAT_KEYS = ("vat", "vatFlag", "isVat", "lotVat")
COLOR_KEYS = ("clr", "color", "lotColor", "extCol", "exteriorColor")
ENGINE_KEYS = ("egn", "engine", "lotEngine", "eng")
TRANS_KEYS = ("tmtp", "tsmn", "transmission", "lotTransmission")
DRIVE_KEYS = ("drv", "drive", "drivetrain")
FUEL_KEYS = ("ft", "fuel", "fuelType")
DAMAGE_KEYS = ("dd", "dmg", "primaryDamage", "lotDamage")
SEC_DAMAGE_KEYS = ("sdd", "sdt", "secondaryDamage")
KEYS_KEYS = ("hk", "hks", "keys", "hasKeys")
HIGHLIGHT_KEYS = ("lt", "lcd", "highlights", "lotHighlights")
VALUE_KEYS = ("acv", "rcv", "estimatedRetailValue", "estRetailValue")
REPAIR_KEYS = ("rc", "repairCost", "estimatedRepairCost")
SALE_KEYS = (
    "ad",
    "auctionDate",
    "saleDate",
    "sale_date",
    "auction_date",
    "lotSaleDate",
    "saledate",
    "auctionDateUtc",
    "auctionDateTime",
    "saleDateTime",
)
VIN_KEYS = ("fv", "vin", "vinNumber", "lotVin", "fullVin", "pv", "maskedVIN", "mvn")

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})\b",
    re.I,
)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
UK_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")

BLOCK_HINTS = (
    "incapsula",
    "access denied",
    "pardon our interruption",
    "attention required",
    "cf-challenge",
    "verify you are human",
)


HOME_URL = "https://www.copart.co.uk/"
DEFAULT_PAGE_CAP = 8
DEFAULT_CDP_PORT = 9222
# Headless-служба на Windows — отдельный порт, чтобы не цепляться к замороженному GUI Chrome
SERVER_CDP_PORT = 9223
INSPECT_URL = "chrome://inspect/#remote-debugging"
CREATE_NO_WINDOW = 0x08000000

LOT_DOM_SCRIPT = r"""() => {
  const text = (el) => (el && (el.textContent || "")).replace(/\s+/g, " ").trim();
  const valueAfterLabel = (labelRe) => {
    const nodes = Array.from(document.querySelectorAll("span, div, dt, th, td, label, p, strong"));
    for (const el of nodes) {
      const t = text(el);
      if (!labelRe.test(t) || t.length > 48) continue;
      const next = el.nextElementSibling;
      if (next && text(next) && !labelRe.test(text(next))) return text(next);
      const parent = el.parentElement;
      if (parent) {
        const kids = Array.from(parent.children).map(text).filter(Boolean);
        const idx = kids.findIndex((k) => labelRe.test(k));
        if (idx >= 0 && kids[idx + 1] && !labelRe.test(kids[idx + 1])) return kids[idx + 1];
      }
    }
    return "";
  };
  const fromPage = (re) => {
    const m = (document.body.innerText || "").match(re);
    return m ? m[1].trim() : "";
  };
  let locationName = text(document.querySelector("#locationInfoButton"));
  if (!locationName) locationName = fromPage(/Location\s*:?\s*([A-Z][A-Z0-9 \-/]{2,40})/i);
  const bodyStyle = valueAfterLabel(/^body style$/i) || fromPage(/Body Style\s*:?\s*([A-Za-z0-9 \-/]+)/i);
  const vehicleType = valueAfterLabel(/^vehicle type$/i) || fromPage(/Vehicle Type\s*:?\s*([A-Za-z0-9 \-/]+)/i);
  const category =
    valueAfterLabel(/^(category|title type|sale title|title code)$/i) ||
    fromPage(/Title Type\s*:?\s*([A-Za-z0-9 \-/]+)/i) ||
    fromPage(/\bCAT(?:EGORY)?\s*([A-Z])\b/i);
  const pageRaw = document.body.innerText || "";
  const pageLow = pageRaw.toLowerCase();
  let vatYes = pageLow.includes("vat applies") || pageLow.includes("+20% vat");
  const vatLabel = Array.from(document.querySelectorAll("span")).find((el) => /vat to be added/i.test(text(el)));
  if (vatLabel && vatLabel.nextElementSibling && /^yes$/i.test(text(vatLabel.nextElementSibling))) vatYes = true;
  const categoryB = Boolean(
    vatYes ||
    /\bCAT(?:EGORY)?\s*B\b/i.test(pageRaw) ||
    /cat b\s*[-–]?\s*breaker/i.test(pageRaw) ||
    /\bCAT\s*B\b/i.test(category) ||
    /^b\b/i.test(category)
  );
  const images = [];
  const pushImg = (raw) => {
    let src = (raw || "").trim();
    if (!src || src.startsWith("data:") || src.startsWith("blob:")) return;
    if (src.startsWith("//")) src = "https:" + src;
    if (src.startsWith("/")) {
      if (!/AUTH_svc|ids-c-prod|\/lpp\/|lotimage|\/vis\/|_ful\.|_thb\.|hdn-us|hdn-eu/i.test(src)) return;
      src = "https://c-static.copart.com" + src;
    }
    if (!src.startsWith("https://")) return;
    const low = src.toLowerCase();
    if (/flag|\/flags\/|placeholder|logo|icon|sprite|onetrust|country|\/content\/|clo-platinum|favicon|avatar/.test(low)) return;
    if (!/(?:[\w.-]+\.)?copart\.(?:com|co\.uk)\//i.test(src)) return;
    if (!/AUTH_svc|ids-c-prod|\/lpp\/|lotimage|\/vis\/|_ful\.|_thb\.|hdn-us|hdn-eu|\.(?:jpe?g|webp)(?:\?|$)/i.test(src)) return;
    // thumb → full where possible
    src = src.replace(/_thb\.(jpe?g|webp)/i, "_ful.$1");
    if (!images.includes(src)) images.push(src);
  };
  Array.from(document.querySelectorAll("img")).forEach((img) => {
    pushImg(img.currentSrc || img.src || "");
    ["data-src", "data-lazy", "data-original", "data-url", "ng-src"].forEach((attr) => pushImg(img.getAttribute(attr) || ""));
    const srcset = img.getAttribute("srcset") || img.getAttribute("data-srcset") || "";
    srcset.split(",").forEach((part) => pushImg((part.trim().split(/\s+/)[0] || "").trim()));
  });
  Array.from(document.querySelectorAll("source")).forEach((el) => {
    pushImg(el.getAttribute("srcset") || el.getAttribute("src") || "");
  });
  Array.from(document.querySelectorAll("[style*='background-image']")).forEach((el) => {
    const m = (el.getAttribute("style") || "").match(/url\(['"]?([^'")]+)/i);
    if (m) pushImg(m[1]);
  });
  // JSON / HTML fallback — Copart часто кладёт URL в скрипты до отрисовки галереи
  try {
    const html = document.documentElement ? document.documentElement.innerHTML : "";
    const re = /https?:\\?\/\\?\/[^\s"'<>]+?(?:AUTH_svc|ids-c-prod|\/lpp\/|_ful\.|_thb\.)[^\s"'<>]+?\.(?:jpe?g|webp)/gi;
    const matches = html.match(re) || [];
    matches.forEach((m) => pushImg(m.replace(/\\\//g, "/").replace(/&amp;/g, "&")));
  } catch (e) {}
  // thumbnails в карусели
  Array.from(document.querySelectorAll("[class*='image'], [class*='Image'], [class*='gallery'], [class*='Gallery'], [class*='thumb']")).forEach((el) => {
    if (el.tagName === "IMG") return;
    const bg = (el.getAttribute("style") || "").match(/url\(['"]?([^'")]+)/i);
    if (bg) pushImg(bg[1]);
    pushImg(el.getAttribute("data-src") || el.getAttribute("data-image") || "");
  });
  const bidText =
    valueAfterLabel(/^(current bid|high bid|current bid:)$/i) ||
    fromPage(/Current bid\s*:?\s*£?\s*([\d,]+(?:\.\d+)?)/i);
  return {
    title: text(document.querySelector("h1")) || text(document.querySelector("h2")),
    location: locationName,
    bodyStyle,
    vehicleType,
    category,
    vin: valueAfterLabel(/^vin\b/i) || fromPage(/\bVIN\s*#?\s*:?\s*([A-HJ-NPR-Z0-9*]{11,17})/i),
    odometer: valueAfterLabel(/^odometer$/i) || fromPage(/Odometer\s*:?\s*([\d,]+)/i),
    bid: bidText,
    saleDate:
      valueAfterLabel(/^(sale date|auction date|sale time)$/i) ||
      fromPage(/\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})\b/i) ||
      fromPage(/\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2})\b/i),
    color: valueAfterLabel(/^color$/i) || valueAfterLabel(/^colour$/i),
    engine: valueAfterLabel(/^engine$/i),
    transmission: valueAfterLabel(/^transmission$/i),
    drive: valueAfterLabel(/^(drive|drivetrain)$/i),
    fuel: valueAfterLabel(/^fuel$/i),
    primaryDamage: valueAfterLabel(/^primary damage$/i),
    secondaryDamage: valueAfterLabel(/^secondary damage$/i),
    keys: valueAfterLabel(/^keys$/i),
    highlights: valueAfterLabel(/^highlights$/i),
    estimatedValue: valueAfterLabel(/^(est\.?\s*retail value|estimated retail value|acv)$/i),
    repairCost: valueAfterLabel(/^(repair cost|est\.?\s*repair cost)$/i),
    year: valueAfterLabel(/^year$/i),
    vatYes,
    categoryB,
    images,
  };
}"""


def parse_lot_id(url: str) -> str | None:
    text = (url or "").strip()
    if text.isdigit() and 6 <= len(text) <= 12:
        return text
    match = LOT_ID_RE.search(text)
    return match.group(1) if match else None


def empty_lot_details(lot_id: str) -> dict:
    return {
        "lot_id": lot_id,
        "title": None,
        "year": None,
        "make": None,
        "model": None,
        "bid": None,
        "location": None,
        "category": None,
        "odometer": None,
        "sale_date": None,
        "vin": None,
        "body_style": None,
        "vehicle_type_raw": None,
        "vat_on_sale": None,
        "url": f"https://www.copart.co.uk/lot/{lot_id}",
        "color": None,
        "engine": None,
        "transmission": None,
        "drive": None,
        "fuel": None,
        "primary_damage": None,
        "secondary_damage": None,
        "keys": None,
        "highlights": None,
        "estimated_value": None,
        "repair_cost": None,
        "images": [],
    }


_IMAGE_SKIP = re.compile(
    r"flag|/flags/|placeholder|logo|icon|sprite|onetrust|country-flag|/country/"
    r"|/content/|clo-platinum|platinum\.png|member-badge|favicon|avatar|spinner|loader",
    re.I,
)
_IMAGE_CDN_HOST = re.compile(r"^https://(?:[\w.-]+\.)?copart\.(?:com|co\.uk)/", re.I)
_IMAGE_LOT_MARK = re.compile(
    r"AUTH_svc|ids-c-prod|/lpp/|lotimage|/vis/|_ful\.|_thb\.|lotimages|hdn-us|hdn-eu",
    re.I,
)
COPART_CDN_BASE = "https://c-static.copart.com"
COPART_IMAGE_REFERER = "https://www.copart.co.uk/"


def _normalize_image_url(url: str) -> str:
    src = str(url or "").strip()
    if not src or src.startswith("data:") or src.startswith("blob:"):
        return ""
    if src.startswith("/api/media/"):
        return src
    if src.startswith("//"):
        src = f"https:{src}"
    if src.startswith("/"):
        if _IMAGE_LOT_MARK.search(src):
            src = COPART_CDN_BASE + src
        else:
            return ""
    if src.startswith("http://"):
        src = "https://" + src[7:]
    if not src.startswith("https://") and _IMAGE_LOT_MARK.search(src):
        src = COPART_CDN_BASE + "/" + src.lstrip("/")
    return src


def _is_lot_image(url: str) -> bool:
    src = _normalize_image_url(url)
    if not src:
        return False
    if src.startswith("/api/media/"):
        return True
    if not src.startswith("https://"):
        return False
    if _IMAGE_SKIP.search(src):
        return False
    if not _IMAGE_CDN_HOST.search(src):
        return False
    if _IMAGE_LOT_MARK.search(src):
        return True
    # Только CDN-хосты вроде cs.copart / c-static — не www.copart.co.uk/content/*.png
    low = src.lower()
    if "www.copart." in low or "/content/" in low:
        return False
    return bool(re.search(r"\.(jpe?g|webp)(?:\?|$)", src, re.I))


def _image_score(url: str) -> int:
    low = url.lower()
    if "/api/media/" in low:
        return 4
    if "_ful." in low or "/ful/" in low:
        return 3
    if "c-static.copart" in low or "cs.copart" in low:
        return 2
    if "_thb." in low:
        return 1
    return 2


def _uniq_images(urls: list) -> list[str]:
    seen: set[str] = set()
    ranked: list[tuple[int, str]] = []
    for raw in urls:
        src = _normalize_image_url(str(raw or ""))
        if not _is_lot_image(src) or src in seen:
            continue
        seen.add(src)
        ranked.append((_image_score(src), src))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [src for _, src in ranked[:16]]


def _looks_like_image_bytes(body: bytes | None) -> bool:
    if not body or len(body) < 800:
        return False
    head = body[:32]
    if head.startswith(b"\xff\xd8\xff"):  # jpeg
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if head[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return True
    if head.lstrip()[:1] in (b"<", b"{") or b"<!DOCTYPE" in body[:200].upper() or b"<html" in body[:200].lower():
        return False
    return len(body) >= 4000


def download_image_bytes(
    page: Any,
    url: str,
    *,
    referer: str = COPART_IMAGE_REFERER,
    timeout_ms: int = 8_000,
    allow_page_fetch: bool = False,
) -> bytes | None:
    """Одна попытка скачать фото. 403/CORS не ретраим — лот без картинок это нормально."""
    headers = {
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        resp = page.context.request.get(url, headers=headers, timeout=timeout_ms)
        if resp.ok:
            body = resp.body()
            if _looks_like_image_bytes(body):
                return body
            return None
        return None
    except Exception:
        return None


def materialize_lot_images(page: Any, lot_id: str, urls: list[str], *, limit: int = 2) -> list[str]:
    """Скачивает фото через сессию Chrome (CDN иначе даёт 403) → локальные /api/media/..."""
    from config import DATA_DIR

    # Prefer full-size over thumbnails
    preferred = []
    for raw in urls or []:
        src = str(raw or "").strip().replace("_thb.", "_ful.")
        preferred.append(src)
    cleaned = _uniq_images(preferred)
    if not cleaned:
        return []
    try:
        limit = max(1, int(os.getenv("LOT_IMAGE_LIMIT", str(limit)) or limit))
    except ValueError:
        pass
    out_dir = DATA_DIR / "lot-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    local: list[str] = []
    for index, url in enumerate(cleaned[:limit]):
        if url.startswith("/api/media/"):
            local.append(url)
            continue
        dest = out_dir / f"{lot_id}_{index}.jpg"
        if dest.is_file() and dest.stat().st_size >= 800:
            local.append(f"/api/media/lot/{lot_id}/{index}")
            continue
        body = download_image_bytes(
            page, url, referer=COPART_IMAGE_REFERER, timeout_ms=8_000, allow_page_fetch=False
        )
        if not body:
            log.info("Лот %s: CDN не отдал фото, продолжаю без картинок", lot_id)
            break
        dest.write_bytes(body)
        local.append(f"/api/media/lot/{lot_id}/{index}")
        log.info("Сохранил фото лота %s #%s (%s байт)", lot_id, index, len(body))
    return local

def _harvest_images_from_page(page: Any, lot_id: str) -> list[str]:
    """Добирает URL фото с открытой страницы лота (галерея может подгрузиться позже)."""
    found: list[str] = []
    try:
        page.evaluate(
            """() => {
              const gallery = document.querySelector(
                "[class*='image-gallery'], [class*='ImageGallery'], [class*='lot-images'], [class*='lotImages'], .swiper, [class*='carousel']"
              );
              if (gallery) gallery.scrollIntoView({ block: 'center' });
              window.scrollBy(0, 400);
            }"""
        )
    except Exception:
        pass
    try:
        page.wait_for_timeout(900)
    except Exception:
        time.sleep(0.9)
    try:
        # клик по первому thumb — иногда подгружает ful
        thumbs = page.locator("img[src*='_thb'], img[src*='_ful'], img[src*='AUTH_svc'], img[src*='ids-c-prod']")
        if thumbs.count() > 0:
            try:
                thumbs.first.click(timeout=1500)
                page.wait_for_timeout(400)
            except Exception:
                pass
    except Exception:
        pass
    try:
        html = page.content() or ""
    except Exception:
        html = ""
    if html:
        for match in re.finditer(
            r"https?://[^\s\"'<>]+?(?:AUTH_svc|ids-c-prod|/lpp/|_ful\.|_thb\.)[^\s\"'<>]+?\.(?:jpe?g|webp)",
            html,
            re.I,
        ):
            found.append(match.group(0).replace("\\/", "/").replace("&amp;", "&"))
    try:
        dom_imgs = page.evaluate(
            """() => {
              const out = [];
              const push = (raw) => {
                let src = (raw || '').trim();
                if (!src || src.startsWith('data:')) return;
                if (src.startsWith('//')) src = 'https:' + src;
                if (!/^https?:/i.test(src)) return;
                if (!/copart\\.(com|co\\.uk)/i.test(src)) return;
                if (!/AUTH_svc|ids-c-prod|\\/lpp\\/|_ful\\.|_thb\\.|lotimage/i.test(src)) return;
                src = src.replace(/_thb\\.(jpe?g|webp)/i, '_ful.$1');
                if (!out.includes(src)) out.push(src);
              };
              document.querySelectorAll('img').forEach((img) => {
                push(img.currentSrc || img.src);
                ['data-src','data-lazy','data-original'].forEach((a) => push(img.getAttribute(a) || ''));
              });
              return out;
            }"""
        )
        if isinstance(dom_imgs, list):
            found.extend(str(x) for x in dom_imgs if x)
    except Exception as exc:
        log.warning("harvest images DOM: %s", exc)
    cleaned = _uniq_images(found)
    if cleaned:
        log.info("Лот %s: нашёл %s фото на странице", lot_id, len(cleaned))
    else:
        log.warning("Лот %s: фото на странице не найдены", lot_id)
    return cleaned


def _screenshot_lot_images(page: Any, lot_id: str, *, limit: int = 2, start_index: int = 0) -> list[str]:
    """Запасной путь: CDN часто 403, а картинки уже отрисованы в Chrome — снимаем их с DOM."""
    from config import DATA_DIR

    out_dir = DATA_DIR / "lot-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    local: list[str] = []
    selectors = (
        "img[src*='_ful']",
        "img[src*='_thb']",
        "img[src*='AUTH_svc']",
        "img[src*='ids-c-prod']",
        "img[src*='/lpp/']",
        "img[src*='lotimage']",
        "img[src*='hdn-']",
    )
    seen_src: set[str] = set()
    next_index = max(0, int(start_index))
    for sel in selectors:
        if len(local) >= limit:
            break
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 8)
        except Exception:
            continue
        for i in range(count):
            if len(local) >= limit:
                break
            try:
                el = loc.nth(i)
                src = (el.get_attribute("src") or el.get_attribute("data-src") or "").strip()
                if src and src in seen_src:
                    continue
                if src:
                    seen_src.add(src)
                box = el.bounding_box()
                if not box or box.get("width", 0) < 80 or box.get("height", 0) < 60:
                    continue
                index = next_index
                dest = out_dir / f"{lot_id}_{index}.jpg"
                raw = el.screenshot(type="jpeg", quality=82, timeout=8_000)
                if not raw or len(raw) < 800:
                    continue
                dest.write_bytes(raw)
                local.append(f"/api/media/lot/{lot_id}/{index}")
                next_index += 1
                log.info("Скриншот фото лота %s #%s (%s байт)", lot_id, index, len(raw))
            except Exception as exc:
                log.warning("screenshot img #%s: %s", i, exc)
    return local


def _attach_lot_images(page: Any, lot_id: str, details: dict) -> dict:
    """Фото необязательны: ошибка CDN не должна ронять карточку лота.

    LOT_KEEP_CDN_IMAGES=1 — не скачивать, оставить прямые URL Copart CDN.
    """
    try:
        urls = list(details.get("images") or [])
        keep_cdn = os.getenv("LOT_KEEP_CDN_IMAGES", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if keep_cdn:
            # Галерея часто догружается после JSON — подождём и снимем DOM
            try:
                page.wait_for_timeout(900)
            except Exception:
                pass
            try:
                page.evaluate("() => window.scrollBy(0, 450)")
            except Exception:
                pass
            harvested = _harvest_images_from_page(page, lot_id)
            urls = list(urls) + list(harvested)
            # клик по миниатюрам, чтобы подтянуть ещё URL
            try:
                thumbs = page.locator(
                    "img[src*='_thb'], img[src*='_ful'], img[src*='AUTH_svc'], img[src*='ids-c-prod']"
                )
                n = min(thumbs.count(), 8)
                for i in range(n):
                    try:
                        thumbs.nth(i).click(timeout=800)
                        page.wait_for_timeout(120)
                    except Exception:
                        continue
                urls = list(urls) + list(_harvest_images_from_page(page, lot_id))
            except Exception:
                pass
            preferred = [str(u or "").strip().replace("_thb.", "_ful.") for u in urls]
            details["images"] = _uniq_images(preferred)
            log.info("Лот %s: CDN-фото %s шт.", lot_id, len(details["images"]))
        else:
            if not urls:
                urls = _harvest_images_from_page(page, lot_id)
            details["images"] = materialize_lot_images(page, lot_id, urls, limit=2)
    except Exception as exc:
        log.info("Лот %s: фото пропущены (%s)", lot_id, exc)
        details["images"] = []
    return details


def materialize_usa_images(page: Any, lot_id: str, urls: list[str], *, limit: int = 2) -> list[str]:
    """Сохраняет фото Bid.cars/IAAI локально → /api/media/usa/..."""
    from config import DATA_DIR

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        src = str(raw or "").strip()
        if not src or src in seen:
            continue
        if src.startswith("//"):
            src = f"https:{src}"
        if src.startswith("/api/media/"):
            cleaned.append(src)
            seen.add(src)
            continue
        if not src.startswith("https://"):
            continue
        low = src.lower()
        if any(x in low for x in ("logo", "icon", "flag", "sprite", "avatar", "favicon", "pixel")):
            continue
        if not any(x in low for x in ("bid.cars", "cloudfront", "amazonaws", "iaai", "lotimages", ".jpg", ".jpeg", ".webp", ".png")):
            continue
        cleaned.append(src)
        seen.add(src)
    if not cleaned:
        return []
    out_dir = DATA_DIR / "lot-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(f"usa_{lot_id}_*.jpg"):
        try:
            stale.unlink()
        except OSError:
            pass
    local: list[str] = []
    referer = "https://bid.cars/"
    for index, url in enumerate(cleaned[:limit]):
        if url.startswith("/api/media/"):
            local.append(url)
            continue
        dest = out_dir / f"usa_{lot_id}_{index}.jpg"
        body = download_image_bytes(
            page,
            url,
            referer=referer,
            timeout_ms=8_000,
            allow_page_fetch=False,
        )
        if not body:
            log.info("USA-лот %s: фото недоступны, продолжаю без картинок", lot_id)
            break
        dest.write_bytes(body)
        local.append(f"/api/media/usa/{lot_id}/{index}")
        log.info("Сохранил USA-фото %s #%s (%s байт)", lot_id, index, len(body))
    return local


class CopartBlockedError(RuntimeError):
    pass


def _is_target_closed(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "targetclosed" in name
        or "has been closed" in text
        or "target closed" in text
        or "browser has been closed" in text
        or "context or browser has been closed" in text
    )


def _pause_ms(low: float, high: float) -> int:
    return int(random.uniform(low, high) * 1000)


def _popen(args: list[str]) -> None:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    subprocess.Popen(args, **kwargs)


def _popen_chrome(args: list[str]) -> None:
    """Запуск Chrome с окном (CREATE_NO_WINDOW прячет GUI и ломает вкладки в службе)."""
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — без скрытия окна
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    subprocess.Popen(args, **kwargs)


def _bot_chrome_user_data() -> Path:
    """Запасной профиль CDP, если обычный Chrome User Data недоступен."""
    path = Path(__file__).resolve().parent / "data" / "chrome-cdp-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quit_chrome_macos() -> None:
    """Закрыть Chrome на Mac, чтобы перезапустить с remote debugging."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Google Chrome" to quit'],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass
    for _ in range(20):
        if not _chrome_running():
            return
        time.sleep(0.4)


def _quit_chrome_windows() -> None:
    """Закрыть Chrome/Edge, чтобы перезапустить с --remote-debugging-port и тем же профилем (VPN)."""
    for image in ("chrome.exe", "msedge.exe"):
        try:
            subprocess.run(
                ["taskkill", "/IM", image, "/F"],
                capture_output=True,
                timeout=30,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    for _ in range(30):
        if not _chrome_running():
            return
        time.sleep(0.4)


def _quit_chrome() -> None:
    if sys.platform == "darwin":
        _quit_chrome_macos()
    elif os.name == "nt":
        _quit_chrome_windows()


def _activate_chrome() -> None:
    """Вывести Chrome на передний план (калькулятор / капча)."""
    if sys.platform == "darwin":
        try:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "Google Chrome" to activate',
                ],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
        return
    if os.name == "nt":
        try:
            # PowerShell: найти окно Chrome и вывести наверх
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Add-Type -Name Win -Namespace Native -MemberDefinition '"
                        "[DllImport(\"user32.dll\")] public static extern bool SetForegroundWindow(IntPtr h);"
                        "[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h, int n);"
                        "'; "
                        "$p = Get-Process chrome -ErrorAction SilentlyContinue | "
                        "Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1; "
                        "if ($p) { [Native.Win]::ShowWindow($p.MainWindowHandle, 9) | Out-Null; "
                        "[Native.Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null }"
                    ),
                ],
                capture_output=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            pass


def _focus_page(page: Any) -> None:
    """Вкладка Playwright + окно Chrome на передний план."""
    try:
        page.bring_to_front()
    except Exception:
        pass
    _activate_chrome()


def _lot_tab_focus() -> bool:
    """Показывать Chrome при лоте: на Mac — да; на Windows-сервере — нет."""
    return os.name != "nt" and not _chrome_headless_cdp()


def _env_flag(name: str) -> bool:
    try:
        from config import load_dotenv_once

        load_dotenv_once()
    except Exception:
        pass
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _chrome_allow_kill() -> bool:
    """
    Убивать процесс Chrome только при CHROME_ALLOW_KILL=1.
    По умолчанию — нет: бот только подключается к уже открытому окну
    (после kill Chrome часто не поднимается, VPN/сессия теряются).
    """
    return _env_flag("CHROME_ALLOW_KILL")


def _calc_recycle_mode() -> str:
    """
    После каждого расчёта в калькуляторе:
      off    — не трогать вкладки/Chrome (по умолчанию — сессия Copart живёт)
      tab    — только новая вкладка лотов
      chrome — полностью перезапустить Chrome (только с CHROME_ALLOW_KILL=1)
    CHROME_RESTART_AFTER_LOT=off|tab|chrome
    """
    raw = (os.getenv("CHROME_RESTART_AFTER_LOT") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return "off"
    if raw in {"tab", "page", "tabs"}:
        return "tab"
    if raw in {"1", "true", "yes", "on", "chrome", "full", "process"}:
        return "chrome"
    # Как раньше: после лота ничего не сбрасываем — иначе Incapsula снова просит проверку
    return "off"


def _is_calc_lot_kind(kind: str | None) -> bool:
    return kind in {
        "lot",
        "bidcars_lot",
        "copart_us_lot",
        "iaai_lot",
        "usa_sublot",
        "ny_dmv_lien",
    }


def _chrome_headless_cdp() -> bool:
    """
    Headless Chrome с CDP — только если явно включили CHROME_HEADLESS_CDP=1.
    Для вашего Chrome с VPN-расширением оставляйте выключенным (HEADLESS=false).
    """
    return _env_flag("CHROME_HEADLESS_CDP")


def _cdp_port() -> int:
    env = (os.getenv("CHROME_CDP_PORT") or "").strip()
    if env.isdigit():
        return int(env)
    if _chrome_headless_cdp():
        return SERVER_CDP_PORT
    return DEFAULT_CDP_PORT


def _cdp_responsive(port: int | None = None, timeout: float = 2.5) -> bool:
    """TCP-порт может быть открыт у зависшего после RDP Chrome — проверяем ответ DevTools."""
    port = int(port or _cdp_port())
    if not _port_open(port):
        return False
    import urllib.error
    import urllib.request

    for path in ("/json/version", "/json/list"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}",
                timeout=timeout,
            ) as resp:
                resp.read(512)
            return True
        except Exception:
            continue
    return False


def _windows_chrome_stability_args() -> list[str]:
    """Флаги, чтобы Chrome реже замирал после Disconnect RDP (без GPU/комpositor сессии)."""
    return [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-software-rasterizer",
        "--in-process-gpu",
        "--force-device-scale-factor=1",
        "--window-size=1920,1080",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _chrome_proxy_server() -> str | None:
    try:
        from config import load_dotenv_once

        load_dotenv_once()
    except Exception:
        pass
    for key in ("CHROME_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        return raw
    return None


def _clear_chrome_profile_locks(user_data: Path) -> None:
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = user_data / name
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def _kill_listeners_on_port(port: int) -> None:
    """Убить только процесс на CDP-порту (headless), не трогая обычный Chrome пользователя."""
    if os.name != "nt":
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"$c = Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
                    "-ErrorAction SilentlyContinue; "
                    "foreach ($x in $c) { Stop-Process -Id $x.OwningProcess -Force -ErrorAction SilentlyContinue }"
                ),
            ],
            capture_output=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _wait_for_cdp(port: int | None = None, seconds: float = 45.0) -> bool:
    """Ждать живой DevTools, не трогая процесс Chrome."""
    port = int(port or _cdp_port())
    deadline = time.time() + max(1.0, seconds)
    while time.time() < deadline:
        if _cdp_responsive(port, timeout=1.5):
            return True
        time.sleep(0.4)
    return _cdp_responsive(port, timeout=1.5)


def _launch_chrome_cdp() -> None:
    """Открыть Chrome с --remote-debugging-port (нужно для Playwright/CDP)."""
    exe = _chrome_exe()
    if exe is None:
        raise RuntimeError("Не найден Google Chrome")
    cdp_port = _cdp_port()
    server_mode = _chrome_headless_cdp()

    if _cdp_responsive(cdp_port):
        return

    if server_mode:
        # Не убиваем GUI Chrome пользователя — только зависший headless на 9223
        if _port_open(cdp_port):
            log.warning("Headless CDP на порту %s завис — перезапускаю только его", cdp_port)
            _kill_listeners_on_port(cdp_port)
            time.sleep(1.0)
        if (os.getenv("CHROME_USER_DATA_DIR") or "").strip() and not _env_flag(
            "CHROME_USE_BOT_PROFILE"
        ):
            user_data = _preferred_chrome_user_data()
        else:
            user_data = _bot_chrome_user_data()
        _clear_chrome_profile_locks(user_data)
    else:
        # Уже открытый Chrome — не убиваем: ждём CDP или подключаемся
        if _chrome_running() or _port_open(cdp_port):
            if _chrome_allow_kill():
                log.warning(
                    "Chrome не отвечает на CDP — CHROME_ALLOW_KILL=1, перезапускаю профиль"
                )
                _quit_chrome()
                time.sleep(1.5)
            else:
                log.info(
                    "Chrome уже запущен — жду remote debugging на порту %s (процесс не трогаю)",
                    cdp_port,
                )
                if _wait_for_cdp(cdp_port, 60.0):
                    log.info("Chrome remote debugging готов (порт %s)", cdp_port)
                    return
                log.warning(
                    "Порт %s не ответил. Запустите Chrome через start-my-chrome.ps1 "
                    "или chrome://inspect → Allow remote debugging. Бот не будет гасить Chrome.",
                    cdp_port,
                )
                return
        user_data = _preferred_chrome_user_data()

    args = [
        str(exe),
        f"--remote-debugging-port={cdp_port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_data}",
    ]
    if server_mode:
        args.extend(
            [
                "--headless=new",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ]
        )
    elif os.name == "nt":
        args.extend(_windows_chrome_stability_args())
    else:
        args.extend(["--no-first-run", "--no-default-browser-check"])

    proxy = _chrome_proxy_server()
    if proxy:
        args.append(f"--proxy-server={proxy}")
        log.info("Chrome proxy: %s", proxy)

    if server_mode:
        log.info(
            "Запускаю headless Chrome (профиль %s), порт %s — переживает disconnect",
            user_data,
            cdp_port,
        )
        _popen(args)
    else:
        log.info(
            "Запускаю ваш Chrome (профиль %s, disable-gpu) на порту %s",
            user_data,
            cdp_port,
        )
        _popen_chrome(args)

    for _ in range(90):
        if _cdp_responsive(cdp_port, timeout=1.5):
            log.info("Chrome remote debugging готов (порт %s)", cdp_port)
            return
        time.sleep(0.3)
    log.warning(
        "Порт %s не ответил вовремя. Проверьте VPN и профиль Chrome.",
        cdp_port,
    )


def _chrome_executables() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    home = Path.home()
    return [
        pf / "Google/Chrome/Application/chrome.exe",
        local / "Google/Chrome/Application/chrome.exe",
        pf86 / "Google/Chrome/Application/chrome.exe",
        pf / "Microsoft/Edge/Application/msedge.exe",
        pf86 / "Microsoft/Edge/Application/msedge.exe",
        local / "Microsoft/Edge/Application/msedge.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        home / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]


def _chrome_exe() -> Path | None:
    for path in _chrome_executables():
        if path.is_file():
            return path
    return None


def _user_data_dirs() -> list[Path]:
    """Обычные профили Chrome/Edge (с VPN), плюс запасной профиль бота."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    home = Path.home()
    dirs: list[Path] = [
        local / "Google/Chrome/User Data",
        local / "Google/Chrome Beta/User Data",
        local / "Microsoft/Edge/User Data",
        home / "Library/Application Support/Google/Chrome",
        home / "Library/Application Support/Google/Chrome Beta",
        home / "Library/Application Support/Microsoft Edge",
    ]
    # Служба NSSM под SYSTEM не видит LOCALAPPDATA пользователя — ищем по C:\Users
    if os.name == "nt":
        users_root = Path(os.environ.get("SystemDrive", "C:") + r"\Users")
        if users_root.is_dir():
            skip = {"public", "default", "default user", "all users", "desktop.ini"}
            for user_home in users_root.iterdir():
                if not user_home.is_dir() or user_home.name.lower() in skip:
                    continue
                dirs.append(user_home / "AppData/Local/Google/Chrome/User Data")
                dirs.append(user_home / "AppData/Local/Google/Chrome Beta/User Data")
                dirs.append(user_home / "AppData/Local/Microsoft/Edge/User Data")
    dirs.append(Path(__file__).resolve().parent / "data" / "chrome-profile")
    dirs.append(Path(__file__).resolve().parent / "data" / "chrome-profile-export")
    dirs.append(_bot_chrome_user_data())
    # Уникальные пути с сохранением порядка
    seen: set[str] = set()
    unique: list[Path] = []
    for path in dirs:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _preferred_chrome_user_data() -> Path:
    """
    Профиль с VPN/логинами пользователя.
    CHROME_USER_DATA_DIR=... — явный путь; иначе свежий Google Chrome User Data; иначе профиль бота.
    """
    env = (os.getenv("CHROME_USER_DATA_DIR") or "").strip().strip('"')
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    if (os.getenv("CHROME_USE_BOT_PROFILE") or "").strip().lower() in {"1", "true", "yes"}:
        return _bot_chrome_user_data()

    candidates: list[Path] = []
    for path in _user_data_dirs():
        if not path.is_dir():
            continue
        if "chrome-cdp-profile" in path.parts:
            continue
        if (path / "Default").is_dir() or (path / "Local State").is_file():
            candidates.append(path)
    if not candidates:
        return _bot_chrome_user_data()

    def _mtime(path: Path) -> float:
        probe = path / "Default"
        try:
            return (probe if probe.exists() else path).stat().st_mtime
        except OSError:
            return 0.0

    # Свежий профиль пользователя (там VPN), не пустой bot-профиль
    preferred = max(candidates, key=_mtime)
    log.info("Chrome User Data для CDP/VPN: %s", preferred)
    return preferred


def _image_running(name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        return name.lower() in (result.stdout or "").lower()
    except Exception:
        return False


def _chrome_running() -> bool:
    if os.name == "nt":
        return _image_running("chrome.exe") or _image_running("msedge.exe")
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Google Chrome|Chromium|Microsoft Edge"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False

def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _read_devtools_active_port(user_data: Path) -> tuple[int, str] | None:
    path = user_data / "DevToolsActivePort"
    if not path.is_file():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        port = int(lines[0])
        ws_path = lines[1] if len(lines) > 1 else ""
        return port, ws_path
    except Exception:
        return None


def _cdp_endpoints() -> list[str]:
    found: list[str] = []
    want_port = _cdp_port()
    server_mode = _chrome_headless_cdp()

    def add(url: str) -> None:
        item = url.strip()
        if item and item not in found:
            found.append(item)

    env = os.getenv("CHROME_CDP_URL", "").strip()
    if env:
        # Env может указывать на мёртвый ws — проверяем порт, если это localhost
        try:
            from urllib.parse import urlparse

            parsed_env = urlparse(env)
            host = (parsed_env.hostname or "").lower()
            port = parsed_env.port or (443 if parsed_env.scheme == "wss" else 80)
            if host in {"127.0.0.1", "localhost"} and not _port_open(int(port)):
                log.warning(
                    "CHROME_CDP_URL=%s, но порт %s закрыт — remote debugging выключен",
                    env[:80],
                    port,
                )
            else:
                add(env)
        except Exception:
            add(env)

    data_dirs = [_bot_chrome_user_data()] if server_mode else (_user_data_dirs() + [_bot_chrome_user_data()])
    for data_dir in data_dirs:
        parsed = _read_devtools_active_port(data_dir)
        if not parsed:
            continue
        port, ws_path = parsed
        if server_mode and port != want_port:
            continue
        # Старый DevToolsActivePort без живого порта — не долбим ECONNREFUSED
        if not _port_open(port):
            continue
        # Новый Chrome remote-debugging часто отвечает только по ws://, http /json даёт 404
        if ws_path:
            path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
            add(f"ws://127.0.0.1:{port}{path}")
        add(f"http://127.0.0.1:{port}")
    if _port_open(want_port):
        for data_dir in data_dirs:
            parsed = _read_devtools_active_port(data_dir)
            if not parsed:
                continue
            port, ws_path = parsed
            if port != want_port or not ws_path:
                continue
            path = ws_path if ws_path.startswith("/") else f"/{ws_path}"
            add(f"ws://127.0.0.1:{port}{path}")
        add(f"http://127.0.0.1:{want_port}")
    return found


def _ensure_user_chrome() -> None:
    # Живой CDP (не просто открытый порт после disconnect)
    if _cdp_responsive():
        return
    if _chrome_headless_cdp():
        if _port_open(_cdp_port()):
            _kill_listeners_on_port(_cdp_port())
            time.sleep(1.0)
        _launch_chrome_cdp()
        return
    if _chrome_running() or _port_open(_cdp_port()):
        if _chrome_allow_kill():
            log.warning("Chrome завис или без CDP — CHROME_ALLOW_KILL=1, убиваю и поднимаю")
            _quit_chrome()
            time.sleep(1.5)
            _launch_chrome_cdp()
            return
        log.info(
            "Chrome уже открыт — переподключаюсь / жду CDP, процесс не гашу"
        )
        if _wait_for_cdp(_cdp_port(), 45.0):
            return
        # Процесс мог сам упасть за время ожидания — тогда можно стартовать
        if not _chrome_running():
            _launch_chrome_cdp()
        return
    _launch_chrome_cdp()


def _open_inspect_page() -> None:
    exe = _chrome_exe()
    if exe is None:
        return
    _popen([str(exe), INSPECT_URL])


class CopartScraper:
    def __init__(
        self,
        urls: str | list | tuple,
        max_pages: int = 0,
        headless: bool = True,
    ) -> None:
        if isinstance(urls, str):
            self.searches = [("Поиск", urls)]
        else:
            self.searches = []
            for item in urls:
                if isinstance(item, str):
                    self.searches.append(("Поиск", item))
                elif isinstance(item, (tuple, list)) and len(item) >= 2:
                    self.searches.append((str(item[0]), str(item[1])))
                else:
                    self.searches.append((item.name, item.url))
        self.max_pages = max_pages
        self.headless = headless
        self.page_limit = max_pages if max_pages > 0 else DEFAULT_PAGE_CAP

    def fetch_lots(self) -> list[dict]:
        return get_scrape_service(self.headless).fetch(self.searches, self.page_limit)

    def collect(self, page: Any, json_target: list[dict], warmed: bool) -> tuple[list[dict], bool]:
        lots_by_id: dict[str, dict] = {}
        if not warmed:
            self._warmup(page)
            warmed = True
        for index, (name, url) in enumerate(self.searches):
            if _service:
                _service.run_pending_lot_jobs()
            if index:
                self._human_pause(page, 6.0, 13.0)
            json_target.clear()
            log.info("Поиск «%s»", name)
            self._scrape_url(page, url, name, json_target, lots_by_id)
        if not lots_by_id:
            log.info("По заданным поискам сейчас нет лотов")
            return [], warmed
        return list(lots_by_id.values()), warmed

    def fetch_lot_details(self, page: Any, url: str, json_target: list[dict], *, fast: bool = False) -> dict:
        if fast:
            return self._fetch_lot_details_fast(page, url, json_target)
        return self._fetch_lot_details_slow(page, url, json_target)

    def _finalize_lot_details(
        self,
        lot_id: str,
        canonical: str,
        json_target: list[dict],
        dom: dict | None = None,
    ) -> dict:
        from_json = self._lot_from_json_bucket(json_target, lot_id)
        extra = self._extras_from_json(json_target, lot_id)
        dom = dom or {}
        from_json = from_json or {}
        all_images: list[str] = []
        for part in (extra.get("images"), from_json.get("images"), dom.get("images")):
            if part:
                all_images.extend(part)
        merged = {
            **extra,
            **from_json,
            **{k: v for k, v in dom.items() if k != "images" and v not in (None, "", [])},
        }
        if not merged.get("title"):
            merged["title"] = f"Lot {lot_id}"
        merged["lot_id"] = lot_id
        merged["url"] = canonical
        merged["images"] = _uniq_images(all_images)
        if merged.get("category"):
            merged["category"] = CopartScraper._normalize_category(merged["category"])
        return merged

    @staticmethod
    def _lot_details_ready(lot: dict, *, started: float | None = None) -> bool:
        if not lot.get("title"):
            return False
        if not lot.get("location"):
            return False
        filled = sum(
            1
            for key in ("category", "sale_date", "bid", "odometer", "body_style", "vin")
            if lot.get(key) not in (None, "", [])
        )
        elapsed = (time.time() - started) if started else 0
        if filled >= 2:
            return True
        if filled >= 1 and elapsed >= 3:
            return True
        if elapsed >= 8 and filled >= 1:
            return True
        if elapsed >= 12:
            return True
        return False

    def _fetch_lot_details_fast(self, page: Any, url: str, json_target: list[dict]) -> dict:
        lot_id = parse_lot_id(url)
        if not lot_id:
            raise ValueError("Нужна ссылка на лот Copart, например https://www.copart.co.uk/lot/12345678")
        canonical = f"https://www.copart.co.uk/lot/{lot_id}"
        log.info("Читаю лот %s со страницы Copart", lot_id)
        json_target.clear()
        current = (page.url or "").lower()
        if f"/lot/{lot_id}" not in current:
            self._safe_goto(page, canonical)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except PlaywrightTimeout:
            pass
        if self._is_blocked(page):
            self._wait_out_protection(page, lot=True, fast=True)
        merged: dict | None = None
        started = time.time()
        deadline = started + 14
        scrolled = False
        while time.time() < deadline:
            if not scrolled and time.time() - started > 1.5:
                try:
                    page.evaluate("() => window.scrollBy(0, 350)")
                    scrolled = True
                except Exception:
                    scrolled = True
            dom = None
            try:
                dom = self._lot_from_dom(page, lot_id, canonical)
            except Exception:
                pass
            candidate = self._finalize_lot_details(lot_id, canonical, json_target, dom)
            if self._lot_details_ready(candidate, started=started):
                merged = candidate
                break
            time.sleep(0.15)
        if merged is None:
            try:
                dom = self._lot_from_dom(page, lot_id, canonical)
            except Exception:
                dom = {}
            merged = self._finalize_lot_details(lot_id, canonical, json_target, dom)
        return _attach_lot_images(page, lot_id, merged)

    def _fetch_lot_details_slow(self, page: Any, url: str, json_target: list[dict]) -> dict:
        lot_id = parse_lot_id(url)
        if not lot_id:
            raise ValueError("Нужна ссылка на лот Copart, например https://www.copart.co.uk/lot/12345678")
        canonical = f"https://www.copart.co.uk/lot/{lot_id}"
        log.info("Открываю страницу лота %s", lot_id)
        json_target.clear()
        try:
            page.bring_to_front()
        except Exception:
            pass
        self._safe_goto(page, canonical)
        self._human_pause(page, 1.8, 3.8)
        self._accept_cookies(page)
        self._human_mouse(page)
        self._wait_out_protection(page, lot=True)
        try:
            page.wait_for_selector(
                "h1, #locationInfoButton, [class*='lot-details'], [class*='lotDetails']",
                timeout=25_000,
            )
        except PlaywrightTimeout:
            pass
        self._human_scroll(page)
        self._human_pause(page, 0.8, 1.6)
        details = self._finalize_lot_details(lot_id, canonical, json_target, self._lot_from_dom(page, lot_id, canonical))
        return _attach_lot_images(page, lot_id, details)

    def _lot_from_json_bucket(self, bucket: list[dict], lot_id: str) -> dict | None:
        for lot in bucket:
            if str(lot.get("lot_id")) == lot_id:
                return lot
        return None

    def _extras_from_json(self, bucket: list[dict], lot_id: str) -> dict:
        extras = empty_lot_details(lot_id)
        images: list[str] = []
        for lot in bucket:
            if str(lot.get("lot_id")) != lot_id:
                continue
            for key, value in lot.items():
                if key == "images" and isinstance(value, list):
                    images.extend(str(item) for item in value if item)
                elif extras.get(key) in (None, "", []) and value not in (None, "", []):
                    extras[key] = value
        extras["images"] = _uniq_images(images)
        return extras

    def _lot_from_dom(self, page: Any, lot_id: str, url: str) -> dict:
        try:
            data = page.evaluate(LOT_DOM_SCRIPT)
        except Exception:
            data = {}
        data = data if isinstance(data, dict) else {}
        details = empty_lot_details(lot_id)
        details.update(
            {
                "title": data.get("title") or details["title"],
                "location": data.get("location") or None,
                "body_style": data.get("bodyStyle") or None,
                "vehicle_type_raw": data.get("vehicleType") or None,
                "category": self._normalize_category(data.get("category")) or ("B" if data.get("categoryB") else None),
                "vin": self._vin(data.get("vin")),
                "odometer": self._number(data.get("odometer")),
                "bid": self._number(data.get("bid")),
                "sale_date": self._sale_date_from_text(str(data.get("saleDate") or "")),
                "color": data.get("color") or None,
                "engine": data.get("engine") or None,
                "transmission": data.get("transmission") or None,
                "drive": data.get("drive") or None,
                "fuel": data.get("fuel") or None,
                "primary_damage": data.get("primaryDamage") or None,
                "secondary_damage": data.get("secondaryDamage") or None,
                "keys": data.get("keys") or None,
                "highlights": data.get("highlights") or None,
                "estimated_value": self._number(data.get("estimatedValue")),
                "repair_cost": self._number(data.get("repairCost")),
                "vat_on_sale": True if data.get("vatYes") else None,
                "images": _uniq_images(data.get("images") or []),
                "url": url,
            }
        )
        if data.get("categoryB") and not details.get("category"):
            details["category"] = "B"
        details["category"] = self._normalize_category(details.get("category"))
        year = self._int(data.get("year"))
        if year:
            details["year"] = year
        title = details.get("title") or ""
        year_match = re.match(r"(19|20)\d{2}", title)
        if not details.get("year") and year_match:
            details["year"] = int(year_match.group(0))
        parts = title.split()
        if not details.get("make") and len(parts) >= 2 and parts[0].isdigit():
            details["make"] = parts[1].upper()
            details["model"] = " ".join(parts[2:]) or None
        return details

    def _warmup(self, page: Any) -> None:
        log.info("Работаю во вкладке вашего Chrome, второе окно не открываю")
        try:
            page.bring_to_front()
        except Exception:
            pass
        current = (page.url or "").lower()
        if "copart.co.uk" not in current:
            self._safe_goto(page, HOME_URL)
        self._human_pause(page, 1.5, 3.5)
        self._accept_cookies(page)
        self._human_mouse(page)
        self._wait_out_protection(page, allow_home=True)

    def _safe_goto(self, page: Any, url: str) -> None:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        except PlaywrightError as exc:
            text = str(exc).lower()
            if "interrupted by another navigation" not in text:
                raise
            log.info("Copart сам открыл другую страницу — продолжаю с неё")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=45_000)
            except PlaywrightTimeout:
                pass

    def _yield_to_calc(self) -> None:
        """Во время мониторинга сразу отдаём Chrome калькулятору."""
        if not _service or _service.lot_waiters <= 0:
            return
        try:
            _service.run_pending_lot_jobs()
        except Exception as exc:
            log.warning("Прерывание ради калькулятора: %s", exc)

    def _human_pause(self, page: Any, low: float, high: float) -> None:
        self._yield_to_calc()
        if _service and _service.lot_waiters > 0:
            low, high = min(low, 0.08), min(high, 0.25)
        ms = _pause_ms(low, high)
        try:
            if page:
                page.wait_for_timeout(ms)
                return
        except PlaywrightError:
            pass
        time.sleep(ms / 1000)

    def _human_mouse(self, page: Any) -> None:
        try:
            page.mouse.move(
                random.randint(180, 1100),
                random.randint(140, 640),
                steps=random.randint(10, 22),
            )
        except Exception:
            return
        self._human_pause(page, 0.2, 0.7)

    def _human_scroll(self, page: Any) -> None:
        for _ in range(random.randint(1, 3)):
            try:
                page.mouse.wheel(0, random.randint(160, 480))
            except Exception:
                return
            self._human_pause(page, 0.4, 1.2)
        if random.random() < 0.35:
            try:
                page.mouse.wheel(0, -random.randint(60, 180))
            except Exception:
                return
            self._human_pause(page, 0.3, 0.8)

    def _scrape_url(
        self,
        page: Any,
        url: str,
        search_name: str,
        json_lots: list[dict],
        lots_by_id: dict[str, dict],
    ) -> None:
        self._yield_to_calc()
        self._safe_goto(page, url)
        self._yield_to_calc()
        self._human_pause(page, 2.2, 5.5)
        self._accept_cookies(page)
        self._human_mouse(page)
        self._wait_out_protection(page)
        self._yield_to_calc()
        self._human_scroll(page)
        if not self._wait_for_results(page):
            log.info("«%s»: пустой результат", search_name)
            return

        before = len(lots_by_id)
        for page_no in range(1, self.page_limit + 1):
            self._yield_to_calc()
            self._tag(json_lots, search_name)
            html_lots = self._lots_from_html(page)
            self._tag(html_lots, search_name)
            self._merge(lots_by_id, json_lots)
            self._merge(lots_by_id, html_lots)
            log.info(
                "«%s» страница %s: всего уникальных лотов %s",
                search_name,
                page_no,
                len(lots_by_id),
            )
            if page_no >= self.page_limit:
                break
            if _service:
                _service.run_pending_lot_jobs()
            self._human_scroll(page)
            self._human_pause(page, 3.5, 8.5)
            if not self._goto_next_page(page, json_lots):
                break
        log.info("«%s»: добавлено %s лотов", search_name, len(lots_by_id) - before)

    def _capture_json(self, response: Any, bucket: list[dict]) -> None:
        try:
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            if response.status != 200:
                return
            data = response.json()
        except Exception:
            return
        found = []
        self._walk_json(data, found)
        if found:
            bucket.extend(found)

    def _walk_json(self, obj: Any, found: list[dict]) -> None:
        if isinstance(obj, dict):
            lot = self._lot_from_obj(obj)
            if lot:
                found.append(lot)
            for value in obj.values():
                self._walk_json(value, found)
        elif isinstance(obj, list):
            for item in obj:
                self._walk_json(item, found)

    def _lot_from_obj(self, obj: dict) -> dict | None:
        lot_id = None
        for key in LOT_ID_KEYS:
            if key in obj and obj[key] not in (None, ""):
                lot_id = str(obj[key]).strip()
                break
        if not lot_id or not lot_id.isdigit() or not (6 <= len(lot_id) <= 12):
            return None
        year = self._first(obj, YEAR_KEYS)
        make = self._first(obj, MAKE_KEYS)
        model = self._first(obj, MODEL_KEYS)
        title = self._first(obj, TITLE_KEYS)
        if not any((year, make, model, title)):
            return None
        if not title:
            title = " ".join(str(part) for part in (year, make, model) if part).strip()
        bid = self._number(self._first(obj, BID_KEYS))
        odo = self._number(self._first(obj, ODO_KEYS))
        images: list[str] = []
        self._collect_images(obj, images)
        return {
            "lot_id": lot_id,
            "title": str(title),
            "year": self._int(year),
            "make": str(make).upper() if make else None,
            "model": str(model) if model else None,
            "bid": bid,
            "location": self._first(obj, LOC_KEYS),
            "category": self._normalize_category(self._first(obj, CAT_KEYS)),
            "odometer": odo,
            "sale_date": self._sale_date(self._first(obj, SALE_KEYS)),
            "vin": self._vin(self._first(obj, VIN_KEYS)),
            "body_style": str(self._first(obj, BODY_KEYS) or "") or None,
            "vehicle_type_raw": str(self._first(obj, ("vehicleType", "vehTypDesc", "vt")) or "") or None,
            "vat_on_sale": self._vat_flag(self._first(obj, VAT_KEYS)),
            "url": f"https://www.copart.co.uk/lot/{lot_id}",
            "color": str(self._first(obj, COLOR_KEYS) or "") or None,
            "engine": str(self._first(obj, ENGINE_KEYS) or "") or None,
            "transmission": str(self._first(obj, TRANS_KEYS) or "") or None,
            "drive": str(self._first(obj, DRIVE_KEYS) or "") or None,
            "fuel": str(self._first(obj, FUEL_KEYS) or "") or None,
            "primary_damage": str(self._first(obj, DAMAGE_KEYS) or "") or None,
            "secondary_damage": str(self._first(obj, SEC_DAMAGE_KEYS) or "") or None,
            "keys": str(self._first(obj, KEYS_KEYS) or "") or None,
            "highlights": str(self._first(obj, HIGHLIGHT_KEYS) or "") or None,
            "estimated_value": self._number(self._first(obj, VALUE_KEYS)),
            "repair_cost": self._number(self._first(obj, REPAIR_KEYS)),
            "images": _uniq_images(images),
        }

    def _collect_images(self, obj: Any, found: list[str]) -> None:
        if isinstance(obj, str):
            src = _normalize_image_url(obj)
            if _is_lot_image(src):
                found.append(src)
            return
        if isinstance(obj, dict):
            for key in (
                "fullUrl",
                "imageUrl",
                "imageURL",
                "highResUrl",
                "thumbnailUrl",
                "thumbUrl",
                "largeUrl",
                "swiftImageUrl",
                "imagePath",
                "imgPath",
                "lotImagePath",
                "url",
                "image",
                "src",
                "path",
            ):
                value = obj.get(key)
                if isinstance(value, str):
                    self._collect_images(value, found)
            for value in obj.values():
                self._collect_images(value, found)
            return
        if isinstance(obj, list):
            for item in obj:
                self._collect_images(item, found)

    def _lots_from_html(self, page: Any) -> list[dict]:
        lots: dict[str, dict] = {}
        links = page.locator('a[href*="/lot/"]')
        count = min(links.count(), 200)
        for i in range(count):
            try:
                href = links.nth(i).get_attribute("href") or ""
            except Exception:
                continue
            match = LOT_ID_RE.search(href)
            if not match:
                continue
            lot_id = match.group(1)
            if lot_id in lots:
                continue
            row_text = ""
            try:
                row = links.nth(i).locator("xpath=ancestor::tr[1]")
                if row.count():
                    row_text = row.inner_text(timeout=1_000)
                else:
                    card = links.nth(i).locator("xpath=ancestor::*[self::article or self::li or contains(@class,'lot')][1]")
                    row_text = card.inner_text(timeout=1_000) if card.count() else links.nth(i).inner_text(timeout=1_000)
            except Exception:
                row_text = ""
            lots[lot_id] = self._lot_from_text(lot_id, row_text, href)
        return list(lots.values())

    def _lot_from_text(self, lot_id: str, text: str, href: str) -> dict:
        title = ""
        for line in (text or "").splitlines():
            clean = " ".join(line.split())
            if clean and "lot #" not in clean.lower() and "watch" not in clean.lower():
                title = clean
                break
        if not title:
            title = f"Lot {lot_id}"
        bid_match = BID_RE.search(text or "")
        odo_match = ODO_RE.search(text or "")
        cat_match = CAT_RE.search(text or "")
        year = None
        year_match = re.match(r"(19|20)\d{2}", title)
        if year_match:
            year = int(year_match.group(0))
        make = None
        parts = title.split()
        if len(parts) >= 2 and parts[0].isdigit():
            make = parts[1].upper()
        return {
            "lot_id": lot_id,
            "title": title,
            "year": year,
            "make": make,
            "model": None,
            "bid": self._number(bid_match.group(1) if bid_match else None),
            "location": None,
            "category": cat_match.group(1) if cat_match else None,
            "odometer": self._number(odo_match.group(1) if odo_match else None),
            "sale_date": self._sale_date_from_text(text or ""),
            "vin": None,
            "body_style": None,
            "vat_on_sale": True if VAT_YES_RE.search(text or "") else None,
            "url": urljoin("https://www.copart.co.uk/", href),
        }

    def _accept_cookies(self, page: Any, *, fast: bool = False) -> None:
        selectors = (
            "#onetrust-accept-btn-handler",
            "button:has-text('Accept All')",
            "button:has-text('Accept Cookies')",
            "button:has-text('I Accept')",
        )
        for selector in selectors:
            try:
                btn = page.locator(selector)
                if btn.count() and btn.first.is_visible():
                    btn.first.click(timeout=2_000 if fast else 3_000)
                    page.wait_for_timeout(150 if fast else 800)
                    return
            except Exception:
                continue

    def _try_larger_page_size(self, page: Any) -> None:
        for value in ("100", "50"):
            try:
                select = page.locator("select").filter(has=page.locator(f'option[value="{value}"]'))
                if select.count():
                    select.first.select_option(value)
                    page.wait_for_timeout(2_000)
                    log.info("Размер страницы: %s", value)
                    return
            except Exception:
                continue

    def _wait_for_results(self, page: Any) -> bool:
        deadline = time.time() + 25
        while time.time() < deadline:
            self._yield_to_calc()
            try:
                page.wait_for_selector('a[href*="/lot/"]', timeout=3_000)
                return True
            except PlaywrightTimeout:
                if self._is_blocked(page):
                    self._wait_out_protection(page)
                    continue
                body = ""
                try:
                    body = (page.inner_text("body") or "").lower()
                except Exception:
                    pass
                empty_hints = (
                    "0 search",
                    "no result",
                    "no lots",
                    "showing 0",
                    "0 entries",
                )
                if any(hint in body for hint in empty_hints):
                    return False
        self._raise_if_blocked(page)
        log.info("На странице нет ссылок на лоты — считаю поиск пустым")
        return False

    def _is_blocked(self, page: Any) -> bool:
        html = ""
        try:
            html = (page.content() or "").lower()
        except Exception:
            return False
        return any(hint in html for hint in BLOCK_HINTS)

    def _wait_out_protection(self, page: Any, allow_home: bool = False, lot: bool = False, *, fast: bool = False) -> None:
        if not self._is_blocked(page):
            return
        if self.headless:
            raise CopartBlockedError(
                "Copart показал защиту. Поставьте HEADLESS=false в .env — окно Chrome откроется один раз."
            )
        log.info("Пройдите проверку в Chrome один раз. Окно не закрывайте. Жду до 3 минут.")
        deadline = time.time() + 180
        while time.time() < deadline:
            self._yield_to_calc()
            try:
                if allow_home:
                    page.wait_for_function(
                        """() => {
                            const html = document.documentElement.innerHTML.toLowerCase();
                            return !html.includes('incapsula') && !html.includes('pardon our interruption');
                        }""",
                        timeout=4_000,
                    )
                elif lot:
                    page.wait_for_function(
                        """() => {
                            const html = document.documentElement.innerHTML.toLowerCase();
                            if (html.includes('incapsula') || html.includes('pardon our interruption')) return false;
                            return Boolean(document.querySelector('h1') || document.querySelector('#locationInfoButton'));
                        }""",
                        timeout=4_000,
                    )
                else:
                    page.wait_for_selector('a[href*="/lot/"]', timeout=4_000)
                break
            except PlaywrightTimeout:
                continue
        else:
            raise CopartBlockedError("Проверка не пройдена за 3 минуты.") from None
        if not fast:
            self._human_pause(page, 1.5, 3.0)

    def _raise_if_blocked(self, page: Any) -> None:
        if self._is_blocked(page):
            raise CopartBlockedError(
                "Copart показал защиту от ботов. Поставьте HEADLESS=false и пройдите проверку один раз."
            )

    def _goto_next_page(self, page: Any, json_lots: list[dict]) -> bool:
        before = self._visible_lot_ids(page)
        selectors = (
            "li.paginate_button.next:not(.disabled) a",
            "a.paginate_button.next:not(.disabled)",
            "button.p-paginator-next:not(.p-disabled)",
            "button[aria-label='Next']:not([disabled])",
            "a[aria-label='Next']",
            "button:has-text('Next')",
            "a:has-text('Next')",
        )
        clicked = False
        for selector in selectors:
            loc = page.locator(selector)
            try:
                if not loc.count():
                    continue
                target = loc.last
                classes = (target.get_attribute("class") or "").lower()
                if "disabled" in classes:
                    continue
                if target.is_disabled():
                    continue
                json_lots.clear()
                self._human_mouse(page)
                try:
                    target.hover(timeout=2_000)
                except Exception:
                    pass
                self._human_pause(page, 0.5, 1.4)
                target.click(timeout=5_000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            return False
        try:
            page.wait_for_function(
                """(prev) => {
                    const hrefs = [...document.querySelectorAll('a[href*="/lot/"]')]
                        .map(a => a.getAttribute('href') || '');
                    const ids = [...new Set(hrefs.map(h => (h.match(/\\/lot\\/(\\d+)/) || [])[1]).filter(Boolean))];
                    return ids.length && ids[0] !== prev[0];
                }""",
                arg=before or [""],
                timeout=20_000,
            )
        except PlaywrightTimeout:
            page.wait_for_timeout(2_500)
        page.wait_for_timeout(800)
        after = self._visible_lot_ids(page)
        return bool(after) and after != before

    def _visible_lot_ids(self, page: Any) -> list[str]:
        hrefs = page.eval_on_selector_all(
            'a[href*="/lot/"]',
            "els => els.map(e => e.getAttribute('href') || '')",
        )
        ids = []
        for href in hrefs:
            match = LOT_ID_RE.search(href or "")
            if match and match.group(1) not in ids:
                ids.append(match.group(1))
        return ids

    @staticmethod
    def _tag(lots: list[dict], search_name: str) -> None:
        for lot in lots:
            names = lot.setdefault("search_names", [])
            if search_name not in names:
                names.append(search_name)

    @staticmethod
    def _merge(target: dict[str, dict], lots: list[dict]) -> None:
        for lot in lots:
            current = target.get(lot["lot_id"])
            if not current:
                copied = dict(lot)
                copied["search_names"] = list(lot.get("search_names") or [])
                target[lot["lot_id"]] = copied
                continue
            for key, value in lot.items():
                if key == "search_names":
                    merged = list(current.get("search_names") or [])
                    for name in value or []:
                        if name not in merged:
                            merged.append(name)
                    current["search_names"] = merged
                elif value not in (None, "") and not current.get(key):
                    current[key] = value

    @staticmethod
    def _normalize_category(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        match = re.search(r"\bCAT(?:EGORY)?\s*([A-Z])\b", text, re.I)
        if match:
            return match.group(1).upper()
        first = text.split()[0].upper() if text.split() else ""
        if first in {"S", "N", "B", "C", "X", "D"}:
            return first
        if re.search(r"CAT\s*B|BREAKER", text, re.I):
            return "B"
        if len(text) <= 4 and text.upper() in {"S", "N", "B", "C", "X", "D"}:
            return text.upper()
        return text[:48]

    @staticmethod
    def _first(obj: dict, keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
        return None

    @staticmethod
    def _vin(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
        if len(text) < 11:
            return None
        return text

    @staticmethod
    def _vat_flag(value: Any) -> bool | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "vat"}:
            return True
        if text in {"0", "false", "no", "n"}:
            return False
        return None

    @staticmethod
    def _sale_date(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            for key in ("date", "value", "auctionDate", "saleDate"):
                parsed = CopartScraper._sale_date(value.get(key))
                if parsed:
                    return parsed
            return None
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 10_000_000_000:
                ts /= 1000
            if ts < 1_000_000_000:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        return CopartScraper._sale_date_from_text(str(value))

    @staticmethod
    def _sale_date_from_text(text: str) -> str | None:
        cleaned = str(text or "").strip()
        iso = re.match(r"(20\d{2}-\d{2}-\d{2})", cleaned)
        if iso:
            return iso.group(1)
        iso = ISO_DATE_RE.search(cleaned)
        if iso:
            return iso.group(1)
        month = MONTH_DATE_RE.search(text)
        if month:
            raw = re.sub(r"\s+", " ", month.group(1)).replace(".", "")
            parts = raw.split()
            if len(parts) == 3:
                month_no = MONTHS.get(parts[1].lower())
                if month_no:
                    return f"{int(parts[2]):04d}-{month_no:02d}-{int(parts[0]):02d}"
        uk = UK_DATE_RE.search(text)
        if uk:
            day, month, year = (int(uk.group(1)), int(uk.group(2)), int(uk.group(3)))
            if month > 12 and day <= 12:
                day, month = month, day
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    @staticmethod
    def _number(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace(",", "").replace("£", "").strip()
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _int(value: Any) -> int | None:
        number = CopartScraper._number(value)
        return int(number) if number is not None else None


class ScrapeService:
    def __init__(self, headless: bool) -> None:
        self.headless = headless
        self.lot_waiters = 0
        self._lot_waiters_lock = threading.Lock()
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._job_seq = 0
        self._job_seq_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._monitor_page: Any = None
        self._lot_page: Any = None
        self._bidcars_page: Any = None
        self._copart_us_page: Any = None
        self._iaai_page: Any = None
        self._ny_dmv_page: Any = None
        self._maps_page: Any = None
        self._json_target: list[dict] = []
        self._json_hook_pages: set[int] = set()
        self._monitor_warmed = False
        self._thread_id: int | None = None
        self._in_lot_interrupt = False

    def _next_job_seq(self) -> int:
        with self._job_seq_lock:
            self._job_seq += 1
            return self._job_seq

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="copart-browser", daemon=True)
        self._thread.start()

    def fetch(self, searches: list[tuple[str, str]], page_limit: int) -> list[dict]:
        return self._run_job({"kind": "search", "searches": searches, "page_limit": page_limit}, timeout=600) or []

    def fetch_lot(self, url: str) -> dict:
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job({"kind": "lot", "url": url}, timeout=180)
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def fetch_image(self, url: str) -> bytes:
        return self._run_job({"kind": "image", "url": url}, timeout=45)

    def fetch_google_miles(self, origin: str, destinations: dict[str, str]) -> dict[str, float]:
        """Мили Google Maps driving: origin → каждый destination."""
        payload = {"kind": "google_miles", "origin": origin, "destinations": destinations}
        # Уже в потоке Chrome — не ставим в очередь (иначе deadlock при Bid.cars).
        if self._thread and threading.current_thread() is self._thread:
            self._ensure_browser()
            return self._google_miles_on_thread(str(origin or ""), dict(destinations or {}))
        return self._run_job(payload, timeout=120) or {}

    def _google_miles_on_thread(self, origin: str, destinations: dict[str, str]) -> dict[str, float]:
        from usa_distance import read_google_maps_driving_miles

        page = self._ensure_maps_tab()
        out: dict[str, float] = {}
        for key, dest in destinations.items():
            miles = read_google_maps_driving_miles(page, origin, dest)
            if miles is not None:
                out[key] = float(miles)
            else:
                log.warning("Google Maps: нет миль %s → %s", origin, dest)
        return out


    def fetch_bidcars_lot(self, url: str) -> dict:
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job({"kind": "bidcars_lot", "url": url}, timeout=240)
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def fetch_copart_us_lot(self, url: str) -> dict:
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job({"kind": "copart_us_lot", "url": url}, timeout=180)
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def fetch_iaai_lot(self, url: str) -> dict:
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job({"kind": "iaai_lot", "url": url}, timeout=240)
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def fetch_usa_lot(self, url: str) -> dict:
        """Роутер: Copart.com / IAAI.com / Bid.cars."""
        from usa_auction import detect_usa_source

        kind = detect_usa_source(url)
        if kind == "copart":
            return self.fetch_copart_us_lot(url)
        if kind == "iaai":
            return self.fetch_iaai_lot(url)
        if kind == "bidcars":
            return self.fetch_bidcars_lot(url)
        raise ValueError(
            "Нужна ссылка Copart.com, IAAI.com или Bid.cars на лот"
        )

    def check_ny_lien(self, *, vin: str, year: int | str, make: str) -> dict:
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job(
                {"kind": "ny_dmv_lien", "vin": vin, "year": year, "make": make},
                timeout=120,
            )
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def check_usa_sublot(
        self,
        *,
        auction_url: str | None = None,
        auction_platform: str | None = None,
        lot_id: str | None = None,
    ) -> dict:
        """Асинхронная проверка Copart Sublot / IAAI Offsite (+$100) после показа цены."""
        with self._lot_waiters_lock:
            self.lot_waiters += 1
        try:
            return self._run_job(
                {
                    "kind": "usa_sublot",
                    "auction_url": auction_url,
                    "auction_platform": auction_platform,
                    "lot_id": lot_id,
                },
                timeout=180,
            ) or {"is_sublot": False, "sublot_location": None}
        finally:
            with self._lot_waiters_lock:
                self.lot_waiters = max(0, self.lot_waiters - 1)

    def fetch_bidcars_search(self, searches: list[tuple[str, str]], page_limit: int) -> list[dict]:
        return self._run_job(
            {"kind": "bidcars_search", "searches": searches, "page_limit": page_limit},
            timeout=600,
        ) or []

    def _run_job(self, payload: dict, timeout: int):
        self.start()
        done = threading.Event()
        priority_by_kind = {
            "lot": 0,
            "bidcars_lot": 0,
            "copart_us_lot": 0,
            "iaai_lot": 0,
            "usa_sublot": 0,
            "ny_dmv_lien": 0,
            "image": 1,
            "google_miles": 2,
        }
        priority = priority_by_kind.get(payload.get("kind"), 10)
        job = {**payload, "done": done, "result": None, "error": None, "cancelled": False}
        self._queue.put((priority, self._next_job_seq(), job))
        if not done.wait(timeout=timeout):
            job["cancelled"] = True
            kind = payload.get("kind")
            if kind in {"bidcars_lot", "bidcars_search", "copart_us_lot", "iaai_lot", "usa_sublot", "ny_dmv_lien"}:
                raise CopartBlockedError(
                    "USA-лот слишком долго отвечает — подождите и нажмите ещё раз."
                )
            raise CopartBlockedError("Copart слишком долго отвечает")
        if job["error"]:
            raise job["error"]
        return job["result"]

    def stop(self) -> None:
        self._queue.put((-1, 0, None))
        if self._thread:
            self._thread.join(timeout=15)

    def _loop(self) -> None:
        self._thread_id = threading.get_ident()
        try:
            while True:
                try:
                    self._open_browser()
                    self._ensure_dedicated_tabs(park=True)
                    break
                except Exception as exc:
                    log.warning("Не удалось подключиться к Chrome (%s). Повтор через 8 с.", exc)
                    time.sleep(8)
            while True:
                try:
                    _, _, job = self._queue.get(timeout=20)
                except queue.Empty:
                    try:
                        self._keepalive_lot_tab()
                    except Exception as exc:
                        log.warning("Keepalive вкладки лотов: %s", exc)
                    continue
                if job is None:
                    break
                if job.get("cancelled"):
                    job["done"].set()
                    continue
                try:
                    job["result"] = self._run_browser_job(job)
                except Exception as exc:
                    if not job.get("cancelled"):
                        if _is_target_closed(exc):
                            log.warning("Связь с Chrome пропала — переподключаюсь к текущему окну")
                            try:
                                self._reconnect_to_chrome()
                                if not job.get("cancelled"):
                                    job["result"] = self._run_browser_job(job)
                            except Exception as retry_exc:
                                if not job.get("cancelled"):
                                    job["error"] = retry_exc
                        else:
                            job["error"] = exc
                else:
                    if not job.get("cancelled"):
                        try:
                            self._recycle_after_calc(job.get("kind"))
                        except Exception as recycle_exc:
                            log.warning("Обновление вкладок после расчёта: %s", recycle_exc)
                job["done"].set()
        finally:
            self._close_browser()

    def run_pending_lot_jobs(self) -> None:
        """Прерывает мониторинг ради калькулятора (Copart lot / Bid.cars)."""
        if self._in_lot_interrupt:
            return
        self._in_lot_interrupt = True
        try:
            while True:
                try:
                    priority, seq, job = self._queue.get_nowait()
                except queue.Empty:
                    break
                if job and job.get("cancelled"):
                    job["done"].set()
                    continue
                kind = (job or {}).get("kind")
                if not job or kind not in {"lot", "bidcars_lot", "copart_us_lot", "iaai_lot", "usa_sublot", "ny_dmv_lien"}:
                    self._queue.put((priority, seq, job))
                    break
                label = {
                    "bidcars_lot": "Bid.cars",
                    "copart_us_lot": "Copart USA",
                    "iaai_lot": "IAAI",
                    "usa_sublot": "Sublot/Offsite",
                    "ny_dmv_lien": "NY DMV залог",
                }.get(kind, "лот Copart")
                log.info("Пауза мониторинга — срочно открываю %s", label)
                try:
                    job["result"] = self._run_browser_job(job)
                except Exception as exc:
                    if job.get("cancelled"):
                        pass
                    elif _is_target_closed(exc):
                        log.warning("Связь с Chrome пропала — переподключаюсь к текущему окну")
                        try:
                            self._reconnect_to_chrome()
                            job["result"] = self._run_browser_job(job)
                        except Exception as retry_exc:
                            job["error"] = retry_exc
                    else:
                        job["error"] = exc
                finally:
                    if not job.get("cancelled"):
                        try:
                            self._recycle_after_calc(kind)
                        except Exception as recycle_exc:
                            log.warning("Обновление вкладок после расчёта: %s", recycle_exc)
                job["done"].set()
        finally:
            self._in_lot_interrupt = False

    def _run_browser_job(self, job: dict):
        kind = job.get("kind") or "search"
        if _is_calc_lot_kind(kind):
            # Mac/Windows: перед лотом убеждаемся, что Playwright видит окна (не только CDP).
            if os.name == "nt":
                self._ensure_chrome_responsive_or_revive()
            else:
                try:
                    self._ensure_context()
                except Exception:
                    log.warning("Контекст Chrome потерян — полный reconnect")
                    self._restart_browser()
                    self._ensure_dedicated_tabs(park=True)
        else:
            self._ensure_browser()
        helper = CopartScraper(job.get("searches") or [], max_pages=job.get("page_limit") or 0, headless=self.headless)
        if kind == "lot":
            lot_id = parse_lot_id(job["url"])
            if not lot_id:
                raise ValueError("Нужна ссылка на лот Copart")
            page = self._ensure_copart_tab(
                f"https://www.copart.co.uk/lot/{lot_id}",
                role="lot",
                focus=_lot_tab_focus(),
            )
            return helper.fetch_lot_details(page, job["url"], self._json_target, fast=True)
        if kind == "image":
            url = str(job.get("url") or "")
            if not _is_lot_image(url):
                raise ValueError("Некорректный URL фото Copart")
            page = self._ensure_copart_tab(HOME_URL, role="lot", focus=False)
            body = download_image_bytes(page, url, referer=COPART_IMAGE_REFERER, allow_page_fetch=False)
            return body
        if kind == "google_miles":
            return self._google_miles_on_thread(
                str(job.get("origin") or ""),
                dict(job.get("destinations") or {}),
            )
        if kind == "bidcars_lot":
            from bidcars import (
                extract_bidcars_lot,
                normalize_bidcars_url,
                parse_bidcars_lot_id,
                prefer_bidcars_cdn_images,
            )

            canonical = normalize_bidcars_url(job["url"])
            page = self._ensure_bidcars_tab(canonical)
            details = extract_bidcars_lot(page, canonical)
            lot_id = str(details.get("lot_id") or parse_bidcars_lot_id(canonical) or "0")
            # Берём CDN Bid.cars напрямую — без локального скачивания (оно часто обнуляло фото)
            cdn = prefer_bidcars_cdn_images(details.get("images") or [], limit=6)
            if cdn:
                details["images"] = cdn
                log.info("Bid.cars %s: CDN-фото %s шт.", lot_id, len(cdn))
            else:
                try:
                    details["images"] = materialize_usa_images(
                        page, lot_id, details.get("images") or [], limit=2
                    )
                except Exception as exc:
                    log.info("Bid.cars %s: фото пропущены (%s)", lot_id, exc)
                    details["images"] = []
            # Sublot/Offsite — не блокируем lookup; проверка отдельно после показа цены
            return details
        if kind == "copart_us_lot":
            from usa_auction import extract_copart_us_lot, normalize_copart_us_url, parse_copart_us_lot_id

            canonical = normalize_copart_us_url(job["url"])
            page = self._ensure_copart_us_tab(canonical, focus=_lot_tab_focus())
            details = extract_copart_us_lot(page, canonical)
            lot_id = str(details.get("lot_id") or parse_copart_us_lot_id(canonical) or "0")
            log.info(
                "Copart USA %s: %s, фото %s, title=%s",
                lot_id,
                details.get("title"),
                len(details.get("images") or []),
                details.get("documents"),
            )
            return details
        if kind == "iaai_lot":
            from usa_auction import extract_iaai_lot, normalize_iaai_url, parse_iaai_stock_id

            canonical = normalize_iaai_url(job["url"])
            page = self._ensure_iaai_tab(canonical, focus=_lot_tab_focus())
            details = extract_iaai_lot(page, canonical)
            lot_id = str(details.get("lot_id") or parse_iaai_stock_id(canonical) or "0")
            log.info(
                "IAAI %s: %s, фото %s, Title/Sale Doc=%s",
                lot_id,
                details.get("title"),
                len(details.get("images") or []),
                details.get("documents"),
            )
            return details
        if kind == "usa_sublot":
            return self._check_usa_sublot_job(
                auction_url=str(job.get("auction_url") or "") or None,
                auction_platform=str(job.get("auction_platform") or "") or None,
                lot_id=str(job.get("lot_id") or "") or None,
            )
        if kind == "ny_dmv_lien":
            from ny_dmv import check_title_status

            page = self._ensure_ny_dmv_tab()
            result = check_title_status(
                page,
                vin=str(job.get("vin") or ""),
                year=job.get("year") or "",
                make=str(job.get("make") or ""),
            )
            log.info(
                "NY DMV lien VIN=%s → %s",
                result.get("vin"),
                result.get("summary"),
            )
            return result
        if kind == "bidcars_search":
            from bidcars import extract_bidcars_search

            page = self._ensure_bidcars_tab("https://bid.cars/ru/search")
            page_limit = job.get("page_limit") or DEFAULT_PAGE_CAP
            lots_by_id: dict[str, dict] = {}
            searches = job.get("searches") or []
            for index, item in enumerate(searches):
                name, url = item[0], item[1]
                if index:
                    helper._human_pause(page, 2.0, 5.0)
                if _service:
                    _service.run_pending_lot_jobs()
                log.info("Bid.cars поиск «%s»", name)
                found = extract_bidcars_search(page, url, max_pages=page_limit)
                for lot in found:
                    names = lot.get("search_names") or []
                    if not isinstance(names, list):
                        names = [names] if names else []
                    if name not in names:
                        names.append(name)
                    lot["search_names"] = names
                    lot["source"] = "bidcars"
                    prev = lots_by_id.get(lot["lot_id"])
                    if prev:
                        merged_names = list(prev.get("search_names") or [])
                        for extra in names:
                            if extra not in merged_names:
                                merged_names.append(extra)
                        prev["search_names"] = merged_names
                    else:
                        lots_by_id[lot["lot_id"]] = lot
            return list(lots_by_id.values())
        if not self._monitor_warmed:
            page = self._ensure_copart_tab(HOME_URL, role="monitor")
            helper._warmup(page)
            self._monitor_warmed = True
        else:
            current = (self._monitor_page.url if self._monitor_page else "") or HOME_URL
            page = self._ensure_copart_tab(current, role="monitor")
        helper.page_limit = job.get("page_limit") or DEFAULT_PAGE_CAP
        lots, self._monitor_warmed = helper.collect(page, self._json_target, self._monitor_warmed)
        return lots

    def _ensure_chrome_responsive_or_revive(self) -> None:
        """После сбоя CDP: сначала reconnect к живому Chrome, процесс не гасим."""
        if _cdp_responsive(timeout=3.0) and self._browser_alive():
            # Быстрый пинг вкладки лотов
            if self._tab_alive(self._lot_page):
                try:
                    self._lot_page.evaluate("() => 1")
                    return
                except Exception:
                    log.warning("Вкладка лотов не отвечает — переподключаюсь к Chrome")
            else:
                try:
                    self._ensure_dedicated_tabs(park=True)
                    return
                except Exception:
                    pass
        if _cdp_responsive(timeout=3.0):
            log.info("CDP жив — переподключаюсь к вашему Chrome")
            try:
                self._reconnect_to_chrome()
                return
            except Exception as exc:
                log.warning("Reconnect не удался (%s)", exc)
                if not _chrome_allow_kill():
                    raise
        else:
            log.warning(
                "CDP не отвечает — %s",
                "жду/переподключаюсь без kill"
                if not _chrome_allow_kill()
                else "полный рестарт Chrome",
            )
        if _chrome_allow_kill():
            self._restart_chrome_fresh()
        else:
            self._reconnect_to_chrome()

    def _recycle_lot_tabs_only(self) -> None:
        """Закрыть вкладки лотов и открыть свежие — процесс Chrome и VPN не трогаем."""
        for attr in (
            "_lot_page",
            "_copart_us_page",
            "_iaai_page",
            "_bidcars_page",
            "_ny_dmv_page",
            "_maps_page",
        ):
            page = getattr(self, attr, None)
            if not page:
                continue
            try:
                if not page.is_closed():
                    page.close()
            except Exception:
                pass
            setattr(self, attr, None)
        self._ensure_dedicated_tabs(park=True)

    def _reconnect_to_chrome(self) -> None:
        """Сбросить Playwright-сессию и подключиться к уже открытому Chrome."""
        log.info("Переподключаюсь к текущему Chrome…")
        self._close_browser()
        _ensure_user_chrome()
        deadline = time.time() + 45
        while time.time() < deadline and not _cdp_responsive(timeout=1.5):
            time.sleep(0.3)
        self._open_browser()
        self._ensure_dedicated_tabs(park=True)
        log.info("Снова на связи с текущим Chrome")

    def _restart_chrome_fresh(self) -> None:
        """Полный подъём Chrome заново (только при CHROME_ALLOW_KILL=1)."""
        if not _chrome_allow_kill() and not _chrome_headless_cdp():
            self._reconnect_to_chrome()
            return
        log.info("Поднимаю Chrome заново…")
        self._close_browser()
        if _chrome_headless_cdp():
            _kill_listeners_on_port(_cdp_port())
            time.sleep(1.0)
        else:
            _quit_chrome()
            time.sleep(1.2)
            try:
                for data_dir in (_preferred_chrome_user_data(), _bot_chrome_user_data()):
                    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                        path = data_dir / name
                        try:
                            if path.exists():
                                path.unlink()
                        except OSError:
                            pass
            except Exception:
                pass
        _ensure_user_chrome()
        # ждём порт
        deadline = time.time() + 45
        while time.time() < deadline and not _port_open(_cdp_port()):
            time.sleep(0.3)
        self._open_browser()
        self._ensure_dedicated_tabs(park=True)
        log.info("Chrome снова готов к расчёту")

    def _recycle_after_calc(self, kind: str | None) -> None:
        if not _is_calc_lot_kind(kind):
            return
        mode = _calc_recycle_mode()
        if mode == "off":
            return
        if mode == "tab":
            log.info("После расчёта обновляю вкладку лотов")
            self._recycle_lot_tabs_only()
            return
        # chrome / full — без CHROME_ALLOW_KILL только reconnect
        if _chrome_allow_kill() or _chrome_headless_cdp():
            self._restart_chrome_fresh()
        else:
            log.info("После расчёта переподключаюсь к Chrome (без kill)")
            self._reconnect_to_chrome()

    def _tab_alive(self, page: Any) -> bool:
        if not page:
            return False
        try:
            _ = page.url
            # Страница могла «умереть» после crash/закрытия вкладки
            if page.is_closed():
                return False
            return True
        except Exception:
            return False

    def _mark_lot_tab(self, page: Any) -> None:
        try:
            page.evaluate("() => { try { document.title = 'MG · лоты (не закрывать)'; } catch (e) {} }")
        except Exception:
            pass

    def _ensure_context(self) -> Any:
        """Контекст CDP: при пустом списке окон — reconnect (Chrome часто ещё жив)."""
        for attempt in range(2):
            self._ensure_browser()
            try:
                contexts = list(self._browser.contexts) if self._browser else []
            except Exception:
                contexts = []
            if contexts:
                self._context = contexts[0]
                return self._context
            if attempt == 0:
                log.warning("Playwright не видит окна Chrome — переподключаюсь по CDP")
                self._restart_browser()
        raise RuntimeError("В Chrome нет окон — оставьте браузер открытым")

    def _ensure_dedicated_tabs(self, *, park: bool = False) -> None:
        """Отдельные вкладки мониторинг + лоты — живут постоянно, остальные вкладки не трогаем."""
        self._ensure_context()

        if not self._tab_alive(self._lot_page):
            page = self._context.new_page()
            self._lot_page = page
            self._attach_json_capture(page)
            log.info("Создал постоянную вкладку Copart: подтягивание лотов")
            if park:
                try:
                    CopartScraper([], headless=self.headless)._safe_goto(page, HOME_URL)
                    self._mark_lot_tab(page)
                    log.info("Вкладка лотов прогрета на %s (VPN/сессия)", HOME_URL)
                except Exception as exc:
                    log.warning("Не удалось прогреть вкладку лотов: %s", exc)

        if not self._tab_alive(self._monitor_page):
            page = self._context.new_page()
            self._monitor_page = page
            self._attach_json_capture(page)
            log.info("Создал постоянную вкладку Copart: мониторинг авто")
            if park:
                try:
                    CopartScraper([], headless=self.headless)._safe_goto(page, HOME_URL)
                    page.evaluate(
                        "() => { try { document.title = 'MG · мониторинг'; } catch (e) {} }"
                    )
                except Exception as exc:
                    log.warning("Не удалось прогреть вкладку мониторинга: %s", exc)

    def _keepalive_lot_tab(self) -> None:
        """Пока очередь пуста — держим вкладку лотов живой (без убийства Chrome)."""
        if not self._browser_alive():
            log.info("Keepalive: Chrome отвалился — подключаюсь снова")
            self._restart_browser()
            self._ensure_dedicated_tabs(park=True)
            return
        if not self._tab_alive(self._lot_page):
            log.info("Keepalive: вкладка лотов закрыта — открываю снова")
            self._ensure_dedicated_tabs(park=True)
            return
        try:
            self._lot_page.evaluate("() => 1")
            self._mark_lot_tab(self._lot_page)
        except Exception:
            log.info("Keepalive: вкладка лотов зависла — пересоздаю")
            self._lot_page = None
            self._ensure_dedicated_tabs(park=True)

    def _attach_json_capture(self, page: Any) -> None:
        page_id = id(page)
        if page_id in self._json_hook_pages:
            return
        helper = CopartScraper([], headless=self.headless)
        page.on(
            "response",
            lambda resp: helper._capture_json(resp, self._json_target),
        )
        self._json_hook_pages.add(page_id)

    def _ensure_copart_tab(self, url: str, *, role: str, focus: bool | None = None) -> Any:
        if role not in {"monitor", "lot"}:
            raise ValueError(f"Unknown tab role: {role}")
        if focus is None:
            focus = _lot_tab_focus()
        self._ensure_dedicated_tabs(park=False)
        attr = "_monitor_page" if role == "monitor" else "_lot_page"
        page = getattr(self, attr)
        if not self._tab_alive(page):
            # _ensure_dedicated_tabs уже должен был создать; на всякий случай ещё раз
            self._ensure_dedicated_tabs(park=role == "lot")
            page = getattr(self, attr)
        if not self._tab_alive(page):
            raise RuntimeError("Не удалось открыть вкладку Copart для лотов")
        if focus:
            _focus_page(page)
        target = url.strip()
        current = (page.url or "").strip()
        target_lot = parse_lot_id(target)
        current_lot = parse_lot_id(current)
        if role == "lot" and target_lot and target_lot == current_lot:
            if focus:
                _focus_page(page)
            self._mark_lot_tab(page)
            return page
        if current.rstrip("/").lower() != target.rstrip("/").lower():
            log.info("Открываю в Chrome (%s): %s", role, target)
            CopartScraper([], headless=self.headless)._safe_goto(page, target)
            if role == "lot":
                self._mark_lot_tab(page)
            if focus:
                _focus_page(page)
        return page

    def _check_usa_sublot_job(
        self,
        *,
        auction_url: str | None = None,
        auction_platform: str | None = None,
        lot_id: str | None = None,
    ) -> dict:
        """Открыть Copart/IAAI по ссылке с Bid.cars и проверить Sublot/Offsite."""
        from usa_auction import normalize_copart_us_url, normalize_iaai_url

        lot_id = str(lot_id or "").strip()
        bare = lot_id.split("-")[-1] if lot_id else ""
        aurl = str(auction_url or "").strip()
        platform = str(auction_platform or "").strip().lower()
        if platform not in {"copart", "iaai"}:
            if "copart.com" in aurl.lower():
                platform = "copart"
            elif "iaai.com" in aurl.lower():
                platform = "iaai"
            elif lot_id.startswith("0-") or lot_id.startswith("1-"):
                platform = "iaai"
            else:
                platform = "copart"

        # Search?Keyword=45446905 → VehicleDetail/45446905~US
        if platform == "iaai" and aurl:
            import re

            m = re.search(r"[?&]Keyword=(\d+)", aurl, re.I)
            if m:
                aurl = normalize_iaai_url(f"https://www.iaai.com/VehicleDetail/{m.group(1)}~US")
            else:
                aurl = normalize_iaai_url(aurl)
        elif platform == "copart" and aurl:
            aurl = normalize_copart_us_url(aurl)
        elif platform == "copart" and bare.isdigit():
            aurl = normalize_copart_us_url(f"https://www.copart.com/lot/{bare}")
        elif platform == "iaai" and bare.isdigit():
            aurl = normalize_iaai_url(f"https://www.iaai.com/VehicleDetail/{bare}~US")
        else:
            return {
                "is_sublot": False,
                "sublot_location": None,
                "auction_platform": platform,
                "auction_url": aurl or None,
                "checked": False,
                "error": "нет ссылки на аукцион",
            }

        auction: dict | None = None
        if platform == "copart":
            page = self._ensure_copart_us_tab(aurl, focus=False)
            from usa_auction import extract_copart_us_lot

            auction = extract_copart_us_lot(page, aurl)
        else:
            page = self._ensure_iaai_tab(aurl, focus=False)
            from usa_auction import extract_iaai_lot

            auction = extract_iaai_lot(page, aurl)

        if not auction:
            return {
                "is_sublot": False,
                "sublot_location": None,
                "auction_platform": platform,
                "auction_url": aurl,
                "checked": False,
                "error": "не удалось прочитать лот",
            }
        is_sublot = bool(auction.get("is_sublot"))
        loc = auction.get("sublot_location")
        log.info(
            "Sublot check %s → %s: %s %s",
            lot_id or bare,
            platform,
            "Sublot/Offsite" if is_sublot else "нет",
            loc or "",
        )
        return {
            "is_sublot": is_sublot,
            "sublot_location": loc,
            "auction_platform": platform,
            "auction_url": auction.get("url") or aurl,
            "checked": True,
            "documents": auction.get("documents"),
            "title_code": auction.get("title_code"),
            "engine": auction.get("engine"),
            "fuel": auction.get("fuel"),
            "year": auction.get("year"),
            "location": auction.get("location"),
        }

    def _enrich_bidcars_sublot(self, details: dict) -> dict:
        """С Bid.cars открываем Copart/IAAI и смотрим Sublot / Offsite (+$100)."""
        result = self._check_usa_sublot_job(
            auction_url=str(details.get("auction_url") or "") or None,
            auction_platform=str(details.get("auction_platform") or "") or None,
            lot_id=str(details.get("lot_id") or "") or None,
        )
        if result.get("auction_platform"):
            details["auction_platform"] = result["auction_platform"]
        if result.get("auction_url"):
            details["auction_url"] = result["auction_url"]
        details["is_sublot"] = bool(result.get("is_sublot"))
        details["sublot_location"] = result.get("sublot_location")
        for key in ("documents", "title_code", "engine", "fuel", "year", "location"):
            if not details.get(key) and result.get(key):
                details[key] = result[key]
        return details

    def _ensure_bidcars_tab(self, url: str) -> Any:
        page = self._bidcars_page
        if not self._tab_alive(page):
            self._ensure_context()
            page = self._context.new_page()
            self._bidcars_page = page
            log.info("Создал вкладку Bid.cars")
        try:
            page.bring_to_front()
        except Exception:
            pass
        # Сам переход делает extract_bidcars_lot: полный document load, не SPA.
        return page

    def _ensure_copart_us_tab(self, url: str, *, focus: bool | None = None) -> Any:
        """Отдельная вкладка Copart.com — как lot-вкладка в калькуляторе."""
        if focus is None:
            focus = _lot_tab_focus()
        page = self._copart_us_page
        if not self._tab_alive(page):
            self._ensure_context()
            page = self._context.new_page()
            self._copart_us_page = page
            log.info("Создал вкладку Copart USA")
        if focus:
            _focus_page(page)
        target = (url or "").strip()
        if not target:
            return page
        current = (page.url or "").strip()
        from usa_auction import parse_copart_us_lot_id

        target_lot = parse_copart_us_lot_id(target)
        current_lot = parse_copart_us_lot_id(current)
        if target_lot and target_lot == current_lot and "/lot/" in current.lower():
            if focus:
                _focus_page(page)
            return page
        if current.rstrip("/").lower() != target.rstrip("/").lower():
            log.info("Открываю в Chrome (copart_us): %s", target)
            CopartScraper([], headless=self.headless)._safe_goto(page, target)
            if focus:
                _focus_page(page)
        return page

    def _ensure_iaai_tab(self, url: str, *, focus: bool | None = None) -> Any:
        """Отдельная вкладка IAAI.com — как lot-вкладка в калькуляторе."""
        if focus is None:
            focus = _lot_tab_focus()
        page = self._iaai_page
        if not self._tab_alive(page):
            self._ensure_context()
            page = self._context.new_page()
            self._iaai_page = page
            log.info("Создал вкладку IAAI")
        if focus:
            try:
                page.bring_to_front()
            except Exception:
                pass
        target = (url or "").strip()
        if not target:
            return page
        current = (page.url or "").strip()
        from usa_auction import parse_iaai_stock_id

        target_id = parse_iaai_stock_id(target)
        current_id = parse_iaai_stock_id(current)
        if target_id and target_id == current_id and "vehicledetail" in current.lower():
            return page
        if current.rstrip("/").lower() != target.rstrip("/").lower():
            log.info("Открываю в Chrome (iaai): %s", target)
            CopartScraper([], headless=self.headless)._safe_goto(page, target)
        return page

    def _ensure_maps_tab(self) -> Any:
        page = self._maps_page
        if not self._tab_alive(page):
            self._ensure_context()
            page = self._context.new_page()
            self._maps_page = page
            log.info("Создал вкладку Google Maps")
        return page

    def _copart_pages_alive(self) -> bool:
        return self._tab_alive(self._monitor_page) or self._tab_alive(self._lot_page)

    def _browser_alive(self) -> bool:
        if not self._browser:
            return False
        try:
            # Пустой contexts при живом CDP — типичный desync Playwright; считаем мёртвым.
            return bool(list(self._browser.contexts))
        except Exception:
            return False

    def _pick_page(self) -> None:
        for _ in range(15):
            try:
                if self._browser and list(self._browser.contexts):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        contexts = list(self._browser.contexts) if self._browser else []
        if not contexts:
            raise RuntimeError("В Chrome нет окон — оставьте браузер открытым")
        self._context = contexts[0]
        log.info("Подключился к Chrome — держу отдельные вкладки: мониторинг и лоты")

    def _ensure_browser(self) -> None:
        if self._browser_alive():
            return
        log.info("Chrome не отвечает — подключаюсь к вашему окну снова")
        self._restart_browser()

    def _restart_browser(self) -> None:
        self._close_browser()
        time.sleep(1.0)
        self._open_browser()

    def _attach(self, endpoints: list[str]) -> None:
        last_error = None
        for index, url in enumerate(endpoints):
            timeout = 90_000 if index == 0 else 20_000
            try:
                log.info("Подключаюсь к уже открытому Chrome")
                self._browser = self._pw.chromium.connect_over_cdp(
                    url,
                    timeout=timeout,
                    no_defaults=True,
                )
                self._pick_page()
                self._monitor_warmed = False
                self._ensure_dedicated_tabs(park=True)
                log.info("Вкладки Copart готовы (мониторинг + лоты) — другие вкладки не трогаю.")
                return
            except Exception as exc:
                last_error = exc
                self._browser = None
                self._context = None
                self._monitor_page = None
                self._lot_page = None
                self._bidcars_page = None
                self._copart_us_page = None
                self._iaai_page = None
                self._maps_page = None
                self._json_hook_pages.clear()
        raise last_error or RuntimeError("Не удалось подключиться к Chrome")

    def _open_browser(self) -> None:
        self._close_browser()
        prompted = False
        last_error = None
        deadline = time.time() + 240
        cdp_port = _cdp_port()
        while time.time() < deadline:
            if not _cdp_responsive(cdp_port, timeout=2.0):
                try:
                    _ensure_user_chrome()
                except Exception as exc:
                    last_error = exc
                    log.warning("Не удалось запустить Chrome: %s", exc)
            endpoints = _cdp_endpoints()
            if endpoints:
                self._pw = sync_playwright().start()
                try:
                    self._attach(endpoints)
                    return
                except Exception as exc:
                    last_error = exc
                    self._close_browser()
                    if _chrome_allow_kill() or _chrome_headless_cdp():
                        log.warning("Chrome не пустил к окну (%s). Поднимаю снова.", exc)
                        if _chrome_headless_cdp():
                            _kill_listeners_on_port(cdp_port)
                        else:
                            _quit_chrome()
                        time.sleep(2)
                    else:
                        log.warning(
                            "Chrome не пустил к окну (%s). Жду и пробую снова без kill.",
                            exc,
                        )
                        time.sleep(2)
                    continue
            if not prompted:
                if not _chrome_headless_cdp():
                    _open_inspect_page()
                log.warning(
                    "Chrome remote debugging выключен (порт %s закрыт). "
                    "Откройте %s → Allow remote debugging, затем повторите.",
                    cdp_port,
                    INSPECT_URL,
                )
                prompted = True
            time.sleep(2)
        raise last_error or RuntimeError(
            f"Chrome remote debugging выключен. Откройте {INSPECT_URL}, включите отладку (Allow) и повторите."
        )

    def _close_browser(self) -> None:
        self._monitor_page = None
        self._lot_page = None
        self._bidcars_page = None
        self._copart_us_page = None
        self._iaai_page = None
        self._maps_page = None
        self._context = None
        self._browser = None
        self._json_hook_pages.clear()
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = None
        self._monitor_warmed = False


_service: ScrapeService | None = None
_service_lock = threading.Lock()


def get_scrape_service(headless: bool) -> ScrapeService:
    global _service
    with _service_lock:
        if _service is None:
            _service = ScrapeService(headless=headless)
            _service.start()
        return _service


def stop_scrape_service() -> None:
    global _service
    with _service_lock:
        if _service is not None:
            _service.stop()
            _service = None
