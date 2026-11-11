import axios from "axios";
import { USER_AGENT } from "./constants.js";

export type KeyTestStatus = "valid" | "invalid" | "limited" | "unreachable" | "missing";

export interface KeyTestResult {
  key: string;
  status: KeyTestStatus;
  message: string;
}

interface Probe {
  url: string;
  params?: Record<string, string>;
  headers?: Record<string, string>;
  /** The answer when the status code alone does not tell (a service that says so in its body or headers). */
  judge?: (status: number, data: any, headers: Record<string, unknown>) => KeyTestStatus | undefined;
  /** Words of its own, for a contact email rather than a key. */
  messages?: Partial<Record<KeyTestStatus, string>>;
}

type Values = Record<string, string | undefined>;

/**
 * One small read-only request per key, made with the key under test: the answer
 * says whether the service takes it. Elsevier's institution token goes with its
 * API key.
 */
const PROBES: Record<string, (v: Values) => Probe> = {
  EASYSCHOLAR_KEY: (v) => ({
    url: "https://www.easyscholar.cc/open/getPublicationRank",
    params: { secretKey: v.EASYSCHOLAR_KEY!, publicationName: "Nature" },
    judge: (status, data) => (status === 200 && data && typeof data === "object"
      ? (data.code === 200 ? "valid" : "invalid") : undefined),
  }),
  SEMANTIC_SCHOLAR_API_KEY: (v) => ({
    url: "https://api.semanticscholar.org/graph/v1/paper/search",
    params: { query: "test", limit: "1", fields: "title" },
    headers: { "x-api-key": v.SEMANTIC_SCHOLAR_API_KEY! },
  }),
  ELSEVIER_API_KEY: (v) => ({
    // The serial title API answers any valid key from anywhere; it needs no subscription.
    url: "https://api.elsevier.com/content/serial/title",
    params: { issn: "0140-6736" },
    headers: {
      "X-ELS-APIKey": v.ELSEVIER_API_KEY!,
      Accept: "application/json",
      ...(v.ELSEVIER_INSTTOKEN ? { "X-ELS-Insttoken": v.ELSEVIER_INSTTOKEN } : {}),
    },
  }),
  SPRINGER_API_KEY: (v) => ({
    url: "https://api.springernature.com/meta/v2/json",
    params: { q: "doi:10.1038/nature14539", p: "1", api_key: v.SPRINGER_API_KEY! },
  }),
  WOS_API_KEY: (v) => ({
    url: `https://api.clarivate.com/apis/wos-starter/${v.WOS_API_VERSION || "v2"}/documents`,
    params: { q: "TS=(test)", limit: "1" },
    headers: { "X-ApiKey": v.WOS_API_KEY! },
  }),
  IEEE_API_KEY: (v) => ({
    url: "https://ieeexploreapi.ieee.org/api/v1/search/articles",
    params: { querytext: "test", max_records: "1", apikey: v.IEEE_API_KEY! },
  }),
  PUBMED_API_KEY: (v) => ({
    url: "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    params: { db: "pubmed", term: "test", retmax: "1", retmode: "json", api_key: v.PUBMED_API_KEY! },
    // NCBI answers a wrong key with 400 and {"error": "API key invalid"}.
    judge: (status, data) => (/api key/i.test(String(data?.error ?? "")) ? "invalid" : undefined),
  }),
  CORE_API_KEY: (v) => ({
    url: "https://api.core.ac.uk/v3/search/works/",
    params: { q: "test", limit: "1" },
    headers: { Authorization: `Bearer ${v.CORE_API_KEY}` },
  }),
  OPENAIRE_API_KEY: (v) => ({
    url: "https://api.openaire.eu/search/researchProducts",
    params: { keywords: "test", size: "1", format: "json" },
    headers: { Authorization: `Bearer ${v.OPENAIRE_API_KEY}` },
  }),
  OPENALEX_API_KEY: (v) => ({
    url: "https://api.openalex.org/works",
    params: { "per-page": "1", select: "id", api_key: v.OPENALEX_API_KEY! },
  }),
  // Contact emails, nothing to sign up for (2026-11-11). Unpaywall answers 422 to an address it does not
  // take (test@example.com, not an email); Crossref names its polite pool in x-api-pool once it takes the mailto.
  PAPER_SEARCH_UNPAYWALL_EMAIL: (v) => ({
    url: "https://api.unpaywall.org/v2/10.1038/nature12373",
    params: { email: v.PAPER_SEARCH_UNPAYWALL_EMAIL! },
    judge: (status) => (status === 422 ? "invalid" : undefined),
    messages: { valid: "可以用：Unpaywall 接受这个邮箱", invalid: "被拒绝：Unpaywall 不接受这个邮箱，请填你自己常用的邮箱" },
  }),
  CROSSREF_MAILTO: (v) => ({
    url: "https://api.crossref.org/works",
    params: { rows: "0", mailto: v.CROSSREF_MAILTO! },
    judge: (status, _data, headers) => (status === 200
      ? (/polite/i.test(String(headers["x-api-pool"] ?? "")) ? "valid" : "invalid") : undefined),
    messages: { valid: "可以用：已走 Crossref 优先通道", invalid: "Crossref 没有认这个邮箱，仍走普通通道" },
  }),
};

/** The key whose probe tests `key`: the institution token is tested with its API key. */
export function probeKeyFor(key: string): string | undefined {
  if (key === "ELSEVIER_INSTTOKEN") return "ELSEVIER_API_KEY";
  return PROBES[key] ? key : undefined;
}

export const TESTABLE_KEYS: readonly string[] = Object.keys(PROBES);

const MESSAGES: Record<KeyTestStatus, string> = {
  valid: "可以用",
  invalid: "被拒绝：key 不对，或已失效",
  limited: "服务器限流，稍后再试；key 本身可能没问题",
  unreachable: "没连上服务器，没法判断；检查网络或代理后再试",
  missing: "没有填",
};

export type HttpGet = (url: string, config: Record<string, unknown>) =>
  Promise<{ status: number; data: unknown; headers?: Record<string, unknown> }>;

const httpGet: HttpGet = (url, config) => axios.get(url, config);

/** Test one key (with its companions, e.g. the institution token) against its service. */
export async function testApiKey(key: string, values: Values, get: HttpGet = httpGet): Promise<KeyTestResult> {
  const probeKey = probeKeyFor(key);
  if (!probeKey) throw new Error(`没有在线测试：${key}`);
  if (!values[probeKey]?.trim()) return { key: probeKey, status: "missing", message: MESSAGES.missing };
  const probe = PROBES[probeKey](values);
  const words = { ...MESSAGES, ...probe.messages };
  let status: number;
  let data: unknown;
  let headers: Record<string, unknown> | undefined;
  try {
    ({ status, data, headers } = await get(probe.url, {
      params: probe.params,
      headers: { "User-Agent": USER_AGENT, ...probe.headers },
      timeout: 15_000,
      validateStatus: () => true,
    }));
  } catch (error: any) {
    return { key: probeKey, status: "unreachable", message: `${words.unreachable}（${error?.code || error?.message || "network"}）` };
  }
  const verdict = probe.judge?.(status, data, { ...headers })
    ?? (status >= 200 && status < 300 ? "valid"
      : status === 401 || status === 403 ? "invalid"
        : status === 429 ? "limited" : "unreachable");
  // The service's own words when it gives some (EasyScholar answers 200 with a message), else the status code.
  const said = [(data as any)?.msg, (data as any)?.error].find((text) => typeof text === "string" && text.length <= 80);
  // A refusal that came as a plain 200 (Crossref's public pool) has no code worth showing.
  const detail = verdict === "valid" || (!said && status === 200) ? "" : `（${said || `HTTP ${status}`}）`;
  return { key: probeKey, status: verdict, message: words[verdict] + detail };
}
