import type {
  AppState,
  AuthConfig,
  AuthUser,
  BidcarsLot,
  CalcHistoryItem,
  IaaiQuote,
  LoginPoll,
  LoginStart,
  Lot,
  LotDetails,
  LotQuote,
  LotStatus,
  SearchItem,
  StockFilter,
} from "./types";

export type BamperPartRow = {
  code: string;
  name: string;
  url: string;
  count: number | null;
  min_byn: number | null;
  avg_byn: number | null;
  samples?: number[];
  ok?: boolean;
  error?: string | null;
};

export type BamperJob = {
  id: string;
  status: "running" | "done" | "cancelled" | "error";
  mode?: "dismantle" | "full" | string;
  vehicle: {
    make?: string | null;
    model?: string | null;
    year?: number | null;
    year_from?: number | null;
    year_to?: number | null;
    marka?: string | null;
    model_slug?: string | null;
    model_candidates?: string[];
    enginevalue?: string | null;
    toplivo?: string | null;
    toplivo_label?: string | null;
    korobka?: string | null;
    korobka_label?: string | null;
    kuzov?: string | null;
    kuzov_label?: string | null;
  };
  total: number;
  done: number;
  with_offers: number;
  sum_min_byn: number;
  sum_avg_byn?: number;
  parts: BamperPartRow[];
  dismantle_codes?: string[];
  error?: string | null;
};

export class AuthError extends Error {
  status = 401;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (res.status === 401) {
    window.dispatchEvent(new Event("crm-unauthorized"));
    throw new AuthError("Нужна авторизация через Telegram");
  }
  if (!res.ok) {
    const text = await res.text();
    let message = text;
    try {
      const data = JSON.parse(text);
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      /* keep raw text */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  authConfig: () => request<AuthConfig>("/api/auth/config"),
  startLogin: () => request<LoginStart>("/api/auth/login", { method: "POST" }),
  pollLogin: (token: string) => request<LoginPoll>(`/api/auth/login/${token}`),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  patchMe: (body: { notify?: boolean }) =>
    request<AuthUser>("/api/auth/me", { method: "PATCH", body: JSON.stringify(body) }),
  users: () => request<AuthUser[]>("/api/users"),
  patchUser: (id: number, body: { notify?: boolean; enabled?: boolean; role?: string }) =>
    request<AuthUser>(`/api/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  state: (platform?: "copart" | "bidcars") => {
    const query = platform ? `?platform=${platform}` : "";
    return request<AppState>(`/api/state${query}`);
  },
  setFxRate: (fx_rate: number) =>
    request<{ fx_rate: number; fx_source: string }>("/api/settings/fx-rate", {
      method: "POST",
      body: JSON.stringify({ fx_rate }),
    }),
  lots: (params: {
    status?: string;
    stock: StockFilter;
    q: string;
    search?: string;
    feed?: boolean;
    source?: "copart" | "bidcars";
  }) => {
    const query = new URLSearchParams({ stock: params.stock });
    if (params.status) query.set("status", params.status);
    if (params.q) query.set("q", params.q);
    if (params.search) query.set("search", params.search);
    if (params.feed) query.set("feed", "1");
    if (params.source) query.set("source", params.source);
    return request<Lot[]>(`/api/lots?${query}`);
  },
  patchLot: (lotId: string, body: { status?: LotStatus; notes?: string }) =>
    request<Lot>(`/api/lots/${lotId}`, { method: "PATCH", body: JSON.stringify(body) }),
  addSearch: (body: {
    name: string;
    url: string;
    comment?: string;
    client_telegram?: string;
    client_phone?: string;
    platform?: "copart" | "bidcars";
  }) => request<SearchItem>("/api/searches", { method: "POST", body: JSON.stringify(body) }),
  patchSearch: (id: number, body: {
    name?: string;
    comment?: string;
    client_telegram?: string;
    client_phone?: string;
  }) => request<SearchItem>(`/api/searches/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  setSearchEnabled: (id: number, enabled: boolean) =>
    request<{ ok: boolean }>(`/api/searches/${id}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  deleteSearch: (id: number) =>
    request<{ ok: boolean }>(`/api/searches/${id}`, { method: "DELETE" }),
  sync: (platform?: "copart" | "bidcars") => {
    const query = platform ? `?platform=${platform}` : "";
    return request<Record<string, unknown>>(`/api/sync${query}`, { method: "POST" });
  },
  lookupLot: (url: string) =>
    request<LotDetails>("/api/calc/lookup", { method: "POST", body: JSON.stringify({ url }) }),
  calcHistory: () => request<{ items: CalcHistoryItem[] }>("/api/calc/history"),
  quoteLot: (body: {
    bid: number;
    lot_id?: string | null;
    history_id?: number | null;
    location?: string | null;
    category?: string | null;
    title?: string;
    body_style?: string | null;
    vat_on_sale?: boolean | null;
    dismantle_type?: string | null;
    dismantle_kg?: number | null;
    delivery_column?: string | null;
    fx_rate?: number | null;
    url?: string | null;
  }) => request<{ quote: LotQuote | null; quote_text: string | null; dismantle_type: string; history_id?: number | null }>("/api/calc/quote", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  quoteIaai: (body: {
    bid: number;
    title?: string;
    body_style?: string | null;
    dismantle_type?: string | null;
    dismantle_kg?: number | null;
    bid_method?: "live" | "proxy";
    volume?: "high" | "standard";
    url?: string | null;
    include_america_delivery?: boolean;
    inland_usd?: number | null;
    inland_miles?: number | null;
    ocean_usd?: number | null;
    bidcars_fee_usd?: number | null;
    destination_port?: string | null;
    ship_from?: string | null;
    location?: string | null;
    us_port?: string | null;
    us_port_label?: string | null;
    miles_to_new_jersey?: number | null;
    miles_to_houston?: number | null;
    distance_source?: string | null;
    history_id?: number | null;
    lot_id?: string | null;
    vin?: string | null;
    odometer?: number | null;
    primary_damage?: string | null;
    documents?: string | null;
    images?: string[] | null;
  }) =>
    request<{ quote: IaaiQuote; quote_text: string; dismantle_type: string; history_id?: number | null }>("/api/calc/iaai", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  lookupBidcars: (url: string) =>
    request<BidcarsLot & { history_id?: number | null; auction?: string }>("/api/calc/usa-lookup", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  calcHistoryItem: (id: number) =>
    request<LotDetails & BidcarsLot & { auction?: string; history_id?: number }>(`/api/calc/history/${id}`),
  bamperSearch: (body: {
    make?: string | null;
    model?: string | null;
    year?: number | null;
    title?: string | null;
    engine?: string | null;
    fuel?: string | null;
    transmission?: string | null;
    body_style?: string | null;
    scrape?: boolean;
    mode?: "dismantle" | "full";
  }) => request<BamperJob>("/api/bamper/search", { method: "POST", body: JSON.stringify(body) }),
  bamperJob: (id: string) => request<BamperJob>(`/api/bamper/jobs/${id}`),
  bamperCancel: (id: string) =>
    request<BamperJob>(`/api/bamper/jobs/${id}/cancel`, { method: "POST", body: "{}" }),
  sendTelegram: (messages: string[]) =>
    request<{ ok: boolean; sent: number }>("/api/telegram/send", {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),
};
