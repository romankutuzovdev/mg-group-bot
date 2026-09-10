from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

log = logging.getLogger("copart")

BIDCARS_LOT_RE = re.compile(
    r"bid\.cars/(?:[a-z]{2}/)?lot/(?:\d+-)?(\d{5,12})",
    re.I,
)
VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b")
MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)", re.I)

# Фиксированный сервисный сбор Bid.Cars (+VAT/Tax), как на карточке лота.
BIDCARS_SERVICE_FEE = 450.0

# Океан США → EU (ориентир; на лоте может подтянуться точнее).
OCEAN_TO_EU_USD = {
    "rotterdam": 1095.0,
    "bremerhaven": 1095.0,
    "gdynia": 1195.0,
    "klaipeda": 1195.0,
}

PORT_LABEL = {
    "rotterdam": "Rotterdam, NL",
    "bremerhaven": "Bremerhaven, DE",
    "gdynia": "Gdynia, PL",
    "klaipeda": "Klaipeda, LT",
}

BIDCARS_DOM_SCRIPT = r"""() => {
  const clean = (v) => (v || "").replace(/\s+/g, " ").trim();
  const urlLotId = (String(window.location.href || "").match(/\/lot\/(?:\d+-)?(\d{5,12})/i) || [])[1] || "";
  const sameLotId = (n) => {
    if (!n || typeof n !== "object" || !urlLotId) return false;
    const nid = String(n.lotNumber || n.lotId || n.lot_id || n.stockNumber || "");
    if (!nid) return false;
    const bare = nid.replace(/^\d+-/, "");
    return nid === urlLotId || bare === urlLotId;
  };
  const isJunk = (v) => {
    const t = clean(v);
    if (!t || t.length > 140) return true;
    if (/localStorage|document\.|stylesheet|\.row-|hover\s*\{|function\s*\(|<\/?[a-z]|калькулятор|история продаж|похожие архивные|процесс покупки|таможенн|ориентировочн|текущая ставка \$|сделать ставку/i.test(t)) return true;
    return false;
  };
  const good = (v) => {
    const t = clean(v);
    return t && !isJunk(t) ? t : "";
  };

  // 1) JSON из __NEXT_DATA__ / script
  const dig = (obj, out = [], depth = 0) => {
    if (!obj || depth > 8) return out;
    if (Array.isArray(obj)) {
      obj.forEach((x) => dig(x, out, depth + 1));
      return out;
    }
    if (typeof obj === "object") {
      out.push(obj);
      Object.values(obj).forEach((x) => dig(x, out, depth + 1));
    }
    return out;
  };
  let fromJson = {};
  try {
    const next = document.querySelector("#__NEXT_DATA__");
    if (next && next.textContent) {
      const parsed = JSON.parse(next.textContent);
      const nodes = dig(parsed);
      const pick = nodes.find((n) => sameLotId(n) && (n.vin || n.VIN || n.lotNumber || n.lot_id || n.title || n.odometer));
      if (pick) fromJson = pick;
    }
  } catch (e) {}

  const j = (keys) => {
    for (const key of keys) {
      for (const [k, v] of Object.entries(fromJson)) {
        if (k.toLowerCase() === key.toLowerCase() && v != null && String(v).trim()) return String(v);
      }
    }
    return "";
  };

  // 2) Точные пары label -> соседнее короткое значение
  const valueByLabel = (labels) => {
    const wanted = labels.map((x) => x.toLowerCase());
    const nodes = Array.from(document.querySelectorAll("li, div, span, dt, dd, p, td, th, strong, b, label"));
    for (const el of nodes) {
      const own = clean(el.childNodes.length ? Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ") : "");
      const full = clean(el.textContent || "");
      const labelText = own || full;
      if (!labelText || labelText.length > 80) continue;
      const low = labelText.toLowerCase().replace(/:$/, "");
      if (!wanted.some((w) => low === w || low.startsWith(w + ":") || low === w + " :")) continue;

      // Bid.cars: значение в .right-info внутри того же .option
      const ri = el.querySelector(":scope > .right-info, :scope > span.right-info, .right-info");
      if (ri) {
        const s = good(ri.textContent);
        if (s && s.length < 120) return s;
      }

      // text after colon in same node
      const colon = labelText.split(":").slice(1).join(":").trim();
      if (good(colon) && colon.length < 100) return good(colon);

      // значение сразу после label в том же элементе: "Двигатель 4.0L, V8"
      for (const w of wanted) {
        if (low.startsWith(w) && full.length > w.length) {
          const rest = clean(full.slice(w.length).replace(/^[:\s]+/, ""));
          if (good(rest) && rest.length < 100 && !wanted.some((x) => rest.toLowerCase() === x)) return rest;
        }
      }

      const sib = el.nextElementSibling;
      if (sib) {
        // не брать соседний .option — это уже другое поле
        if (sib.classList && sib.classList.contains("option")) continue;
        const s = good(sib.textContent);
        if (s) return s;
      }
      const parent = el.parentElement;
      if (parent) {
        const kids = Array.from(parent.children);
        const idx = kids.indexOf(el);
        if (idx >= 0 && kids[idx + 1]) {
          const nxt = kids[idx + 1];
          if (nxt.classList && nxt.classList.contains("option")) continue;
          const s = good(nxt.textContent);
          if (s) return s;
        }
      }
    }
    return "";
  };

  // Пары Bid.cars: .option / .right-info / label+value
  const optionValue = (labels) => {
    const wanted = labels.map((x) => x.toLowerCase());
    const nodes = Array.from(
      document.querySelectorAll(
        ".option, [class*='option'], .info-row, .spec-item, li, .lot-details div, .right-info"
      )
    );
    for (const el of nodes) {
      const full = clean(el.textContent || "");
      if (!full || full.length > 160) continue;
      const low = full.toLowerCase();
      const hit = wanted.find((w) => low.startsWith(w) || low.includes(w + ":") || low.includes(w + " :"));
      if (!hit) continue;
      const ri = el.querySelector(".right-info, [class*='right-info'], .value, strong, b");
      if (ri) {
        const s = good(ri.textContent);
        if (s && s.length < 120 && !wanted.some((w) => s.toLowerCase() === w)) return s;
      }
      const colon = full.split(":").slice(1).join(":").trim();
      if (good(colon) && colon.length < 120) return good(colon);
      // "Документы о продаже Salvage Title" без двоеточия
      const stripped = full.replace(new RegExp("^[^:]*?" + hit, "i"), "").replace(/^[:\s]+/, "").trim();
      if (good(stripped) && stripped.length < 120 && stripped.toLowerCase() !== hit) return good(stripped);
    }
    return "";
  };

  const isDocLike = (v) => {
    const t = clean(v);
    if (!t || t.length < 2 || t.length > 120) return false;
    // не путать с заголовком лота «2020 Mercedes…»
    if (/^(19|20)\d{2}\s+[A-Za-z]/.test(t)) return false;
    if (/localStorage|document\.|stylesheet|калькулятор/i.test(t)) return false;
    return true;
  };

  // 3) Regex по тексту страницы (короткие захваты)
  const page = clean(document.body ? document.body.innerText : "");
  const rx = (re) => {
    const m = page.match(re);
    if (!m) return "";
    return good(m[1] || "");
  };

  const title =
    (() => {
      const h1 = good(document.querySelector("h1") && document.querySelector("h1").textContent);
      if (h1 && /^(19|20)\d{2}\b/.test(h1) && !/salvage|title|document/i.test(h1)) return h1;
      return "";
    })();

  const vin =
    good(j(["vin", "VIN"])) ||
    rx(/\bVIN\b\s*#?\s*:?\s*([A-HJ-NPR-Z0-9]{17})\b/i) ||
    ((page.match(/\b([A-HJ-NPR-Z0-9]{17})\b/) || [])[1] || "");

  // Местоположение на карточке Bid.cars — приоритет над JSON branch/yard
  const location =
    valueByLabel(["местоположение", "location"]) ||
    optionValue(["местоположение", "location"]) ||
    rx(/Местоположение\s*:?\s*([^\n]{3,80})/i) ||
    rx(/Location\s*:?\s*([^\n]{3,80})/i) ||
    good(j(["location", "locationName", "yard", "branch", "branchName", "facility"])) ||
    valueByLabel(["branch"]);

  const ship_from =
    valueByLabel(["отправка из", "shipping from", "ship from"]) ||
    optionValue(["отправка из", "shipping from", "ship from"]) ||
    rx(/Отправка из\s*:?\s*([^\n]{3,80})/i) ||
    rx(/Shipping from\s*:?\s*([^\n]{3,80})/i) ||
    good(j(["shipFrom", "shippingFrom", "portOfDeparture", "departurePort"]));

  const seller =
    good(j(["seller", "sellerName"])) ||
    valueByLabel(["продавец", "seller"]) ||
    optionValue(["продавец", "seller"]) ||
    rx(/Продавец\s*:?\s*([^\n]{3,80})/i);

  const documentsRaw =
    good(j(["saleDocument", "saleDocuments", "titleCode", "titleType", "titleGroup", "documentType"])) ||
    optionValue([
      "документы о продаже",
      "sale documents",
      "title/sale doc",
      "title / sale doc",
      "sale doc",
      "title code",
    ]) ||
    valueByLabel([
      "документы о продаже",
      "sale documents",
      "title/sale doc",
      "title / sale doc",
      "sale doc",
      "title code",
    ]) ||
    rx(/Документы о продаже\s*:?\s*([^\n]{3,100})/i) ||
    rx(/Title\s*\/?\s*Sale\s*Doc(?:uments?)?\s*:?\s*([^\n]{3,100})/i) ||
    rx(/Sale documents\s*:?\s*([^\n]{3,100})/i) ||
    rx(/\b((?:[A-Z]{2}\s*-\s*)?(?:Certificate of Title|Clean Title|Salvage(?: Title)?|Clear Title|Bill of Sale|BOS|Parts only|Junk Title|Scrap Title)[^\n]{0,60})/i);
  const documents = isDocLike(documentsRaw) ? documentsRaw : "";

  const odometer =
    good(j(["odometer", "odometerReading", "mileage"])) ||
    valueByLabel(["одометр", "odometer"]) ||
    rx(/Одометр\s*:?\s*([\d\s]+\s*(?:мил[ая]|mi(?:le)?s?|km)?)/i) ||
    rx(/Odometer\s*:?\s*([\d,\s]+\s*(?:mi(?:le)?s?|km)?)/i);

  const primary_damage =
    good(j(["primaryDamage", "damagePrimary"])) ||
    valueByLabel(["первичное повреждение", "primary damage"]) ||
    rx(/Первичное повреждение\s*:?\s*([^\n]{2,40})/i) ||
    rx(/Primary damage\s*:?\s*([^\n]{2,40})/i);

  const secondary_damage =
    good(j(["secondaryDamage"])) ||
    valueByLabel(["вторичное повреждение", "secondary damage"]) ||
    rx(/Вторичное повреждение\s*:?\s*([^\n]{1,40})/i);

  const keys =
    good(j(["keys", "hasKeys"])) ||
    valueByLabel(["ключ", "keys"]) ||
    rx(/Ключ(?:и)?\s*:?\s*([^\n]{2,40})/i);

  const body_style =
    good(j(["bodyStyle", "bodyType", "vehicleType"])) ||
    valueByLabel(["тип кузова", "body style", "body type"]) ||
    rx(/Тип кузова\s*:?\s*([A-Za-zА-Яа-яЁё /-]{3,30})/i) ||
    rx(/Body (?:style|type)\s*:?\s*([A-Za-z /-]{3,30})/i);

  const color =
    good(j(["color", "colour", "exteriorColor"])) ||
    valueByLabel(["цвет", "color", "colour", "внешний вид"]) ||
    rx(/(?:Цвет|Colour|Color|Внешний вид)\s*:?\s*([A-Za-zА-Яа-яЁё ]{3,30})/i);

  const engine =
    optionValue(["двигатель", "engine"]) ||
    valueByLabel(["двигатель", "engine"]) ||
    good(j(["engine", "engineSize"])) ||
    rx(/Двигатель\s*:?\s*([^\n]{3,60})/i) ||
    rx(/Engine\s*:?\s*([^\n]{3,60})/i);

  const transmission =
    optionValue(["коробка передач", "коробка", "transmission"]) ||
    valueByLabel(["коробка передач", "коробка", "transmission"]) ||
    good(j(["transmission"])) ||
    rx(/(?:Коробка(?: передач)?|Transmission)\s*:?\s*([^\n]{3,40})/i);

  const drive =
    optionValue(["тип привода", "тип приводной линии", "drive", "drivetrain"]) ||
    valueByLabel(["тип привода", "тип приводной линии", "drive", "drivetrain"]) ||
    good(j(["drive", "drivetrain"])) ||
    rx(/(?:Тип привода|Тип приводной линии|Drive|Drivetrain)\s*:?\s*([^\n]{2,40})/i);

  const fuel =
    optionValue(["тип топлива", "fuel type", "fuel"]) ||
    valueByLabel(["тип топлива", "fuel type", "fuel"]) ||
    good(j(["fuel", "fuelType"])) ||
    rx(/(?:Тип топлива|Fuel(?:\s*type)?)\s*:?\s*([^\n]{3,30})/i);

  const auction_platform = (() => {
    const t = page;
    if (/данные получены с платформы\s*copart|platform\s*copart|from\s*copart/i.test(t)) return "copart";
    if (/данные получены с платформы\s*iaai|platform\s*iaai|from\s*iaai/i.test(t)) return "iaai";
    if (/copart/i.test(t) && !/iaai/i.test(t)) return "copart";
    if (/iaai/i.test(t)) return "iaai";
    return "";
  })();

  const bid =
    good(j(["currentBid", "highBid", "current_bid", "high_bid", "bidAmount", "bid"])) ||
    valueByLabel(["текущая ставка", "current bid", "high bid"]) ||
    rx(/Текущая ставка\s*\$?\s*([\d,]+(?:\.\d+)?)/i) ||
    rx(/Current\s*bid\s*\$?\s*([\d,]+(?:\.\d+)?)/i) ||
    rx(/High\s*bid\s*\$?\s*([\d,]+(?:\.\d+)?)/i);

  const inland_usd =
    rx(/Грузоперевозка в порт\s*\$?\s*([\d,]+(?:\.\d+)?)/i) ||
    rx(/Trucking\s*\$?\s*([\d,]+(?:\.\d+)?)/i);

  const bidcars_fee_usd =
    rx(/BidCars сборы[^\n$]*\$\s*([\d,]+(?:\.\d+)?)/i) ||
    rx(/BidCars fee[^\n$]*\$\s*([\d,]+(?:\.\d+)?)/i);

  // Аукционные сборы с калькулятора Bid.cars ($1,190 - $1,295 → берём верх)
  const auction_fees_raw = (() => {
    const range = page.match(/Аукционные сборы[\s\S]{0,80}?\$\s*([\d,]+(?:\.\d+)?)\s*[-–—]\s*\$?\s*([\d,]+(?:\.\d+)?)/i)
      || page.match(/Auction fees?[\s\S]{0,80}?\$\s*([\d,]+(?:\.\d+)?)\s*[-–—]\s*\$?\s*([\d,]+(?:\.\d+)?)/i);
    if (range) return range[2] || range[1];
    const one = page.match(/Аукционные сборы[\s\S]{0,60}?\$\s*([\d,]+(?:\.\d+)?)/i)
      || page.match(/Auction fees?[\s\S]{0,60}?\$\s*([\d,]+(?:\.\d+)?)/i);
    return one ? one[1] : "";
  })();

  const auction_url = (() => {
    const as = Array.from(document.querySelectorAll('a[href*="iaai.com"], a[href*="copart.com"]'));
    for (const a of as) {
      const href = String(a.href || "");
      if (/vehicledetail|\/lot\/\d+/i.test(href)) return href;
    }
    for (const a of as) {
      const href = String(a.href || "");
      // Bid.cars часто даёт iaai.com/Search?Keyword=ID
      if (/iaai\.com\/Search\?Keyword=/i.test(href) || /copart\.com\/lot\//i.test(href)) return href;
    }
    for (const a of as) {
      const href = String(a.href || "");
      if (/iaai\.com|copart\.com/i.test(href) && !/login|register|help|about/i.test(href)) return href;
    }
    return "";
  })();

  const lotId = urlLotId;
  const junkImg = (src) => /logo|icon|flag|sprite|avatar|svg|pixel|placeholder|banner|favicon|sprite|badge|button|spinner|loader|og-image|default/i.test(src || "");
  const looksPhoto = (src) => {
    if (!src || src.startsWith("data:")) return false;
    if (junkImg(src)) return false;
    if (!/^https?:/i.test(src) && !src.startsWith("//")) return false;
    return /\\.(jpe?g|webp)(\\?|$)/i.test(src) || /cloudfront|amazonaws|iaai\\.com|lotimages|vis\\.iaai|cdn\\.bid\\.cars/i.test(src);
  };
  const abs = (src) => {
    let s = (src || "").trim();
    if (s.startsWith("//")) s = "https:" + s;
    return s;
  };
  const inRelated = (el) => {
    let p = el;
    for (let i = 0; i < 8 && p; i++) {
      const cls = String(p.className || "");
      const id = String(p.id || "");
      if (/similar|related|recommend|archive|похож|архив|recently|viewed/i.test(cls + " " + id)) return true;
      const kids = p.children ? Array.from(p.children) : [];
      const head = kids.find((c) => c && /^H[23]$/.test(c.tagName));
      const ht = head ? String(head.textContent || "") : "";
      if (/похож|similar|related|архивн|recommend|recently/i.test(ht)) return true;
      p = p.parentElement;
    }
    return false;
  };
  const pushImg = (list, raw) => {
    const src = abs(raw);
    if (!looksPhoto(src)) return;
    if (lotId) {
      const otherLot = src.match(/\/lot\/(?:\d+-)?(\d{6,12})/i);
      if (otherLot && otherLot[1] !== lotId) return;
    }
    if (!list.includes(src)) list.push(src);
  };

  const images = [];
  try {
    const acc = [];
    const walk = (obj, depth) => {
      if (!obj || depth > 10) return;
      if (Array.isArray(obj)) { obj.forEach((x) => walk(x, depth + 1)); return; }
      if (typeof obj !== "object") return;
      const same = sameLotId(obj);
      const take = (v) => {
        if (!v) return;
        if (typeof v === "string") pushImg(acc, v);
        else if (Array.isArray(v)) v.forEach(take);
        else if (typeof v === "object") take(v.url || v.src || v.large || v.full || v.original || v.image);
      };
      if (same) {
        ["images", "photos", "imageUrls", "pictures", "gallery", "image", "imageUrl", "largeImage", "preview"].forEach((k) => take(obj[k]));
      }
      Object.values(obj).forEach((x) => { if (x && typeof x === "object") walk(x, depth + 1); });
    };
    walk(fromJson, 0);
    const nextEl = document.querySelector("#__NEXT_DATA__");
    if (nextEl && nextEl.textContent) walk(JSON.parse(nextEl.textContent), 0);
    acc.forEach((s) => pushImg(images, s));
  } catch (e) {}

  const og = document.querySelector('meta[property="og:image"]');
  if (og) pushImg(images, og.getAttribute("content"));

  Array.from(document.querySelectorAll("img")).forEach((img) => {
    if (inRelated(img)) return;
    const w = img.naturalWidth || img.width || 0;
    const h = img.naturalHeight || img.height || 0;
    if (w && h && (w < 140 || h < 90)) return;
    pushImg(images, img.currentSrc || img.src);
    ["data-src", "data-lazy", "data-original"].forEach((a) => pushImg(images, img.getAttribute(a)));
  });

  images.sort((a, b) => {
    const score = (s) => {
      let n = 0;
      if (lotId && s.includes(lotId)) n += 30;
      if (/_ful|large|original|full|1920|1280/i.test(s)) n += 8;
      if (/_thb|thumb|small|100x|150x/i.test(s)) n -= 8;
      return n;
    };
    return score(b) - score(a);
  });

  return {
    title,
    lot_id: lotId,
    vin,
    location,
    ship_from,
    seller,
    documents,
    sale_date: rx(/Прямой аукцион\s*([^\n]{5,60})/i) || rx(/Live auction\s*([^\n]{5,60})/i),
    odometer,
    primary_damage,
    secondary_damage,
    keys,
    body_style,
    color,
    engine,
    transmission,
    drive,
    fuel,
    auction_platform,
    estimated_value: rx(/ACV\s*\/\s*ERC\s*\$?([\d,]+)/i) || "",
    bid,
    inland_usd,
    bidcars_fee_usd,
    auction_fees_usd: auction_fees_raw,
    auction_url,
    images: images.slice(0, 12),
    page_snip: page.slice(0, 4000),
  };
}"""


def parse_bidcars_lot_id(url: str) -> str | None:
    text = str(url or "").strip()
    if text.isdigit() and 5 <= len(text) <= 12:
        return text
    match = BIDCARS_LOT_RE.search(text)
    if match:
        return match.group(1)
    bare = re.search(r"(?:^|[^\d])(\d{6,12})(?:[^\d]|$)", text)
    return bare.group(1) if bare else None


def title_from_url(url: str) -> str | None:
    match = re.search(r"/lot/(?:\d+-)?\d+/([^/?#]+)", str(url or ""), re.I)
    if not match:
        return None
    slug = match.group(1)
    slug = re.sub(r"-?[A-HJ-NPR-Z0-9]{17}$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug).strip()
    slug = re.sub(r"\s+", " ", slug)
    if re.match(r"^(19|20)\d{2}\b", slug):
        return slug
    return None


def normalize_bidcars_url(url: str) -> str:
    raw = str(url or "").strip()
    lot_id = parse_bidcars_lot_id(raw)
    if not lot_id:
        raise ValueError("Нужна ссылка bid.cars на лот, например https://bid.cars/ru/lot/0-45677502/...")
    if raw.startswith("http"):
        parsed = urlparse(raw)
        if "bid.cars" in (parsed.netloc or "").lower():
            return raw.split("?")[0].rstrip("/")
    return f"https://bid.cars/ru/lot/0-{lot_id}"


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = MONEY_RE.search(text) or re.search(r"([\d,]+(?:\.\d+)?)", text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _year_make_model(title: str) -> tuple[int | None, str | None, str | None]:
    match = re.match(r"^(20\d{2}|19\d{2})\s+(\S+)\s+(.+)$", title.strip())
    if not match:
        return None, None, None
    year = int(match.group(1))
    make = match.group(2)
    model = re.sub(r",.*$", "", match.group(3)).strip()
    return year, make, model


def _clean_field(value: Any, *, max_len: int = 120) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if len(text) > max_len:
        return None
    junk = re.compile(
        r"localStorage|document\.|stylesheet|\.row-|hover\s*\{|function\s*\(|</?[a-z]|"
        r"калькулятор|история продаж|похожие архивные|процесс покупки|таможенн|"
        r"ориентировочн|сделать ставку|продавец\s+извините",
        re.I,
    )
    if junk.search(text):
        return None
    return text


def _sanitize_engine(value: Any) -> str | None:
    """Отсечь перепутанные КПП/привод/топливо; оставить строки вида 4.0L, V8."""
    text = _clean_field(value, max_len=60)
    if not text:
        return None
    low = text.lower()
    if re.search(
        r"коробк|transmission|automatic|manual|автоматич|механич|"
        r"привод|drivetrain|\bawd\b|\bfwd\b|\brwd\b|\b4wd\b|"
        r"тип топлива|fuel type|^fuel$|бензинов|дизельн|hybrid|электрич",
        low,
    ):
        return None
    if re.search(r"\d", text) or re.search(r"\bv\s*\d|цил|cyl|\bhp\b|двигат|engine", low):
        return text
    return None


def _engine_from_snip(snip: str) -> str | None:
    m = re.search(
        r"Двигатель\s*:?\s*((?:\d+[.,]?\d*\s*[LlЛл]|\d{3,4}\s*(?:cc|см))[^\n]{0,50})",
        snip or "",
        re.I,
    ) or re.search(
        r"Engine\s*:?\s*((?:\d+[.,]?\d*\s*L|\d{3,4}\s*cc)[^\n]{0,50})",
        snip or "",
        re.I,
    )
    return _sanitize_engine(m.group(1) if m else None)


def _filter_bidcars_images(urls: list | None, lot_id: str | None) -> list[str]:
    lot_id = str(lot_id or "").strip()
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        src = str(raw or "").strip()
        if src.startswith("//"):
            src = "https:" + src
        if not src.startswith("https://"):
            continue
        # CDN Bid.cars: thumb → full
        src = src.replace("_thb.", "_ful.")
        low = src.lower()
        if re.search(
            r"logo|icon|flag|sprite|avatar|svg|pixel|placeholder|banner|favicon|badge|spinner|/img/upd/",
            low,
        ):
            continue
        if not re.search(
            r"images\.bid\.cars|cdn\.bid\.cars|cloudfront|amazonaws|iaai\.com|lotimages|vis\.iaai|\.(?:jpe?g|webp|png)(?:\?|$)",
            low,
        ):
            continue
        if lot_id:
            other = re.search(r"/lot/(?:\d+-)?(\d{6,12})", src, re.I)
            if other and other.group(1) != lot_id:
                continue
        if src in seen:
            continue
        seen.add(src)
        out.append(src)

    def score(src: str) -> int:
        n = 0
        low = src.lower()
        if "images.bid.cars" in low or "cdn.bid.cars" in low:
            n += 50
        if lot_id and lot_id in src:
            n += 30
        if re.search(r"_ful|large|original|full", src, re.I):
            n += 8
        if re.search(r"_thb|thumb|small", src, re.I):
            n -= 8
        return n

    out.sort(key=score, reverse=True)
    return out[:8]


def prefer_bidcars_cdn_images(urls: list | None, *, limit: int = 6) -> list[str]:
    """Только прямые CDN-ссылки Bid.cars (без локального /api/media)."""
    cleaned = _filter_bidcars_images(urls, None)
    out: list[str] = []
    for src in cleaned:
        low = src.lower()
        if "images.bid.cars" in low or "cdn.bid.cars" in low:
            out.append(src)
        elif re.search(r"cloudfront|amazonaws|iaai\.com|lotimages|vis\.iaai", low):
            out.append(src)
        if len(out) >= max(1, limit):
            break
    return out


def _odometer_miles(value: Any) -> float | None:
    text = str(value or "")
    # "395k miles" / "395 k miles"
    k_match = re.search(r"([\d]+(?:[.,]\d+)?)\s*k\s*(?:мил|mi)", text, re.I)
    if k_match:
        try:
            return float(k_match.group(1).replace(",", ".")) * 1000.0
        except ValueError:
            pass
    # "107 463 mi" / "107,463 miles"
    match = re.search(r"([\d\s,]{3,15})\s*(?:мил|mi)", text, re.I)
    if match:
        digits = re.sub(r"[^\d]", "", match.group(1))
        if digits:
            return float(digits)
    digits = re.sub(r"[^\d]", "", text)
    if digits and 3 <= len(digits) <= 7:
        return float(digits)
    return None


def _place_from_page(snip: str, *labels: str) -> str | None:
    text = snip or ""
    for label in labels:
        pattern = rf"{label}\s*:?\s*([A-Za-z][A-Za-z0-9 .'-]{{1,40}}(?:\s*\([A-Z]{{2}}\))?)"
        match = re.search(pattern, text, re.I)
        if match:
            return _clean_field(match.group(1), max_len=60)
    # запасной: City (ST)
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?\s*\([A-Z]{2}\))", text):
        place = _clean_field(match.group(1), max_len=60)
        if place:
            return place
    return None


def inland_default(ship_from: str | None) -> float:
    """Запасной фикс, если геокод не сработал."""
    return 450.0


def ocean_default(port: str) -> float:
    key = str(port or "rotterdam").strip().lower()
    return float(OCEAN_TO_EU_USD.get(key) or OCEAN_TO_EU_USD["rotterdam"])


def normalize_bidcars_details(raw: dict, url: str) -> dict:
    from usa_distance import resolve_us_inland

    snip = str(raw.get("page_snip") or "")
    title = ""
    # 1) из URL: .../2019-Mercedes-Benz-CLA-250-VIN
    url_title = title_from_url(url) or ""
    title = url_title
    # 2) заголовок карточки — только если страница уже этого лота
    dom_title = _clean_field(raw.get("title"), max_len=160) or ""
    if dom_title and re.match(r"^(19|20)\d{2}\b", dom_title) and not re.search(
        r"salvage|title document|история", dom_title, re.I
    ):
        title = dom_title
    if not title:
        m_title = re.search(r"((?:19|20)\d{2}\s+[A-Za-z][A-Za-z0-9 ,.-]{3,60})", snip)
        cand = _clean_field(m_title.group(1) if m_title else "", max_len=160) or ""
        if cand and not re.search(r"salvage|document", cand, re.I):
            title = cand
    year, make, model = _year_make_model(title)
    vin = str(raw.get("vin") or "").strip().upper()
    if not VIN_RE.fullmatch(vin):
        found = VIN_RE.search(snip + " " + title)
        vin = found.group(1) if found else None
    lot_id = str(parse_bidcars_lot_id(url) or raw.get("lot_id") or "").strip()

    location = _clean_field(raw.get("location"), max_len=80) or _place_from_page(
        snip, "Местоположение", "Location"
    )
    ship_from = _clean_field(raw.get("ship_from"), max_len=80) or _place_from_page(
        snip, "Отправка из", "Shipping from", "Ship from"
    )
    # Не подменять Местоположение вторым городом со страницы — мили только от него
    if location:
        location = re.sub(r"\s+", " ", location).strip()
        # обрезать хвосты вроде "Отправка из ..." если regex захватил лишнее
        location = re.split(r"\s+(?:Отправка из|Shipping from|Продавец|Seller)\b", location, maxsplit=1)[0].strip()

    # Мили inland: только «Местоположение», не «Отправка из» и не branch из JSON
    route = resolve_us_inland(location, None, allow_chrome_maps=False)
    inland = route.get("inland_usd")
    if inland is None:
        inland = inland_default(location or ship_from)

    body_style = _clean_field(raw.get("body_style"), max_len=40)
    if not body_style:
        m = re.search(
            r"(?:Тип кузова|Body (?:style|type))\s*:?\s*([A-Za-zА-Яа-яЁё /-]{3,30})",
            snip,
            re.I,
        )
        body_style = _clean_field(m.group(1) if m else "", max_len=40)

    primary_damage = _clean_field(raw.get("primary_damage"), max_len=40)
    if not primary_damage:
        m = re.search(
            r"(?:Первичное повреждение|Primary damage)\s*:?\s*([^\n]{2,40})",
            snip,
            re.I,
        )
        primary_damage = _clean_field(m.group(1) if m else "", max_len=40)

    documents = _clean_field(raw.get("documents"), max_len=100)
    if documents and re.match(r"^(?:19|20)\d{2}\s+[A-Za-z]", documents):
        documents = ""
    if not documents:
        m = (
            re.search(
                r"(?:Документы о продаже|Sale documents|Title\s*/?\s*Sale\s*Doc(?:uments)?)\s*:?\s*([^\n]{3,100})",
                snip,
                re.I,
            )
            or re.search(
                r"\b((?:[A-Z]{2}\s*-\s*)?(?:Certificate of Title|Clean Title|Salvage(?: Title)?|Clear Title|Bill of Sale|BOS|Parts only|Junk Title|Scrap Title)[^\n]{0,60})",
                snip,
                re.I,
            )
        )
        documents = _clean_field(m.group(1) if m else "", max_len=100)

    odometer = _odometer_miles(raw.get("odometer"))
    if odometer is None:
        m_odo = re.search(r"Одометр\s*:?\s*([^\n]{3,40})", snip, re.I) or re.search(
            r"Odometer\s*:?\s*([^\n]{3,40})", snip, re.I
        )
        if m_odo:
            odometer = _odometer_miles(m_odo.group(1))

    bid = _num(raw.get("bid"))
    if bid is None or bid <= 0:
        m = (
            re.search(r"Текущая ставка\s*\$?\s*([\d,]+(?:\.\d+)?)", snip, re.I)
            or re.search(r"Current\s*bid\s*\$?\s*([\d,]+(?:\.\d+)?)", snip, re.I)
            or re.search(r"High\s*bid\s*\$?\s*([\d,]+(?:\.\d+)?)", snip, re.I)
            or re.search(r"(?:Buy\s*now|Buy\s*It\s*Now)\s*\$?\s*([\d,]+(?:\.\d+)?)", snip, re.I)
        )
        parsed = _num(m.group(1) if m else None)
        if parsed is not None and parsed > 0:
            bid = parsed

    return {
        "source": "bidcars",
        "lot_id": lot_id,
        "title": title or f"Lot {lot_id}",
        "year": year,
        "make": make,
        "model": model,
        "vin": vin,
        "url": url,
        "location": location,
        "ship_from": ship_from,
        "seller": _clean_field(raw.get("seller"), max_len=80),
        "documents": documents,
        "title_code": documents,
        "sale_date": _clean_field(raw.get("sale_date"), max_len=80),
        "odometer": odometer,
        "primary_damage": primary_damage,
        "secondary_damage": _clean_field(raw.get("secondary_damage"), max_len=40),
        "keys": _clean_field(raw.get("keys"), max_len=40),
        "body_style": body_style,
        "color": _clean_field(raw.get("color"), max_len=40),
        "engine": _sanitize_engine(raw.get("engine")) or _engine_from_snip(snip),
        "transmission": _clean_field(raw.get("transmission"), max_len=40),
        "drive": _clean_field(raw.get("drive"), max_len=40),
        "fuel": _clean_field(raw.get("fuel"), max_len=40),
        "estimated_value": _clean_field(raw.get("estimated_value"), max_len=40),
        "bid": bid,
        "images": _filter_bidcars_images(list(raw.get("images") or []), lot_id),
        "inland_usd": inland,
        "inland_miles": route.get("inland_miles"),
        "us_port": route.get("us_port"),
        "us_port_label": route.get("us_port_label"),
        "miles_to_new_jersey": route.get("miles_to_new_jersey"),
        "miles_to_houston": route.get("miles_to_houston"),
        "distance_source": route.get("distance_source"),
        "inland_route": route,
        "bidcars_fee_usd": BIDCARS_SERVICE_FEE,
        "ocean_usd_by_port": {},
        "auction_platform": (
            (lambda plat, aurl: (
                "copart"
                if plat == "copart" or (aurl and "copart.com" in aurl.lower())
                else "iaai"
                if plat == "iaai" or (aurl and "iaai.com" in aurl.lower())
                else "iaai"
            ))(
                str(raw.get("auction_platform") or "").strip().lower(),
                str(raw.get("auction_url") or "").strip().lower(),
            )
        ),
        "auction_url": _clean_field(raw.get("auction_url"), max_len=300),
        "auction_fees_usd": _num(raw.get("auction_fees_usd")),
        "is_sublot": False,
        "sublot_location": None,
    }


def extract_bidcars_lot(page: Any, url: str) -> dict:
    canonical = normalize_bidcars_url(url)
    want_id = parse_bidcars_lot_id(canonical) or ""
    log.info("Bid.cars: открываю %s", canonical)
    # Next.js не обновляет __NEXT_DATA__ при клиентском переходе.
    # Если вкладка уже на этом URL, Playwright тоже не перезагружает документ —
    # остаётся первая открытая машина. Сначала about:blank, потом полный заход.
    try:
        current = (page.url or "").strip()
        if current and current != "about:blank":
            page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.goto(canonical, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_function(
            """(id) => {
              const href = String(location.href || '');
              if (!id || !href.includes(id)) return false;
              const h1 = (document.querySelector('h1') && document.querySelector('h1').innerText) || '';
              const t = (document.body && document.body.innerText) || '';
              return h1.length > 5 && /VIN|Одометр|Odometer|Местоположение|Location/i.test(t);
            }""",
            arg=want_id,
            timeout=25000,
        )
    except Exception:
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
    page.wait_for_timeout(800)
    data = page.evaluate(BIDCARS_DOM_SCRIPT)
    if not isinstance(data, dict):
        data = {}
    href = ""
    try:
        href = str(page.url or "")
    except Exception:
        href = ""
    if want_id and want_id not in href:
        log.warning("Bid.cars: URL после загрузки не тот лот (%s, ждали %s), перезагружаю", href, want_id)
        try:
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            data = page.evaluate(BIDCARS_DOM_SCRIPT)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            pass
    try:
        plain = page.evaluate("() => (document.body && document.body.innerText) || ''")
        if isinstance(plain, str) and plain:
            data["page_snip"] = plain[:8000]
    except Exception:
        pass
    return normalize_bidcars_details(data, canonical)


BIDCARS_SEARCH_RE = re.compile(
    r"bid\.cars/(?:[a-z]{2}/)?search(?:/|$|\?)",
    re.I,
)

BIDCARS_SEARCH_SCRIPT = r"""() => {
  const clean = (v) => (v || "").replace(/\s+/g, " ").trim();
  const money = (v) => {
    const t = clean(String(v || ""));
    const m = t.match(/\$?\s*([\d,]+(?:\.\d+)?)/);
    return m ? m[1].replace(/,/g, "") : "";
  };
  const lotFromHref = (href) => {
    const m = String(href || "").match(/\/lot\/(?:\d+-)?(\d{5,12})/i);
    return m ? m[1] : "";
  };
  const abs = (href) => {
    try { return new URL(href, location.href).href.split("?")[0]; } catch (e) { return href || ""; }
  };
  const lots = {};
  const merge = (lot) => {
    const id = String(lot.lot_id || "").replace(/^\d+-/, "");
    if (!id || !/^\d{5,12}$/.test(id)) return;
    const prev = lots[id] || { lot_id: id };
    const pick = (key, val) => {
      if (val == null || val === "") return;
      if (prev[key] == null || prev[key] === "") prev[key] = val;
    };
    pick("title", lot.title);
    pick("vin", lot.vin);
    pick("location", lot.location);
    pick("odometer", lot.odometer);
    pick("bid", lot.bid);
    pick("sale_date", lot.sale_date);
    pick("primary_damage", lot.primary_damage);
    pick("body_style", lot.body_style);
    pick("url", lot.url);
    pick("year", lot.year);
    pick("make", lot.make);
    pick("model", lot.model);
    if (Array.isArray(lot.images)) {
      const imgs = Array.isArray(prev.images) ? prev.images.slice() : [];
      lot.images.forEach((u) => {
        const src = clean(u);
        if (src && !imgs.includes(src)) imgs.push(src);
      });
      if (imgs.length) prev.images = imgs.slice(0, 12);
    }
    lots[id] = prev;
  };

  const dig = (obj, out = [], depth = 0) => {
    if (!obj || depth > 10) return out;
    if (Array.isArray(obj)) {
      obj.forEach((x) => dig(x, out, depth + 1));
      return out;
    }
    if (typeof obj === "object") {
      out.push(obj);
      Object.values(obj).forEach((x) => dig(x, out, depth + 1));
    }
    return out;
  };

  const fromNode = (n) => {
    if (!n || typeof n !== "object") return;
    const href = n.detailUrl || n.url || n.href || n.link || "";
    const lotId =
      lotFromHref(href) ||
      String(n.lot || n.lotNumber || n.lotId || n.lot_id || n.stockNumber || "").replace(/^\d+-/, "");
    if (!lotId) return;
    const title = clean(n.name || n.nameShort || n.title || n.lotDesc || "");
    const vin = clean(n.vin || n.VIN || "");
    const images = [];
    const pushImg = (v) => {
      const src = clean(String(v || ""));
      if (!src || src.startsWith("data:")) return;
      if (!/cloudfront|amazonaws|iaai|bid\.cars|lotimages|\.(?:jpe?g|webp|png)(?:\?|$)/i.test(src)) return;
      if (!images.includes(src)) images.push(src);
    };
    ["image", "imageUrl", "thumbnail", "thumb", "preview", "largeImage", "photo"].forEach((k) => pushImg(n[k]));
    ["images", "photos", "imageUrls", "gallery"].forEach((k) => {
      const arr = n[k];
      if (Array.isArray(arr)) arr.forEach(pushImg);
      else pushImg(arr);
    });
    merge({
      lot_id: lotId,
      title,
      vin,
      location: clean(n.location || n.locationName || n.yard || n.branch),
      odometer: n.odometer || n.odometerReading || n.mileage || "",
      bid: money(n.prebidPrice || n.finalBid || n.currentBid || n.buyNowPrice || n.bid || n.price),
      sale_date: clean(n.prebidCloseTime || n.saleDate || n.auctionDate || n.timeLeftFormatted),
      primary_damage: clean(n.primaryDamage || n.lossType),
      body_style: clean(n.bodyStyle || n.vehicleType),
      year: n.year,
      make: n.make,
      model: n.model,
      url: abs(href) || (lotId ? (location.origin + "/ru/lot/0-" + lotId) : ""),
      images,
    });
  };

  try {
    const next = document.querySelector("#__NEXT_DATA__");
    if (next && next.textContent) {
      dig(JSON.parse(next.textContent)).forEach(fromNode);
    }
  } catch (e) {}

  const cards = Array.from(document.querySelectorAll(".item-horizontal, .lots-search .item-horizontal, [class*='item-horizontal']"));
  const roots = cards.length
    ? cards
    : Array.from(document.querySelectorAll('a[href*="/lot/"]')).map((a) => {
        let el = a;
        for (let i = 0; i < 12 && el && el.parentElement; i++) {
          el = el.parentElement;
          const cls = String(el.className || "");
          if (/item-horizontal|lots-search/i.test(cls)) return el;
        }
        return a.closest(".item-horizontal") || a.parentElement || a;
      });

  roots.forEach((root) => {
    if (!root) return;
    const a =
      root.querySelector('a.item-title[href*="/lot/"], a[href*="/lot/"]') ||
      (root.matches && root.matches('a[href*="/lot/"]') ? root : null);
    const href = a ? a.getAttribute("href") || "" : "";
    const lotId =
      lotFromHref(href) ||
      lotFromHref((root.innerText || "").match(/0-(\d{5,12})/) ? "0-" + (root.innerText.match(/0-(\d{5,12})/) || [])[1] : "");
    if (!lotId) return;
    const text = String(root.innerText || "");
    const textOne = clean(text);
    const titleLine =
      clean((a && a.textContent) || "") ||
      text.split("\n").map(clean).find((line) => /^(19|20)\d{2}\b/.test(line)) ||
      "";
    const loc =
      clean((text.match(/Location:\s*([^\n]+)/i) || [])[1] || "") ||
      clean((textOne.match(/Location:\s*([A-Za-z .'-]+(?:\s*\([A-Z]{2}\))?)/i) || [])[1] || "");
    const odo =
      (text.match(/([\d.,]+)\s*k\s*miles/i) || [])[0] ||
      (text.match(/([\d\s,]{2,12})\s*(?:mi|miles|мил)/i) || [])[1] ||
      "";
    // Current Bid предпочтительнее Buy Now / estimate range
    let bid = "";
    const cur = text.match(/Current\s*Bid:\s*\$?\s*([\d,]+(?:\.\d+)?)/i);
    if (cur) bid = cur[1].replace(/,/g, "");
    if (!bid) {
      const bn = text.match(/Buy\s*Now:\s*\$?\s*([\d,]+(?:\.\d+)?)/i);
      if (bn) bid = bn[1].replace(/,/g, "");
    }
    if (!bid) {
      const range = text.match(/\$\s*([\d,]+)\s*[-–]\s*\$\s*[\d,]+/);
      if (range) bid = range[1].replace(/,/g, "");
    }
    const images = [];
    Array.from(root.querySelectorAll("img")).forEach((img) => {
      const src = clean(
        img.currentSrc || img.src || img.getAttribute("data-src") || img.getAttribute("data-lazy") || ""
      );
      if (!src || src.startsWith("data:")) return;
      if (/\/img\/upd\/|\/images\/(?:logo|current|archieved)/i.test(src)) return;
      if (!/images\.bid\.cars|cloudfront|amazonaws|iaai|lotimages|vis\.iaai|\.(?:jpe?g|webp|png)(?:\?|$)/i.test(src)) return;
      if (!images.includes(src)) images.push(src);
    });
    // background-image на слайдах карусели
    Array.from(root.querySelectorAll("[style*='background'], .carousel-item, [class*='carousel']")).forEach((el) => {
      const st = String(el.getAttribute("style") || "");
      const m = st.match(/url\(['"]?(https?:\/\/[^'")\s]+)/i);
      if (m && /images\.bid\.cars|\.(?:jpe?g|webp|png)/i.test(m[1]) && !images.includes(m[1])) images.push(m[1]);
    });
    merge({
      lot_id: lotId,
      title: titleLine || clean((a && a.getAttribute("title")) || ""),
      location: loc && loc.length < 80 ? loc : "",
      odometer: odo,
      bid,
      url: abs(href) || (location.origin + "/en/lot/0-" + lotId),
      images,
    });
  });

  let nextUrl = "";
  const nextEl = document.querySelector('a[rel="next"], a[aria-label*="Next" i], a[aria-label*="След" i]');
  if (nextEl && nextEl.href) nextUrl = nextEl.href;
  if (!nextUrl) {
    const here = new URL(location.href);
    const pathPage = (here.pathname.match(/\/page\/(\d+)/i) || [])[1];
    const herePage = Number(pathPage || here.searchParams.get("page") || "1");
    const want = herePage + 1;
    // /en/automobile/page/2
    const autoNext = document.querySelector(`a[href*="/automobile/page/${want}"]`);
    if (autoNext && autoNext.href) nextUrl = autoNext.href;
    if (!nextUrl) {
      for (const a of Array.from(document.querySelectorAll("a[href]"))) {
        try {
          const u = new URL(a.href, location.href);
          if (u.origin !== here.origin) continue;
          const pPath = (u.pathname.match(/\/page\/(\d+)/i) || [])[1];
          const p = Number(pPath || u.searchParams.get("page") || "0");
          if (p === want && (/\/automobile/i.test(u.pathname) || /\/search/i.test(u.pathname))) {
            nextUrl = u.href;
            break;
          }
        } catch (e) {}
      }
    }
  }
  const labelNext = Array.from(document.querySelectorAll("a, button")).find((el) =>
    /^(next|следующ|далее|›|»)$/i.test(clean(el.textContent || ""))
  );
  if (!nextUrl && labelNext && labelNext.href) nextUrl = labelNext.href;

  return {
    lots: Object.values(lots),
    nextUrl,
    count: Object.keys(lots).length,
  };
}"""


def is_bidcars_url(url: str) -> bool:
    host = (urlparse(str(url or "").strip()).netloc or "").lower()
    if not host:
        return "bid.cars" in str(url or "").lower()
    return "bid.cars" in host


def is_bidcars_search_url(url: str) -> bool:
    text = str(url or "").strip()
    if not is_bidcars_url(text):
        return False
    if BIDCARS_LOT_RE.search(text):
        return False
    if BIDCARS_SEARCH_RE.search(text):
        return True
    parsed = urlparse(text if "://" in text else f"https://{text}")
    path = (parsed.path or "").lower()
    if "/search" in path or path.rstrip("/") in {"", "/en", "/ru", "/uk"}:
        return True
    # Каталог авто: /en/automobile/page/1
    return bool(re.search(r"/(?:en|ru|uk)/automobile(?:/|$)", path))


def normalize_bidcars_search_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Вставьте URL поиска с Bid.cars")
    if raw.startswith("www."):
        raw = f"https://{raw}"
    if not raw.startswith("http://") and not raw.startswith("https://"):
        if "bid.cars" in raw.lower():
            raw = f"https://{raw.lstrip('/')}"
        else:
            raise ValueError("Нужен полный URL поиска Bid.cars (https://bid.cars/…)")
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if "bid.cars" not in host:
        raise ValueError("Нужен URL с bid.cars, например https://bid.cars/ru/search/results?…")
    if BIDCARS_LOT_RE.search(raw):
        raise ValueError("Это ссылка на лот. Нужен URL поиска Bid.cars с фильтрами")
    path = (parsed.path or "").lower()
    if "/search" in path or re.search(r"/(?:en|ru|uk)/automobile(?:/|$)", path):
        return raw.split("#")[0]
    raise ValueError(
        "Нужен URL поиска Bid.cars, например https://bid.cars/en/automobile/page/1 "
        "или https://bid.cars/ru/search/results?make=Toyota"
    )


def bidcars_store_lot_id(lot_id: str) -> str:
    text = str(lot_id or "").strip()
    if text.lower().startswith("bc-"):
        return f"bc-{text[3:]}"
    bare = parse_bidcars_lot_id(text) or text
    return f"bc-{bare}"


def bidcars_display_lot_id(lot_id: str) -> str:
    text = str(lot_id or "").strip()
    if text.lower().startswith("bc-"):
        return text[3:]
    return text


def _search_page_url(url: str, page_no: int) -> str:
    parsed = urlparse(url)
    path = parsed.path or ""
    # /en/automobile/page/3
    if re.search(r"/automobile(?:/page/\d+)?/?$", path, re.I):
        lang = "en"
        parts = [p for p in path.split("/") if p]
        if parts and len(parts[0]) == 2:
            lang = parts[0]
        new_path = f"/{lang}/automobile/page/{max(1, page_no)}"
        return urlunparse(parsed._replace(path=new_path, query=""))
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page_no <= 1:
        query.pop("page", None)
    else:
        query["page"] = [str(page_no)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _lot_from_search_item(raw: dict, search_url: str) -> dict | None:
    lot_id = parse_bidcars_lot_id(str(raw.get("lot_id") or raw.get("url") or ""))
    if not lot_id:
        return None
    title = _clean_field(raw.get("title"), max_len=160) or ""
    if not title:
        title = title_from_url(str(raw.get("url") or "")) or f"Lot {lot_id}"
    year, make, model = _year_make_model(title)
    if not year:
        year = _int_year(raw.get("year"))
    if not make:
        make = _clean_field(raw.get("make"), max_len=40)
        if make:
            make = make.upper()
    if not model:
        model = _clean_field(raw.get("model"), max_len=80)
    href = str(raw.get("url") or "").strip()
    if href and not href.startswith("http"):
        href = f"https://bid.cars{href}" if href.startswith("/") else ""
    if not href:
        parsed = urlparse(search_url)
        lang = "ru"
        parts = [p for p in (parsed.path or "").split("/") if p]
        if parts and len(parts[0]) == 2:
            lang = parts[0]
        href = f"https://bid.cars/{lang}/lot/0-{lot_id}"
    vin = str(raw.get("vin") or "").strip().upper()
    if vin and not VIN_RE.fullmatch(vin):
        vin = ""
    return {
        "lot_id": bidcars_store_lot_id(lot_id),
        "title": title,
        "year": year,
        "make": make,
        "model": model,
        "vin": vin or None,
        "url": href.split("?")[0].rstrip("/"),
        "location": _clean_field(raw.get("location"), max_len=80),
        "odometer": _odometer_miles(raw.get("odometer")),
        "bid": _num(raw.get("bid")),
        "sale_date": _clean_field(raw.get("sale_date"), max_len=80),
        "primary_damage": _clean_field(raw.get("primary_damage"), max_len=40),
        "body_style": _clean_field(raw.get("body_style"), max_len=40),
        "images": [
            str(u).strip()
            for u in (raw.get("images") or [])
            if str(u or "").strip().startswith("http")
        ][:12],
        "source": "bidcars",
        "category": None,
        "vat_on_sale": None,
    }


def _int_year(value: Any) -> int | None:
    try:
        year = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2100:
        return year
    return None


def extract_bidcars_search(page: Any, url: str, *, max_pages: int = 8) -> list[dict]:
    canonical = normalize_bidcars_search_url(url)
    limit = max_pages if max_pages and max_pages > 0 else 8
    lots_by_id: dict[str, dict] = {}
    log.info("Bid.cars поиск: открываю %s (до %s стр.)", canonical, limit)
    target = canonical
    for page_no in range(1, limit + 1):
        try:
            href_now = (page.url or "").strip()
            if href_now and href_now != "about:blank":
                page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass
        page.goto(target, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_function(
                """() => {
                  const links = document.querySelectorAll('a[href*="/lot/"]').length;
                  const next = document.querySelector("#__NEXT_DATA__");
                  return links > 0 || (next && next.textContent && next.textContent.length > 200);
                }""",
                timeout=25000,
            )
        except Exception:
            page.wait_for_timeout(2500)
        try:
            page.evaluate("() => window.scrollBy(0, 1200)")
        except Exception:
            pass
        page.wait_for_timeout(1500)
        data: dict = {}
        try:
            raw = page.evaluate(BIDCARS_SEARCH_SCRIPT)
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}
        before = len(lots_by_id)
        for item in data.get("lots") or []:
            if not isinstance(item, dict):
                continue
            lot = _lot_from_search_item(item, canonical)
            if lot:
                lots_by_id[lot["lot_id"]] = lot
        added = len(lots_by_id) - before
        log.info("Bid.cars поиск стр. %s: +%s, всего %s", page_no, added, len(lots_by_id))
        if page_no >= limit:
            break
        # Для /automobile/page/N продолжаем, даже если дубли; стоп только если 0 новых
        if added == 0:
            break
        next_url = str(data.get("nextUrl") or "").strip()
        if next_url and "bid.cars" in next_url.lower():
            target = next_url.split("#")[0]
        else:
            target = _search_page_url(canonical, page_no + 1)
    return list(lots_by_id.values())
