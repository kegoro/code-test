import type {
  Candle,
  FinancialsSeries,
  InstitutionalDay,
  InstitutionalSeries,
  KlineRepository,
  KlineSeries,
  LiveQuote,
  NewsItem,
  NewsSeries,
  QuarterEPS,
} from "./types";
import { maskToken } from "./finmind-token";

const FINMIND_BASE =
  process.env.FINMIND_API_BASE ?? "https://api.finmindtrade.com/api/v4/data";

const REVALIDATE_SECONDS = 60 * 30;

function logFetch(dataset: string, symbol: string, token: string | undefined): void {
  // eslint-disable-next-line no-console
  console.log(
    `[FinMind] Fetching ${dataset} (data_id=${symbol}), Token: ${maskToken(token)}`
  );
}

interface FinMindRow {
  date: string;
  stock_id: string;
  Trading_Volume: number;
  Trading_money: number;
  open: number;
  max: number;
  min: number;
  close: number;
  spread: number;
  Trading_turnover: number;
}

interface FinMindResponse {
  msg: string;
  status: number;
  data: FinMindRow[];
}

function isFinMindRow(value: unknown): value is FinMindRow {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["date"] === "string" &&
    typeof r["open"] === "number" &&
    typeof r["max"] === "number" &&
    typeof r["min"] === "number" &&
    typeof r["close"] === "number" &&
    typeof r["Trading_Volume"] === "number"
  );
}

function isFinMindResponse(value: unknown): value is FinMindResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["status"] === "number" &&
    typeof r["msg"] === "string" &&
    Array.isArray(r["data"])
  );
}

function toCandle(row: FinMindRow): Candle | null {
  const ts = Date.parse(`${row.date}T00:00:00+08:00`);
  if (!Number.isFinite(ts)) return null;
  if (![row.open, row.max, row.min, row.close].every(Number.isFinite)) return null;
  return {
    timestamp: ts,
    open: row.open,
    high: row.max,
    low: row.min,
    close: row.close,
    volume: Number.isFinite(row.Trading_Volume) ? row.Trading_Volume : 0,
  };
}

function oneYearAgoIso(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

function nDaysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

interface FinMindInstRow {
  date: string;
  stock_id: string;
  name: string;
  buy: number;
  sell: number;
}

interface FinMindInstResponse {
  msg: string;
  status: number;
  data: FinMindInstRow[];
}

function isFinMindInstRow(value: unknown): value is FinMindInstRow {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["date"] === "string" &&
    typeof r["name"] === "string" &&
    typeof r["buy"] === "number" &&
    typeof r["sell"] === "number"
  );
}

function isFinMindInstResponse(value: unknown): value is FinMindInstResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["status"] === "number" &&
    typeof r["msg"] === "string" &&
    Array.isArray(r["data"])
  );
}

function classifyInstitution(name: string): "foreign" | "trust" | "dealer" | null {
  const lower = name.toLowerCase();
  if (lower.startsWith("foreign")) return "foreign";
  if (lower.startsWith("investment_trust")) return "trust";
  if (lower.startsWith("dealer")) return "dealer";
  return null;
}

interface FinMindNewsRow {
  date: string;
  stock_id: string;
  title: string;
  description?: string | null;
  link?: string | null;
  source?: string | null;
}

interface FinMindNewsResponse {
  msg: string;
  status: number;
  data: FinMindNewsRow[];
}

function isFinMindNewsRow(value: unknown): value is FinMindNewsRow {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return typeof r["date"] === "string" && typeof r["title"] === "string";
}

function isFinMindNewsResponse(value: unknown): value is FinMindNewsResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["status"] === "number" &&
    typeof r["msg"] === "string" &&
    Array.isArray(r["data"])
  );
}

interface FinMindFinRow {
  date: string;
  stock_id: string;
  type: string;
  value: number | null;
  origin_name?: string;
}

interface FinMindFinResponse {
  msg: string;
  status: number;
  data: FinMindFinRow[];
}

function isFinMindFinRow(value: unknown): value is FinMindFinRow {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["date"] === "string" &&
    typeof r["type"] === "string" &&
    (typeof r["value"] === "number" || r["value"] === null)
  );
}

function isFinMindFinResponse(value: unknown): value is FinMindFinResponse {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    typeof r["status"] === "number" &&
    typeof r["msg"] === "string" &&
    Array.isArray(r["data"])
  );
}

function dateToQuarterTag(date: string): string {
  const parts = date.split("-");
  const yStr = parts[0];
  const mStr = parts[1];
  if (!yStr || !mStr) return date;
  const m = Number.parseInt(mStr, 10);
  if (m === 3) return `${yStr}-Q1`;
  if (m === 6) return `${yStr}-Q2`;
  if (m === 9) return `${yStr}-Q3`;
  if (m === 12) return `${yStr}-Q4`;
  return date;
}

function extractEPS(rows: readonly FinMindFinRow[]): readonly QuarterEPS[] {
  const result: QuarterEPS[] = [];
  for (const r of rows) {
    if (r.type !== "EPS") continue;
    if (typeof r.value !== "number" || !Number.isFinite(r.value)) continue;
    const ts = Date.parse(`${r.date}T00:00:00+08:00`);
    if (!Number.isFinite(ts)) continue;
    result.push({
      date: r.date,
      timestamp: ts,
      quarter: dateToQuarterTag(r.date),
      eps: r.value,
    });
  }
  result.sort((a, b) => a.timestamp - b.timestamp);
  return result;
}

function aggregateInstitutional(
  rows: readonly FinMindInstRow[]
): readonly InstitutionalDay[] {
  const byDate = new Map<string, { foreignNet: number; trustNet: number; dealerNet: number }>();
  for (const r of rows) {
    const cls = classifyInstitution(r.name);
    if (cls === null) continue;
    const acc = byDate.get(r.date) ?? { foreignNet: 0, trustNet: 0, dealerNet: 0 };
    const net = (Number.isFinite(r.buy) ? r.buy : 0) - (Number.isFinite(r.sell) ? r.sell : 0);
    if (cls === "foreign") acc.foreignNet += net;
    else if (cls === "trust") acc.trustNet += net;
    else acc.dealerNet += net;
    byDate.set(r.date, acc);
  }
  const result: InstitutionalDay[] = [];
  for (const [date, sums] of byDate.entries()) {
    const ts = Date.parse(`${date}T00:00:00+08:00`);
    if (!Number.isFinite(ts)) continue;
    result.push({ date, timestamp: ts, ...sums });
  }
  result.sort((a, b) => a.timestamp - b.timestamp);
  return result;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export class FinMindRepository implements KlineRepository {
  constructor(private readonly token?: string) {}

  async getDaily(
    symbol: string,
    opts?: { startDate?: string }
  ): Promise<KlineSeries> {
    const startDate = opts?.startDate ?? oneYearAgoIso();
    const url = new URL(FINMIND_BASE);
    url.searchParams.set("dataset", "TaiwanStockPrice");
    url.searchParams.set("data_id", symbol);
    url.searchParams.set("start_date", startDate);
    if (this.token) url.searchParams.set("token", this.token);

    logFetch("TaiwanStockPrice", symbol, this.token);
    const res = await fetch(url.toString(), {
      next: { revalidate: REVALIDATE_SECONDS, tags: [`kline:${symbol}`] },
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      throw new Error(`FinMind HTTP ${res.status} ${res.statusText}`);
    }

    const json: unknown = await res.json();
    if (!isFinMindResponse(json)) {
      throw new Error("FinMind response shape unexpected");
    }
    if (json.status !== 200) {
      throw new Error(`FinMind error: ${json.msg || "unknown"}`);
    }

    const candles = json.data
      .filter(isFinMindRow)
      .map(toCandle)
      .filter((c): c is Candle => c !== null)
      .sort((a, b) => a.timestamp - b.timestamp);

    return {
      symbol,
      candles,
      source: "finmind",
      fetchedAt: new Date().toISOString(),
      startDate,
      endDate: todayIso(),
    };
  }

  async getNews(
    symbol: string,
    opts?: { startDate?: string }
  ): Promise<NewsSeries> {
    const startDate = opts?.startDate ?? nDaysAgoIso(30);
    const url = new URL(FINMIND_BASE);
    url.searchParams.set("dataset", "TaiwanStockNews");
    url.searchParams.set("data_id", symbol);
    url.searchParams.set("start_date", startDate);
    if (this.token) url.searchParams.set("token", this.token);

    logFetch("TaiwanStockNews", symbol, this.token);
    const res = await fetch(url.toString(), {
      next: { revalidate: 21_600, tags: [`news:${symbol}`] },
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      throw new Error(`FinMind HTTP ${res.status} ${res.statusText}`);
    }

    const json: unknown = await res.json();
    if (!isFinMindNewsResponse(json)) {
      throw new Error("FinMind news response shape unexpected");
    }
    if (json.status !== 200) {
      throw new Error(`FinMind error: ${json.msg || "unknown"}`);
    }

    const items: NewsItem[] = json.data.filter(isFinMindNewsRow).map((r) => ({
      date: r.date,
      title: r.title,
      description: typeof r.description === "string" ? r.description : "",
      link: typeof r.link === "string" ? r.link : "",
      source: typeof r.source === "string" ? r.source : "",
    }));
    items.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

    return {
      symbol,
      items,
      source: "finmind",
      fetchedAt: new Date().toISOString(),
      startDate,
    };
  }

  async getFinancials(
    symbol: string,
    opts?: { startDate?: string }
  ): Promise<FinancialsSeries> {
    const startDate = opts?.startDate ?? nDaysAgoIso(365 * 2 + 90);
    const url = new URL(FINMIND_BASE);
    url.searchParams.set("dataset", "TaiwanStockFinancialStatements");
    url.searchParams.set("data_id", symbol);
    url.searchParams.set("start_date", startDate);
    if (this.token) url.searchParams.set("token", this.token);

    logFetch("TaiwanStockFinancialStatements", symbol, this.token);
    const res = await fetch(url.toString(), {
      next: { revalidate: 86_400, tags: [`fin:${symbol}`] },
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      throw new Error(`FinMind HTTP ${res.status} ${res.statusText}`);
    }

    const json: unknown = await res.json();
    if (!isFinMindFinResponse(json)) {
      throw new Error("FinMind financials response shape unexpected");
    }
    if (json.status !== 200) {
      throw new Error(`FinMind error: ${json.msg || "unknown"}`);
    }

    const epsByQuarter = extractEPS(json.data.filter(isFinMindFinRow));

    return {
      symbol,
      epsByQuarter,
      source: "finmind",
      fetchedAt: new Date().toISOString(),
      startDate,
    };
  }

  async getInstitutional(
    symbol: string,
    opts?: { startDate?: string }
  ): Promise<InstitutionalSeries> {
    const startDate = opts?.startDate ?? nDaysAgoIso(60);
    const url = new URL(FINMIND_BASE);
    url.searchParams.set("dataset", "TaiwanStockInstitutionalInvestorsBuySell");
    url.searchParams.set("data_id", symbol);
    url.searchParams.set("start_date", startDate);
    if (this.token) url.searchParams.set("token", this.token);

    logFetch("TaiwanStockInstitutionalInvestorsBuySell", symbol, this.token);
    const res = await fetch(url.toString(), {
      next: { revalidate: REVALIDATE_SECONDS, tags: [`inst:${symbol}`] },
      headers: { Accept: "application/json" },
    });

    if (!res.ok) {
      throw new Error(`FinMind HTTP ${res.status} ${res.statusText}`);
    }

    const json: unknown = await res.json();
    if (!isFinMindInstResponse(json)) {
      throw new Error("FinMind institutional response shape unexpected");
    }
    if (json.status !== 200) {
      throw new Error(`FinMind error: ${json.msg || "unknown"}`);
    }

    const rows = aggregateInstitutional(json.data.filter(isFinMindInstRow));

    return {
      symbol,
      rows,
      source: "finmind",
      fetchedAt: new Date().toISOString(),
      startDate,
    };
  }

  async getLatestQuote(symbol: string): Promise<LiveQuote | null> {
    const series = await this.getDaily(symbol, { startDate: nDaysAgoIso(14) });
    const candles = series.candles;
    if (candles.length === 0) return null;
    const last = candles[candles.length - 1];
    if (!last) return null;
    const prev = candles.length >= 2 ? candles[candles.length - 2] : undefined;
    const prevClose = prev?.close ?? last.open;
    const denom = prevClose === 0 ? 1 : prevClose;
    const changePct = ((last.close - prevClose) / denom) * 100;
    return {
      symbol,
      last: last.close,
      prevClose,
      changePct,
      volume: last.volume,
      asOf: new Date(last.timestamp).toISOString().slice(0, 10),
    };
  }
}
