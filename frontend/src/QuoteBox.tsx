import type { IaaiQuote, LotQuote, UsaPriceSheet } from "./types";

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
    .map((u) => String(u || "").trim().replace("_thb.", "_ful.").replace("_ths.", "_ful."))
    .filter((u) => {
      if (!u) return false;
      if (u.startsWith("/api/media/")) return true;
      if (!/^https:\/\//i.test(u)) return false;
      const low = u.toLowerCase();
      if (/logo|icon|flag|sprite|avatar|favicon|pixel|\/img\/upd\/|hcaptcha/.test(low)) return false;
      if (u.startsWith("/api/media/usa/")) return true;
      return /images\.bid\.cars|cdn\.bid\.cars|cs\.copart\.com|c-static\.copart\.com|vis\.iaai\.com|cloudfront|amazonaws|iaai|lotimages|bid\.cars|copart\.com/i.test(low);
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
  const feeLabel = quote.copart.buyer_fee_label || "Fee A · 12+ авто/год";
  const buyerFee = quote.copart.buyer_fee ?? quote.copart.buyer_a;
  const auctionFees =
    quote.copart.auction_fees ??
    quote.copart.fees_net + quote.copart.vat_fees;
  return (
    <div className="quote-box">
      <div className="quote-caption">Расчёт Copart Англия</div>
      <div className="quote-vat-note">Аукционные сборы Copart.co.uk · {feeLabel}</div>
      {vatOnSale ? (
        <div className="quote-vat-note">
          {catB ? "Категория B — VAT 20% на комиссии и на ставку" : "VAT 20% на комиссии и на ставку"}
        </div>
      ) : null}
      <QuoteRow label="Ставка" value={money(quote.copart.bid, 2)} />
      <QuoteRow
        label="Buyer fee"
        hint={
          quote.copart.buyer_fee_tier === "B"
            ? feeLabel
            : `${feeLabel} · Fee B было бы ${money(quote.copart.buyer_b, 2)}`
        }
        value={money(buyerFee, 2)}
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
        label="Аукционный сбор"
        hint="комиссии + VAT на комиссии"
        value={money(auctionFees, 2)}
      />
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

export const RESTORATION_SIZE_OPTIONS: { key: "regular" | "oversize" | "moto"; label: string }[] = [
  { key: "regular", label: "Regular / Large" },
  { key: "oversize", label: "Oversize" },
  { key: "moto", label: "Moto" },
];

function moneyCell(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return usd(Number(value), 0);
}

/** Сворачиваемый прайс MG GROUP: суша с площадки + море с порта по размерам. */
export function UsaPriceSheetPanel({
  sheet,
  defaultOpen = false,
}: {
  sheet: UsaPriceSheet | null | undefined;
  defaultOpen?: boolean;
}) {
  if (!sheet) return null;
  const sizes = (["regular", "oversize", "moto"] as const).filter(
    (key) => sheet.inland_by_size?.[key] != null || sheet.ocean_by_size?.[key] != null
  );
  if (!sizes.length) return null;
  const selected = sheet.selected_size || "";
  const auction = (sheet.auction || "").toUpperCase();
  const dest = (sheet.ocean_destination || "klaipeda").toString();
  const summaryInland = moneyCell(sheet.selected_inland_usd);
  const summaryOcean = moneyCell(sheet.selected_ocean_usd);
  return (
    <details className="price-sheet" open={defaultOpen || undefined}>
      <summary className="price-sheet-summary">
        <span>Прайс доставки</span>
        <span className="price-sheet-summary-meta">
          {sheet.us_port_label || "порт"}
          {summaryInland !== "—" ? ` · суша ${summaryInland}` : ""}
          {summaryOcean !== "—" ? ` · море ${summaryOcean}` : ""}
        </span>
      </summary>
      <div className="price-sheet-body">
        <div className="hint" style={{ marginTop: 0 }}>
          {sheet.yard || "—"}
          {auction ? ` · ${auction}` : ""}
          {sheet.us_port_label ? ` → ${sheet.us_port_label}` : ""}
          {` · море до ${dest}`}
        </div>
        <table className="price-sheet-table">
          <thead>
            <tr>
              <th>Размер</th>
              <th>Суша до порта</th>
              <th>Море ({dest})</th>
            </tr>
          </thead>
          <tbody>
            {sizes.map((key) => {
              const label = sheet.size_labels?.[key] || RESTORATION_SIZE_OPTIONS.find((o) => o.key === key)?.label || key;
              const active = key === selected;
              return (
                <tr key={key} className={active ? "is-selected" : undefined}>
                  <td>
                    {label}
                    {active ? <span className="price-sheet-badge">выбрано</span> : null}
                  </td>
                  <td>{moneyCell(sheet.inland_by_size?.[key])}</td>
                  <td>{moneyCell(sheet.ocean_by_size?.[key])}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function IaaiQuoteBox({ quote }: { quote: IaaiQuote }) {
  const fees = quote.iaai;
  const usa = quote.delivery_usa;
  const isRestoration = quote.purpose === "restoration";
  const feesFromBidcars = fees.fees_source === "bidcars" || fees.auction_fees_usd != null;
  const baseUsa = quote.subtotal_usa ?? (usa?.america_subtotal_usd ?? fees.iaai_total);
  const totalUsa =
    quote.usa_with_fees ??
    baseUsa + (quote.dispatching_usd ?? 250) + (quote.transfer_fee ?? 0);
  const isHigh = fees.volume === "high";
  const sizeLabel = quote.vehicle_size_label || usa?.vehicle_size_label || "";
  return (
    <div className="quote-box">
      <div className="quote-caption">
        {isRestoration
          ? `Расчёт под восстановление${sizeLabel ? ` — ${sizeLabel}` : ""}`
          : `Расчёт IAAI USA — ${fees.volume_label || "Standard"}`}
      </div>
      {feesFromBidcars ? (
        <div className="quote-vat-note">Аукционные сборы с Bid.cars</div>
      ) : (
        <div className="quote-vat-note">{fees.volume_label} · {fees.bid_method === "live" ? "Live online" : "Proxy"}</div>
      )}
      <QuoteRow label="Bid Amount" value={usd(fees.bid, 2)} />
      {feesFromBidcars ? (
        <>
          <QuoteRow
            label="Аукционные сборы"
            hint="с калькулятора Bid.cars"
            value={usd(fees.auction_fees_usd ?? fees.fees_net, 2)}
          />
          <QuoteRow label="Итого аукцион" value={usd(fees.iaai_total, 2)} total />
        </>
      ) : (
        <>
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
        </>
      )}
      {usa ? (
        isRestoration ? (
          <>
            <div className="quote-caption" style={{ marginTop: 10 }}>Доставка США (прайс)</div>
            <QuoteRow
              label="Площадка"
              hint={usa.matched_auction ? String(usa.matched_auction).toUpperCase() : undefined}
              value={usa.matched_yard || usa.location || "—"}
            />
            <QuoteRow
              label="Порт вывоза"
              hint={sizeLabel || undefined}
              value={usa.us_port_label || "—"}
            />
            <QuoteRow
              label={`Суша до порта${sizeLabel ? ` · ${sizeLabel}` : ""}`}
              hint={usa.distance_source || undefined}
              value={usd(usa.inland_usd, 0)}
            />
            {usa.ocean_usd > 0 ? (
              <QuoteRow
                label={`Море до ${(usa.ocean_destination || "klaipeda").toString()}`}
                hint={sizeLabel || undefined}
                value={usd(usa.ocean_usd, 0)}
              />
            ) : null}
            {quote.title_document ? (
              <QuoteRow
                label="Документы / Title"
                hint={
                  quote.title_fee_info?.unmatched
                    ? `${quote.title_document} · нет в прайсе Title`
                    : quote.title_fee_info?.matched_rule
                      ? `${quote.title_document} → ${quote.title_fee_info.matched_rule}`
                      : quote.title_document
                }
                value={
                  quote.title_fee_info?.unmatched
                    ? "нет в прайсе"
                    : quote.title_doc_usd != null
                      ? quote.title_doc_usd > 0
                        ? usd(quote.title_doc_usd, 0)
                        : `${usd(0, 0)} · без доплат`
                      : "—"
                }
              />
            ) : isRestoration ? (
              <QuoteRow
                label="Документы / Title"
                hint="тип не подтянулся с лота — укажите вручную после обновления"
                value="—"
              />
            ) : null}
            {isRestoration && quote.is_sublot ? (
              <QuoteRow
                label="Sublot / Offsite"
                hint={quote.sublot_location || "доплата за дополнительную площадку"}
                value={usd(quote.sublot_usd ?? 100, 0)}
              />
            ) : null}
          </>
        ) : (
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
            {usa.ocean_usd > 0 ? (
              <QuoteRow
                label="Море до ЕС"
                hint={sizeLabel || undefined}
                value={usd(usa.ocean_usd, 2)}
              />
            ) : null}
          </>
        )
      ) : null}
      {isRestoration && quote.title_document && !usa ? (
        <QuoteRow
          label="Документы / Title"
          hint={
            quote.title_fee_info?.unmatched
              ? `${quote.title_document} · нет в прайсе Title`
              : quote.title_fee_info?.matched_rule
                ? `${quote.title_document} → ${quote.title_fee_info.matched_rule}`
                : quote.title_document
          }
          value={
            quote.title_fee_info?.unmatched
              ? "нет в прайсе"
              : quote.title_doc_usd != null
                ? quote.title_doc_usd > 0
                  ? usd(quote.title_doc_usd, 0)
                  : `${usd(0, 0)} · без доплат`
                : "—"
          }
        />
      ) : null}
      {isRestoration && quote.is_sublot && !usa ? (
        <QuoteRow
          label="Sublot / Offsite"
          hint={quote.sublot_location || "доплата за дополнительную площадку"}
          value={usd(quote.sublot_usd ?? 100, 0)}
        />
      ) : null}
      <QuoteRow label="Диспетчинг" value={usd(quote.dispatching_usd ?? 250)} />
      <QuoteRow
        label={`Комиссия за перевод ${((quote.transfer_fee_rate ?? 0.035) * 100).toLocaleString("ru-RU")}%`}
        hint={`${usd(baseUsa, 2)} × ${((quote.transfer_fee_rate ?? 0.035) * 100).toLocaleString("ru-RU")}%`}
        value={usd(quote.transfer_fee ?? 0, 2)}
      />
      <QuoteRow label="Расходы США" value={usd(totalUsa, 2)} total />
      {!isRestoration && quote.dismantle_usd != null && quote.dismantle_usd > 0 ? (
        <QuoteRow
          label={quote.dismantle_label || "Разбор США"}
          hint={
            quote.dismantle_mode === "weight" && quote.dismantle_kg
              ? usaDismantleWeightHint(quote.dismantle_kg)
              : USA_DISMANTLE_LABEL[quote.dismantle_type] ||
                USA_DISMANTLE_LABEL[usaDismantleType(quote.dismantle_type)] ||
                quote.dismantle_type
          }
          value={usd(quote.dismantle_usd)}
        />
      ) : null}
      {!isRestoration && quote.grand_usd != null ? (
        <QuoteRow label="Итого с разбором" value={usd(quote.grand_usd, 2)} total />
      ) : null}
    </div>
  );
}
