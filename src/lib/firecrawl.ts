// Client Firecrawl — API v2, endpoint /scrape
//
// Pourquoi REST plutôt que le SDK `firecrawl` : tous les connecteurs de ce repo
// enveloppent déjà leurs appels tiers dans `fetch` + `AbortSignal.timeout`
// (cf. lib/connectors/http.ts). La surface utilisée ici est un seul endpoint,
// et rester en REST évite une dépendance de plus dans le bundle serverless.
// Le skill firecrawl-build sanctionne explicitement ce choix quand « the
// existing networking layer already wraps third-party APIs ».
//
// Ce que Firecrawl apporte à cette application :
//  1. il franchit les boucliers anti-bot (SIMAGRI-CI/Anubis, Selina/403) qui
//     bloquent les IP Vercel — le scraping redevient exécutable depuis l'app
//     au lieu de dépendre du runner GitHub ;
//  2. l'extraction structurée (format `json` + schéma) remplace les regex
//     collées au HTML, qui cassent au premier changement de gabarit.

const DEFAUT_API = "https://api.firecrawl.dev";

/** Base API : hébergé par défaut, surchargeable pour une instance self-hosted. */
function apiUrl(): string {
  return (process.env.FIRECRAWL_API_URL || DEFAUT_API).replace(/\/+$/, "");
}

/**
 * Deux chemins d'activation :
 *  - cloud : FIRECRAWL_API_KEY (api.firecrawl.dev) ;
 *  - self-hosted : FIRECRAWL_API_URL seul. Vérifié dans le dépôt Firecrawl
 *    (apps/api/src/controllers/auth.ts) : quand `USE_DB_AUTHENTICATION !== true`
 *    l'API renvoie un ACUC simulé sans valider la moindre clé — mais l'absence
 *    totale d'en-tête `Authorization` retombe sur `handleKeylessAuth`, qui
 *    répond 401. D'où le jeton fictif envoyé plus bas.
 */
export function firecrawlActif(): boolean {
  return Boolean(process.env.FIRECRAWL_API_KEY || process.env.FIRECRAWL_API_URL);
}

/** true si l'on parle à une instance auto-hébergée sans clé. */
export function firecrawlSelfHosted(): boolean {
  return Boolean(process.env.FIRECRAWL_API_URL && !process.env.FIRECRAWL_API_KEY);
}

/** Erreur dédiée : permet aux connecteurs de distinguer « pas de clé » d'un vrai échec. */
export class FirecrawlIndisponible extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FirecrawlIndisponible";
  }
}

export interface MetaScrape {
  statusCode?: number;
  /** "hit" | "miss" — absent si maxAge:0 (preuve qu'aucune copie indexée n'a servi). */
  cacheState?: string;
  cachedAt?: string;
  sourceURL?: string;
  url?: string;
  title?: string;
}

export interface ResultatScrape<T> {
  json?: T;
  markdown?: string;
  metadata: MetaScrape;
}

export interface OptionsScrape {
  /** Schéma JSON de l'extraction structurée. */
  schema?: Record<string, unknown>;
  /** Consigne en langage naturel accompagnant le schéma. */
  prompt?: string;
  /** Récupérer aussi le markdown (utile pour diagnostiquer une extraction vide). */
  markdown?: boolean;
  onlyMainContent?: boolean;
  /**
   * Âge maximal (ms) d'une copie indexée réutilisable. Omettre laisse Firecrawl
   * choisir la fenêtre par domaine (bon défaut). 0 force un scrape live.
   */
  maxAge?: number;
  waitFor?: number;
  /** Budget côté Firecrawl (ms). */
  timeout?: number;
  /** "enhanced" pour les sites à bouclier anti-bot (valeurs confirmées v2). */
  proxy?: "basic" | "enhanced" | "auto";
  /** Bloque pubs et bannières cookies — réduit le bruit d'extraction. */
  blockAds?: boolean;
  location?: { country?: string; languages?: string[] };
  /** Budget de la requête HTTP côté application (ms). */
  timeoutMs?: number;
}

interface ReponseScrape {
  success?: boolean;
  error?: string;
  data?: {
    json?: unknown;
    markdown?: string;
    metadata?: MetaScrape;
  };
}

/**
 * Scrape une page et renvoie l'extraction structurée.
 *
 * Lève `FirecrawlIndisponible` si la clé manque — l'appelant décide alors de
 * retomber sur son chemin historique plutôt que de planter.
 */
export async function scraper<T = unknown>(
  url: string,
  opts: OptionsScrape = {},
): Promise<ResultatScrape<T>> {
  // Jeton fictif accepté par une instance self-hosted en USE_DB_AUTHENTICATION=false ;
  // il évite le 401 déclenché par l'absence d'en-tête Authorization.
  const cle = process.env.FIRECRAWL_API_KEY
    ?? (process.env.FIRECRAWL_API_URL ? "self-hosted" : undefined);
  if (!cle) {
    throw new FirecrawlIndisponible(
      "Firecrawl non configuré — définir FIRECRAWL_API_KEY (cloud) ou FIRECRAWL_API_URL (instance auto-hébergée)",
    );
  }

  const formats: unknown[] = [];
  if (opts.schema || opts.prompt) {
    formats.push({
      type: "json",
      ...(opts.schema ? { schema: opts.schema } : {}),
      ...(opts.prompt ? { prompt: opts.prompt } : {}),
    });
  }
  if (opts.markdown !== false) formats.push("markdown");

  const corps: Record<string, unknown> = { url, formats };
  if (opts.onlyMainContent !== undefined) corps.onlyMainContent = opts.onlyMainContent;
  if (opts.maxAge !== undefined) corps.maxAge = opts.maxAge;
  if (opts.waitFor !== undefined) corps.waitFor = opts.waitFor;
  if (opts.timeout !== undefined) corps.timeout = opts.timeout;
  if (opts.proxy !== undefined) corps.proxy = opts.proxy;
  if (opts.blockAds !== undefined) corps.blockAds = opts.blockAds;
  if (opts.location !== undefined) corps.location = opts.location;

  const res = await fetch(`${apiUrl()}/v2/scrape`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${cle}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(corps),
    signal: AbortSignal.timeout(opts.timeoutMs ?? 60_000),
  });

  const texte = await res.text();
  let json: ReponseScrape;
  try {
    json = JSON.parse(texte) as ReponseScrape;
  } catch {
    throw new Error(`Firecrawl HTTP ${res.status} — réponse illisible : ${texte.slice(0, 120)}`);
  }

  if (!res.ok || json.success === false) {
    // 401/402 = clé invalide ou crédits épuisés : à distinguer d'une page en échec.
    const detail = json.error ?? `HTTP ${res.status}`;
    if (res.status === 401 || res.status === 402) {
      const indice = res.status === 401 && firecrawlSelfHosted()
        ? " (instance auto-hébergée : vérifier USE_DB_AUTHENTICATION=false)"
        : "";
      throw new FirecrawlIndisponible(`Firecrawl ${res.status} — ${detail}${indice}`);
    }
    throw new Error(`Firecrawl ${res.status} — ${detail}`);
  }

  return {
    json: json.data?.json as T | undefined,
    markdown: json.data?.markdown,
    metadata: json.data?.metadata ?? {},
  };
}

/** Résumé court de la fraîcheur, à écrire dans les notes/logs des connecteurs. */
export function resumeFraicheur(meta: MetaScrape): string {
  const bouts: string[] = [];
  if (meta.statusCode) bouts.push(`HTTP ${meta.statusCode}`);
  if (meta.cacheState) bouts.push(`cache ${meta.cacheState}`);
  else bouts.push("scrape live");
  if (meta.cachedAt) bouts.push(`copie ${meta.cachedAt.slice(0, 16)}`);
  return bouts.join(", ");
}
