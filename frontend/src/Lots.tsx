import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { useFxRate } from "./FxRateContext";
import { QuoteBox, dismantleTypeLabel, deliveryTypeLabel, money, usd } from "./QuoteBox";
import type { AppState, Lot, LotStatus, StockFilter } from "./types";
import { STATUS_LABEL } from "./types";

function when(value: string | null | undefined) {
  if (!value) return "ещё не было";
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(value: string | null | undefined) {
  if (!value) return "ещё не проверялось";
  const mins = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (mins < 1) return "только что";
  if (mins < 60) return `${mins} мин назад`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} ч назад`;
  return when(value);
}

export default function Lots({ platform = "copart" }: { platform?: "copart" | "bidcars" }) {
  const isBidcars = platform === "bidcars";
  const siteName = isBidcars ? "Bid.cars" : "Copart";
  const { fxRate } = useFxRate();
  const [state, setState] = useState<AppState | null>(null);
  const [lots, setLots] = useState<Lot[]>([]);
  const [listMode, setListMode] = useState<"feed" | "hidden">("feed");
  const [stock, setStock] = useState<StockFilter>("in");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Lot | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [addingSearch, setAddingSearch] = useState(false);
  const [error, setError] = useState("");

  const loadState = async () => {
    setState(await api.state(platform));
  };

  const loadLots = async () => {
    if (listMode === "hidden") {
      setLots(await api.lots({ stock, q: query, status: "skip", source: platform }));
      return;
    }
    setLots(await api.lots({ stock, q: query, feed: true, source: platform }));
  };

  const refresh = async () => {
    try {
      await loadState();
      await loadLots();
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка API. Запущен ли python app.py?");
    }
  };

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 20000);
    return () => clearInterval(timer);
  }, [listMode, stock, query, fxRate, platform]);

  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const dismissLot = async (lot: Lot) => {
    await api.patchLot(lot.lot_id, { status: "skip" });
    if (selected?.lot_id === lot.lot_id) setSelected(null);
    await refresh();
  };

  const onAddSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const url = String(data.get("url") || "").trim();
    if (!url) {
      setError(isBidcars ? "Вставьте URL поиска с Bid.cars" : "Вставьте URL поиска с Copart");
      return;
    }
    setAddingSearch(true);
    setError("");
    try {
      const created = await api.addSearch({
        name: String(data.get("name") || ""),
        url,
        comment: String(data.get("comment") || ""),
        client_telegram: String(data.get("telegram") || ""),
        client_phone: String(data.get("phone") || ""),
        platform,
      });
      form.reset();
      await refresh();
      if (created.seeding) {
        setError("");
        for (let i = 0; i < 60; i += 1) {
          await new Promise((resolve) => setTimeout(resolve, 3000));
          const next = await api.state();
          setState(next);
          await loadLots();
          if (!next.sync.running) break;
        }
        await refresh();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось добавить поиск");
    } finally {
      setAddingSearch(false);
    }
  };

  const onSync = async () => {
    setSyncing(true);
    try {
      await api.sync(platform);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка синхронизации");
    } finally {
      setSyncing(false);
    }
  };

  const selectedLot = useMemo(
    () => lots.find((lot) => lot.lot_id === selected?.lot_id) ?? selected,
    [lots, selected],
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="hint">
          Python каждые {state?.interval_minutes ?? 10} минут проверяет ваши поиски {siteName}.
          {state?.telegram
            ? ` Новые авто — в Telegram (${state.notify_count ?? 0} чел.).`
            : " Telegram не задан — уведомлений не будет."}
        </div>
        <div className="stats">
          <div className="stat"><b>{state?.stats.in_search ?? state?.stats.in_stock ?? 0}</b><small>в поиске</small></div>
          <div className="stat"><b>{state?.stats.new ?? 0}</b><small>новых</small></div>
        </div>
        <div className="hint">
          {state?.sync.running || syncing
            ? `Идёт проверка ${siteName}…`
            : `Последняя проверка: ${ago(state?.sync.last?.finished_at || state?.sync.last?.started_at)}`}
        </div>
        {error ? <div className="error">{error}</div> : null}
        <button className="btn" onClick={() => void onSync()} disabled={syncing}>
          {syncing ? "Проверяю…" : "Проверить сейчас"}
        </button>
        <h2>Поиски</h2>
        <div>
          {state?.searches.map((item) => (
            <div className="search-card" key={item.id}>
              <strong>{item.name}</strong>
              {item.params && item.params.length > 0 ? (
                <div className="chips">
                  {item.params.map((param) => (
                    <span className="chip" key={`${param.key}-${param.value}`}>
                      {param.label}: {param.value}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="hint">{item.summary}</div>
              )}
              <div className="hint">
                {item.in_search ?? 0} в поиске · {item.new_count ?? 0} новых
                {" · "}
                {item.enabled ? "включён" : "выключен"}
                {!item.seeded_at ? " · первичная загрузка…" : ""}
                {" · "}Проверено: {ago(item.last_checked_at || state?.sync.last?.finished_at || state?.sync.last?.started_at)}
              </div>
              {item.owner_name || item.client_telegram || item.client_phone || item.comment ? (
                <div className="search-client">
                  {item.owner_name ? <div>Менеджер: {item.owner_name}</div> : null}
                  {item.client_telegram ? <div>Telegram клиента: {item.client_telegram}</div> : null}
                  {item.client_phone ? <div>Телефон: {item.client_phone}</div> : null}
                  {item.comment ? <div>Комментарий: {item.comment}</div> : null}
                </div>
              ) : null}
              <div className="row">
                <button
                  className="btn ghost small"
                  onClick={() => void api.setSearchEnabled(item.id, !item.enabled).then(refresh)}
                >
                  {item.enabled ? "Выкл" : "Вкл"}
                </button>
                <button
                  className="btn ghost small"
                  onClick={() => {
                    if (confirm("Удалить этот поиск?")) void api.deleteSearch(item.id).then(refresh);
                  }}
                >
                  Удалить
                </button>
              </div>
            </div>
          ))}
        </div>
        <form className="form" onSubmit={(event) => void onAddSearch(event)}>
          <input className="field" name="name" placeholder="Название (необязательно)" />
          <textarea className="field" name="url" rows={3} placeholder={isBidcars ? "URL поиска с Bid.cars — фильтры подтянутся сами" : "URL поиска с Copart — фильтры подтянутся сами"} required />
          <input className="field" name="telegram" placeholder="Telegram клиента: @username или ID" />
          <input className="field" name="phone" placeholder="Телефон клиента" />
          <textarea className="field" name="comment" rows={2} placeholder="Комментарий: для кого ищем, цвет, бюджет…" />
          <div className="hint">
            Когда авто появится в поиске, уведомление придёт в Telegram только вам. Клиенту бот ничего не пишет — его Telegram и телефон только для заметки.
          </div>
          <button className="btn" type="submit" disabled={addingSearch}>
            {addingSearch ? "Добавляю…" : "Добавить поиск"}
          </button>
        </form>
      </aside>

      <main className="main">
        <div className="top">
          <div>
            <div className="brand" style={{ fontSize: 26 }}>Новые находки</div>
            <div className="hint">
              Только лоты, которых не было на первом прогоне. База мониторинга скрыта.
            </div>
          </div>
          <div className="top-right">
            <div className="filters">
            <select className="select" value={listMode} onChange={(e) => setListMode(e.target.value as "feed" | "hidden")}>
              <option value="feed">Только новые</option>
              <option value="hidden">Скрытые</option>
            </select>
            <select className="select" value={stock} onChange={(e) => setStock(e.target.value as StockFilter)}>
              <option value="in">Сейчас на {siteName}</option>
              <option value="out">Уже нет в поиске</option>
              <option value="all">Все</option>
            </select>
            <input className="field" placeholder="Поиск по названию / lot" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
        </div>

        {lots.length === 0 ? (
          <div className="empty">
            {listMode === "feed"
              ? "Новых лотов пока нет. Появятся только те, которых не было на первом прогоне."
              : "Скрытых лотов нет."}
          </div>
        ) : (
          <div className="lot-list">
            {lots.map((lot) => (
              <div key={lot.lot_id} className={`lot-card-wrap ${lot.in_stock ? "" : "gone"}`}>
              <button
                type="button"
                className={`lot-card ${lot.in_stock ? "" : "gone"}`}
                onClick={() => setSelected(lot)}
              >
                <div className="lot-card-top">
                  <div>
                    <div className="title">{lot.title || `Lot ${lot.lot_id}`}</div>
                    <div className="meta">
                      #{lot.display_lot_id || lot.lot_id} · {lot.location || "площадка ?"}
                      {lot.category ? ` · Cat ${lot.category}` : ""}
                    </div>
                    {lot.search_params && lot.search_params.length > 0 ? (
                      <div className="chips">
                        {lot.search_params.map((param) => (
                          <span className="chip" key={`${lot.lot_id}-${param.key}-${param.value}`}>
                            {param.label}: {param.value}
                          </span>
                        ))}
                      </div>
                    ) : lot.search_names?.length ? (
                      <div className="meta">{lot.search_names.join(", ")}</div>
                    ) : null}
                    {lot.search_contacts?.length ? (
                      <div className="meta">
                        {lot.search_contacts.map((c) =>
                          [c.telegram, c.phone, c.comment].filter(Boolean).join(" · "),
                        ).join(" · ")}
                      </div>
                    ) : null}
                  </div>
                  <span className={`badge s-${lot.status}`}>{STATUS_LABEL[lot.status]}</span>
                </div>
                <div className="lot-card-prices">
                  <span className="lot-price-item">
                    <span className="lot-price-kind">Ставка</span>
                    <b>{isBidcars ? usd(lot.bid) : money(lot.bid)}</b>
                  </span>
                  {isBidcars ? (
                    <>
                      <span className="lot-price-item">
                        <span className="lot-price-kind">Пробег</span>
                        <b>{lot.odometer != null ? Number(lot.odometer).toLocaleString("en-US") : "—"}</b>
                      </span>
                      <span className="lot-price-item">
                        <span className="lot-price-kind">Аукцион</span>
                        <b>{lot.sale_date || "—"}</b>
                      </span>
                    </>
                  ) : (
                    <>
                  <span className="lot-price-item">
                    <span className="lot-price-kind">Copart</span>
                    <b>{money(lot.quote?.copart.copart_total)}</b>
                  </span>
                  <span className="lot-price-item">
                    <span className="lot-price-kind">
                      Доставка
                      {lot.quote
                        ? ` · ${lot.quote.delivery.region_key} · ${deliveryTypeLabel(lot.quote)}`
                        : ""}
                    </span>
                    <b>{money(lot.quote?.delivery.amount)}</b>
                  </span>
                  <span className="lot-price-item">
                    <span className="lot-price-kind">
                      Разбор{lot.quote ? ` · ${dismantleTypeLabel(lot.quote)}` : ""}
                    </span>
                    <b>{usd(lot.quote?.dismantle_usd)}</b>
                  </span>
                  <span className="lot-price-item">
                    <span className="lot-price-kind">Итого UK</span>
                    <b className="num strong">{money(lot.quote?.total_uk)}</b>
                  </span>
                  {lot.quote?.grand_usd != null ? (
                    <span className="lot-price-item">
                      <span className="lot-price-kind">Итого USD</span>
                      <b className="num strong">{usd(lot.quote.grand_usd, 2)}</b>
                    </span>
                  ) : null}
                    </>
                  )}
                </div>
                <div className="lot-card-foot">
                  <span>Проверено: {ago(lot.last_seen)}</span>
                  <span>Аукцион: {lot.sale_date || "—"}</span>
                  {lot.event === "relist" ? <span>повторный аукцион</span> : null}
                </div>
              </button>
              {listMode !== "hidden" ? (
                <button
                  type="button"
                  className="lot-dismiss"
                  title="Убрать из новых находок"
                  onClick={(event) => {
                    event.stopPropagation();
                    void dismissLot(lot);
                  }}
                >
                  Убрать
                </button>
              ) : null}
              </div>
            ))}
          </div>
        )}
      </main>

      {selectedLot ? (
        <>
          <div className="drawer-backdrop" onClick={() => setSelected(null)} aria-hidden />
          <aside className="drawer" role="dialog" aria-modal="true">
            <div className="drawer-head">
              <button type="button" className="drawer-close" onClick={() => setSelected(null)} aria-label="Закрыть">
                ×
              </button>
            </div>
          <h3>{selectedLot.title}</h3>
          <p className="hint">Lot {selectedLot.display_lot_id || selectedLot.lot_id} · {selectedLot.search_names?.join(", ")}</p>
          {selectedLot.search_contacts?.length ? (
            <div className="search-client">
              {selectedLot.search_contacts.map((c, idx) => (
                <div key={`${c.search}-${idx}`}>
                  {c.telegram ? <div>Telegram: {c.telegram}</div> : null}
                  {c.phone ? <div>Телефон: {c.phone}</div> : null}
                  {c.comment ? <div>Комментарий: {c.comment}</div> : null}
                </div>
              ))}
            </div>
          ) : null}
          {selectedLot.search_params && selectedLot.search_params.length > 0 ? (
            <div className="chips">
              {selectedLot.search_params.map((param) => (
                <span className="chip" key={`d-${param.key}-${param.value}`}>
                  {param.label}: {param.value}
                </span>
              ))}
            </div>
          ) : null}
          <p>
            Ставка {isBidcars ? usd(selectedLot.bid) : money(selectedLot.bid)}<br />
            Аукцион {selectedLot.sale_date || "—"}<br />
            Пробег {selectedLot.odometer ?? "—"}<br />
            Проверено {ago(selectedLot.last_seen)} · {when(selectedLot.last_seen)}<br />
            {selectedLot.in_stock ? "Сейчас есть в поиске" : "Больше нет в результатах"}
          </p>
          {isBidcars ? (
            <p className="hint">
              {selectedLot.bid == null
                ? "Нет ставки — появится, когда Bid.cars отдаст current bid."
                : "Точный расчёт США — во вкладке Калькулятор по ссылке на лот."}
            </p>
          ) : selectedLot.quote ? (
            <QuoteBox quote={selectedLot.quote} />
          ) : (
            <p className="hint">Нет ставки — расчёт появится, когда Copart отдаст current bid.</p>
          )}
          <p><a href={selectedLot.url} target="_blank" rel="noreferrer">Открыть на {siteName}</a></p>
          <label className="hint">Статус</label>
          <select
            className="select"
            value={selectedLot.status}
            onChange={(e) => {
              const next = e.target.value as LotStatus;
              void api.patchLot(selectedLot.lot_id, { status: next }).then(refresh);
            }}
          >
            {Object.entries(STATUS_LABEL).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <div style={{ height: 10 }} />
          <label className="hint">Заметка</label>
          <textarea
            className="field"
            rows={5}
            defaultValue={selectedLot.notes}
            key={selectedLot.lot_id + selectedLot.notes}
            onBlur={(e) => {
              void api.patchLot(selectedLot.lot_id, { notes: e.target.value }).then(refresh);
            }}
          />
          {listMode !== "hidden" ? (
            <button
              type="button"
              className="btn ghost"
              onClick={() => void dismissLot(selectedLot)}
            >
              Убрать из списка
            </button>
          ) : null}
        </aside>
        </>
      ) : null}
    </div>
  );
}
