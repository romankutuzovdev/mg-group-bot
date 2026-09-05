from __future__ import annotations

from calculator import (
    TRANSFER_FEE_RATE,
    classify_vehicle,
    round2,
)

# IAAI USA — по умолчанию Standard (как на обычном аккаунте Bid.cars / IAAI).
# High Volume — опт: ниже buyer fee и ниже service/environmental.
# Официальные цифры на аккаунте могут чуть отличаться — сверяйте invoice.

# Standard (аккаунт пользователя): Service $105, Environmental $15
IAAI_SERVICE_FEE_STANDARD = 105.0
IAAI_ENVIRONMENTAL_FEE_STANDARD = 15.0
# High Volume (опт): Service $79, Environmental $10
IAAI_SERVICE_FEE_HIGH = 79.0
IAAI_ENVIRONMENTAL_FEE_HIGH = 10.0
IAAI_TITLE_FEE = 20.0
# алиасы для старого кода
IAAI_SERVICE_FEE = IAAI_SERVICE_FEE_STANDARD
IAAI_ENVIRONMENTAL_FEE = IAAI_ENVIRONMENTAL_FEE_STANDARD
USA_DISPATCHING_USD = 200.0
USA_DISMANTLE_WEIGHT_BASE = 1300.0
USA_DISMANTLE_WEIGHT_PER_KG = 2.2

# Тарифы разбора USA (премиум).
USA_DISMANTLE_TARIFFS_USD = {
    "sedan": 4100.0,       # Легковые авто
    "suv": 4450.0,         # Внедорожник / кроссовер
    "frame_suv": 4850.0,   # Рамный внедорожник
}

USA_DISMANTLE_FROM_TYPE = {
    "sedan": "car",
    "suv": "suv",
    "frame_suv": "pickup",
    # алиасы UK-классификации → USA
    "sprinter": "car",
    "pickup": "pickup",
}

# UK типы / синонимы → ключ тарифа USA
USA_DISMANTLE_ALIASES = {
    "sedan": "sedan",
    "sprinter": "sedan",
    "suv": "suv",
    "pickup": "frame_suv",
    "frame_suv": "frame_suv",
}

# (max_price, high_volume_fee, standard_fee)
IAAI_BUYER_FEE_BANDS = [
    (49.99, 0, 25),
    (99.99, 0, 45),
    (199.99, 25, 80),
    (299.99, 60, 130),
    (349.99, 85, 137),
    (399.99, 100, 145),
    (449.99, 125, 175),
    (499.99, 135, 185),
    (549.99, 145, 205),
    (599.99, 155, 210),
    (699.99, 170, 240),
    (799.99, 195, 270),
    (899.99, 215, 295),
    (999.99, 230, 320),
    (1199.99, 250, 375),
    (1299.99, 270, 395),
    (1399.99, 285, 410),
    (1499.99, 300, 430),
    (1599.99, 315, 445),
    (1699.99, 330, 465),
    (1799.99, 350, 485),
    (1999.99, 370, 510),
    (2399.99, 390, 535),
    (2499.99, 425, 570),
    (2999.99, 460, 610),
    (3499.99, 505, 655),
    (3999.99, 555, 705),
    (4499.99, 600, 725),
    (4999.99, 625, 750),
    (5499.99, 650, 775),
    (5999.99, 675, 800),
    (6499.99, 700, 825),
    (6999.99, 720, 845),
    (7499.99, 755, 880),
    (7999.99, 775, 900),
    (8499.99, 800, 925),
    (9999.99, 820, 945),
    (11499.99, 850, 1000),
    (11999.99, 860, 1000),
    (12499.99, 875, 1000),
    (14999.99, 890, 1000),
]

# (max_price, live_fee, proxy_fee)
IAAI_VIRTUAL_BID_BANDS = [
    (99.99, 0, 0),
    (499.99, 50, 40),
    (999.99, 65, 55),
    (1499.99, 85, 75),
    (1999.99, 95, 85),
    (3999.99, 110, 100),
    (5999.99, 125, 110),
    (7999.99, 145, 125),
    (float("inf"), 160, 140),
]


def get_iaai_buyer_fee(price: float, *, volume: str = "high") -> float:
    sale = float(price or 0)
    high = volume != "standard"
    if sale >= 15000:
        return round2(sale * (0.06 if high else 0.075))
    for max_price, fee_hv, fee_std in IAAI_BUYER_FEE_BANDS:
        if sale <= max_price:
            return float(fee_hv if high else fee_std)
    return round2(sale * (0.06 if high else 0.075))


def get_iaai_virtual_bid_fee(price: float, method: str = "live") -> float:
    sale = float(price or 0)
    proxy = str(method or "live").strip().lower() == "proxy"
    for max_price, live_fee, proxy_fee in IAAI_VIRTUAL_BID_BANDS:
        if sale <= max_price:
            return float(proxy_fee if proxy else live_fee)
    return 140.0 if proxy else 160.0


def estimate_iaai_wholesale(
    bid: float,
    *,
    bid_method: str = "live",
    volume: str = "standard",
) -> dict:
    sale = round2(bid)
    buyer_hv = get_iaai_buyer_fee(sale, volume="high")
    buyer_std = get_iaai_buyer_fee(sale, volume="standard")
    is_high = str(volume or "standard").strip().lower() == "high"
    buyer = buyer_hv if is_high else buyer_std
    method = "proxy" if str(bid_method).strip().lower() == "proxy" else "live"
    virtual = get_iaai_virtual_bid_fee(sale, method)
    if is_high:
        service = IAAI_SERVICE_FEE_HIGH
        environmental = IAAI_ENVIRONMENTAL_FEE_HIGH
    else:
        service = IAAI_SERVICE_FEE_STANDARD
        environmental = IAAI_ENVIRONMENTAL_FEE_STANDARD
    title = IAAI_TITLE_FEE
    fixed = round2(service + environmental + title)
    fees_net = round2(buyer + virtual + fixed)
    total = round2(sale + fees_net)
    return {
        "auction": "iaai",
        "market": "US",
        "currency": "USD",
        "volume": "high" if is_high else "standard",
        "volume_label": "Опт (High Volume)" if is_high else "Standard",
        "bid": sale,
        "buyer_fee": buyer,
        "buyer_fee_high": buyer_hv,
        "buyer_fee_standard": buyer_std,
        "saving_vs_standard": round2(buyer_std - buyer_hv) if is_high else 0.0,
        "saving_vs_high": round2(buyer_std - buyer_hv) if not is_high else 0.0,
        "bid_method": method,
        "virtual_bid": virtual,
        "service_fee": service,
        "environmental_fee": environmental,
        "title_fee": title,
        "fixed_fees": fixed,
        "fees_net": fees_net,
        "iaai_total": total,
    }


def quote_iaai(
    *,
    bid: float | None,
    title: str = "",
    body_style: str | None = None,
    dismantle_type: str | None = None,
    dismantle_kg: float | None = None,
    bid_method: str = "live",
    volume: str = "standard",
    inland_usd: float | None = None,
    ocean_usd: float | None = None,
    bidcars_fee_usd: float | None = None,
    destination_port: str | None = None,
    ship_from: str | None = None,
    location: str | None = None,
    inland_miles: float | None = None,
    us_port: str | None = None,
    us_port_label: str | None = None,
    miles_to_new_jersey: float | None = None,
    miles_to_houston: float | None = None,
    distance_source: str | None = None,
    include_america_delivery: bool = False,
) -> dict | None:
    if bid is None:
        return None
    classified = classify_vehicle(" ".join(part for part in (body_style, title) if part))
    raw_type = str(dismantle_type or classified.get("dismantle_type") or "sedan").strip().lower()
    dtype = USA_DISMANTLE_ALIASES.get(raw_type, "sedan")
    classified = {
        "vehicle_type": USA_DISMANTLE_FROM_TYPE.get(dtype, classified["vehicle_type"]),
        "dismantle_type": dtype,
        "matched": True,
    }
    iaai = estimate_iaai_wholesale(float(bid), bid_method=bid_method, volume=volume)
    kg = None if dismantle_kg in (None, "") else float(dismantle_kg)
    if kg and kg > 0:
        dismantle = round2(USA_DISMANTLE_WEIGHT_BASE + USA_DISMANTLE_WEIGHT_PER_KG * kg)
        dismantle_mode = "weight"
    else:
        dismantle = USA_DISMANTLE_TARIFFS_USD[classified["dismantle_type"]]
        dismantle_mode = "tariff"
        kg = None

    delivery = None
    america_subtotal = iaai["iaai_total"]
    if include_america_delivery:
        from bidcars import PORT_LABEL, inland_default
        from usa_distance import resolve_us_inland

        port = str(destination_port or "rotterdam").strip().lower()
        if port not in PORT_LABEL:
            port = "rotterdam"

        # Мили только от Местоположение (location), не от «Отправка из»
        route = None
        if inland_usd in (None, "") or inland_miles in (None, ""):
            route = resolve_us_inland(location, None, allow_chrome_maps=False)

        if inland_usd not in (None, ""):
            inland = round2(inland_usd)
        elif route and route.get("inland_usd") is not None:
            inland = round2(route["inland_usd"])
        else:
            inland = round2(inland_default(location or ship_from))

        miles = inland_miles
        if miles in (None, "") and route:
            miles = route.get("inland_miles")
        if miles in (None, "") and inland is not None:
            miles = float(inland)

        chosen_us_port = us_port or (route or {}).get("us_port")
        chosen_us_label = us_port_label or (route or {}).get("us_port_label")
        nj = miles_to_new_jersey if miles_to_new_jersey not in (None, "") else (route or {}).get("miles_to_new_jersey")
        hu = miles_to_houston if miles_to_houston not in (None, "") else (route or {}).get("miles_to_houston")
        src = distance_source or (route or {}).get("distance_source")

        ocean = 0.0
        fee = 0.0
        shipping_total = round2(inland)
        america_subtotal = round2(iaai["iaai_total"] + inland)
        delivery = {
            "from": "USA",
            "location": location,
            "ship_from": ship_from,
            "us_port": chosen_us_port,
            "us_port_label": chosen_us_label,
            "inland_miles": None if miles in (None, "") else round(float(miles), 1),
            "miles_to_new_jersey": None if nj in (None, "") else round(float(nj), 1),
            "miles_to_houston": None if hu in (None, "") else round(float(hu), 1),
            "distance_source": src,
            "rate_usd_per_mile": 1.0,
            "destination_port": port,
            "destination_label": PORT_LABEL[port],
            "inland_usd": inland,
            "ocean_usd": ocean,
            "bidcars_fee_usd": fee,
            "shipping_total_usd": shipping_total,
            "america_subtotal_usd": america_subtotal,
        }

    dispatching = USA_DISPATCHING_USD
    transfer_fee = round2(america_subtotal * TRANSFER_FEE_RATE)
    usa_with_fees = round2(america_subtotal + dispatching + transfer_fee)

    return {
        "auction": "iaai",
        "iaai": iaai,
        "delivery_usa": delivery,
        "subtotal_usa": america_subtotal,
        "dispatching_usd": dispatching,
        "transfer_fee": transfer_fee,
        "transfer_fee_rate": TRANSFER_FEE_RATE,
        "usa_with_fees": usa_with_fees,
        "dismantle_usd": dismantle,
        "dismantle_type": classified["dismantle_type"],
        "dismantle_mode": dismantle_mode,
        "dismantle_kg": kg,
        "vehicle_type": classified["vehicle_type"],
        "grand_usd": round2(usa_with_fees + dismantle),
    }


def format_iaai_quote_text(lot: dict, quote: dict) -> str:
    iaai = quote["iaai"]
    is_high = iaai.get("volume") == "high"
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"Расчёт IAAI USA — {iaai.get('volume_label') or 'Standard'}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if lot.get("title"):
        lines.append(str(lot["title"]))
    if lot.get("url"):
        lines.append(str(lot["url"]))
    if lot.get("title") or lot.get("url"):
        lines.append("")
    if lot.get("location"):
        lines.append(f"Местоположение: {lot.get('location')}")
    buyer_line = f"Buyer Fee: ${iaai['buyer_fee']:,.2f}"
    if is_high:
        buyer_line = (
            f"Buyer Fee (опт): ${iaai['buyer_fee']:,.2f}"
            f"  (Standard было бы ${iaai['buyer_fee_standard']:,.2f},"
            f" экономия ${iaai['saving_vs_standard']:,.2f})"
        )
    lines.extend(
        [
            f"Тип авто: {quote['dismantle_type']}",
            f"Покупатель: {iaai['volume_label']}",
            f"Ставка online: {'Live' if iaai['bid_method'] == 'live' else 'Proxy'}",
            "",
            f"Bid Amount: ${iaai['bid']:,.2f}",
            buyer_line,
            f"Internet Bid Fee: ${iaai['virtual_bid']:,.2f}",
            f"Service Fee: ${iaai['service_fee']:,.2f}",
            f"Environmental Fee: ${iaai['environmental_fee']:,.2f}",
            f"Title Handling Fee: ${iaai['title_fee']:,.2f}",
            "────────────────────",
            f"IAAI Total / Estimated Final Cost: ${iaai['iaai_total']:,.2f}",
        ]
    )
    delivery = quote.get("delivery_usa")
    if delivery:
        lines.extend(
            [
                "",
                "Порт вывоза США",
                f"Местоположение → New Jersey: {delivery.get('miles_to_new_jersey') or '—'} mi",
                f"Местоположение → Houston: {delivery.get('miles_to_houston') or '—'} mi",
                f"Ближе: {delivery.get('us_port_label') or '—'} · {delivery.get('inland_miles') or '—'} mi ($1/mi)",
                f"До разборки США (от {delivery.get('location') or 'местоположения'}): {delivery.get('inland_miles') or '—'} mi → ${delivery['inland_usd']:,.2f}",
            ]
        )
    lines.append("")
    lines.append(f"Диспетчинг: ${quote['dispatching_usd']:,.2f}")
    lines.append(
        f"Комиссия за перевод 3%: ${quote['transfer_fee']:,.2f}"
        f" (${quote['subtotal_usa']:,.2f} × 3%)"
    )
    lines.append("────────────────────")
    lines.append(f"Расходы США: ${quote['usa_with_fees']:,.2f}")
    lines.append("")
    usa_labels = {
        "sedan": "Легковые авто (премиум)",
        "suv": "Внедорожник / кроссовер (премиум)",
        "frame_suv": "Рамный внедорожник (премиум)",
    }
    if quote.get("dismantle_mode") == "weight" and quote.get("dismantle_kg"):
        kg = quote["dismantle_kg"]
        lines.append(
            f"Разбор США: ${quote['dismantle_usd']:,.2f} (1300 USD + 2.2 × {kg:g} кг)"
        )
    else:
        dtype = quote["dismantle_type"]
        label = usa_labels.get(dtype, dtype)
        lines.append(f"Разбор США: ${quote['dismantle_usd']:,.2f} ({label})")
    if quote.get("grand_usd") is not None:
        lines.append(f"Итого с разбором: ${quote['grand_usd']:,.2f}")
    return "\n".join(lines)
