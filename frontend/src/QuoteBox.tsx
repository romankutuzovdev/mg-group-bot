import type { IaaiQuote, LotQuote } from "./types";

export const DELIVERY_LABEL: Record<string, string> = {
  sedan: "Седан",
  jeep: "Джип",
  bus: "Бус",
};

export const DELIVERY_RATES: Record<string, Record<string, number>> = {
  DEFAULT: { sedan: 300, jeep: 350, bus: 500 },
  ROCHFORD: { sedan: 130, jeep: 160, bus: 200 },
  COLCHESTER: { sedan: 190, jeep: 230, bus: 285 },
  SANDY: { sedan: 180, jeep: 230, bus: 330 },
  SANDWICH: { sedan: 130, jeep: 160, bus: 200 },
  NEWBURY: { sedan: 220, jeep: 260, bus: 330 },
  WISBECH: { sedan: 230, jeep: 280, bus: 380 },
  CORBY: { sedan: 230, jeep: 280, bus: 380 },
  WESTBURY: { sedan: 320, jeep: 380, bus: 480 },
  BRISTOL: { sedan: 300, jeep: 350, bus: 500 },
  WOLVERHAMPTON: { sedan: 320, jeep: 350, bus: 500 },
  SANDTOFT: { sedan: 370, jeep: 420, bus: 570 },
  CHESTER: { sedan: 420, jeep: 470, bus: 600 },
  YORK: { sedan: 410, jeep: 460, bus: 600 },
  PETERLEE: { sedan: 470, jeep: 570, bus: 650 },
  WHITBURN: { sedan: 910, jeep: 1100, bus: 1365 },
  "EAST KILBRIDE": { sedan: 880, jeep: 1060, bus: 1320 },
  GLOUCESTER: { sedan: 300, jeep: 350, bus: 500 },
};

export function resolveDeliveryRegion(location: string | null | undefined): string {
  const name = (location || "").trim().toUpperCase();
  if (!name) return "DEFAULT";
  if (name in DELIVERY_RATES) return name;
  for (const key of Object.keys(DELIVERY_RATES)) {
    if (key === "DEFAULT") continue;
    if (name.includes(key) || key.includes(name)) return key;
  }
  return "DEFAULT";
}

export function deliveryPrice(location: string | null | undefined, column: string): number {
  const region = resolveDeliveryRegion(location);
  const rates = DELIVERY_RATES[region] || DELIVERY_RATES.DEFAULT;
  return rates[column] ?? rates.sedan;
}

export function autoDeliveryColumn(vehicleType: string, categoryB: boolean): string {
  if (vehicleType === "sprinter") return "bus";
  if (vehicleType === "suv" || vehicleType === "pickup") return "jeep";
  if (categoryB) return "jeep";
  return "sedan";
}

export const DISMANTLE_LABEL: Record<string, string> = {
  sedan: "Седан",
  suv: "SUV / джип",
  sprinter: "Спринтер / бус",
  pickup: "Пикап",
};

export const DISMANTLE_TARIFF_USD: Record<string, number> = {
  sedan: 2200,
  suv: 2450,
  sprinter: 2350,
  pickup: 2650,
};

/** Тарифы разбора USA (премиум). */
export const USA_DISMANTLE_LABEL: Record<string, string> = {
  sedan: "Легковые авто (премиум)",
  suv: "Внедорожник / кроссовер (премиум)",
  frame_suv: "Рамный внедорожник (премиум)",
};

export const USA_DISMANTLE_TARIFF_USD: Record<string, number> = {
  sedan: 4100,
  suv: 4450,
  frame_suv: 4850,
};

export function usaDismantleType(raw: string | null | undefined): string {
  const key = String(raw || "sedan").toLowerCase();
  if (key === "frame_suv" || key === "pickup") return "frame_suv";
  if (key === "suv") return "suv";
  return "sedan";
}

export const DISMANTLE_WEIGHT_BASE = 800;
export const DISMANTLE_WEIGHT_PER_KG = 1.6;

/** Разбор по весу — USA (Bid.cars / IAAI). */
export const USA_DISMANTLE_WEIGHT_BASE = 1300;
export const USA_DISMANTLE_WEIGHT_PER_KG = 2.2;

export function dismantleWeightTotal(kg: number): number {
  return DISMANTLE_WEIGHT_BASE + DISMANTLE_WEIGHT_PER_KG * kg;
}

export function usaDismantleWeightTotal(kg: number): number {
  return USA_DISMANTLE_WEIGHT_BASE + USA_DISMANTLE_WEIGHT_PER_KG * kg;
}

export function dismantleWeightHint(kg?: number | null): string {
  if (kg && kg > 0) {
    return `800 USD + 1.6 × ${kg} кг = ${usd(dismantleWeightTotal(kg))}`;
  }
  return "800 USD + 1.6 × кг";
}

export function usaDismantleWeightHint(kg?: number | null): string {
  if (kg && kg > 0) {
    return `1300 USD + 2.2 × ${kg} кг = ${usd(usaDismantleWeightTotal(kg))}`;
  }
  return "1300 USD + 2.2 × кг";
}

export function isCopartPhotoUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  const raw = url.trim();
  if (raw.startsWith("/api/media/")) return true;
  const src = raw.startsWith("//") ? `https:${raw}` : raw;
  if (!src.startsWith("https://")) return false;
  const low = src.toLowerCase();
  if (/flag|\/flags\/|placeholder|logo|icon|sprite|onetrust|country|\/content\/|clo-platinum|favicon|avatar/.test(low)) {
    return false;
  }
  if (!/(?:[\w.-]+\.)?copart\.(?:com|co\.uk)\//i.test(src)) return false;
  return /AUTH_svc|ids-c-prod|\/lpp\/|lotimage|\/vis\/|_ful\.|_thb\./i.test(src);
}

/** Локальный прокси — прямые CDN-ссылки Copart в браузере дают 403. */
export function copartDisplayUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("/api/media/")) return url;
  if (isCopartPhotoUrl(url)) return `/api/media/copart?u=${encodeURIComponent(url)}`;
  return url;
}

export function copartPhotoUrls(urls: string[] | null | undefined, limit = 2): string[] {
  return (urls || []).filter(isCopartPhotoUrl).slice(0, limit).map(copartDisplayUrl);
}

/** Фото Bid.cars / локальный /api/media/usa/... */
export function usaDisplayUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("/api/media/")) return url;
  return url;
}

export function usaPhotoUrls(urls: string[] | null | undefined, limit = 2): string[] {
  return (urls || [])
    .map((u) => String(u || "").trim())
    .filter((u) => {
      if (!u) return false;
      if (u.startsWith("/api/media/")) return true;
      if (!/^https:\/\//i.test(u)) return false;
      const low = u.toLowerCase();
      if (/logo|icon|flag|sprite|avatar|favicon|pixel/.test(low)) return false;
      if (u.startsWith("/api/media/usa/")) return true;
      return /cloudfront|amazonaws|iaai|lotimages|bid\.cars\/.*\.(?:jpe?g|webp)/i.test(low);
    })
    .slice(0, limit)
    .map(usaDisplayUrl);
}

export function money(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

export function usd(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Number(value));
}

export function deliveryNote(quote: LotQuote) {
  const info = quote.delivery;
  if (info.manual) return `${info.region_key}, ${info.label} (вручную)`;
  if (info.sedan_as_jeep) return `${info.region_key}, седан как джип (Cat B)`;
  return `${info.region_key}, ${info.label}`;
}

export function deliveryTypeLabel(quote: LotQuote) {
  const info = quote.delivery;
  const column = DELIVERY_LABEL[info.column] || info.label;
  if (info.manual) return column;
  if (info.sedan_as_jeep) return `${column}, Cat B`;
  return column;
}

export function dismantleTypeLabel(quote: LotQuote) {
  if (quote.dismantle_mode === "weight" && quote.dismantle_kg) {
    return dismantleWeightHint(quote.dismantle_kg);
  }
  return DISMANTLE_LABEL[quote.dismantle_type] || quote.dismantle_type;
}

export function QuoteRow({
  label,
  hint,
  value,
  total,
  highlight,
}: {
  label: string;
  hint?: string;
  value: string;
  total?: boolean;
  highlight?: boolean;
}) {
  const classes = ["quote-row"];
  if (total) classes.push("total");
  if (highlight) classes.push("vat-cat-b");
  return (
    <div className={classes.join(" ")}>
      <div>
        <span>{label}</span>
        {hint ? <small>{hint}</small> : null}
      </div>
      <b>{value}</b>
    </div>
  );
}

export function QuoteBox({ quote }: { quote: LotQuote }) {
  const catB = quote.category_b;
  const vatOnSale = Boolean(quote.copart.vat_on_sale || quote.copart.vat_sale);
  return (
    <div className="quote-box">
      <div className="quote-caption">Расчёт Copart Англия</div>
      {vatOnSale ? (
        <div className="quote-vat-note">
          {catB ? "Категория B — VAT 20% на комиссии и на ставку" : "VAT 20% на комиссии и на ставку"}
        </div>
      ) : null}
      <QuoteRow label="Ставка" value={money(quote.copart.bid, 2)} />
      <QuoteRow
        label="Buyer fee (опт)"
        hint={`Fee B было бы ${money(quote.copart.buyer_b, 2)}`}
        value={money(quote.copart.buyer_a, 2)}
      />
      <QuoteRow label="Live bid fee" value={money(quote.copart.live_bid, 2)} />
      <QuoteRow label="Lot retrieval" value={money(quote.copart.retrieval, 2)} />
      <QuoteRow
        label="VAT 20% на комиссии"
        hint="buyer fee + live bid + retrieval"
        value={money(quote.copart.vat_fees, 2)}
      />
      {vatOnSale ? (
        <QuoteRow
          label="VAT 20% на ставку"
          hint={catB ? "Cat B · 20% × ставка" : "20% × ставка"}
          value={money(quote.copart.vat_sale, 2)}
          highlight
        />
      ) : null}
      <QuoteRow
        label="VAT итого"
        hint={vatOnSale ? "комиссии + ставка" : "только комиссии"}
        value={money(quote.copart.vat_sum, 2)}
        highlight={vatOnSale}
      />
      <QuoteRow
        label="Copart Total"
        hint={vatOnSale ? "ставка + комиссии + VAT (вкл. VAT на ставку)" : "ставка + комиссии + VAT"}
        value={money(quote.copart.copart_total, 2)}
      />
      <QuoteRow label="Доставка" hint={deliveryNote(quote)} value={money(quote.delivery.amount, 2)} />
      <QuoteRow
        label="Комиссия за перевод 3%"
        hint={`${money(quote.subtotal, 2)} × 3%`}
        value={money(quote.transfer_fee, 2)}
      />
      <QuoteRow label="Итого UK" value={money(quote.total_uk, 2)} total />
      {quote.fx_rate ? (
        <>
          <QuoteRow label="Курс GBP→USD" value={String(quote.fx_rate)} />
          <QuoteRow label="Расходы Англии" value={usd(quote.england_usd, 2)} />
        </>
      ) : null}
      <QuoteRow
        label="Разбор"
        hint={
          quote.dismantle_mode === "weight" && quote.dismantle_kg
            ? dismantleWeightHint(quote.dismantle_kg)
            : DISMANTLE_LABEL[quote.dismantle_type] || quote.dismantle_type
        }
        value={usd(quote.dismantle_usd)}
      />
      {quote.grand_usd != null ? (
        <QuoteRow label="Итого с разбором" value={usd(quote.grand_usd, 2)} total />
      ) : null}
    </div>
  );
}

export function IaaiQuoteBox({ quote }: { quote: IaaiQuote }) {
  const fees = quote.iaai;
  const usa = quote.delivery_usa;
  const baseUsa = quote.subtotal_usa ?? (usa?.america_subtotal_usd ?? fees.iaai_total);
  const totalUsa =
    quote.usa_with_fees ??
    baseUsa + (quote.dispatching_usd ?? 200) + (quote.transfer_fee ?? 0);
  const isHigh = fees.volume === "high";
  return (
    <div className="quote-box">
      <div className="quote-caption">Расчёт IAAI USA — {fees.volume_label || "Standard"}</div>
      <div className="quote-vat-note">{fees.volume_label} · {fees.bid_method === "live" ? "Live online" : "Proxy"}</div>
      <QuoteRow label="Bid Amount" value={usd(fees.bid, 2)} />
      <QuoteRow
        label={isHigh ? "Buyer Fee (опт)" : "Buyer Fee"}
        hint={
          isHigh
            ? `Standard было бы ${usd(fees.buyer_fee_standard, 2)}, экономия ${usd(fees.saving_vs_standard, 2)}`
            : fees.buyer_fee_high != null
              ? `High Volume было бы ${usd(fees.buyer_fee_high, 2)}`
              : undefined
        }
        value={usd(fees.buyer_fee, 2)}
      />
      <QuoteRow
        label="Internet Bid Fee"
        hint={fees.bid_method === "live" ? "Live online" : "Proxy / pre-bid"}
        value={usd(fees.virtual_bid, 2)}
      />
      <QuoteRow label="Service Fee" value={usd(fees.service_fee, 2)} />
      <QuoteRow label="Environmental Fee" value={usd(fees.environmental_fee, 2)} />
      <QuoteRow label="Title Handling Fee" value={usd(fees.title_fee, 2)} />
      <QuoteRow label="Estimated Final Cost" value={usd(fees.iaai_total, 2)} total />
      {usa ? (
        <>
          <div className="quote-caption" style={{ marginTop: 10 }}>Порт вывоза США</div>
          <QuoteRow
            label="Местоположение → New Jersey"
            hint={usa.location || undefined}
            value={`${usa.miles_to_new_jersey ?? "—"} mi`}
          />
          <QuoteRow
            label="Местоположение → Houston"
            hint={usa.location || undefined}
            value={`${usa.miles_to_houston ?? "—"} mi`}
          />
          <QuoteRow
            label="Ближе порт"
            hint={usa.distance_source ? `маршрут: ${usa.distance_source}` : undefined}
            value={usa.us_port_label || "—"}
          />
          <QuoteRow
            label="До разборки США"
            hint={
              [
                usa.location ? `от местоположения: ${usa.location}` : null,
                usa.us_port_label || null,
                "$1 = 1 миля",
                usa.distance_source || null,
              ]
                .filter(Boolean)
                .join(" · ")
            }
            value={`${usa.inland_miles ?? "—"} mi → ${usd(usa.inland_usd, 0)}`}
          />
        </>
      ) : null}
      <QuoteRow label="Диспетчинг" value={usd(quote.dispatching_usd ?? 200)} />
      <QuoteRow
        label="Комиссия за перевод 3%"
        hint={`${usd(baseUsa, 2)} × 3%`}
        value={usd(quote.transfer_fee ?? 0, 2)}
      />
      <QuoteRow label="Расходы США" value={usd(totalUsa, 2)} total />
      <QuoteRow
        label="Разбор США"
        hint={
          quote.dismantle_mode === "weight" && quote.dismantle_kg
            ? usaDismantleWeightHint(quote.dismantle_kg)
            : USA_DISMANTLE_LABEL[quote.dismantle_type] ||
              USA_DISMANTLE_LABEL[usaDismantleType(quote.dismantle_type)] ||
              quote.dismantle_type
        }
        value={usd(quote.dismantle_usd)}
      />
      {quote.grand_usd != null ? (
        <QuoteRow label="Итого с разбором" value={usd(quote.grand_usd, 2)} total />
      ) : null}
    </div>
  );
}
