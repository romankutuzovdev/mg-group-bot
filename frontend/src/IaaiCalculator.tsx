import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { api } from "./api";
import BamperParts from "./BamperParts";
import {
  USA_DISMANTLE_LABEL,
  USA_DISMANTLE_TARIFF_USD,
  USA_DISMANTLE_WEIGHT_BASE,
  USA_DISMANTLE_WEIGHT_PER_KG,
  IaaiQuoteBox,
  usaDismantleType,
  usaDismantleWeightHint,
  usaPhotoUrls,
  usd,
} from "./QuoteBox";
import type { BidcarsLot, IaaiQuote } from "./types";

type Props = {
  url?: string;
  onUrlChange?: (value: string) => void;
  historyId?: number | null;
  onHistoryId?: (id: number | null) => void;
  onHistoryChange?: () => void;
  restoreLot?: (BidcarsLot & { history_id?: number | null }) | null;
  historyPanel?: ReactNode;
};

export default function IaaiCalculator({
  url: urlProp,
  onUrlChange,
  historyId = null,
  onHistoryId,
  onHistoryChange,
  restoreLot = null,
  historyPanel,
}: Props = {}) {
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
  const [quoting, setQuoting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

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
    setBid(data.bid != null ? String(data.bid) : "");
    setVehicleType(usaDismantleType(data.dismantle_type));
    setUrl(data.url || url);
    if (data.inland_usd != null) setInland(String(data.inland_usd));
    setInlandMiles(data.inland_miles ?? null);
    setUsPortLabel(data.us_port_label || "");
    setUsPort(data.us_port || null);
    setMilesNj(data.miles_to_new_jersey ?? null);
    setMilesHouston(data.miles_to_houston ?? null);
    setDistanceSource(data.distance_source || "");
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

  const onLookup = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    setLot(null);
    setQuote(null);
    setQuoteText("");
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
          dismantle_kg: dismantleMode === "weight" && Number(kg) > 0 ? Number(kg) : null,
          bid_method: bidMethod,
          volume,
          url: lot?.url || url || null,
          location: lot?.location,
          ship_from: lot?.ship_from,
          include_america_delivery: true,
          inland_usd: Number(inland) > 0 ? Number(inland) : null,
          inland_miles: inlandMiles,
          us_port: usPort,
          us_port_label: usPortLabel || null,
          miles_to_new_jersey: milesNj,
          miles_to_houston: milesHouston,
          distance_source: distanceSource || null,
          history_id: historyIdRef.current,
          lot_id: lot?.lot_id || null,
          vin: lot?.vin,
          odometer: lot?.odometer ?? null,
          primary_damage: lot?.primary_damage,
          documents: lot?.documents,
          images: lot?.images || null,
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
    if (!quoteText) return;
    await navigator.clipboard.writeText(quoteText);
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
            placeholder="Ссылка Copart UK / Bid.cars или номер лота"
            required
          />
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Открываю Bid.cars…" : "Подтянуть лот"}
          </button>
        </form>
        {error ? <div className="error">{error}</div> : null}
        {loading ? <div className="hint">Открываю карточку в Chrome и читаю данные лота…</div> : null}

        <div className="calc-workspace">
          <div className="calc-left">
            <section className="calc-lot">
              {(() => {
                const photos = usaPhotoUrls(lot?.images, 2);
                if (!photos.length) return null;
                return (
                  <div className={`calc-photos photos-${photos.length}`}>
                    {photos.map((src) => (
                      <img key={src} src={src} alt="" loading="lazy" />
                    ))}
                  </div>
                );
              })()}
              <h3>{lot?.title || "IAAI через Bid.cars"}</h3>
              <p className="hint">
                Аукционные сборы — как на аккаунте IAAI (Standard по умолчанию). До разборки США: ближе NJ или Houston, $1 = 1 миля.
              </p>
              {lot ? (
                <div className="facts">
                  <div className="fact"><small>Lot</small><b>{lot.lot_id || "—"}</b></div>
                  <div className="fact"><small>VIN</small><b>{lot.vin || "—"}</b></div>
                  <div className="fact"><small>Местоположение</small><b>{lot.location || "—"}</b></div>
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
                  <div className="fact"><small>Кузов</small><b>{lot.body_style || "—"}</b></div>
                  <div className="fact"><small>Пробег</small><b>{lot.odometer != null ? String(lot.odometer) : "—"}</b></div>
                  <div className="fact"><small>Повреждение</small><b>{lot.primary_damage || "—"}</b></div>
                  <div className="fact"><small>Документы</small><b>{lot.documents || "—"}</b></div>
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
            <label className="hint">Ваша ставка ($)</label>
            <input
              className="field"
              type="number"
              min="0"
              step="1"
              value={bid}
              onChange={(e) => setBid(e.target.value)}
              placeholder="Hammer price"
            />

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

            <label className="hint">Тип покупателя IAAI</label>
            <div className="segment">
              <label className="check">
                <input type="radio" checked={volume === "standard"} onChange={() => setVolume("standard")} />
                Standard
              </label>
              <label className="check">
                <input type="radio" checked={volume === "high"} onChange={() => setVolume("high")} />
                High Volume (опт)
              </label>
            </div>

            {usPortLabel ? (
              <div className="hint" style={{ marginBottom: 8 }}>
                Порт США: {usPortLabel}
                {milesNj != null && milesHouston != null
                  ? ` · NJ ${milesNj} mi / Houston ${milesHouston} mi`
                  : ""}
                {inlandMiles != null ? ` · $${Math.round(Number(inlandMiles))}` : ""}
              </div>
            ) : null}

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

            {quoting ? <div className="hint">Считаю…</div> : null}
            {quote ? <IaaiQuoteBox quote={quote} /> : <p className="hint">Введите ставку или подтяните лот.</p>}
            <button className="btn ghost" type="button" onClick={() => void copyQuote()} disabled={!quoteText}>
              {copied ? "Скопировано" : "Скопировать расчёт"}
            </button>
          </section>
        </div>
        {lot ? (
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
