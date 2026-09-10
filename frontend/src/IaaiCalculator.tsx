import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { api } from "./api";
import BamperParts from "./BamperParts";
import CustomsByPanel, { parseEngineCcLocal } from "./CustomsByPanel";
import {
  USA_DISMANTLE_LABEL,
  USA_DISMANTLE_TARIFF_USD,
  USA_DISMANTLE_WEIGHT_BASE,
  USA_DISMANTLE_WEIGHT_PER_KG,
  IaaiQuoteBox,
  RESTORATION_SIZE_OPTIONS,
  UsaPriceSheetPanel,
  usaDismantleType,
  usaDismantleWeightHint,
  usaPhotoUrls,
  usd,
} from "./QuoteBox";
import type { BidcarsLot, IaaiQuote } from "./types";

type Props = {
  variant?: "iaai" | "restoration";
  url?: string;
  onUrlChange?: (value: string) => void;
  historyId?: number | null;
  onHistoryId?: (id: number | null) => void;
  onHistoryChange?: () => void;
  restoreLot?: (BidcarsLot & { history_id?: number | null }) | null;
  historyPanel?: ReactNode;
};

/** Порт моря по возрасту и объёму: 3–5 лет ≤1.9л → Klaipeda; до 5 лет >1.9л → Poti. */
export function suggestOceanDestination(
  year?: number | null,
  engine?: string | null,
  title?: string | null
): "klaipeda" | "poti" | null {
  if (!year || year < 1950) return null;
  const age = new Date().getFullYear() - year;
  if (age < 0 || age > 5) return null;
  const cc = parseEngineCcLocal(engine, title);
  if (!cc || cc <= 0) return null;
  if (cc > 1900) return "poti";
  if (age >= 3) return "klaipeda";
  return null;
}

export default function IaaiCalculator({
  variant = "iaai",
  url: urlProp,
  onUrlChange,
  historyId = null,
  onHistoryId,
  onHistoryChange,
  restoreLot = null,
  historyPanel,
}: Props = {}) {
  const isRestoration = variant === "restoration";
  const [localUrl, setLocalUrl] = useState("");
  const url = urlProp !== undefined ? urlProp : localUrl;
  const setUrl = (value: string) => {
    if (onUrlChange) onUrlChange(value);
    else setLocalUrl(value);
  };
  const [lot, setLot] = useState<BidcarsLot | null>(null);
  const [loading, setLoading] = useState(false);
  const [bid, setBid] = useState("");
  const [title, setTitle] = useState("");
  const [bidMethod, setBidMethod] = useState<"live" | "proxy">("live");
  const [volume, setVolume] = useState<"standard" | "high">("standard");
  const [vehicleType, setVehicleType] = useState("sedan");
  const [vehicleSize, setVehicleSize] = useState<"regular" | "oversize" | "moto">("regular");
  const [oceanDestination, setOceanDestination] = useState<"klaipeda" | "poti">("klaipeda");
  const [oceanManual, setOceanManual] = useState(false);
  const [titleDocument, setTitleDocument] = useState("");
  const [titleOptions, setTitleOptions] = useState<{ name: string; cost_usd: number; cost_raw?: string }[]>([]);
  const [dismantleMode, setDismantleMode] = useState<"tariff" | "weight">("tariff");
  const [kg, setKg] = useState("");
  const [inland, setInland] = useState("");
  const [inlandMiles, setInlandMiles] = useState<number | null>(null);
  const [usPortLabel, setUsPortLabel] = useState("");
  const [milesNj, setMilesNj] = useState<number | null>(null);
  const [milesHouston, setMilesHouston] = useState<number | null>(null);
  const [distanceSource, setDistanceSource] = useState("");
  const [usPort, setUsPort] = useState<string | null>(null);
  const [quote, setQuote] = useState<IaaiQuote | null>(null);
  const [quoteText, setQuoteText] = useState("");
  const [customsAppendix, setCustomsAppendix] = useState("");
  const [quoting, setQuoting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [sublotChecking, setSublotChecking] = useState(false);
  const [sublotStatus, setSublotStatus] = useState("");
  const sublotCheckedRef = useRef<string | null>(null);
  const isCopartUs = lot?.auction_platform === "copart" || lot?.source === "copart_us";

  const historyIdRef = useRef(historyId);
  const onHistoryIdRef = useRef(onHistoryId);
  const onHistoryChangeRef = useRef(onHistoryChange);
  historyIdRef.current = historyId;
  onHistoryIdRef.current = onHistoryId;
  onHistoryChangeRef.current = onHistoryChange;
  const historyReloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleHistoryReload = () => {
    if (historyReloadTimer.current) clearTimeout(historyReloadTimer.current);
    historyReloadTimer.current = setTimeout(() => {
      onHistoryChangeRef.current?.();
    }, 800);
  };

  const applyLot = (data: BidcarsLot & { history_id?: number | null }) => {
    setLot(data);
    setTitle(data.title || "");
    // Текущая ставка с Bid.cars — только если реально есть (> 0)
    const lotBid = data.bid != null ? Number(data.bid) : NaN;
    setBid(Number.isFinite(lotBid) && lotBid > 0 ? String(lotBid) : "");
    setVehicleType(usaDismantleType(data.dismantle_type));
    setUrl(data.url || url);
    const docs = String(data.title_code || data.documents || "").trim();
    setTitleDocument(docs);
    setOceanManual(false);
    const suggested = suggestOceanDestination(data.year, data.engine, data.title);
    if (suggested) setOceanDestination(suggested);
    if (data.inland_usd != null) setInland(String(data.inland_usd));
    setInlandMiles(data.inland_miles ?? null);
    setUsPortLabel(data.us_port_label || "");
    setUsPort(data.us_port || null);
    setMilesNj(data.miles_to_new_jersey ?? null);
    setMilesHouston(data.miles_to_houston ?? null);
    setDistanceSource(data.distance_source || "");
    setSublotChecking(false);
    setSublotStatus("");
    sublotCheckedRef.current = null;
    if (data.quote) {
      setQuote(data.quote);
      setQuoteText(data.quote_text || "");
    }
    if (data.history_id != null) onHistoryIdRef.current?.(data.history_id);
  };

  useEffect(() => {
    if (!restoreLot) return;
    applyLot(restoreLot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoreLot]);

  useEffect(() => {
    if (!isRestoration || !lot) return;
    const key = `${lot.lot_id || ""}|${lot.auction_url || ""}|${lot.auction_platform || ""}`;
    if (!key || key === "||") return;
    if (sublotCheckedRef.current === key) return;
    // Уже знаем результат (например с прямой ссылки Copart/IAAI)
    if (lot.is_sublot === true) {
      sublotCheckedRef.current = key;
      setSublotStatus(lot.sublot_location ? `${lot.sublot_location} · +$100` : "да · +$100");
      return;
    }
    // Только для Bid.cars — открываем площадку после показа цены
    if (lot.source !== "bidcars" && !lot.auction_url) {
      sublotCheckedRef.current = key;
      return;
    }
    let cancelled = false;
    sublotCheckedRef.current = key;
    setSublotChecking(true);
    setSublotStatus("проверяю…");
    void api
      .checkSublot({
        auction_url: lot.auction_url || null,
        auction_platform: lot.auction_platform || null,
        lot_id: lot.lot_id || null,
      })
      .then((data) => {
        if (cancelled) return;
        setLot((prev) => {
          if (!prev) return prev;
          const next = { ...prev };
          next.is_sublot = Boolean(data.is_sublot);
          next.sublot_location = data.sublot_location || null;
          if (data.auction_platform) next.auction_platform = data.auction_platform;
          if (data.auction_url) next.auction_url = data.auction_url;
          return next;
        });
        if (data.is_sublot) {
          setSublotStatus(
            data.sublot_location ? `${data.sublot_location} · +$100` : "да · +$100",
          );
        } else {
          setSublotStatus(data.checked === false ? data.error || "не проверено" : "нет");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSublotStatus(err instanceof Error ? err.message : "ошибка проверки");
          // разрешим повтор
          if (sublotCheckedRef.current === key) sublotCheckedRef.current = null;
        }
      })
      .finally(() => {
        if (!cancelled) setSublotChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isRestoration, lot?.lot_id, lot?.auction_url, lot?.source, lot?.auction_platform]);

  useEffect(() => {
    if (!isRestoration) return;
    void api
      .titleTariffs()
      .then((data) => setTitleOptions(data.items || []))
      .catch(() => setTitleOptions([]));
  }, [isRestoration]);

  useEffect(() => {
    if (!isRestoration || oceanManual || !lot) return;
    const suggested = suggestOceanDestination(lot.year, lot.engine, lot.title || title);
    if (suggested) setOceanDestination(suggested);
  }, [isRestoration, oceanManual, lot, title]);

  const onLookup = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setLot(null);
    setQuote(null);
    setQuoteText("");
    setCustomsAppendix("");
    try {
      const data = await api.lookupBidcars(url.trim());
      applyLot(data);
      onHistoryChangeRef.current?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось открыть Bid.cars");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const price = Number(bid);
    if (!price || price < 0) {
      setQuote(null);
      setQuoteText("");
      setCustomsAppendix("");
      setQuoting(false);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setQuoting(true);
      void api
        .quoteIaai({
          bid: price,
          title: title.trim() || undefined,
          body_style: lot?.body_style,
          dismantle_type: vehicleType,
          dismantle_kg:
            !isRestoration && dismantleMode === "weight" && Number(kg) > 0 ? Number(kg) : null,
          bid_method: bidMethod,
          volume,
          url: lot?.url || url || null,
          location: lot?.location,
          ship_from: lot?.ship_from,
          include_america_delivery: true,
          inland_usd: isRestoration ? null : Number(inland) > 0 ? Number(inland) : null,
          inland_miles: isRestoration ? null : inlandMiles,
          us_port: isRestoration ? null : usPort,
          us_port_label: isRestoration ? null : usPortLabel || null,
          miles_to_new_jersey: isRestoration ? null : milesNj,
          miles_to_houston: isRestoration ? null : milesHouston,
          distance_source: isRestoration ? null : distanceSource || null,
          history_id: historyIdRef.current,
          lot_id: lot?.lot_id || null,
          vin: lot?.vin,
          odometer: lot?.odometer ?? null,
          primary_damage: lot?.primary_damage,
          documents: titleDocument || lot?.documents || null,
          images: lot?.images || null,
          purpose: isRestoration ? "restoration" : "iaai",
          vehicle_size: isRestoration ? vehicleSize : null,
          auction_platform:
            lot?.auction_platform || (lot?.source === "copart_us" ? "copart" : "iaai"),
          ocean_destination: isRestoration ? oceanDestination : null,
          title_code: titleDocument || lot?.title_code || lot?.documents || null,
          is_sublot: isRestoration ? Boolean(lot?.is_sublot) : null,
          sublot_location: isRestoration ? lot?.sublot_location || null : null,
          auction_fees_usd:
            isRestoration && lot?.auction_fees_usd != null ? Number(lot.auction_fees_usd) : null,
        })
        .then((data) => {
          if (cancelled) return;
          setQuote(data.quote);
          setQuoteText(data.quote_text || "");
          if (data.history_id != null && data.history_id !== historyIdRef.current) {
            onHistoryIdRef.current?.(data.history_id);
            scheduleHistoryReload();
          } else {
            scheduleHistoryReload();
          }
          setError("");
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : "Ошибка расчёта");
        })
        .finally(() => {
          if (!cancelled) setQuoting(false);
        });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // historyId / callbacks специально не в deps — иначе цикл quote → history → re-render → quote
  }, [
    bid,
    title,
    vehicleType,
    vehicleSize,
    oceanDestination,
    titleDocument,
    isRestoration,
    dismantleMode,
    kg,
    bidMethod,
    volume,
    inland,
    inlandMiles,
    lot,
    url,
    usPort,
    usPortLabel,
    milesNj,
    milesHouston,
    distanceSource,
  ]);

  useEffect(() => {
    return () => {
      if (historyReloadTimer.current) clearTimeout(historyReloadTimer.current);
    };
  }, []);

  const copyQuote = async () => {
    const text = `${quoteText || ""}${customsAppendix || ""}`.trim();
    if (!text) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="calc-layout">
      <div className="calc-main">
        <form className="calc-form" onSubmit={(event) => void onLookup(event)}>
          <input
            className="field"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Ссылка Copart.com / IAAI.com / Bid.cars"
            required
          />
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Открываю лот…" : "Подтянуть лот"}
          </button>
        </form>
        {error ? <div className="error">{error}</div> : null}
        {loading ? <div className="hint">Открываю карточку в Chrome и читаю данные лота…</div> : null}

        <div className="calc-workspace">
          <div className="calc-left">
            <section className="calc-lot">
              {(() => {
                const photos = usaPhotoUrls(lot?.images, isRestoration ? 3 : 2);
                if (!photos.length) return null;
                return (
                  <div className={`calc-photos photos-${photos.length}`}>
                    {photos.map((src) => (
                      <img key={src} src={src} alt="" loading="lazy" />
                    ))}
                  </div>
                );
              })()}
              <h3>{lot?.title || (isRestoration ? "Авто под восстановление" : "Аукцион USA")}</h3>
              <p className="hint">
                {isRestoration
                  ? "Аукционные сборы — с Bid.cars. Доставка до порта и море — из прайса MG GROUP по размеру: Regular / Large, Oversize, Moto."
                  : isCopartUs
                    ? "Аукционные сборы — официальная сетка Copart USA для licensed business и secured payment. 12+ авто недостаточно для High Volume в США."
                    : "Аукционные сборы — как на аккаунте IAAI (Standard по умолчанию). До разборки США: ближе NJ или Houston, $1 = 1 миля."}
              </p>
              {lot ? (
                <div className="facts">
                  <div className="fact"><small>Lot</small><b>{lot.lot_id || "—"}</b></div>
                  <div className="fact"><small>VIN</small><b>{lot.vin || "—"}</b></div>
                  <div className="fact"><small>Местоположение</small><b>{lot.location || "—"}</b></div>
                  {isRestoration ? (
                    <>
                      <div className="fact">
                        <small>Порт вывоза (прайс)</small>
                        <b>{quote?.delivery_usa?.us_port_label || "—"}</b>
                      </div>
                      <div className="fact">
                        <small>Суша до порта</small>
                        <b>
                          {quote?.delivery_usa?.inland_usd != null
                            ? usd(quote.delivery_usa.inland_usd, 0)
                            : "—"}
                        </b>
                      </div>
                      <div className="fact">
                        <small>Море (Klaipeda)</small>
                        <b>
                          {quote?.delivery_usa?.ocean_usd != null
                            ? usd(quote.delivery_usa.ocean_usd, 0)
                            : "—"}
                        </b>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="fact">
                        <small>Местоположение → NJ</small>
                        <b>{milesNj != null ? `${milesNj} mi` : "—"}</b>
                      </div>
                      <div className="fact">
                        <small>Местоположение → Houston</small>
                        <b>{milesHouston != null ? `${milesHouston} mi` : "—"}</b>
                      </div>
                      <div className="fact"><small>Ближе порт</small><b>{usPortLabel || "—"}</b></div>
                      <div className="fact">
                        <small>До разборки США</small>
                        <b>{inlandMiles != null ? `${inlandMiles} mi · $${Math.round(inlandMiles)}` : "—"}</b>
                      </div>
                    </>
                  )}
                  <div className="fact"><small>Кузов</small><b>{lot.body_style || "—"}</b></div>
                  <div className="fact"><small>Год</small><b>{lot.year != null ? String(lot.year) : "—"}</b></div>
                  <div className="fact">
                    <small>Двигатель</small>
                    <b>{lot.engine || "—"}</b>
                  </div>
                  <div className="fact">
                    <small>Объём</small>
                    <b>
                      {(() => {
                        const cc = parseEngineCcLocal(lot.engine, lot.title);
                        if (!cc) return "—";
                        const liters = (cc / 1000).toLocaleString("ru-RU", {
                          minimumFractionDigits: cc % 100 === 0 ? 1 : 1,
                          maximumFractionDigits: 1,
                        });
                        return `${cc} см³ · ${liters} л`;
                      })()}
                    </b>
                  </div>
                  <div className="fact"><small>Топливо</small><b>{lot.fuel || "—"}</b></div>
                  <div className="fact"><small>Пробег</small><b>{lot.odometer != null ? String(lot.odometer) : "—"}</b></div>
                  {isRestoration && lot.is_sublot ? (
                    <div className="fact">
                      <small>Sublot / Offsite</small>
                      <b>{lot.sublot_location || "да"} · +$100</b>
                    </div>
                  ) : isRestoration && sublotChecking ? (
                    <div className="fact">
                      <small>Sublot / Offsite</small>
                      <b>проверяю…</b>
                    </div>
                  ) : isRestoration && sublotStatus ? (
                    <div className="fact">
                      <small>Sublot / Offsite</small>
                      <b>{sublotStatus}</b>
                    </div>
                  ) : null}
                  <div className="fact"><small>Повреждение</small><b>{lot.primary_damage || "—"}</b></div>
                  <div className="fact">
                    <small>
                      {lot.auction_platform === "copart" || lot.source === "copart_us"
                        ? "Title code"
                        : "Title / Sale Doc"}
                    </small>
                    <b>{titleDocument || lot.title_code || lot.documents || "—"}</b>
                  </div>
                  {isRestoration ? (
                    <div className="fact">
                      <small>Доплата за документы</small>
                      <b>
                        {!titleDocument && !(lot.title_code || lot.documents)
                          ? "не подтянулись с лота"
                          : quote?.title_fee_info?.unmatched
                            ? "нет в прайсе"
                            : quote?.title_doc_usd != null
                              ? quote.title_doc_usd > 0
                                ? usd(quote.title_doc_usd, 0)
                                : `${usd(0, 0)} · без доплат`
                              : "—"}
                      </b>
                    </div>
                  ) : null}
                  <div className="fact">
                    <small>Источник</small>
                    <b>{(lot.auction_platform || lot.source || "—").toString().toUpperCase()}</b>
                  </div>
                  {lot.url ? (
                    <div className="fact">
                      <small>Ссылка</small>
                      <b><a href={lot.url} target="_blank" rel="noreferrer">открыть</a></b>
                    </div>
                  ) : null}
                </div>
              ) : (
                <p className="hint">Вставьте ссылку Bid.cars — бот откроет лот в Chrome и подтянет данные.</p>
              )}
            </section>
            {historyPanel}
          </div>

          <section className="calc-panel">
            <label className="hint">
              Ваша ставка ($)
              {isRestoration && lot?.bid != null && Number(lot.bid) > 0 ? (
                <span style={{ fontWeight: 400 }}> · с Bid.cars: {usd(Number(lot.bid), 0)}</span>
              ) : null}
            </label>
            <input
              className="field"
              type="number"
              min="0"
              step="1"
              value={bid}
              onChange={(e) => setBid(e.target.value)}
              placeholder={
                isRestoration && lot?.bid != null && Number(lot.bid) > 0
                  ? `Текущая ставка ${Number(lot.bid)}`
                  : "Hammer price"
              }
            />

            {!isRestoration ? (
              <>
                <label className="hint">Тип ставки online</label>
                <div className="segment">
                  <label className="check">
                    <input type="radio" checked={bidMethod === "live"} onChange={() => setBidMethod("live")} />
                    Live online
                  </label>
                  <label className="check">
                    <input type="radio" checked={bidMethod === "proxy"} onChange={() => setBidMethod("proxy")} />
                    Proxy / pre-bid
                  </label>
                </div>

                <label className="hint">Тип покупателя {isCopartUs ? "Copart USA" : "IAAI"}</label>
                <div className="segment">
                  <label className="check">
                    <input type="radio" checked={volume === "standard"} onChange={() => setVolume("standard")} />
                    Standard
                  </label>
                  <label className="check">
                    <input type="radio" checked={volume === "high"} onChange={() => setVolume("high")} />
                    {isCopartUs ? "High Volume (25+ авто и $75k+/год)" : "High Volume (опт)"}
                  </label>
                </div>
              </>
            ) : lot?.auction_fees_usd != null ? (
              <div className="hint" style={{ marginBottom: 8 }}>
                Аукционные сборы Bid.cars: {usd(Number(lot.auction_fees_usd), 0)}
              </div>
            ) : null}

            {!isRestoration && usPortLabel ? (
              <div className="hint" style={{ marginBottom: 8 }}>
                Порт США: {usPortLabel}
                {milesNj != null && milesHouston != null
                  ? ` · NJ ${milesNj} mi / Houston ${milesHouston} mi`
                  : ""}
                {inlandMiles != null ? ` · $${Math.round(Number(inlandMiles))}` : ""}
              </div>
            ) : null}

            {isRestoration && quote?.delivery_usa?.us_port_label ? (
              <div className="hint" style={{ marginBottom: 8 }}>
                Порт: {quote.delivery_usa.us_port_label}
                {quote.delivery_usa.inland_usd != null
                  ? ` · суша ${usd(quote.delivery_usa.inland_usd, 0)}`
                  : ""}
                {quote.delivery_usa.ocean_usd
                  ? ` · море ${usd(quote.delivery_usa.ocean_usd, 0)}`
                  : ""}
              </div>
            ) : null}

            {isRestoration ? (
              <>
                <label className="hint">Размер машины</label>
                <div className="segment">
                  {RESTORATION_SIZE_OPTIONS.map((opt) => (
                    <label className="check" key={opt.key}>
                      <input
                        type="radio"
                        checked={vehicleSize === opt.key}
                        onChange={() => setVehicleSize(opt.key)}
                      />
                      {opt.label}
                    </label>
                  ))}
                </div>
                <label className="hint">Море до порта</label>
                <div className="segment">
                  <label className="check">
                    <input
                      type="radio"
                      checked={oceanDestination === "klaipeda"}
                      onChange={() => {
                        setOceanManual(true);
                        setOceanDestination("klaipeda");
                      }}
                    />
                    Klaipeda
                  </label>
                  <label className="check">
                    <input
                      type="radio"
                      checked={oceanDestination === "poti"}
                      onChange={() => {
                        setOceanManual(true);
                        setOceanDestination("poti");
                      }}
                    />
                    Poti
                  </label>
                </div>
                <div className="hint" style={{ marginBottom: 8 }}>
                  {(() => {
                    const cc = parseEngineCcLocal(lot?.engine, lot?.title || title);
                    const age =
                      lot?.year && lot.year > 1950 ? new Date().getFullYear() - lot.year : null;
                    const auto = suggestOceanDestination(lot?.year, lot?.engine, lot?.title || title);
                    if (oceanManual) {
                      return "Порт выбран вручную.";
                    }
                    if (auto === "klaipeda") {
                      return `Авто: Klaipeda (возраст ${age} лет · ${cc} см³ ≤ 1.9 л).`;
                    }
                    if (auto === "poti") {
                      return `Авто: Poti (до 5 лет · ${cc} см³ > 1.9 л).`;
                    }
                    return "Правило: 3–5 лет и ≤1.9 л → Klaipeda; до 5 лет и >1.9 л → Poti.";
                  })()}
                </div>
                <label className="hint">Title / документы</label>
                {(() => {
                  const lotRaw = String(lot?.title_code || lot?.documents || "").trim();
                  const matchedOpt =
                    titleOptions.find((o) => o.name === titleDocument) ||
                    (quote?.title_fee_info && !quote.title_fee_info.unmatched && quote.title_fee_info.matched_rule
                      ? titleOptions.find((o) => o.name === quote.title_fee_info!.matched_rule)
                      : undefined);
                  const selectValue = matchedOpt?.name || (titleDocument ? "__other__" : "");
                  const feeLabel =
                    matchedOpt != null
                      ? matchedOpt.cost_usd > 0
                        ? usd(matchedOpt.cost_usd, 0)
                        : "без доплат"
                      : quote?.title_fee_info?.unmatched
                        ? "нет в прайсе"
                        : quote?.title_doc_usd != null
                          ? quote.title_doc_usd > 0
                            ? usd(quote.title_doc_usd, 0)
                            : "без доплат"
                          : "—";
                  return (
                    <>
                      <select
                        className="select"
                        value={selectValue}
                        onChange={(e) => {
                          const v = e.target.value;
                          if (v === "") {
                            setTitleDocument("");
                            return;
                          }
                          if (v === "__other__") return;
                          setTitleDocument(v);
                        }}
                      >
                        <option value="">Не выбран</option>
                        {titleOptions.map((opt) => (
                          <option key={opt.name} value={opt.name}>
                            {opt.name} — {opt.cost_usd > 0 ? usd(opt.cost_usd, 0) : "без доплат"}
                          </option>
                        ))}
                        {titleDocument && !matchedOpt ? (
                          <option value="__other__">Иной тип (нет в прайсе)</option>
                        ) : null}
                      </select>
                      <input
                        className="field"
                        style={{ marginTop: 6 }}
                        value={titleDocument}
                        onChange={(e) => {
                          setTitleDocument(e.target.value);
                        }}
                        placeholder="Текст Title с лота или свой (Salvage, BOS…)"
                      />
                      <div className="hint" style={{ marginTop: 6, marginBottom: 4 }}>
                        {lotRaw ? (
                          <>
                            С сайта: <b>{lotRaw}</b>
                          </>
                        ) : (
                          "С сайта тип не подтянулся"
                        )}
                      </div>
                      <div
                        className="hint"
                        style={{
                          marginBottom: 8,
                          fontWeight: 600,
                          color: matchedOpt ? "var(--text)" : titleDocument ? "#b45309" : "var(--muted)",
                        }}
                      >
                        {matchedOpt
                          ? `В прайсе: ${matchedOpt.name} · ${feeLabel}`
                          : titleDocument
                            ? `Иной тип: «${titleDocument}» · нет в вашей базе Title`
                            : "Выберите сертификат из прайса выше"}
                      </div>
                    </>
                  );
                })()}
              </>
            ) : (
              <>
                <label className="hint">Тип авто для разбора</label>
                <select className="select" value={vehicleType} onChange={(e) => setVehicleType(e.target.value)}>
                  {Object.entries(USA_DISMANTLE_LABEL).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label} ({usd(USA_DISMANTLE_TARIFF_USD[key])})
                    </option>
                  ))}
                </select>

                <label className="hint">Разбор</label>
                <div className="segment">
                  <label className="check">
                    <input type="radio" checked={dismantleMode === "tariff"} onChange={() => setDismantleMode("tariff")} />
                    По тарифу
                  </label>
                  <label className="check">
                    <input type="radio" checked={dismantleMode === "weight"} onChange={() => setDismantleMode("weight")} />
                    По весу — 1300 USD + 2.2 × кг
                  </label>
                </div>

                {dismantleMode === "weight" ? (
                  <>
                    <input className="field" type="number" min="0" placeholder="Вес, кг" value={kg} onChange={(e) => setKg(e.target.value)} />
                    <div className="hint">
                      {Number(kg) > 0
                        ? usaDismantleWeightHint(Number(kg))
                        : `Формула: ${USA_DISMANTLE_WEIGHT_BASE} USD + ${USA_DISMANTLE_WEIGHT_PER_KG} × кг`}
                    </div>
                  </>
                ) : null}
              </>
            )}

            {isRestoration && quote?.delivery_usa?.price_sheet ? (
              <UsaPriceSheetPanel sheet={quote.delivery_usa.price_sheet} />
            ) : null}

            {quoting ? <div className="hint">Считаю…</div> : null}
            {quote ? <IaaiQuoteBox quote={quote} /> : <p className="hint">Введите ставку или подтяните лот.</p>}
            {isRestoration && quote ? (
              <CustomsByPanel
                priceUsd={quote.usa_with_fees ?? quote.grand_usd ?? quote.subtotal_usa}
                year={lot?.year}
                engine={lot?.engine}
                fuel={lot?.fuel}
                title={lot?.title || title}
                onGrandTotal={(info) => setCustomsAppendix(info?.text || "")}
              />
            ) : null}
            <button
              className="btn ghost"
              type="button"
              onClick={() => void copyQuote()}
              disabled={!quoteText && !customsAppendix}
            >
              {copied ? "Скопировано" : "Скопировать расчёт"}
            </button>
          </section>
        </div>
        {!isRestoration && lot ? (
          <BamperParts
            make={lot.make}
            model={lot.model}
            year={lot.year}
            title={lot.title}
            vin={lot.vin}
            lotId={lot.lot_id}
            url={lot.url}
            engine={lot.engine}
            fuel={lot.fuel}
            transmission={lot.transmission}
            bodyStyle={lot.body_style}
          />
        ) : null}
      </div>
    </div>
  );
}
