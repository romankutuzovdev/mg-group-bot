from __future__ import annotations

import re
from typing import Any

VAT_RATE = 0.2
TRANSFER_FEE_RATE = 0.03
LOT_RETRIEVAL_FEE = 50.0
DISMANTLE_WEIGHT_BASE = 800.0
DISMANTLE_WEIGHT_PER_KG = 1.6
DISMANTLE_FROM_TYPE = {
    "sedan": "car",
    "suv": "suv",
    "sprinter": "van",
    "pickup": "pickup",
}

DELIVERY_RATES = {
    "DEFAULT": {"sedan": 300, "jeep": 350, "bus": 500},
    "ROCHFORD": {"sedan": 130, "jeep": 160, "bus": 200},
    "COLCHESTER": {"sedan": 190, "jeep": 230, "bus": 285},
    "SANDY": {"sedan": 180, "jeep": 230, "bus": 330},
    "SANDWICH": {"sedan": 130, "jeep": 160, "bus": 200},
    "NEWBURY": {"sedan": 220, "jeep": 260, "bus": 330},
    "WISBECH": {"sedan": 230, "jeep": 280, "bus": 380},
    "CORBY": {"sedan": 230, "jeep": 280, "bus": 380},
    "WESTBURY": {"sedan": 320, "jeep": 380, "bus": 480},
    "BRISTOL": {"sedan": 300, "jeep": 350, "bus": 500},
    "WOLVERHAMPTON": {"sedan": 320, "jeep": 350, "bus": 500},
    "SANDTOFT": {"sedan": 370, "jeep": 420, "bus": 570},
    "CHESTER": {"sedan": 420, "jeep": 470, "bus": 600},
    "YORK": {"sedan": 410, "jeep": 460, "bus": 600},
    "PETERLEE": {"sedan": 470, "jeep": 570, "bus": 650},
    "WHITBURN": {"sedan": 910, "jeep": 1100, "bus": 1365},
    "EAST KILBRIDE": {"sedan": 880, "jeep": 1060, "bus": 1320},
    "GLOUCESTER": {"sedan": 300, "jeep": 350, "bus": 500},
}

DELIVERY_COLUMN_LABEL = {"sedan": "Седан", "jeep": "Джип", "bus": "Бус"}

DISMANTLE_TARIFFS_USD = {
    "sedan": 2200,
    "suv": 2450,
    "sprinter": 2350,
    "pickup": 2650,
}

COPART_BODY_RULES = [
    ("motorcycle", "sedan", re.compile(r"\b(motor\s*cycles?|motorbikes?|scooters?|mopeds?|quads?|atvs?)\b", re.I)),
    ("pickup", "pickup", re.compile(r"\b(pick[\s-]?ups?|double\s*cabs?|crew\s*cabs?|пикап)\b", re.I)),
    ("van", "sprinter", re.compile(r"\b(sprinters?|minibuses?|mini\s*buses?|микроавтобус|people\s*carriers?|mpvs?|panel\s*vans?|combi\s*vans?|crew\s*vans?|box\s*vans?|lutons?|campers?|motorhomes?|minivans?|vans?|buses?)\b", re.I)),
    ("suv", "suv", re.compile(r"\b(suvs?|sport\s*utility|4\s*[xх]\s*4s?|crossovers?|jeeps?|estates?|wagons?|station\s*wagons?|внедорожник)\b", re.I)),
    ("pickup", "pickup", re.compile(r"\b(trucks?|lorries?|tippers?|dropsides?|chassis\s*cabs?)\b", re.I)),
    ("car", "sedan", re.compile(r"\b(hatchbacks?|hatches?|saloons?|sedans?|coupes?|coup[eé]s?|convertibles?|cabriolets?|roadsters?|targas?|limousines?|fastbacks?|hardtops?|soft\s*tops?|седан)\b", re.I)),
]

BUYER_FEE_BANDS = [
    (49.99, 5, 20),
    (99.99, 20, 65),
    (199.99, 45, 85),
    (299.99, 65, 105),
    (349.99, 75, 115),
    (399.99, 85, 125),
    (449.99, 95, 135),
    (499.99, 100, 140),
    (549.99, 105, 145),
    (599.99, 115, 150),
    (699.99, 125, 165),
    (799.99, 140, 180),
    (899.99, 155, 195),
    (999.99, 170, 210),
    (1199.99, 185, 225),
    (1299.99, 205, 245),
    (1399.99, 215, 255),
    (1499.99, 225, 265),
    (1599.99, 235, 275),
    (1699.99, 245, 285),
    (1799.99, 260, 300),
    (1999.99, 270, 310),
    (2399.99, 300, 340),
    (2499.99, 325, 365),
    (2999.99, 350, 390),
    (3499.99, 385, 425),
    (3999.99, 425, 465),
    (4499.99, 470, 510),
    (4999.99, 495, 535),
    (5999.99, 515, 555),
    (7499.99, 525, 565),
    (9999.99, 550, 590),
]

LIVE_BID_FEE_BANDS = [
    (99.99, 0),
    (499.99, 35),
    (999.99, 49),
    (1499.99, 69),
    (1999.99, 79),
    (3999.99, 89),
    (5999.99, 99),
    (7999.99, 105),
    (float("inf"), 109),
]


def round2(value: Any) -> float:
    return round(float(value or 0) * 100) / 100


def is_category_b(category: Any, title: str = "") -> bool:
    raw = str(category or "").strip().upper()
    if raw in {"B", "CAT B", "CATEGORY B", "CATB"}:
        return True
    return bool(re.search(r"\bCAT(?:EGORY)?\s*B\b", f"{category or ''} {title or ''}", re.I))


def classify_vehicle(hint: str) -> dict:
    blob = re.sub(r"[_/]+", " ", str(hint or "").lower())
    blob = re.sub(r"\s+", " ", blob).strip()
    for vehicle_type, dismantle_type, pattern in COPART_BODY_RULES:
        if pattern.search(blob):
            return {"vehicle_type": vehicle_type, "dismantle_type": dismantle_type, "matched": True}
    return {"vehicle_type": "car", "dismantle_type": "sedan", "matched": False}


def resolve_region(raw: str | None) -> str:
    name = re.sub(r"\s+", " ", str(raw or "")).strip().upper()
    if not name:
        return "DEFAULT"
    if name in DELIVERY_RATES:
        return name
    keys = [key for key in DELIVERY_RATES if key != "DEFAULT"]
    for key in keys:
        if key in name or name in key:
            return key
    return "DEFAULT"


def delivery_column(dismantle_type: str) -> str:
    if dismantle_type == "sprinter":
        return "bus"
    if dismantle_type in {"suv", "pickup"}:
        return "jeep"
    return "sedan"


def get_delivery(
    region: str | None,
    dismantle_type: str,
    category_b: bool,
    column_override: str | None = None,
) -> dict:
    key = resolve_region(region)
    rates = DELIVERY_RATES.get(key) or DELIVERY_RATES["DEFAULT"]
    base = delivery_column(dismantle_type)
    sedan_as_jeep = bool(category_b) and base == "sedan"
    auto_column = "jeep" if sedan_as_jeep else base
    picked = str(column_override or "").strip().lower()
    manual = picked in DELIVERY_COLUMN_LABEL
    column = picked if manual else auto_column
    if manual:
        sedan_as_jeep = False
    return {
        "region_key": key,
        "base_column": base,
        "auto_column": auto_column,
        "column": column,
        "sedan_as_jeep": sedan_as_jeep,
        "manual": manual,
        "amount": float(rates.get(column) or rates["sedan"]),
        "label": DELIVERY_COLUMN_LABEL.get(column, column),
    }


def get_buyer_fee(price: float, tier: str = "A") -> float:
    if price >= 10000:
        return round2(price * (0.065 if tier == "B" else 0.055))
    for max_price, fee_a, fee_b in BUYER_FEE_BANDS:
        if price <= max_price:
            return float(fee_b if tier == "B" else fee_a)
    return float(BUYER_FEE_BANDS[-1][2 if tier == "B" else 1])


def get_live_bid_fee(price: float) -> float:
    for max_price, fee in LIVE_BID_FEE_BANDS:
        if price <= max_price:
            return float(fee)
    return 109.0


def estimate_copart_wholesale(bid: float, vat_on_sale: bool) -> dict:
    sale = round2(bid)
    buyer_a = get_buyer_fee(sale, "A")
    buyer_b = get_buyer_fee(sale, "B")
    live_bid = get_live_bid_fee(sale)
    retrieval = LOT_RETRIEVAL_FEE
    fees_net = round2(buyer_a + live_bid + retrieval)
    vat_fees = round2(fees_net * VAT_RATE)
    vat_sale = round2(sale * VAT_RATE) if vat_on_sale else 0.0
    copart_total = round2(sale + fees_net + vat_fees + vat_sale)
    return {
        "bid": sale,
        "buyer_a": buyer_a,
        "buyer_b": buyer_b,
        "saving": round2(buyer_b - buyer_a),
        "live_bid": live_bid,
        "retrieval": retrieval,
        "fees_net": fees_net,
        "vat_fees": vat_fees,
        "vat_sale": vat_sale,
        "vat_on_sale": bool(vat_on_sale),
        "vat_sum": round2(vat_fees + vat_sale),
        "copart_total": copart_total,
    }


def quote_lot(
    *,
    bid: float | None,
    location: str | None = None,
    category: str | None = None,
    title: str = "",
    body_style: str | None = None,
    vat_on_sale: bool | None = None,
    dismantle_type: str | None = None,
    dismantle_kg: float | None = None,
    delivery_column: str | None = None,
    fx_rate: float | None = None,
) -> dict | None:
    if bid is None:
        return None
    classified = classify_vehicle(" ".join(part for part in (body_style, title) if part))
    dtype = str(dismantle_type or "").strip().lower()
    if dtype in DISMANTLE_TARIFFS_USD:
        classified = {
            "vehicle_type": DISMANTLE_FROM_TYPE.get(dtype, classified["vehicle_type"]),
            "dismantle_type": dtype,
            "matched": True,
        }
    category_b = is_category_b(category, title)
    # Cat B всегда VAT на ставку; иначе — флаг VAT с карточки лота
    vat = bool(category_b or vat_on_sale)
    copart = estimate_copart_wholesale(float(bid), vat)
    delivery = get_delivery(
        location,
        classified["dismantle_type"],
        category_b,
        column_override=delivery_column,
    )
    subtotal = round2(copart["copart_total"] + delivery["amount"])
    transfer_fee = round2(subtotal * TRANSFER_FEE_RATE)
    total = round2(subtotal + transfer_fee)
    kg = None if dismantle_kg in (None, "") else float(dismantle_kg)
    if kg and kg > 0:
        dismantle = round2(DISMANTLE_WEIGHT_BASE + DISMANTLE_WEIGHT_PER_KG * kg)
        dismantle_mode = "weight"
    else:
        dismantle = DISMANTLE_TARIFFS_USD[classified["dismantle_type"]]
        dismantle_mode = "tariff"
        kg = None
    result = {
        "copart": copart,
        "delivery": delivery,
        "subtotal": subtotal,
        "transfer_fee": transfer_fee,
        "total_uk": total,
        "dismantle_usd": dismantle,
        "dismantle_type": classified["dismantle_type"],
        "dismantle_mode": dismantle_mode,
        "dismantle_kg": kg,
        "vehicle_type": classified["vehicle_type"],
        "category_b": category_b,
        "fx_rate": None,
        "england_usd": None,
        "grand_usd": None,
    }
    if fx_rate not in (None, "") and float(fx_rate) > 0:
        rate = float(fx_rate)
        england = round2(total * rate)
        result["fx_rate"] = rate
        result["england_usd"] = england
        result["grand_usd"] = round2(england + dismantle)
    return result


def format_quote_text(lot: dict, quote: dict) -> str:
    copart = quote["copart"]
    delivery = quote["delivery"]
    if delivery.get("manual"):
        note = f"{delivery['region_key']}, {delivery['label']} (вручную)"
    elif delivery.get("sedan_as_jeep"):
        note = f"{delivery['region_key']}, седан как джип (Cat B)"
    else:
        note = f"{delivery['region_key']}, {delivery['label']}"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        "Расчёт Copart UK",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if lot.get("title"):
        lines.append(str(lot["title"]))
    if lot.get("url"):
        lines.append(str(lot["url"]))
    if lot.get("title") or lot.get("url"):
        lines.append("")
    lines.extend(
        [
            f"Регион: {lot.get('location') or delivery['region_key']}",
            f"Тип авто: {quote['dismantle_type']}",
        ]
    )
    if quote.get("category_b") or copart.get("vat_on_sale"):
        lines.append(
            "Категория B — VAT на комиссии и на ставку"
            if quote.get("category_b")
            else "VAT на комиссии и на ставку"
        )
    lines.extend(
        [
            "",
            f"Ставка: £{copart['bid']:,.2f}",
            f"Buyer fee (опт): £{copart['buyer_a']:,.2f}",
            f"Live bid fee: £{copart['live_bid']:,.2f}",
            f"Lot retrieval: £{copart['retrieval']:,.2f}",
            f"VAT 20% на комиссии: £{copart['vat_fees']:,.2f}",
        ]
    )
    if copart.get("vat_on_sale") and copart.get("vat_sale"):
        lines.append(
            f"VAT 20% на ставку{' (Cat B)' if quote.get('category_b') else ''}: £{copart['vat_sale']:,.2f}"
        )
    lines.extend(
        [
            f"VAT итого: £{copart['vat_sum']:,.2f}",
            "────────────────────",
            f"Copart Total: £{copart['copart_total']:,.2f}",
            f"Доставка: £{delivery['amount']:,.2f} ({note})",
            f"Комиссия за перевод 3%: £{quote['transfer_fee']:,.2f}",
            "────────────────────",
            f"Итого UK: £{quote['total_uk']:,.2f}",
            "",
        ]
    )
    if quote.get("fx_rate"):
        lines.append(f"Курс GBP→USD: {quote['fx_rate']}")
        lines.append(f"Расходы Англии: ${quote['england_usd']:,.2f}")
    else:
        lines.append("Курс GBP→USD: не указан")
    if quote.get("dismantle_mode") == "weight" and quote.get("dismantle_kg"):
        kg = quote["dismantle_kg"]
        lines.append(
            f"Разбор: ${quote['dismantle_usd']:,.2f} (800 USD + 1.6 × {kg:g} кг)"
        )
    else:
        lines.append(f"Разбор: ${quote['dismantle_usd']:,.2f} ({quote['dismantle_type']})")
    if quote.get("grand_usd") is not None:
        lines.append(f"Итого с разбором: ${quote['grand_usd']:,.2f}")
    return "\n".join(lines)
