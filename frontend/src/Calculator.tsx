import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import BamperParts from "./BamperParts";
import FxRateControl from "./FxRateControl";
import { useFxRate } from "./FxRateContext";
import IaaiCalculator from "./IaaiCalculator";

import {
  DELIVERY_LABEL,
  DISMANTLE_LABEL,
  DISMANTLE_TARIFF_USD,
  DISMANTLE_WEIGHT_BASE,
  DISMANTLE_WEIGHT_PER_KG,
  QuoteBox,
  autoDeliveryColumn,
  deliveryPrice,
  dismantleWeightHint,
  isCopartPhotoUrl,
  copartDisplayUrl,
  copartPhotoUrls,
  money,
  usd,
} from "./QuoteBox";

import type { BidcarsLot, CalcHistoryItem, LotDetails, LotQuote } from "./types";



const FACTS: { key: keyof LotDetails; label: string }[] = [

  { key: "lot_id", label: "Lot" },

  { key: "year", label: "Год" },

  { key: "make", label: "Марка" },

  { key: "model", label: "Модель" },

  { key: "vin", label: "VIN" },

  { key: "location", label: "Площадка" },

  { key: "category", label: "Категория" },

  { key: "sale_date", label: "Аукцион" },

  { key: "odometer", label: "Пробег" },

  { key: "body_style", label: "Кузов" },

  { key: "vehicle_type_raw", label: "Тип Copart" },

  { key: "color", label: "Цвет" },

  { key: "engine", label: "Двигатель" },

  { key: "transmission", label: "КПП" },

  { key: "drive", label: "Привод" },

  { key: "fuel", label: "Топливо" },

  { key: "primary_damage", label: "Повреждение" },

  { key: "secondary_damage", label: "Вторичное" },

  { key: "keys", label: "Ключи" },

  { key: "highlights", label: "Highlights" },

  { key: "estimated_value", label: "Est. value" },

  { key: "repair_cost", label: "Repair cost" },

];



function formatDate(value: string) {

  const iso = value.match(/^(20\d{2}-\d{2}-\d{2})/);

  if (iso) {

    return new Date(`${iso[1]}T12:00:00`).toLocaleDateString("ru-RU", {

      day: "numeric",

      month: "short",

      year: "numeric",

    });

  }

  return value;

}



function factValue(lot: LotDetails, key: keyof LotDetails) {

  const value = lot[key];

  if (value === null || value === undefined || value === "") return "—";

  if (key === "estimated_value" || key === "repair_cost") return money(Number(value));

  if (key === "odometer") return Number(value).toLocaleString("en-GB");

  if (key === "category") return `Cat ${value}`;

  if (key === "sale_date") return formatDate(String(value));

  return String(value);

}



function lotPhotos(lot: LotDetails | null) {
  return copartPhotoUrls(lot?.images, 2);
}

/** Bid.cars / IAAI ссылка → USA расчёт, иначе Copart UK. */
function detectSource(value: string): "copart" | "iaai" {
  const v = value.trim().toLowerCase();
  if (/(?:^|\/\/|\.)bid\.cars\b|iaai\.com\b/i.test(v)) return "iaai";
  return "copart";
}


function historyThumb(item: CalcHistoryItem): string | null {
  const image = item.image;
  if (!image) return null;
  if (image.startsWith("/api/media/")) return image;
  if (isCopartPhotoUrl(image)) return copartDisplayUrl(image);
  // isCopartPhotoUrl is typed as `url is string`, so after false branch TS thinks never — keep as string
  const src: string = image;
  const low = src.toLowerCase();
  if (/\/content\/|clo-platinum|logo|icon|flag|favicon/.test(low)) return null;
  if (src.startsWith("https://")) return src;
  return null;
}

function historyAuction(item: CalcHistoryItem): "copart" | "iaai" {
  const raw = String(item.auction || "").toLowerCase();
  if (raw === "iaai" || raw === "bidcars" || raw === "usa") return "iaai";
  if (detectSource(item.url || "") === "iaai") return "iaai";
  return "copart";
}

function HistoryPanel({
  history,
  historyId,
  open,
  onToggle,
  onOpen,
}: {
  history: CalcHistoryItem[];
  historyId: number | null;
  open: boolean;
  onToggle: () => void;
  onOpen: (item: CalcHistoryItem) => void;
}) {
  return (
    <aside className={`calc-history${open ? "" : " collapsed"}`}>
      <button type="button" className="calc-history-toggle" onClick={onToggle} aria-expanded={open}>
        <span>История расчётов{history.length ? ` · ${history.length}` : ""}</span>
        <span className="calc-history-chevron" aria-hidden>{open ? "▴" : "▾"}</span>
      </button>
      {open ? (
        history.length === 0 ? (
          <p className="hint">Здесь появятся лоты Copart и Bid.cars, которые вы считали.</p>
        ) : (
          <div className="calc-history-list">
            {history.map((item) => {
              const historyPhoto = historyThumb(item);
              const auction = historyAuction(item);
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`calc-history-item${historyId === item.id ? " active" : ""}${historyPhoto ? "" : " no-photo"}`}
                  onClick={() => onOpen(item)}
                >
                  {historyPhoto ? <img src={historyPhoto} alt="" loading="lazy" /> : null}
                  <div className="calc-history-body">
                    <b>{item.title || `Lot ${item.lot_id}`}</b>
                    <small>{auction === "iaai" ? "Bid.cars / IAAI" : "Copart UK"}</small>
                    <small>
                      {item.bid != null ? `Ставка ${auction === "iaai" ? usd(item.bid) : money(item.bid)}` : "—"}
                      {item.total_uk != null ? ` · UK ${money(item.total_uk)}` : ""}
                      {item.grand_usd != null ? ` · ${usd(item.grand_usd)}` : ""}
                    </small>
                    <small>{item.location || "—"}{item.category ? ` · Cat ${item.category}` : ""}</small>
                  </div>
                </button>
              );
            })}
          </div>
        )
      ) : null}
    </aside>
  );
}

export default function Calculator() {

  const { fxRate } = useFxRate();

  const [url, setUrl] = useState("");
  const source = detectSource(url);

  const [lot, setLot] = useState<LotDetails | null>(null);

  const [historyId, setHistoryId] = useState<number | null>(null);

  const [history, setHistory] = useState<CalcHistoryItem[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [iaaiRestore, setIaaiRestore] = useState<(BidcarsLot & { history_id?: number | null }) | null>(null);

  const changeUrl = (value: string, opts?: { keepHistory?: boolean }) => {
    if (!opts?.keepHistory && detectSource(value) !== detectSource(url)) {
      setHistoryId(null);
      setIaaiRestore(null);
    }
    setUrl(value);
  };

  const [bid, setBid] = useState("");

  const [vehicleType, setVehicleType] = useState("sedan");

  const [deliveryColumn, setDeliveryColumn] = useState("");

  const [dismantleMode, setDismantleMode] = useState<"tariff" | "weight">("tariff");

  const [kg, setKg] = useState("");

  const [quote, setQuote] = useState<LotQuote | null>(null);

  const [quoteText, setQuoteText] = useState("");

  const [loading, setLoading] = useState(false);

  const [quoting, setQuoting] = useState(false);

  const [error, setError] = useState("");

  const [copied, setCopied] = useState(false);
  const historyIdRef = useRef(historyId);
  historyIdRef.current = historyId;
  const historyReloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reloadHistory = useCallback(async () => {
    try {
      const data = await api.calcHistory();
      setHistory(data.items);
    } catch {
      /* ignore */
    }
  }, []);

  const scheduleHistoryReload = useCallback(() => {
    if (historyReloadTimer.current) clearTimeout(historyReloadTimer.current);
    historyReloadTimer.current = setTimeout(() => {
      void reloadHistory();
    }, 800);
  }, [reloadHistory]);

  const onIaaiHistoryChange = useCallback(() => {
    scheduleHistoryReload();
  }, [scheduleHistoryReload]);



  useEffect(() => {

    void reloadHistory();

  }, [reloadHistory]);

  useEffect(() => {
    if (source === "iaai") {
      setLot(null);
      setQuote(null);
      setQuoteText("");
      setError("");
    } else {
      setIaaiRestore(null);
    }
  }, [source]);

  const applyLot = (data: LotDetails) => {

    setLot(data);

    setHistoryId(data.history_id ?? null);

    setBid(data.bid != null ? String(data.bid) : "");

    setVehicleType(data.dismantle_type || data.quote?.dismantle_type || "sedan");

    setDeliveryColumn("");

    setQuote(data.quote);

    setQuoteText(data.quote_text || "");

    setUrl(data.url || data.lot_id);
    setHistoryOpen(false);

  };



  const onLookup = async (event: FormEvent) => {

    event.preventDefault();

    setLoading(true);

    setError("");

    setCopied(false);

    try {

      const data = await api.lookupLot(url.trim());

      applyLot(data);

      void reloadHistory();

    } catch (err) {

      setError(err instanceof Error ? err.message : "Не удалось открыть лот");

    } finally {

      setLoading(false);

    }

  };



  const openHistoryItem = async (item: CalcHistoryItem) => {
    setError("");
    setCopied(false);
    try {
      const data = await api.calcHistoryItem(item.id);
      const auction =
        String((data as { auction?: string }).auction || item.auction || "").toLowerCase() === "iaai" ||
        detectSource(String((data as { url?: string }).url || item.url || "")) === "iaai"
          ? "iaai"
          : "copart";
      if (auction === "iaai") {
        setLot(null);
        setIaaiRestore({ ...(data as BidcarsLot), history_id: item.id });
        setHistoryId(item.id);
        changeUrl(String((data as { url?: string }).url || item.url || ""), { keepHistory: true });
        setHistoryOpen(false);
      } else {
        setIaaiRestore(null);
        applyLot(data as LotDetails);
        changeUrl((data as LotDetails).url || (data as LotDetails).lot_id, { keepHistory: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось открыть запись");
    }
  };

  useEffect(() => {

    if (!lot) return;

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

        .quoteLot({

          bid: price,

          lot_id: lot.lot_id,

          history_id: historyIdRef.current,

          location: lot.location,

          category: lot.category,

          title: lot.title,

          body_style: [lot.body_style, lot.vehicle_type_raw].filter(Boolean).join(" "),

          vat_on_sale: lot.vat_on_sale,

          dismantle_type: vehicleType,

          delivery_column: deliveryColumn || null,

          dismantle_kg: dismantleMode === "weight" && Number(kg) > 0 ? Number(kg) : null,

          url: lot.url,

        })

        .then((data) => {

          if (cancelled) return;

          setQuote(data.quote);

          setQuoteText(data.quote_text || "");

          if (data.history_id != null && data.history_id !== historyIdRef.current) {
            setHistoryId(data.history_id);
          }
          scheduleHistoryReload();

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

  }, [lot, bid, vehicleType, deliveryColumn, dismantleMode, kg, fxRate, scheduleHistoryReload]);



  const copyQuote = async () => {

    if (!quoteText) return;

    await navigator.clipboard.writeText(quoteText);

    setCopied(true);

    setTimeout(() => setCopied(false), 1500);

  };



  const photos = lotPhotos(lot);

  const categoryB = quote?.category_b ?? String(lot?.category || "").trim().toUpperCase() === "B";

  const autoColumn = autoDeliveryColumn(vehicleType, categoryB);

  const autoDeliveryLabel = DELIVERY_LABEL[autoColumn] || autoColumn;

  const autoDeliveryAmount =
    quote?.delivery && !deliveryColumn
      ? quote.delivery.amount
      : deliveryPrice(lot?.location, autoColumn);



  return (

    <div className="calc-page">
      <div className="calc-toolbar">
        <FxRateControl />
      </div>
      {source === "iaai" ? (
        <IaaiCalculator
          url={url}
          onUrlChange={changeUrl}
          historyId={historyId}
          onHistoryId={setHistoryId}
          onHistoryChange={onIaaiHistoryChange}
          restoreLot={iaaiRestore}
          historyPanel={
            <HistoryPanel
              history={history}
              historyId={historyId}
              open={historyOpen}
              onToggle={() => setHistoryOpen((v) => !v)}
              onOpen={(item) => void openHistoryItem(item)}
            />
          }
        />
      ) : (
      <div className="calc-layout">

        <div className="calc-main">

          <form className="calc-form" onSubmit={(event) => void onLookup(event)}>

            <input

              className="field"

              value={url}

              onChange={(e) => changeUrl(e.target.value)}

              placeholder="Ссылка Copart UK / Bid.cars или номер лота"

              required

            />

            <button className="btn" type="submit" disabled={loading}>

              {loading ? "Подтягиваю с Copart…" : "Подтянуть лот"}

            </button>

          </form>

          {error ? <div className="error">{error}</div> : null}

          {loading ? <div className="hint">Загружаю страницу лота в фоне — данные подтянутся из Copart автоматически.</div> : null}



          {lot ? (
            <>
            <div className="calc-workspace">
              <div className="calc-left">
              <section className="calc-lot">
                {photos.length > 0 ? (
                  <div className={`calc-photos photos-${photos.length}`}>
                    {photos.map((src) => (
                      <img key={src} src={src} alt="" loading="lazy" />
                    ))}
                  </div>
                ) : null}
                {lot.cached ? <div className="hint">Не удалось открыть Copart — взял данные из CRM.</div> : null}
                <h3>{lot.title || `Lot ${lot.lot_id}`}</h3>
                <p className="hint">
                  Текущая ставка Copart: {money(lot.bid)} · аукционные сборы Fee A (12+ авто/год) ·{" "}
                  <a href={lot.url} target="_blank" rel="noreferrer">открыть лот</a>
                </p>
                <div className="facts">
                  {FACTS.filter((item) => {
                    const value = lot[item.key];
                    if (["lot_id", "location", "category", "sale_date", "vin", "odometer", "body_style"].includes(item.key)) {
                      return true;
                    }
                    return value !== null && value !== undefined && value !== "";
                  }).map((item) => (
                    <div className="fact" key={item.key}>
                      <small>{item.label}</small>
                      <b>{factValue(lot, item.key)}</b>
                    </div>
                  ))}
                </div>
              </section>

              <HistoryPanel
                history={history}
                historyId={historyId}
                open={historyOpen}
                onToggle={() => setHistoryOpen((v) => !v)}
                onOpen={(item) => void openHistoryItem(item)}
              />
              </div>

              <section className="calc-panel">
                <label className="hint">Ваша ставка (£)</label>
                <input className="field" type="number" min="0" step="1" value={bid} onChange={(e) => setBid(e.target.value)} />

                <label className="hint">Тип доставки</label>
                <select className="select" value={deliveryColumn} onChange={(e) => setDeliveryColumn(e.target.value)}>
                  <option value="">
                    Авто — {autoDeliveryLabel} ({money(autoDeliveryAmount)})
                  </option>
                  {Object.entries(DELIVERY_LABEL).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label} ({money(deliveryPrice(lot?.location, key))})
                    </option>
                  ))}
                </select>

                <label className="hint">Тип авто для разбора</label>
                <select className="select" value={vehicleType} onChange={(e) => setVehicleType(e.target.value)}>
                  {Object.entries(DISMANTLE_LABEL).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label} ({usd(DISMANTLE_TARIFF_USD[key])})
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
                    По весу — 800 USD + 1.6 × кг
                  </label>
                </div>
                {dismantleMode === "weight" ? (
                  <>
                    <input className="field" type="number" min="0" placeholder="Вес, кг" value={kg} onChange={(e) => setKg(e.target.value)} />
                    <div className="hint">
                      {Number(kg) > 0
                        ? dismantleWeightHint(Number(kg))
                        : `Формула: ${DISMANTLE_WEIGHT_BASE} USD + ${DISMANTLE_WEIGHT_PER_KG} × кг`}
                    </div>
                  </>
                ) : null}

                {quoting ? <div className="hint">Считаю…</div> : null}
                {quote ? <QuoteBox quote={quote} /> : <p className="hint">Введите ставку, чтобы увидеть Copart Total и Итого UK.</p>}
                <button className="btn ghost" type="button" onClick={() => void copyQuote()} disabled={!quoteText}>
                  {copied ? "Скопировано" : "Скопировать расчёт"}
                </button>
              </section>
            </div>
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
            </>
          ) : (
            <HistoryPanel
              history={history}
              historyId={historyId}
              open={historyOpen}
              onToggle={() => setHistoryOpen((v) => !v)}
              onOpen={(item) => void openHistoryItem(item)}
            />
          )}
        </div>
      </div>
      )}

    </div>

  );

}


