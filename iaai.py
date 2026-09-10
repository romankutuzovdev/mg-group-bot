from __future__ import annotations

from calculator import (
    classify_vehicle,
    round2,
)

# Комиссия за перевод для расчётов USA (IAAI / восстановление)
USA_TRANSFER_FEE_RATE = 0.035
# Copart Sublot / IAAI Offsite — доплата за вывоз с дополнительной площадки
SUBLOT_FEE_USD = 100.0

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
USA_DISPATCHING_USD = 250.0
USA_DISMANTLE_WEIGHT_BASE = 1300.0
USA_DISMANTLE_WEIGHT_PER_KG = 2.2

# Тарифы разбора USA (премиум).
USA_DISMANTLE_TARIFFS_USD = {
    "sedan": 4100.0,       # Легковые авто
    "suv": 4450.0,         # Внедорожник / кроссовер
    "frame_suv": 4850.0,   # Рамный внедорожник
}

# Тарифы «авто под восстановление» по размеру машины.
RESTORATION_VEHICLE_SIZES = ("regular", "oversize", "moto")
RESTORATION_SIZE_LABELS = {
    "regular": "Regular / Large",
    "oversize": "Oversize",
    "moto": "Moto",
}
# Пока те же порядки, что разбор USA — поменяем, когда дадите точные цифры.
RESTORATION_SIZE_TARIFFS_USD = {
    "regular": 4100.0,
    "oversize": 4850.0,
    "moto": 1800.0,
}
RESTORATION_OCEAN_USD = {
    "regular": 1095.0,
    "oversize": 1595.0,
    "moto": 650.0,
}
RESTORATION_DISMANTLE_TARIFFS_USD = {
    "sedan": 4100.0,
    "suv": 4450.0,
    "frame_suv": 4850.0,
}
RESTORATION_DISMANTLE_WEIGHT_BASE = 1300.0
RESTORATION_DISMANTLE_WEIGHT_PER_KG = 2.2

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


def estimate_bidcars_auction_fees(bid: float, auction_fees_usd: float) -> dict:
    """Аукционные сборы с карточки Bid.cars — без Live/Proxy и без Standard/High."""
    sale = round2(bid)
    fees = round2(float(auction_fees_usd or 0))
    return {
        "auction": "bidcars",
        "market": "US",
        "currency": "USD",
        "volume": "bidcars",
        "volume_label": "Bid.cars",
        "bid": sale,
        "buyer_fee": 0.0,
        "buyer_fee_high": 0.0,
        "buyer_fee_standard": 0.0,
        "saving_vs_standard": 0.0,
        "saving_vs_high": 0.0,
        "bid_method": "bidcars",
        "virtual_bid": 0.0,
        "service_fee": 0.0,
        "environmental_fee": 0.0,
        "title_fee": 0.0,
        "fixed_fees": 0.0,
        "auction_fees_usd": fees,
        "fees_net": fees,
        "iaai_total": round2(sale + fees),
        "fees_source": "bidcars",
    }


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
    purpose: str = "iaai",
    vehicle_size: str | None = None,
    auction_platform: str | None = None,
    ocean_destination: str | None = None,
    documents: str | None = None,
    title_code: str | None = None,
    is_sublot: bool | None = None,
    sublot_location: str | None = None,
    auction_fees_usd: float | None = None,
) -> dict | None:
    if bid is None:
        return None
    is_restoration = str(purpose or "").strip().lower() == "restoration"
    size_raw = str(vehicle_size or "").strip().lower().replace(" ", "_").replace("-", "_")
    if size_raw in {"regular_large", "large", "reg"}:
        size_raw = "regular"
    if size_raw not in RESTORATION_VEHICLE_SIZES:
        size_raw = "regular" if is_restoration else ""
    tariffs = RESTORATION_DISMANTLE_TARIFFS_USD if is_restoration else USA_DISMANTLE_TARIFFS_USD
    weight_base = RESTORATION_DISMANTLE_WEIGHT_BASE if is_restoration else USA_DISMANTLE_WEIGHT_BASE
    weight_per_kg = RESTORATION_DISMANTLE_WEIGHT_PER_KG if is_restoration else USA_DISMANTLE_WEIGHT_PER_KG
    classified = classify_vehicle(" ".join(part for part in (body_style, title) if part))
    raw_type = str(dismantle_type or classified.get("dismantle_type") or "sedan").strip().lower()
    dtype = USA_DISMANTLE_ALIASES.get(raw_type, "sedan")
    classified = {
        "vehicle_type": USA_DISMANTLE_FROM_TYPE.get(dtype, classified["vehicle_type"]),
        "dismantle_type": dtype,
        "matched": True,
    }
    # Восстановление: аукционные сборы только с Bid.cars (без Live/Proxy и Standard/High).
    if is_restoration:
        fees = float(auction_fees_usd) if auction_fees_usd is not None else 0.0
        iaai = estimate_bidcars_auction_fees(float(bid), fees)
    else:
        iaai = estimate_iaai_wholesale(float(bid), bid_method=bid_method, volume=volume)
    kg = None if dismantle_kg in (None, "") else float(dismantle_kg)
    if is_restoration:
        # Для «под восстановление» отдельный тариф разбора не считаем — только аукцион + доставка.
        dismantle = 0.0
        dismantle_mode = "none"
        kg = None
    elif kg and kg > 0:
        dismantle = round2(weight_base + weight_per_kg * kg)
        dismantle_mode = "weight"
    else:
        dismantle = tariffs[classified["dismantle_type"]]
        dismantle_mode = "tariff"
        kg = None

    title_doc_text = str(title_code or documents or "").strip() or None
    title_fee_info = None
    title_doc_usd = 0.0
    if is_restoration and title_doc_text:
        from usa_title import lookup_title_fee

        title_fee_info = lookup_title_fee(title_doc_text)
        if title_fee_info and title_fee_info.get("cost_usd") is not None:
            title_doc_usd = round2(title_fee_info["cost_usd"])
        # unmatched → 0 в сумме, но в UI будет предупреждение
    elif is_restoration and not title_doc_text:
        title_fee_info = None
        title_doc_usd = 0.0

    sublot_on = bool(is_sublot)
    sublot_addr = str(sublot_location or "").strip() or None
    sublot_usd = round2(SUBLOT_FEE_USD) if sublot_on else 0.0

    delivery = None
    america_subtotal = iaai["iaai_total"]
    if include_america_delivery:
        from bidcars import PORT_LABEL, inland_default
        from usa_distance import resolve_us_inland
        from usa_tariffs import lookup_usa_delivery

        port = str(destination_port or "rotterdam").strip().lower()
        if port not in PORT_LABEL:
            port = "rotterdam"

        tariff = None
        if is_restoration:
            # Для восстановления inland/море — из прайса Copart/IAAI + B2B, не мили.
            # Клиентский inland_usd с lookup миль игнорируем.
            tariff = lookup_usa_delivery(
                location,
                size_raw or "regular",
                auction=auction_platform or "iaai",
                ocean_destination=str(ocean_destination or "klaipeda").strip().lower() or "klaipeda",
            )

        route = None
        if not tariff and (inland_usd in (None, "") or inland_miles in (None, "")):
            route = resolve_us_inland(location, None, allow_chrome_maps=False)

        if tariff and tariff.get("inland_usd") is not None:
            inland = round2(tariff["inland_usd"])
        elif inland_usd not in (None, "") and not is_restoration:
            inland = round2(inland_usd)
        elif route and route.get("inland_usd") is not None:
            inland = round2(route["inland_usd"])
        else:
            inland = round2(inland_default(location or ship_from))

        miles = None if tariff else inland_miles
        if miles in (None, "") and route:
            miles = route.get("inland_miles")
        if miles in (None, "") and not tariff and inland is not None:
            miles = float(inland)

        if tariff:
            chosen_us_port = tariff.get("us_port")
            chosen_us_label = tariff.get("us_port_label")
            nj = None
            hu = None
            src = "MG GROUP tariff"
        else:
            chosen_us_port = us_port or (route or {}).get("us_port")
            chosen_us_label = us_port_label or (route or {}).get("us_port_label")
            nj = miles_to_new_jersey if miles_to_new_jersey not in (None, "") else (route or {}).get("miles_to_new_jersey")
            hu = miles_to_houston if miles_to_houston not in (None, "") else (route or {}).get("miles_to_houston")
            src = distance_source or (route or {}).get("distance_source")

        ocean = 0.0
        if ocean_usd not in (None, ""):
            ocean = round2(ocean_usd)
        elif tariff and tariff.get("ocean_usd") is not None:
            ocean = round2(tariff["ocean_usd"])
        elif is_restoration and size_raw:
            ocean = round2(RESTORATION_OCEAN_USD.get(size_raw, RESTORATION_OCEAN_USD["regular"]))
        fee = 0.0
        shipping_total = round2(inland + ocean)
        america_subtotal = round2(iaai["iaai_total"] + inland + ocean + title_doc_usd + sublot_usd)
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
            "rate_usd_per_mile": None if tariff else 1.0,
            "destination_port": port,
            "destination_label": PORT_LABEL[port],
            "inland_usd": inland,
            "ocean_usd": ocean,
            "ocean_destination": (tariff or {}).get("ocean_destination") or ocean_destination or "klaipeda",
            "vehicle_size": size_raw or None,
            "vehicle_size_label": RESTORATION_SIZE_LABELS.get(size_raw) if size_raw else None,
            "matched_yard": (tariff or {}).get("matched_location"),
            "matched_auction": (tariff or {}).get("matched_auction"),
            "tariff_source": (tariff or {}).get("tariff_source"),
            "price_sheet": (tariff or {}).get("price_sheet"),
            "bidcars_fee_usd": fee,
            "shipping_total_usd": shipping_total,
            "america_subtotal_usd": america_subtotal,
        }
    elif is_restoration and (title_doc_usd or sublot_usd):
        america_subtotal = round2(iaai["iaai_total"] + title_doc_usd + sublot_usd)

    dispatching = USA_DISPATCHING_USD
    transfer_fee = round2(america_subtotal * USA_TRANSFER_FEE_RATE)
    usa_with_fees = round2(america_subtotal + dispatching + transfer_fee)

    return {
        "auction": "iaai",
        "purpose": "restoration" if is_restoration else "iaai",
        "vehicle_size": size_raw or None,
        "vehicle_size_label": RESTORATION_SIZE_LABELS.get(size_raw) if size_raw else None,
        "iaai": iaai,
        "delivery_usa": delivery,
        "subtotal_usa": america_subtotal,
        "dispatching_usd": dispatching,
        "transfer_fee": transfer_fee,
        "transfer_fee_rate": USA_TRANSFER_FEE_RATE,
        "usa_with_fees": usa_with_fees,
        "dismantle_usd": dismantle,
        "dismantle_type": classified["dismantle_type"],
        "dismantle_mode": dismantle_mode,
        "dismantle_kg": kg,
        "dismantle_label": None if is_restoration else "Разбор США",
        "vehicle_type": classified["vehicle_type"],
        "title_document": title_doc_text,
        "title_fee_info": title_fee_info,
        "title_doc_usd": title_doc_usd if is_restoration else None,
        "is_sublot": sublot_on if is_restoration else None,
        "sublot_location": sublot_addr if is_restoration else None,
        "sublot_usd": sublot_usd if is_restoration and sublot_on else (0.0 if is_restoration else None),
        # Восстановление: без тарифа разбора — итого = расходы США.
        "grand_usd": round2(usa_with_fees if is_restoration else usa_with_fees + dismantle),
    }


def format_iaai_quote_text(lot: dict, quote: dict) -> str:
    iaai = quote["iaai"]
    is_high = iaai.get("volume") == "high"
    fees_from_bidcars = iaai.get("fees_source") == "bidcars" or (
        quote.get("purpose") == "restoration" and iaai.get("auction_fees_usd") is not None
    )
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        (
            "Расчёт под восстановление"
            if quote.get("purpose") == "restoration"
            else f"Расчёт IAAI USA — {iaai.get('volume_label') or 'Standard'}"
        ),
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
    if fees_from_bidcars:
        lines.extend(
            [
                f"Тип авто: {quote.get('vehicle_size_label') or quote['dismantle_type']}",
                "",
                f"Bid Amount: ${iaai['bid']:,.2f}",
                f"Аукционные сборы (Bid.cars): ${float(iaai.get('auction_fees_usd') or iaai.get('fees_net') or 0):,.2f}",
                "────────────────────",
                f"Итого аукцион: ${iaai['iaai_total']:,.2f}",
            ]
        )
    else:
        buyer_line = f"Buyer Fee: ${iaai['buyer_fee']:,.2f}"
        if is_high:
            buyer_line = (
                f"Buyer Fee (опт): ${iaai['buyer_fee']:,.2f}"
                f"  (Standard было бы ${iaai['buyer_fee_standard']:,.2f},"
                f" экономия ${iaai['saving_vs_standard']:,.2f})"
            )
        lines.extend(
            [
                f"Тип авто: {quote.get('vehicle_size_label') or quote['dismantle_type']}",
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
        if quote.get("purpose") == "restoration":
            lines.extend(
                [
                    "",
                    "Доставка США (прайс MG GROUP)",
                    f"Площадка: {delivery.get('matched_yard') or delivery.get('location') or '—'}",
                    f"Порт вывоза: {delivery.get('us_port_label') or '—'}",
                    f"Суша до порта ({delivery.get('vehicle_size_label') or '—'}): ${delivery['inland_usd']:,.2f}",
                ]
            )
            if float(delivery.get("ocean_usd") or 0) > 0:
                dest = str(delivery.get("ocean_destination") or "klaipeda").title()
                lines.append(f"Море до {dest}: ${float(delivery['ocean_usd']):,.2f}")
        else:
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
            if float(delivery.get("ocean_usd") or 0) > 0:
                size_note = delivery.get("vehicle_size_label") or quote.get("vehicle_size_label") or ""
                lines.append(
                    f"Море до ЕС: ${float(delivery['ocean_usd']):,.2f}"
                    + (f" ({size_note})" if size_note else "")
                )
    if quote.get("purpose") == "restoration" and quote.get("title_document"):
        fee = quote.get("title_doc_usd")
        info = quote.get("title_fee_info") or {}
        lines.append("")
        if info.get("unmatched") or fee is None:
            lines.append(f"Title / документы: {quote['title_document']} → нет в прайсе")
        else:
            rule = info.get("matched_rule") or ""
            lines.append(
                f"Title / документы: {quote['title_document']} → ${float(fee):,.2f}"
                + (f" ({rule})" if rule else "")
            )
    if quote.get("purpose") == "restoration" and quote.get("is_sublot"):
        addr = quote.get("sublot_location") or "Sublot / Offsite"
        fee = float(quote.get("sublot_usd") or SUBLOT_FEE_USD)
        lines.append("")
        lines.append(f"Sublot / Offsite: {addr} → ${fee:,.2f}")
    lines.append("")
    lines.append(f"Диспетчинг: ${quote['dispatching_usd']:,.2f}")
    rate_pct = float(quote.get("transfer_fee_rate") or USA_TRANSFER_FEE_RATE) * 100
    lines.append(
        f"Комиссия за перевод {rate_pct:g}%: ${quote['transfer_fee']:,.2f}"
        f" (${quote['subtotal_usa']:,.2f} × {rate_pct:g}%)"
    )
    lines.append("────────────────────")
    lines.append(f"Расходы США: ${quote['usa_with_fees']:,.2f}")
    if quote.get("purpose") != "restoration" and float(quote.get("dismantle_usd") or 0) > 0:
        lines.append("")
        usa_labels = {
            "sedan": "Легковые авто (премиум)",
            "suv": "Внедорожник / кроссовер (премиум)",
            "frame_suv": "Рамный внедорожник (премиум)",
        }
        dismantle_title = quote.get("dismantle_label") or "Разбор США"
        if quote.get("dismantle_mode") == "weight" and quote.get("dismantle_kg"):
            kg = quote["dismantle_kg"]
            lines.append(
                f"{dismantle_title}: ${quote['dismantle_usd']:,.2f} (1300 USD + 2.2 × {kg:g} кг)"
            )
        else:
            dtype = quote["dismantle_type"]
            label = usa_labels.get(dtype, dtype)
            lines.append(f"{dismantle_title}: ${quote['dismantle_usd']:,.2f} ({label})")
    if quote.get("grand_usd") is not None and quote.get("purpose") != "restoration":
        lines.append(f"Итого с разбором: ${quote['grand_usd']:,.2f}")
    return "\n".join(lines)
