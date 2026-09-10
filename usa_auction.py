"""Прямой парсинг лотов USA: Copart.com и IAAI.com (не Bid.cars)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from usa_distance import resolve_us_inland

log = logging.getLogger("copart")

VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b", re.I)


def detect_usa_source(url: str) -> str | None:
    host = (urlparse(str(url or "").strip()).netloc or "").lower()
    if "copart.com" in host and "copart.co.uk" not in host:
        return "copart"
    if "iaai.com" in host:
        return "iaai"
    if "bid.cars" in host:
        return "bidcars"
    return None


def parse_copart_us_lot_id(url: str) -> str | None:
    text = str(url or "").strip()
    m = re.search(r"copart\.com/lot/(\d{5,12})", text, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{5,12}", text):
        return text
    return None


def parse_iaai_stock_id(url: str) -> str | None:
    text = str(url or "").strip()
    m = re.search(r"iaai\.com/vehicledetail/(\d{5,12})", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r"[?&]itemid=(\d{5,12})", text, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{5,12}", text):
        return text
    return None


def normalize_copart_us_url(url: str) -> str:
    lot_id = parse_copart_us_lot_id(url)
    if not lot_id:
        raise ValueError(
            "Нужна ссылка Copart USA, например https://www.copart.com/lot/78843645/..."
        )
    return f"https://www.copart.com/lot/{lot_id}"


def normalize_iaai_url(url: str) -> str:
    stock = parse_iaai_stock_id(url)
    if not stock:
        raise ValueError(
            "Нужна ссылка IAAI, например https://www.iaai.com/vehicledetail/45945014~US"
        )
    return f"https://www.iaai.com/VehicleDetail/{stock}~US"


def _clean(value: Any, *, max_len: int = 120) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or text in {"-", "—", "N/A", "n/a"}:
        return None
    return text[:max_len]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("$", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def _title_case_words(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    return " ".join(part.capitalize() if part.isupper() or part.islower() else part for part in text.split())


def format_copart_title_code(ld: dict) -> str | None:
    """Как на сайте: 'TX - Certificate Of Title - Clean Title'."""
    state = _clean(ld.get("ts") or ld.get("titleState"), max_len=8)
    title_desc = _title_case_words(ld.get("td") or ld.get("titleDesc"))
    group = _title_case_words(ld.get("tgd") or ld.get("titleGroupDesc"))
    parts = [p for p in (state, title_desc, group) if p]
    if parts:
        return " - ".join(parts)
    return _clean(ld.get("stt") or ld.get("titleType"))


def format_copart_sublot(ld: dict) -> tuple[bool, str | None]:
    """Copart Sublot: slfg / subLotFacilityId / sla+slc… → (is_sublot, address)."""
    flag = ld.get("slfg")
    facility = ld.get("subLotFacilityId")
    has_flag = flag is True or str(flag).lower() in {"true", "1", "yes"}
    has_facility = facility not in (None, "", 0, "0")
    name = _clean(ld.get("sln"), max_len=80)
    street = _clean(ld.get("sla"), max_len=80)
    city = _clean(ld.get("slc"), max_len=40)
    state = _clean(ld.get("sls"), max_len=8)
    zipc = _clean(ld.get("slpc"), max_len=20)
    parts = [p for p in (street, city, state, zipc) if p]
    addr = ", ".join(parts) if parts else None
    if name and addr:
        addr = f"{name}: {addr}"
    elif name:
        addr = name
    is_sublot = bool(has_flag or has_facility or street or (name and "sublot" in name.lower()))
    if not is_sublot:
        return False, None
    return True, addr


def format_iaai_offsite(raw: dict) -> tuple[bool, str | None]:
    """IAAI Offsite = аналог Copart Sublot (+$100)."""
    loc = _clean(raw.get("vehicle_location") or raw.get("offsite_label"), max_len=40) or ""
    addr = _clean(raw.get("offsite_address") or raw.get("sublot_location"), max_len=160)
    low = loc.lower()
    is_offsite = "offsite" in low or "off-site" in low
    if not is_offsite:
        yard = _clean(raw.get("location"), max_len=80) or ""
        if yard.lower() == "offsite":
            is_offsite = True
    if not is_offsite:
        return False, None
    if addr:
        return True, addr if "offsite" in addr.lower() else f"Offsite: {addr}"
    return True, loc or "Offsite"


def prefer_copart_cdn_images(urls: list | None, *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        src = str(raw or "").strip()
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("https://"):
            continue
        src = src.replace("_thb.", "_ful.").replace("_ths.", "_ful.")
        low = src.lower()
        if not re.search(r"cs\.copart\.com|c-static\.copart\.com|copart\.com/.+\.(?:jpe?g|webp|png)", low):
            continue
        if any(x in low for x in ("logo", "icon", "sprite", "avatar", "favicon")):
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append(src)
        if len(out) >= limit:
            break
    return out


def prefer_iaai_cdn_images(urls: list | None, *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        src = str(raw or "").strip()
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("https://"):
            continue
        low = src.lower()
        if not re.search(r"vis\.iaai\.com|iaai\.com|cloudfront|amazonaws|lotimages|\.(?:jpe?g|webp|png)", low):
            continue
        if any(x in low for x in ("logo", "icon", "sprite", "avatar", "favicon", "hcaptcha")):
            continue
        if src in seen:
            continue
        seen.add(src)
        out.append(src)
        if len(out) >= limit:
            break
    return out


def _with_inland(details: dict) -> dict:
    location = details.get("location")
    route = resolve_us_inland(location, None, allow_chrome_maps=False)
    details["inland_usd"] = route.get("inland_usd")
    details["inland_miles"] = route.get("inland_miles")
    details["us_port"] = route.get("us_port")
    details["us_port_label"] = route.get("us_port_label")
    details["miles_to_new_jersey"] = route.get("miles_to_new_jersey")
    details["miles_to_houston"] = route.get("miles_to_houston")
    details["distance_source"] = route.get("distance_source")
    details["inland_route"] = route
    details["ocean_usd_by_port"] = {}
    return details


def normalize_copart_us_details(ld: dict, *, url: str, images: list[str] | None = None) -> dict:
    lot_id = str(ld.get("lotNumberStr") or ld.get("ln") or parse_copart_us_lot_id(url) or "").strip()
    year = ld.get("lcy")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    make = _clean(ld.get("mkn"), max_len=40)
    model = _clean(ld.get("lm") or ld.get("lmg"), max_len=60)
    title = _clean(ld.get("ld"), max_len=160) or " ".join(
        str(p) for p in (year, make, model) if p
    )
    dyn = ld.get("dynamicLotDetails") if isinstance(ld.get("dynamicLotDetails"), dict) else {}
    bid = _num(dyn.get("currentBid"))
    if bid is None or bid <= 0:
        bid = _num(ld.get("hb") or ld.get("cu"))
    title_code = format_copart_title_code(ld)
    location = _clean(ld.get("yn") or ld.get("loc"), max_len=80)
    is_sublot, sublot_location = format_copart_sublot(ld)
    details = {
        "source": "copart_us",
        "auction_platform": "copart",
        "lot_id": lot_id,
        "title": title or f"Lot {lot_id}",
        "year": year,
        "make": make,
        "model": model,
        "vin": _clean(ld.get("fv"), max_len=20),
        "url": url,
        "location": location,
        "ship_from": location,
        "seller": _clean(ld.get("scn") or ld.get("sord"), max_len=80),
        "documents": title_code,
        "title_code": title_code,
        "sale_date": None,
        "odometer": _num(ld.get("orr")),
        "primary_damage": _clean(ld.get("dd"), max_len=60),
        "secondary_damage": _clean(ld.get("sdd"), max_len=60),
        "keys": _clean(ld.get("hk") or ld.get("syn"), max_len=40),
        "body_style": _clean(ld.get("bstl") or ld.get("vehTypeDescription"), max_len=40),
        "color": _clean(ld.get("clr"), max_len=40),
        "engine": _clean(ld.get("egn"), max_len=60),
        "transmission": _clean(ld.get("tmtp") or ld.get("tr"), max_len=40),
        "drive": _clean(ld.get("drv") or ld.get("drive"), max_len=40),
        "fuel": _clean(ld.get("ft") or ld.get("fuel"), max_len=40),
        "estimated_value": _clean(ld.get("lotPlugAcv") or ld.get("la"), max_len=40),
        "bid": bid,
        "images": prefer_copart_cdn_images(images or [], limit=8),
        "bidcars_fee_usd": 0,
        "is_sublot": is_sublot,
        "sublot_location": sublot_location,
    }
    ad = ld.get("ad")
    if isinstance(ad, (int, float)) and ad > 0:
        try:
            from datetime import datetime, timezone

            details["sale_date"] = datetime.fromtimestamp(ad / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except Exception:
            pass
    return _with_inland(details)


def extract_copart_us_lot(page: Any, url: str) -> dict:
    canonical = normalize_copart_us_url(url)
    lot_id = parse_copart_us_lot_id(canonical) or ""
    log.info("Copart USA: читаю лот %s", lot_id)
    # Вкладку уже открыл scraper._ensure_copart_us_tab (как калькулятор).
    # Если всё же не на лоте — догружаем.
    try:
        current = (page.url or "").lower()
        if f"/lot/{lot_id}" not in current:
            page.goto(canonical, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        log.warning("Copart USA goto: %s", exc)
    try:
        page.wait_for_selector("h1, [class*='lot-details'], [data-uname*='lot']", timeout=20_000)
    except Exception:
        pass
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass

    payload = page.evaluate(
        """async (lotId) => {
          const out = {lot: null, images: [], error: null};
          try {
            const r = await fetch('https://www.copart.com/public/data/lotdetails/solr/' + lotId, {
              credentials: 'include',
              headers: { 'Accept': 'application/json' },
            });
            out.lot = await r.json();
          } catch (e) {
            out.error = String(e);
          }
          try {
            const r2 = await fetch('https://www.copart.com/public/data/lotdetails/solr/lotImages/' + lotId, {
              credentials: 'include',
              headers: { 'Accept': 'application/json' },
            });
            const j = await r2.json();
            const list = (((j || {}).data || {}).imagesList || {});
            const content = Array.isArray(list.content) ? list.content
              : Array.isArray(list.IMAGE) ? list.IMAGE
              : [];
            out.images = content.map(x => x.highResUrl || x.fullUrl || x.thumbnailUrl).filter(Boolean);
          } catch (e) {}
          return out;
        }""",
        lot_id,
    )
    if not payload or not payload.get("lot"):
        raise RuntimeError(payload.get("error") if payload else "Нет ответа lotdetails Copart")
    root = payload["lot"]
    if int(root.get("returnCode") or 0) != 1:
        raise RuntimeError(root.get("returnCodeDesc") or "Copart lotdetails error")
    ld = ((root.get("data") or {}).get("lotDetails")) or {}
    if not ld:
        raise RuntimeError("Copart: пустой lotDetails")
    details = normalize_copart_us_details(ld, url=canonical, images=list(payload.get("images") or []))
    if not details.get("images"):
        # fallback: DOM img CDN
        try:
            dom_imgs = page.evaluate(
                """() => [...document.querySelectorAll('img')]
                  .map(i => i.currentSrc || i.src)
                  .filter(u => /cs\\.copart\\.com|c-static\\.copart\\.com/i.test(u || ''))"""
            )
            details["images"] = prefer_copart_cdn_images(dom_imgs, limit=8)
        except Exception:
            pass
    return details


IAAI_DOM_SCRIPT = r"""() => {
  const text = (document.body && document.body.innerText) || '';
  const good = (v) => {
    const s = String(v || '').replace(/\s+/g, ' ').trim();
    return s && s !== '-' ? s : '';
  };
  const labelValue = (names) => {
    const want = names.map(n => n.toLowerCase());
    const nodes = [...document.querySelectorAll('div, span, dt, dd, th, td, li, p, label')];
    for (const el of nodes) {
      const raw = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (!raw || raw.length > 80) continue;
      const low = raw.toLowerCase().replace(/:$/, '');
      if (!want.some(w => low === w || low.startsWith(w + ' ') || low === w + ':')) continue;
      let val = '';
      const next = el.nextElementSibling;
      if (next) val = good(next.textContent);
      if (!val && el.parentElement) {
        const kids = [...el.parentElement.children];
        const idx = kids.indexOf(el);
        if (idx >= 0 && kids[idx + 1]) val = good(kids[idx + 1].textContent);
      }
      if (!val) {
        const m = raw.match(/:\s*(.+)$/);
        if (m) val = good(m[1]);
      }
      if (val && val.toLowerCase() !== low) return val;
    }
    // line-based fallback
    const lines = text.split(/\n+/).map(s => s.trim()).filter(Boolean);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      for (const name of names) {
        const re = new RegExp('^' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*:?\\s*(.*)$', 'i');
        const m = line.match(re);
        if (m) {
          if (m[1] && m[1].trim()) return m[1].trim();
          if (lines[i + 1]) return lines[i + 1];
        }
      }
    }
    return '';
  };
  const imgs = [];
  const push = (u) => {
    if (!u) return;
    let s = String(u).trim();
    if (s.startsWith('//')) s = 'https:' + s;
    if (!/^https?:/i.test(s)) return;
    if (!/vis\.iaai\.com|iaai\.com|cloudfront|amazonaws|lotimages|\.(jpe?g|webp|png)/i.test(s)) return;
    if (/logo|icon|sprite|avatar|favicon|hcaptcha/i.test(s)) return;
    if (!imgs.includes(s)) imgs.push(s);
  };
  document.querySelectorAll('img').forEach(img => {
    push(img.currentSrc || img.src);
    ['data-src', 'data-lazy', 'data-original'].forEach(a => push(img.getAttribute(a)));
  });
  const html = document.documentElement ? document.documentElement.innerHTML : '';
  const mImgs = html.match(/https?:\/\/[^"'\\\s>]+(?:vis\.iaai\.com|cloudfront)[^"'\\\s>]+\.(?:jpe?g|webp|png)/gi) || [];
  mImgs.forEach(push);

  const challenge = !!(document.querySelector('#main-iframe, #px-captcha, iframe[src*="hcaptcha"], iframe[src*="Incapsula"]'))
    || /Incapsula|hcaptcha/i.test(html.slice(0, 2000));

  return {
    challenge,
    h1: good((document.querySelector('h1') || {}).innerText),
    title: good((document.querySelector('h1') || {}).innerText),
    stock: labelValue(['Stock #', 'Stock#', 'Stock No', 'Stock Number']),
    vin: labelValue(['VIN', 'VIN #']),
    location: labelValue(['Yard Location', 'Branch', 'Location', 'Selling Branch']),
    documents: labelValue(['Title/Sale Doc', 'Title / Sale Doc', 'Sale Doc', 'Title Code', 'Title Type']),
    odometer: labelValue(['Odometer', 'Odometer Reading']),
    primary_damage: labelValue(['Primary Damage', 'Damage']),
    secondary_damage: labelValue(['Secondary Damage']),
    keys: labelValue(['Keys', 'Key']),
    body_style: labelValue(['Body Style', 'Vehicle Type']),
    color: labelValue(['Exterior Color', 'Color']),
    engine: labelValue(['Engine']),
    transmission: labelValue(['Transmission']),
    drive: labelValue(['Drive Line Type', 'Drive', 'Drivetrain']),
    fuel: labelValue(['Fuel Type', 'Fuel']),
    sale_date: labelValue(['Auction Date', 'Sale Date', 'Live Auction']),
    bid: labelValue(['Current Bid', 'High Bid', 'Starting Bid']),
    seller: labelValue(['Seller', 'Seller Name']),
    vehicle_location: labelValue(['Vehicle Location']),
    images: imgs.slice(0, 12),
    page_snip: text.slice(0, 8000),
  };
}"""


def normalize_iaai_details(raw: dict, *, url: str) -> dict:
    stock = _clean(raw.get("stock") or parse_iaai_stock_id(url), max_len=20) or ""
    title = _clean(raw.get("title") or raw.get("h1"), max_len=160)
    year = None
    make = None
    model = None
    if title:
        m = re.match(r"((?:19|20)\d{2})\s+([A-Za-z0-9\-]+)\s+(.+)", title)
        if m:
            year = int(m.group(1))
            make = m.group(2)
            model = m.group(3).strip()
    documents = _clean(raw.get("documents"), max_len=120)
    bid = _num(raw.get("bid"))
    # Offsite address: после "Offsite" на странице идут branch + street + city
    offsite_addr = _clean(raw.get("offsite_address"), max_len=160)
    if not offsite_addr:
        snip = str(raw.get("page_snip") or "")
        m = re.search(
            r"Vehicle Location:\s*\n?\s*Offsite\s*\n([^\n]+)\n([^\n]+)\n([^\n]+)",
            snip,
            re.I,
        )
        if m:
            offsite_addr = _clean(", ".join(p.strip() for p in m.groups() if p.strip()), max_len=160)
        else:
            m2 = re.search(r"\bOffsite\s*\n([^\n]{5,80})\n([^\n]{5,80})\n([^\n]{5,80})", snip, re.I)
            if m2:
                offsite_addr = _clean(", ".join(p.strip() for p in m2.groups() if p.strip()), max_len=160)
    raw_off = {
        **raw,
        "offsite_address": offsite_addr,
        "vehicle_location": raw.get("vehicle_location"),
    }
    is_sublot, sublot_location = format_iaai_offsite(raw_off)
    yard = _clean(raw.get("location"), max_len=80)
    if yard and yard.lower() == "offsite":
        yard = _clean(raw.get("branch") or yard, max_len=80)
    details = {
        "source": "iaai",
        "auction_platform": "iaai",
        "lot_id": stock,
        "title": title or f"IAAI {stock}",
        "year": year,
        "make": make,
        "model": model,
        "vin": _clean(raw.get("vin"), max_len=20),
        "url": url,
        "location": yard,
        "ship_from": yard,
        "seller": _clean(raw.get("seller"), max_len=80),
        "documents": documents,
        "title_code": documents,
        "sale_date": _clean(raw.get("sale_date"), max_len=80),
        "odometer": _num(raw.get("odometer")),
        "primary_damage": _clean(raw.get("primary_damage"), max_len=60),
        "secondary_damage": _clean(raw.get("secondary_damage"), max_len=60),
        "keys": _clean(raw.get("keys"), max_len=40),
        "body_style": _clean(raw.get("body_style"), max_len=40),
        "color": _clean(raw.get("color"), max_len=40),
        "engine": _clean(raw.get("engine"), max_len=60),
        "transmission": _clean(raw.get("transmission"), max_len=40),
        "drive": _clean(raw.get("drive"), max_len=40),
        "fuel": _clean(raw.get("fuel"), max_len=40),
        "estimated_value": None,
        "bid": bid,
        "images": prefer_iaai_cdn_images(list(raw.get("images") or []), limit=8),
        "bidcars_fee_usd": 0,
        "is_sublot": is_sublot,
        "sublot_location": sublot_location,
    }
    if details["vin"] and not VIN_RE.fullmatch(details["vin"] or ""):
        found = VIN_RE.search(str(raw.get("page_snip") or ""))
        if found:
            details["vin"] = found.group(1).upper()
    return _with_inland(details)


def extract_iaai_lot(page: Any, url: str, *, wait_challenge_s: float = 90.0) -> dict:
    canonical = normalize_iaai_url(url)
    stock = parse_iaai_stock_id(canonical) or ""
    log.info("IAAI: читаю stock %s", stock)
    # Вкладку уже открыл scraper._ensure_iaai_tab (как калькулятор).
    try:
        current = (page.url or "").lower()
        if stock and stock not in current:
            page.goto(canonical, wait_until="domcontentloaded", timeout=90_000)
    except Exception as exc:
        log.warning("IAAI goto: %s", exc)

    import time

    deadline = time.time() + max(15.0, wait_challenge_s)
    raw: dict = {}
    while time.time() < deadline:
        try:
            raw = page.evaluate(IAAI_DOM_SCRIPT) or {}
        except Exception:
            raw = {}
        if raw and not raw.get("challenge") and (raw.get("h1") or raw.get("vin") or raw.get("stock")):
            break
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.wait_for_timeout(2000)
        except Exception:
            time.sleep(2)

    if raw.get("challenge") and not (raw.get("h1") or raw.get("vin")):
        raise RuntimeError(
            "IAAI показывает защиту (hCaptcha/Incapsula). "
            "Во вкладке IAAI в Chrome бота пройдите проверку и нажмите «Подтянуть лот» ещё раз."
        )
    return normalize_iaai_details(raw, url=canonical)
