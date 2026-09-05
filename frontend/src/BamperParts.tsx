import { useEffect, useMemo, useState } from "react";
import { api, ApiError, type BamperJob, type BamperPartRow } from "./api";

function byn(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value).toLocaleString("ru-RU")} BYN`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function slugFile(value: string): string {
  return value
    .trim()
    .replace(/[^\p{L}\p{N}]+/gu, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "auto";
}

type VehicleInfo = {
  make?: string | null;
  model?: string | null;
  year?: number | null;
  title?: string | null;
  vin?: string | null;
  lotId?: string | null;
  url?: string | null;
  engine?: string | null;
  fuel?: string | null;
  transmission?: string | null;
  bodyStyle?: string | null;
};

function carTitle(info: VehicleInfo, job: BamperJob | null): string {
  const named = [info.year, info.make, info.model].filter(Boolean).join(" ");
  if (named) return named;
  if (info.title) return info.title;
  const v = job?.vehicle;
  if (v) {
    return [v.year || info.year, v.make || v.marka, v.model || v.model_slug].filter(Boolean).join(" ");
  }
  return "Авто";
}

const MAIN_PART_CODES = [
  "bamper-peredniy",
  "bamper-zadniy",
  "kapot",
  "kryshka-bagazhnika-dver-3-5",
  "dver-perednyaya-levaya",
  "dver-perednyaya-pravaya",
  "dver-zadnyaya-levaya",
  "dver-zadnyaya-pravaya",
  "krylo-perednee-levoe",
  "krylo-perednee-pravoe",
  "krylo-zadnee-levoe",
  "krylo-zadnee-pravoe",
  "porog-levyy",
  "porog-pravyy",
  "lonzheron-levyy",
  "lonzheron-pravyy",
  "krysha",
  "spoyler",
  "reshetka-radiatora",
  "fara-levaya",
  "fara-pravaya",
  "fara-protivotumannaya-levaya",
  "fara-protivotumannaya-pravaya",
  "fonar-zadniy-levyy",
  "fonar-zadniy-pravyy",
  "povorotnik-levyy",
  "povorotnik-pravyy",
  "zerkalo-naruzhnoe-levoe",
  "zerkalo-naruzhnoe-pravoe",
  "steklo-lobovoe",
  "steklo-zadnee",
  "dvigatel",
  "kpp-avtomaticheskaya-akpp",
  "kpp-mekhanicheskaya-mkpp",
  "razdatochnaya-korobka",
  "generator",
  "starter",
  "turbina",
  "radiator-osnovnoy",
  "radiator-konditsionera",
  "kompressor-konditsionera",
  "ventilyator-radiatora",
  "nasos-toplivnyy",
  "bak-toplivnyy",
  "glushitel",
  "katalizator",
  "amortizator-peredniy-levyy",
  "amortizator-peredniy-pravyy",
  "amortizator-zadniy-levyy",
  "amortizator-zadniy-pravyy",
  "rychag-peredniy-levyy",
  "rychag-peredniy-pravyy",
  "stupitsa-perednyaya-levaya",
  "stupitsa-perednyaya-pravaya",
  "poluos-perednyaya-levaya-privodnoy-val-shrus",
  "poluos-perednyaya-pravaya-privodnoy-val-shrus",
  "rulevaya-reyka",
  "nasos-gidrousilitelya-rulya",
  "koleso-v-sbore",
  "disk-litoy",
  "panel-perednyaya-salona-torpedo",
  "shchitok-priborov-pribornaya-panel",
  "sidene-perednee-levoe",
  "sidene-perednee-pravoe",
  "sidene-zadnee",
] as const;

function proposalParts(job: BamperJob): BamperPartRow[] {
  const codes = job.dismantle_codes?.length ? job.dismantle_codes : [...MAIN_PART_CODES];
  const byCode = new Map((job.parts || []).map((p) => [p.code, p]));
  const main = codes.map((code) => byCode.get(code)).filter((p): p is BamperPartRow => Boolean(p));
  if (main.length) return main;
  return [...(job.parts || [])].sort((a, b) => a.name.localeCompare(b.name, "ru"));
}

function proposalTotals(parts: BamperPartRow[]): { sumAvg: number; withOffers: number } {
  let sumAvg = 0;
  let withOffers = 0;
  for (const p of parts) {
    if (p.avg_byn != null && !Number.isNaN(p.avg_byn)) sumAvg += p.avg_byn;
    if (p.count && p.count > 0) withOffers += 1;
  }
  return { sumAvg, withOffers };
}

const PART_GROUPS: { title: string; codes: readonly string[] }[] = [
  { title: "Кузов", codes: MAIN_PART_CODES.slice(0, 19) },
  { title: "Оптика и стёкла", codes: MAIN_PART_CODES.slice(19, 31) },
  { title: "ДВС / КПП", codes: MAIN_PART_CODES.slice(31, 46) },
  { title: "Ходовая", codes: MAIN_PART_CODES.slice(46, 60) },
  { title: "Салон", codes: MAIN_PART_CODES.slice(60) },
];

const TG_MAX = 3900;

function escTg(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function groupedParts(parts: BamperPartRow[]): { title: string; items: BamperPartRow[] }[] {
  const byCode = new Map(parts.map((p) => [p.code, p]));
  const used = new Set<string>();
  const groups: { title: string; items: BamperPartRow[] }[] = [];
  for (const g of PART_GROUPS) {
    const items = g.codes.map((c) => byCode.get(c)).filter((p): p is BamperPartRow => Boolean(p));
    items.forEach((p) => used.add(p.code));
    if (items.length) groups.push({ title: g.title, items });
  }
  const rest = parts.filter((p) => !used.has(p.code));
  if (rest.length) groups.push({ title: "Прочее", items: rest });
  return groups;
}

function packTelegram(chunks: string[]): string[] {
  const pieces: string[] = [];
  for (const chunk of chunks) {
    if (!chunk) continue;
    if (chunk.length <= TG_MAX) {
      pieces.push(chunk);
      continue;
    }
    let buf = "";
    for (const line of chunk.split("\n")) {
      const next = buf ? `${buf}\n${line}` : line;
      if (next.length <= TG_MAX) {
        buf = next;
      } else {
        if (buf) pieces.push(buf);
        buf = line.slice(0, TG_MAX);
      }
    }
    if (buf) pieces.push(buf);
  }
  const out: string[] = [];
  let buf = "";
  for (const chunk of pieces) {
    if (!buf) {
      buf = chunk;
      continue;
    }
    if (buf.length + 2 + chunk.length <= TG_MAX) {
      buf += `\n\n${chunk}`;
    } else {
      out.push(buf);
      buf = chunk;
    }
  }
  if (buf) out.push(buf);
  return out;
}

function formatProposalTelegram(job: BamperJob, info: VehicleInfo, html: boolean): string[] {
  const car = carTitle(info, job);
  const date = new Date().toLocaleDateString("ru-RU");
  const parts = proposalParts(job);
  const totals = proposalTotals(parts);
  const b = (s: string) => (html ? `<b>${escTg(s)}</b>` : s);
  const i = (s: string) => (html ? `<i>${escTg(s)}</i>` : s);
  const t = (s: string) => (html ? escTg(s) : s);
  const code = (s: string) => (html ? `<code>${escTg(s)}</code>` : s);

  const head: string[] = [
    b("MG Group"),
    t("Коммерческое предложение"),
    t(date),
    "",
    b(car),
  ];
  if (info.vin) head.push(`VIN: ${code(info.vin)}`);
  if (info.lotId) head.push(`Лот: ${code(String(info.lotId))}`);
  if (info.url) {
    head.push(html ? `<a href="${escTg(info.url)}">Открыть лот</a>` : info.url);
  }
  head.push("");
  head.push(b(`Оценка: ${byn(totals.sumAvg || null)}`));
  head.push(i("основные запчасти · средние цены Bamper.by"));

  const blocks = [head.join("\n")];
  for (const group of groupedParts(parts)) {
    const lines = [b(group.title)];
    for (const p of group.items) {
      const price = p.avg_byn != null ? byn(p.avg_byn) : "по запросу";
      lines.push(`• ${t(p.name)} — ${t(price)}`);
      if (p.url) {
        lines.push(html ? `<a href="${escTg(p.url)}">Bamper.by</a>` : p.url);
      }
    }
    blocks.push(lines.join("\n"));
  }
  blocks.push(i("Цены средние на дату. Не являются публичной офертой."));
  return packTelegram(blocks);
}

function formatProposalText(job: BamperJob, info: VehicleInfo): string {
  const car = carTitle(info, job);
  const date = new Date().toLocaleDateString("ru-RU");
  const parts = proposalParts(job);
  const totals = proposalTotals(parts);
  const lines = [
    "MG Group",
    "Коммерческое предложение",
    date,
    "",
    `Авто: ${car}`,
  ];
  if (info.vin) lines.push(`VIN: ${info.vin}`);
  if (info.lotId) lines.push(`Лот: ${info.lotId}`);
  if (info.url) lines.push(info.url);
  lines.push("");
  lines.push(`Оценка авто (основные запчасти, сумма средних цен Bamper.by): ${byn(totals.sumAvg || null)}`);
  lines.push(`Основных позиций: ${parts.length}`);
  if (totals.withOffers) lines.push(`С объявлениями: ${totals.withOffers}`);
  lines.push("");
  lines.push("Запчасти:");
  parts.forEach((p, idx) => {
    const price = p.avg_byn != null ? byn(p.avg_byn) : "по запросу";
    const ads = p.count == null ? "" : `, объявлений: ${p.count}`;
    lines.push(`${idx + 1}. ${p.name} — ${price}${ads}`);
    lines.push(p.url);
  });
  lines.push("");
  lines.push("Цены — средние по объявлениям bamper.by на дату предложения.");
  lines.push("Не являются публичной офертой.");
  return lines.join("\n");
}

function formatProposalHtml(job: BamperJob, info: VehicleInfo): string {
  const car = carTitle(info, job);
  const date = new Date().toLocaleDateString("ru-RU");
  const parts = proposalParts(job);
  const totals = proposalTotals(parts);
  const rows = parts
    .map((p, idx) => {
      const price = p.avg_byn != null ? byn(p.avg_byn) : "по запросу";
      const ads = p.count == null ? "—" : String(p.count);
      return `<tr>
        <td>${idx + 1}</td>
        <td>${escapeHtml(p.name)}<div class="code">${escapeHtml(p.code)}</div></td>
        <td>${ads}</td>
        <td>${escapeHtml(price)}</td>
        <td><a href="${escapeHtml(p.url)}">${escapeHtml(p.url)}</a></td>
      </tr>`;
    })
    .join("\n");
  const facts = [
    info.vin ? `<p><b>VIN:</b> ${escapeHtml(info.vin)}</p>` : "",
    info.lotId ? `<p><b>Лот:</b> ${escapeHtml(info.lotId)}</p>` : "",
    info.url ? `<p><b>Ссылка на лот:</b> <a href="${escapeHtml(info.url)}">${escapeHtml(info.url)}</a></p>` : "",
  ]
    .filter(Boolean)
    .join("\n");
  return `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <title>Коммерческое предложение — ${escapeHtml(car)}</title>
  <style>
    body { font-family: Arial, sans-serif; color: #111; margin: 32px; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .brand { color: #555; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; }
    .meta { margin: 16px 0 20px; }
    .total { font-size: 18px; margin: 12px 0 20px; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; text-align: left; }
    th { background: #f3f3f3; }
    td a { word-break: break-all; }
    .code { color: #777; font-size: 11px; margin-top: 2px; }
    .note { color: #555; font-size: 12px; margin-top: 18px; }
  </style>
</head>
<body>
  <div class="brand">MG Group</div>
  <h1>Коммерческое предложение</h1>
  <p>${escapeHtml(date)}</p>
  <div class="meta">
    <p><b>Авто:</b> ${escapeHtml(car)}</p>
    ${facts}
  </div>
  <p class="total"><b>Оценка авто (основные запчасти, сумма средних цен):</b> ${escapeHtml(byn(totals.sumAvg || null))}</p>
  <p>Основных позиций: ${parts.length}${totals.withOffers ? ` · с объявлениями: ${totals.withOffers}` : ""}</p>
  <table>
    <thead>
      <tr>
        <th>№</th>
        <th>Запчасть</th>
        <th>Объявл.</th>
        <th>Средняя цена</th>
        <th>Ссылка Bamper.by</th>
      </tr>
    </thead>
    <tbody>
      ${rows}
    </tbody>
  </table>
  <p class="note">Цены — средние по объявлениям bamper.by на дату предложения. Не являются публичной офертой.</p>
</body>
</html>`;
}

type Props = VehicleInfo;

export default function BamperParts({
  make,
  model,
  year,
  title,
  vin,
  lotId,
  url,
  engine,
  fuel,
  transmission,
  bodyStyle,
}: Props) {
  const [job, setJob] = useState<BamperJob | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [onlyOffers, setOnlyOffers] = useState(false);
  const [copied, setCopied] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const info: VehicleInfo = { make, model, year, title, vin, lotId, url, engine, fuel, transmission, bodyStyle };

  useEffect(() => {
    setJob(null);
    setError(null);
    setQ("");
    setCopied(false);
    setSent(false);
  }, [make, model, year, title, vin, lotId, url, engine, fuel, transmission, bodyStyle]);

  useEffect(() => {
    if (!job?.id || job.status !== "running") return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await api.bamperJob(job.id);
        if (!cancelled) setJob(next);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setJob(null);
          setError("Поиск сброшен после перезапуска сервера. Нажмите «Искать по этому авто» ещё раз.");
        }
      }
    };
    const timer = window.setInterval(() => void tick(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status]);

  const start = async (scrape: boolean, mode: "dismantle" | "full" = "dismantle") => {
    if (!make && !title) {
      setError("Сначала подтяните лот — нужна марка/модель авто.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const next = await api.bamperSearch({
        make: make || null,
        model: model || null,
        year: year ?? null,
        title: title || null,
        engine: engine || null,
        fuel: fuel || null,
        transmission: transmission || null,
        body_style: bodyStyle || null,
        scrape,
        mode,
      });
      setJob(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const cancel = async () => {
    if (!job?.id) return;
    try {
      const next = await api.bamperCancel(job.id);
      setJob(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const rows = useMemo(() => {
    const parts = job?.parts || [];
    const query = q.trim().toLowerCase();
    return parts.filter((p) => {
      if (onlyOffers) {
        if (!(p.count && p.count > 0)) return false;
      }
      if (!query) return true;
      return p.name.toLowerCase().includes(query) || p.code.toLowerCase().includes(query);
    });
  }, [job, q, onlyOffers]);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const ac = a.count || 0;
      const bc = b.count || 0;
      if (Boolean(bc) !== Boolean(ac)) return bc ? 1 : -1;
      const aa = a.avg_byn ?? 0;
      const ba = b.avg_byn ?? 0;
      if (ba !== aa) return ba - aa;
      return a.name.localeCompare(b.name, "ru");
    });
  }, [rows]);

  const years =
    job?.vehicle?.year_from && job?.vehicle?.year_to
      ? `${job.vehicle.year_from}–${job.vehicle.year_to}`
      : job?.vehicle?.year
        ? String(job.vehicle.year)
        : year
          ? String(year)
          : "";
  const advancedBits = [
    years,
    job?.vehicle?.enginevalue ? `${job.vehicle.enginevalue} л` : "",
    job?.vehicle?.toplivo_label || "",
    job?.vehicle?.korobka_label || "",
    job?.vehicle?.kuzov_label || "",
  ].filter(Boolean);
  const vehicleLabel = job?.vehicle
    ? `${job.vehicle.marka || "?"} / ${job.vehicle.model_slug || "?"}${advancedBits.length ? ` · ${advancedBits.join(", ")}` : ""}`
    : [make, model, year].filter(Boolean).join(" · ") || title || "—";

  const kpParts = useMemo(() => (job ? proposalParts(job) : []), [job]);
  const kpTotals = useMemo(() => proposalTotals(kpParts), [kpParts]);
  const tgPlain = useMemo(
    () => (job ? formatProposalTelegram(job, info, false) : []),
    [job, make, model, year, title, vin, lotId, url],
  );
  const tgHtml = useMemo(
    () => (job ? formatProposalTelegram(job, info, true) : []),
    [job, make, model, year, title, vin, lotId, url],
  );
  const progress = job && job.total > 0 ? Math.round((100 * job.done) / job.total) : 0;
  const canSearch = Boolean(make || title);
  const estimate = kpTotals.sumAvg || 0;
  const canExport = Boolean(job && kpParts.length);

  const copyProposal = async () => {
    if (!job) return;
    const text = tgPlain.join("\n\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      setError("Не удалось скопировать. Выделите текст ниже вручную.");
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  const sendProposal = async () => {
    if (!job || !tgHtml.length) return;
    setSending(true);
    setError(null);
    try {
      await api.sendTelegram(tgHtml);
      setSent(true);
      window.setTimeout(() => setSent(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  };

  const downloadProposal = () => {
    if (!job) return;
    const html = formatProposalHtml(job, info);
    const name = `KP_${slugFile(carTitle(info, job))}.html`;
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
    URL.revokeObjectURL(href);
  };

  return (
    <section className="bamper-box">
      <div className="bamper-head">
        <div>
          <h3>Запчасти для коммерческого предложения</h3>
          <p className="hint">
            КП по <b>основным запчастям</b> этого авто ({vehicleLabel}): кузов, оптика, ДВС/КПП, ходовая, салон.
            Поиск на Bamper — <b>расширенный</b> (год, объём, топливо, КПП, кузов с лота).
            Оценка — сумма средних цен Bamper, не минимальных.
          </p>
        </div>
        <div className="bamper-actions">
          <button
            className="btn"
            type="button"
            disabled={!canSearch || loading || job?.status === "running"}
            onClick={() => void start(true, "dismantle")}
          >
            {loading ? "Стартую…" : job?.status === "running" ? "Идёт поиск…" : "Собрать КП"}
          </button>
          <button
            className="btn ghost"
            type="button"
            disabled={!canSearch || loading || job?.status === "running"}
            onClick={() => void start(false, "dismantle")}
          >
            Только ссылки
          </button>
          <button
            className="btn ghost"
            type="button"
            disabled={!canSearch || loading || job?.status === "running"}
            onClick={() => void start(true, "full")}
            title="Весь каталог Bamper, в КП всё равно попадут только основные детали"
          >
            Весь каталог
          </button>
          {job?.status === "running" ? (
            <button className="btn ghost" type="button" onClick={() => void cancel()}>
              Стоп
            </button>
          ) : null}
        </div>
      </div>

      {error ? <div className="error">{error}</div> : null}

      {job ? (
        <>
          <div className="bamper-estimate">
            <span>Для КП · оценка по основным деталям</span>
            <b>{byn(estimate || null)}</b>
            <small>сумма средних цен, {kpParts.length} позиций</small>
            <div className="bamper-actions">
              <button className="btn" type="button" disabled={!canExport || sending} onClick={() => void sendProposal()}>
                {sending ? "Отправляю…" : sent ? "Отправлено в Telegram" : "Отправить в Telegram"}
              </button>
              <button className="btn ghost" type="button" disabled={!canExport} onClick={() => void copyProposal()}>
                {copied ? "Скопировано" : "Скопировать для Telegram"}
              </button>
              <button className="btn ghost" type="button" disabled={!canExport} onClick={downloadProposal}>
                Скачать HTML
              </button>
            </div>
          </div>
          <div className="bamper-meta">
            <span>
              Режим: {job.mode === "dismantle" ? "основные запчасти" : "весь каталог"}
            </span>
            <span>
              В списке {job.parts.length} из {job.total}
              {job.status === "running" ? ` · проверено ${job.done} (${progress}%)` : ""}
            </span>
            <span>С объявлениями: {job.with_offers}</span>
            <span className="hint">сумма мин. цен: {byn(job.sum_min_byn || null)}</span>
            <span className="hint">статус: {job.status}</span>
          </div>
          {job.status === "running" ? (
            <div className="bamper-progress">
              <i style={{ width: `${progress}%` }} />
            </div>
          ) : null}
          <div className="bamper-filters">
            <input
              className="field"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Фильтр: бампер, фара, дверь…"
            />
            <label className="check">
              <input type="checkbox" checked={onlyOffers} onChange={(e) => setOnlyOffers(e.target.checked)} />
              Только с объявлениями
            </label>
          </div>
          <div className="bamper-table-wrap">
            <table className="bamper-table">
              <thead>
                <tr>
                  <th>Деталь</th>
                  <th>Объявл.</th>
                  <th>От</th>
                  <th>Средняя</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((p) => (
                  <tr key={p.code}>
                    <td>
                      <b>{p.name}</b>
                      <small>{p.code}</small>
                    </td>
                    <td>{p.count == null ? "…" : p.count}</td>
                    <td>{byn(p.min_byn)}</td>
                    <td>{byn(p.avg_byn)}</td>
                    <td>
                      <a href={p.url} target="_blank" rel="noreferrer">
                        Bamper
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {sorted.length === 0 ? (
              <p className="hint">Нет строк по фильтру — снимите «Только с объявлениями» или измените поиск.</p>
            ) : null}
          </div>
        </>
      ) : (
        <p className="hint">
          Подтяните лот и нажмите «Собрать КП» — в предложение попадут основные детали (бампер, двери, фары, двигатель, КПП…). Потом можно скопировать или скачать.
        </p>
      )}
    </section>
  );
}
