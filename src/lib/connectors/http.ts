// Shared HTTP client for all connectors
// Applies web-scraper best practices: realistic browser headers, retry with backoff, timeout
// Based on anti-blocking strategies: Layer 1 (headers/UA), no browser fingerprint spoofing needed for APIs

const USER_AGENTS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
];

let uaIndex = 0;
function nextUA(): string {
  const ua = USER_AGENTS[uaIndex % USER_AGENTS.length];
  uaIndex++;
  return ua;
}

function browserHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    "User-Agent": nextUA(),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    ...extra,
  };
}

function jsonHeaders(extra?: Record<string, string>): Record<string, string> {
  return {
    "User-Agent": nextUA(),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    ...extra,
  };
}

async function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export interface FetchOptions {
  timeoutMs?: number;
  retries?: number;
  backoffMs?: number;
  headers?: Record<string, string>;
  isJson?: boolean;
  method?: string;
  body?: string;
}

// Fetch with retry + exponential backoff — never throws on network errors, returns null
export async function fetchWithRetry(url: string, opts: FetchOptions = {}): Promise<Response | null> {
  const {
    timeoutMs = 30_000,
    retries = 3,
    backoffMs = 1_000,
    headers,
    isJson = false,
    method = "GET",
    body,
  } = opts;

  const baseHeaders = isJson ? jsonHeaders(headers) : browserHeaders(headers);

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers: baseHeaders,
        body,
        signal: AbortSignal.timeout(timeoutMs),
      });

      // Retry on transient server errors
      if ((res.status === 429 || res.status >= 500) && attempt < retries) {
        const delay = backoffMs * Math.pow(2, attempt);
        await sleep(delay);
        continue;
      }

      return res;
    } catch (err) {
      if (attempt < retries) {
        const delay = backoffMs * Math.pow(2, attempt);
        await sleep(delay);
        continue;
      }
      throw err;
    }
  }

  return null;
}

export async function fetchHtml(url: string, opts: FetchOptions = {}): Promise<string> {
  const res = await fetchWithRetry(url, { ...opts, isJson: false });
  if (!res) throw new Error(`Fetch failed after retries: ${url}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} — ${url}`);
  return res.text();
}

export async function fetchJson<T = unknown>(url: string, opts: FetchOptions = {}): Promise<T> {
  const res = await fetchWithRetry(url, { ...opts, isJson: true });
  if (!res) throw new Error(`Fetch failed after retries: ${url}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} — ${url}`);
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("json") && !ct.includes("text")) {
    throw new Error(`Unexpected content-type: ${ct} — ${url}`);
  }
  return res.json() as Promise<T>;
}

// Try multiple URLs, return first that succeeds
export async function fetchHtmlFallback(urls: string[], opts: FetchOptions = {}): Promise<{ html: string; url: string } | null> {
  for (const url of urls) {
    try {
      const html = await fetchHtml(url, opts);
      if (html.length > 500) return { html, url };
    } catch {
      continue;
    }
  }
  return null;
}

// Rate limiter: minimum ms between calls to same domain
const lastCallMs: Record<string, number> = {};
export async function rateLimitedFetch(url: string, minIntervalMs: number, opts: FetchOptions = {}): Promise<Response | null> {
  const domain = new URL(url).hostname;
  const now = Date.now();
  const last = lastCallMs[domain] ?? 0;
  const wait = minIntervalMs - (now - last);
  if (wait > 0) await sleep(wait);
  lastCallMs[domain] = Date.now();
  return fetchWithRetry(url, opts);
}
