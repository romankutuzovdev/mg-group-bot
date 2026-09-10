import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { QuoteRow, usd } from "./QuoteBox";

export type CustomsByResult = {
  ok: boolean;
  engine_type: string;
  is_electric: boolean;
  person: string;
  age_band: string;
  age_band_label: string;
  year?: number | null;
  engine_cc?: number | null;
  customs_value_eur: number;
  customs_value_usd?: number | null;
  duty_eur: number;
  duty_byn: number;
  duty_note?: string;
  formula?: string;
  benefit_50?: boolean;
  util_fee_byn: number;
  customs_ops_fee_byn: number;
  epts_fee_byn: number;
  total_byn: number;
  total_eur: number;
  total_usd?: number | null;
  rates?: { EUR_BYN?: number; USD_BYN?: number; source?: string };
  notes?: string[];
};

type Props = {
  priceUsd?: number | null;
  year?: number | null;
  engine?: string | null;
  fuel?: string | null;
  title?: string | null;
  engineCcHint?: number | null;
  /** Колбэк: итого США + растаможка (для копирования расчёта). */
  onGrandTotal?: (info: {
    usa_usd: number;
    customs_usd: number | null;
    customs_byn: number;
    grand_usd: number | null;
    grand_byn: number | null;
    text: string;
  } | null) => void;
};

function byn(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits })} BYN`;
}

function eur(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `€${value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Парсим см³ из строки двигателя / title на клиенте. */
export function parseEngineCcLocal(engine?: string | null, title?: string | null): number | null {
  const text = `${engine || ""} ${title || ""}`;
  if (!text.trim()) return null;
  let m = text.match(/(\d{3,4})\s*(?:cc|см\s*³|см3|cm3|куб)/i);
  if (m) return Number(m[1]);
  m = text.match(/(\d)\s*[.,]\s*(\d)\s*[lл]\b/i);
  if (m) return Number(m[1]) * 1000 + Number(m[2]) * 100;
  m = text.match(/(\d)[.,](\d)\s*(?:litre|liter)\b/i);
  if (m) return Number(m[1]) * 1000 + Number(m[2]) * 100;
  m = text.match(/\b(\d{1,2})\s*[lл]\b/i);
  if (m) {
    const liters = Number(m[1]);
    if (liters >= 1 && liters <= 8) return liters * 1000;
  }
  m = text.match(/\b(\d{4})\b/);
  if (m) {
    const n = Number(m[1]);
    if (n >= 600 && n <= 8000) return n;
  }
  return null;
}

export default function CustomsByPanel({
  priceUsd,
  year,
  engine,
  fuel,
  title,
  engineCcHint,
  onGrandTotal,
}: Props) {
  const [ageBand, setAgeBand] = useState<"under3" | "age3to5" | "over5" | "auto">("auto");
  const [engineType, setEngineType] = useState<"auto" | "fuel" | "electric" | "phev" | "erev">("auto");
  const [cc, setCc] = useState("");
  const [ccTouched, setCcTouched] = useState(false);
  const [benefit50, setBenefit50] = useState(false);
  const [ratesAuto, setRatesAuto] = useState(true);
  const [eurByn, setEurByn] = useState("");
  const [usdByn, setUsdByn] = useState("");
  const [result, setResult] = useState<CustomsByResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const reqId = useRef(0);

  useEffect(() => {
    void api
      .state()
      .then((s) => {
        const st = s as {
          eur_byn?: number | null;
          usd_byn?: number | null;
          byn_rates_source?: string | null;
        };
        if (st.eur_byn) setEurByn(String(st.eur_byn));
        if (st.usd_byn) setUsdByn(String(st.usd_byn));
        if (st.byn_rates_source === "manual") setRatesAuto(false);
      })
      .catch(() => undefined);
  }, []);

  // Автоподстановка объёма с лота (пока пользователь сам не правил поле)
  useEffect(() => {
    if (ccTouched) return;
    const fromHint = engineCcHint && engineCcHint > 0 ? engineCcHint : null;
    const parsed = fromHint || parseEngineCcLocal(engine, title);
    if (parsed && parsed > 0) setCc(String(parsed));
  }, [engineCcHint, engine, title, ccTouched]);

  const price = Number(priceUsd);
  const canCalc = Number.isFinite(price) && price > 0;
  const ccNum = Number(cc) > 0 ? Number(cc) : null;
  const eurNum = Number(String(eurByn).replace(",", ".")) || null;
  const usdNum = Number(String(usdByn).replace(",", ".")) || null;

  useEffect(() => {
    if (!canCalc) {
      setResult(null);
      setLoading(false);
      setError("");
      return;
    }
    const id = ++reqId.current;
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      void api
        .customsBy({
          price_usd: price,
          year: year ?? null,
          age_band: ageBand === "auto" ? null : ageBand,
          engine_type: engineType === "auto" ? null : engineType,
          engine_cc: ccNum,
          fuel: fuel || null,
          engine: engine || null,
          title: title || null,
          person: "individual",
          benefit_50: benefit50,
          include_epts: true,
          rates_auto: ratesAuto,
          eur_byn: ratesAuto ? null : eurNum,
          usd_byn: ratesAuto ? null : usdNum,
        })
        .then((data) => {
          if (id !== reqId.current) return;
          setResult(data);
          setError("");
          if (!ccTouched && data.engine_cc && !ccNum) {
            setCc(String(data.engine_cc));
          }
          if (ratesAuto && data.rates?.EUR_BYN) setEurByn(String(data.rates.EUR_BYN));
          if (ratesAuto && data.rates?.USD_BYN) setUsdByn(String(data.rates.USD_BYN));
        })
        .catch((err) => {
          if (id !== reqId.current) return;
          setError(err instanceof Error ? err.message : "Ошибка растаможки");
        })
        .finally(() => {
          if (id === reqId.current) setLoading(false);
        });
    }, 280);
    return () => {
      clearTimeout(timer);
    };
  }, [
    canCalc,
    price,
    year,
    ageBand,
    engineType,
    ccNum,
    fuel,
    engine,
    title,
    benefit50,
    ccTouched,
    ratesAuto,
    eurNum,
    usdNum,
  ]);

  const engineLabel = useMemo(() => {
    if (!result) return "";
    if (result.is_electric) return "Электро";
    if (result.engine_type === "erev") return "Гибрид EREV";
    if (result.engine_type === "phev") return "Гибрид / PHEV";
    return "Топливо";
  }, [result]);

  const usdBynRate = result?.rates?.USD_BYN || usdNum || null;
  const customsUsd =
    result?.total_usd != null && Number.isFinite(result.total_usd)
      ? result.total_usd
      : result && usdBynRate
        ? result.total_byn / usdBynRate
        : null;
  const grandUsd =
    canCalc && customsUsd != null && Number.isFinite(customsUsd) ? price + customsUsd : null;
  const usaByn = canCalc && usdBynRate ? price * usdBynRate : null;
  const grandByn =
    result && usaByn != null ? usaByn + result.total_byn : null;

  useEffect(() => {
    if (!onGrandTotal) return;
    if (!result || !canCalc || grandUsd == null) {
      onGrandTotal(null);
      return;
    }
    const lines = [
      "",
      "────────────────────",
      `Растаможка РБ: ${result.total_byn.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BYN` +
        (customsUsd != null ? ` (~$${customsUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })})` : ""),
      `Итого с растаможкой: $${grandUsd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` +
        (grandByn != null
          ? ` · ${grandByn.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} BYN`
          : ""),
    ];
    onGrandTotal({
      usa_usd: price,
      customs_usd: customsUsd,
      customs_byn: result.total_byn,
      grand_usd: grandUsd,
      grand_byn: grandByn,
      text: lines.join("\n"),
    });
  }, [onGrandTotal, result, canCalc, grandUsd, grandByn, price, customsUsd]);

  if (!canCalc) {
    return (
      <div className="customs-by">
        <div className="quote-caption">Растаможка РБ</div>
        <p className="hint">Сначала посчитайте расходы США — растаможка возьмёт эту сумму как таможенную стоимость.</p>
      </div>
    );
  }

  return (
    <div className="customs-by">
      <div className="quote-caption">Растаможка РБ (ЕАЭС)</div>
      <p className="hint" style={{ marginBottom: 8 }}>
        Единый платёж по Решению ЕЭК №107 + утилсбор. EV → пошлина 0.
        {year ? ` · год с лота: ${year}` : ""}
      </p>

      <label className="hint">Курсы для растаможки (BYN)</label>
      <label className="check" style={{ marginBottom: 8 }}>
        <input
          type="checkbox"
          checked={ratesAuto}
          onChange={(e) => {
            const on = e.target.checked;
            setRatesAuto(on);
            if (on) {
              void api.setBynRates({ auto: true }).then((r) => {
                if (r.eur_byn) setEurByn(String(r.eur_byn));
                if (r.usd_byn) setUsdByn(String(r.usd_byn));
              });
            }
          }}
        />
        Взять автоматически (НБРБ)
      </label>
      <div className="fx-row" style={{ gap: 8, marginBottom: 8 }}>
        <label className="hint" style={{ flex: 1 }}>
          EUR
          <input
            className="field"
            type="number"
            min="0"
            step="0.0001"
            value={eurByn}
            disabled={ratesAuto}
            onChange={(e) => {
              setRatesAuto(false);
              setEurByn(e.target.value);
            }}
            onBlur={() => {
              if (!ratesAuto && Number(eurByn) > 0) {
                void api.setBynRates({ eur_byn: Number(eurByn), usd_byn: usdNum, auto: false });
              }
            }}
          />
        </label>
        <label className="hint" style={{ flex: 1 }}>
          USD
          <input
            className="field"
            type="number"
            min="0"
            step="0.0001"
            value={usdByn}
            disabled={ratesAuto}
            onChange={(e) => {
              setRatesAuto(false);
              setUsdByn(e.target.value);
            }}
            onBlur={() => {
              if (!ratesAuto && Number(usdByn) > 0) {
                void api.setBynRates({ eur_byn: eurNum, usd_byn: Number(usdByn), auto: false });
              }
            }}
          />
        </label>
      </div>

      <label className="hint">Возраст авто</label>
      <div className="segment">
        {(
          [
            ["auto", "Авто"],
            ["under3", "< 3 лет"],
            ["age3to5", "3–5 лет"],
            ["over5", "> 5 лет"],
          ] as const
        ).map(([key, label]) => (
          <label className="check" key={key}>
            <input type="radio" checked={ageBand === key} onChange={() => setAgeBand(key)} />
            {label}
          </label>
        ))}
      </div>

      <label className="hint">Тип двигателя</label>
      <div className="segment">
        {(
          [
            ["auto", "Авто"],
            ["fuel", "Топливо"],
            ["electric", "Электро"],
            ["phev", "PHEV"],
            ["erev", "EREV"],
          ] as const
        ).map(([key, label]) => (
          <label className="check" key={key}>
            <input type="radio" checked={engineType === key} onChange={() => setEngineType(key)} />
            {label}
          </label>
        ))}
      </div>

      <label className="hint">Объём двигателя, см³</label>
      <input
        className="field"
        type="number"
        min="0"
        step="1"
        value={cc}
        onChange={(e) => {
          setCcTouched(true);
          setCc(e.target.value);
        }}
        placeholder={engine || "например 1998"}
        disabled={engineType === "electric" || result?.is_electric === true}
      />

      <label className="check" style={{ marginTop: 8, marginBottom: 8 }}>
        <input type="checkbox" checked={benefit50} onChange={(e) => setBenefit50(e.target.checked)} />
        Льгота 50% (Указ №140)
      </label>

      {loading ? <div className="hint">Считаю растаможку…</div> : null}
      {error ? <div className="error">{error}</div> : null}

      {result ? (
        <div className="quote-box" style={{ marginTop: 8 }}>
          <div className="quote-vat-note">
            {result.age_band_label}
            {engineLabel ? ` · ${engineLabel}` : ""}
            {result.engine_cc ? ` · ${result.engine_cc} см³` : ""}
            {result.rates?.EUR_BYN ? ` · EUR ${result.rates.EUR_BYN}` : ""}
          </div>
          <QuoteRow
            label="Таможенная стоимость"
            hint={result.customs_value_usd != null ? usd(result.customs_value_usd, 0) : undefined}
            value={eur(result.customs_value_eur)}
          />
          <QuoteRow
            label={result.is_electric ? "Единый платёж (EV = 0)" : "Единый таможенный платёж"}
            hint={result.formula || result.duty_note}
            value={`${eur(result.duty_eur)} · ${byn(result.duty_byn)}`}
          />
          <QuoteRow label="Утилизационный сбор" value={byn(result.util_fee_byn)} />
          <QuoteRow label="Таможенный сбор" value={byn(result.customs_ops_fee_byn)} />
          {result.epts_fee_byn > 0 ? <QuoteRow label="ЭПТС" value={byn(result.epts_fee_byn)} /> : null}
          <QuoteRow
            label="Итого растаможка РБ"
            hint={customsUsd != null ? `~${usd(customsUsd, 0)}` : undefined}
            value={byn(result.total_byn)}
            total
          />
          {grandUsd != null ? (
            <>
              <div className="quote-caption" style={{ marginTop: 12 }}>
                Итоговая стоимость
              </div>
              <QuoteRow label="Расходы США" value={usd(price, 2)} />
              <QuoteRow
                label="Растаможка РБ"
                hint={byn(result.total_byn)}
                value={customsUsd != null ? `~${usd(customsUsd, 2)}` : "—"}
              />
              <QuoteRow
                label="Итого с растаможкой"
                hint={grandByn != null ? byn(grandByn) : undefined}
                value={usd(grandUsd, 2)}
                total
              />
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
