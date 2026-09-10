export type LotStatus = "new" | "watching" | "bid" | "skip" | "won" | "lost";
export type StockFilter = "in" | "out" | "all";

export interface UsaDelivery {
  from: string;
  location?: string | null;
  ship_from?: string | null;
  us_port?: string | null;
  us_port_label?: string | null;
  inland_miles?: number | null;
  miles_to_new_jersey?: number | null;
  miles_to_houston?: number | null;
  distance_source?: string | null;
  rate_usd_per_mile?: number | null;
  destination_port: string;
  destination_label: string;
  inland_usd: number;
  ocean_usd: number;
  ocean_destination?: string | null;
  vehicle_size?: string | null;
  vehicle_size_label?: string | null;
  matched_yard?: string | null;
  matched_auction?: string | null;
  tariff_source?: string | null;
  price_sheet?: UsaPriceSheet | null;
  bidcars_fee_usd: number;
  shipping_total_usd: number;
  america_subtotal_usd: number;
}

export interface UsaPriceSheet {
  yard?: string | null;
  auction?: string | null;
  us_port?: string | null;
  us_port_label?: string | null;
  ocean_destination?: string | null;
  selected_size?: string | null;
  size_labels?: Record<string, string>;
  inland_by_size?: Record<string, number | null>;
  ocean_by_size?: Record<string, number | null>;
  selected_inland_usd?: number | null;
  selected_ocean_usd?: number | null;
}

export interface IaaiFees {
  auction: "iaai" | "bidcars" | string;
  market: string;
  currency: string;
  volume: string;
  volume_label: string;
  bid: number;
  buyer_fee: number;
  buyer_fee_high: number;
  buyer_fee_standard: number;
  saving_vs_standard: number;
  bid_method: string;
  virtual_bid: number;
  service_fee: number;
  environmental_fee: number;
  title_fee: number;
  fixed_fees: number;
  fees_net: number;
  iaai_total: number;
  auction_fees_usd?: number | null;
  fees_source?: "bidcars" | "iaai" | string | null;
}

export interface IaaiQuote {
  auction: "iaai";
  purpose?: "iaai" | "restoration" | string;
  vehicle_size?: string | null;
  vehicle_size_label?: string | null;
  iaai: IaaiFees;
  delivery_usa?: UsaDelivery | null;
  subtotal_usa?: number;
  dispatching_usd?: number;
  transfer_fee?: number;
  transfer_fee_rate?: number;
  usa_with_fees?: number;
  dismantle_usd: number;
  dismantle_type: string;
  dismantle_mode?: string;
  dismantle_kg?: number | null;
  dismantle_label?: string;
  vehicle_type: string;
  title_document?: string | null;
  title_doc_usd?: number | null;
  title_fee_info?: {
    document_raw?: string;
    matched_rule?: string | null;
    matched_id?: string | null;
    cost_usd?: number | null;
    free?: boolean;
    unmatched?: boolean;
  } | null;
  is_sublot?: boolean | null;
  sublot_location?: string | null;
  sublot_usd?: number | null;
  grand_usd?: number | null;
}

export interface BidcarsLot {
  source: "bidcars" | "copart_us" | "iaai" | string;
  auction_platform?: "copart" | "iaai" | string;
  lot_id: string;
  title: string;
  year: number | null;
  make: string | null;
  model: string | null;
  vin: string | null;
  url: string;
  location: string | null;
  ship_from: string | null;
  seller?: string | null;
  documents?: string | null;
  title_code?: string | null;
  sale_date?: string | null;
  odometer?: number | null;
  primary_damage?: string | null;
  secondary_damage?: string | null;
  keys?: string | null;
  body_style?: string | null;
  color?: string | null;
  engine?: string | null;
  transmission?: string | null;
  drive?: string | null;
  fuel?: string | null;
  estimated_value?: string | null;
  bid: number | null;
  images?: string[];
  inland_usd?: number | null;
  inland_miles?: number | null;
  us_port?: string | null;
  us_port_label?: string | null;
  is_sublot?: boolean | null;
  sublot_location?: string | null;
  miles_to_new_jersey?: number | null;
  miles_to_houston?: number | null;
  distance_source?: string | null;
  inland_route?: Record<string, unknown> | null;
  bidcars_fee_usd?: number | null;
  auction_url?: string | null;
  auction_fees_usd?: number | null;
  ocean_usd_by_port?: Record<string, number>;
  dismantle_type?: string;
  quote?: IaaiQuote | null;
  quote_text?: string | null;
}

export interface LotQuote {
  copart: {
    bid: number;
    buyer_a: number;
    buyer_b: number;
    buyer_fee?: number;
    buyer_fee_tier?: "A" | "B" | string;
    buyer_fee_label?: string;
    saving: number;
    live_bid: number;
    retrieval: number;
    fees_net: number;
    auction_fees?: number;
    vat_fees: number;
    vat_sale: number;
    vat_on_sale: boolean;
    vat_sum: number;
    copart_total: number;
    fees_source?: string;
  };
  delivery: {
    region_key: string;
    base_column: string;
    auto_column?: string;
    column: string;
    sedan_as_jeep: boolean;
    manual?: boolean;
    amount: number;
    label: string;
  };
  subtotal: number;
  transfer_fee: number;
  total_uk: number;
  dismantle_usd: number;
  dismantle_type: string;
  dismantle_mode?: string;
  dismantle_kg?: number | null;
  vehicle_type: string;
  category_b: boolean;
  fx_rate?: number | null;
  england_usd?: number | null;
  grand_usd?: number | null;
}

export interface Lot {
  lot_id: string;
  display_lot_id?: string;
  title: string;
  year: number | null;
  make: string | null;
  model: string | null;
  bid: number | null;
  location: string | null;
  category: string | null;
  odometer: number | null;
  sale_date: string | null;
  vin: string | null;
  url: string;
  source?: "copart" | "bidcars" | string;
  search_names: string[];
  search_params?: { key: string; label: string; value: string }[];
  search_summary?: string;
  search_contacts?: SearchContact[];
  status: LotStatus;
  notes: string;
  first_seen: string;
  last_seen: string;
  in_stock: number;
  event: string | null;
  previous_sale_date: string | null;
  body_style: string | null;
  vat_on_sale: boolean | null;
  quote: LotQuote | null;
}

export interface LotDetails {
  lot_id: string;
  title: string;
  year: number | null;
  make: string | null;
  model: string | null;
  bid: number | null;
  location: string | null;
  category: string | null;
  odometer: number | null;
  sale_date: string | null;
  vin: string | null;
  body_style: string | null;
  vehicle_type_raw?: string | null;
  vat_on_sale: boolean | null;
  url: string;
  color?: string | null;
  engine?: string | null;
  transmission?: string | null;
  drive?: string | null;
  fuel?: string | null;
  primary_damage?: string | null;
  secondary_damage?: string | null;
  keys?: string | null;
  highlights?: string | null;
  estimated_value?: number | null;
  repair_cost?: number | null;
  images?: string[];
  dismantle_type?: string;
  cached?: boolean;
  quote: LotQuote | null;
  quote_text?: string | null;
  history_id?: number | null;
}

export interface CalcHistoryItem {
  id: number;
  lot_id: string;
  title: string | null;
  url: string | null;
  image: string | null;
  bid: number | null;
  total_uk: number | null;
  grand_usd: number | null;
  category: string | null;
  location: string | null;
  auction?: "copart" | "iaai" | string | null;
  created_at: string;
  updated_at: string;
}

export interface SearchContact {
  search: string;
  comment: string;
  telegram: string;
  phone: string;
}

export interface SearchItem {
  id: number;
  name: string;
  url: string;
  enabled: number;
  created_at: string;
  seeded_at?: string | null;
  seeding?: boolean;
  comment?: string;
  client_telegram?: string;
  client_phone?: string;
  owner_user_id?: number | null;
  owner_name?: string;
  params?: { key: string; label: string; value: string }[];
  summary?: string;
  in_search?: number;
  new_count?: number;
  last_in_search?: number | null;
  last_new?: number | null;
  last_checked_at?: string | null;
  platform?: "copart" | "bidcars" | string;
  kind?: "client" | "restoration" | string;
}

export interface AppState {
  stats: {
    in_stock: number;
    in_search?: number;
    new: number;
    watching: number;
    bid: number;
    gone: number;
    all: number;
  };
  sync: {
    running: boolean;
    last: {
      started_at: string;
      finished_at: string | null;
      lots_found: number | null;
      new_count: number | null;
      error: string | null;
    } | null;
  };
  searches: SearchItem[];
  platform?: "copart" | "bidcars" | string;
  kind?: "client" | "restoration" | string;
  interval_minutes: number;
  telegram: boolean;
  notify_count?: number;
  me?: AuthUser | null;
  fx_rate: number | null;
  fx_source?: string | null;
  eur_byn?: number | null;
  usd_byn?: number | null;
  byn_rates_source?: string | null;
}

export interface AuthUser {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  role: "admin" | "user" | string;
  notify: boolean;
  enabled: boolean;
}

export interface AuthConfig {
  configured: boolean;
  bot_username: string | null;
  user: AuthUser | null;
  telegram_poll_ok?: boolean | null;
  telegram_poll_error?: string | null;
}

export interface LoginStart {
  token: string;
  bot_username: string;
  bot_url: string;
}

export interface LoginPoll {
  status: "pending" | "ok" | "expired" | "denied";
  user?: AuthUser;
}

export const STATUS_LABEL: Record<LotStatus, string> = {
  new: "Новое",
  watching: "Слежу",
  bid: "Ставка",
  skip: "Не нужно",
  won: "Купил",
  lost: "Ушло",
};
