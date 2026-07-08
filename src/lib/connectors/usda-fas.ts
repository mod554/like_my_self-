// Connecteur IMF Primary Commodity Prices — Maïs mondial
// Source : https://www.imf.org/external/datamapper/api/v1/ — Domaine public FMI
// Fréquence : mensuelle (mise à jour IMF ~fin de mois)
// Couverture : Prix maïs mondial (USD/tonne) + indicateurs agronomiques

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "USDA_FAS_PSD";

// IMF Primary Commodity Prices API (public, no auth required)
// PMAIZE = Maize (corn), USD per metric tonne
// PRAWM = Raw Materials composite index (backup)
const IMF_BASE = "https://www.imf.org/external/datamapper/api/v1";

interface ImfIndicatorValues {
  [countryOrWorld: string]: Record<string, number>;
}

interface ImfResponse {
  values: {
    [indicator: string]: ImfIndicatorValues;
  };
}

async function fetchImfCommodityPrices(indicator: string): Promise<Record<string, number>> {
  // IMF DataMapper API: GET /v1/{indicator} → { values: { PMAIZE: { WLD: { "2020": 165.1, ... } } } }
  const url = `${IMF_BASE}/${indicator}`;
  const response = await fetch(url, {
    headers: { "Accept": "application/json", "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(45_000),
  });
  if (!response.ok) throw new Error(`IMF API HTTP ${response.status} — ${indicator}`);
  const json = await response.json() as ImfResponse;
  const indicatorData = json.values?.[indicator];
  if (!indicatorData) {
    throw new Error(`Pas de données IMF pour ${indicator} — réponse: ${JSON.stringify(json).slice(0, 200)}`);
  }
  // WLD = world aggregate series
  const series = indicatorData["WLD"] ?? Object.values(indicatorData)[0];
  if (!series || Object.keys(series).length === 0) {
    throw new Error(`Série IMF ${indicator} vide`);
  }
  return series;
}

// Source primaire : Yahoo Finance — futures maïs CBOT ZC=F (parité TradingView
// ZC1!). API JSON publique sans clé. Prix en cents USD/boisseau → USD/tonne.
async function fetchYahooCorn(): Promise<{ date: string; usdParTonne: number }[]> {
  const res = await fetch("https://query1.finance.yahoo.com/v8/finance/chart/ZC=F?range=3mo&interval=1d", {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`Yahoo HTTP ${res.status}`);
  const json = await res.json() as {
    chart?: { result?: { timestamp?: number[]; indicators?: { quote?: { close?: (number | null)[] }[] } }[] };
  };
  const r = json.chart?.result?.[0];
  const ts = r?.timestamp ?? [];
  const closes = r?.indicators?.quote?.[0]?.close ?? [];
  const sorties: { date: string; usdParTonne: number }[] = [];
  for (let i = 0; i < ts.length; i++) {
    const c = closes[i];
    if (c == null || c <= 0) continue;
    const date = new Date(ts[i] * 1000).toISOString().slice(0, 10);
    sorties.push({ date, usdParTonne: Math.round((c / 100) * 39.3683 * 100) / 100 });
  }
  if (sorties.length === 0) throw new Error("Yahoo série vide");
  return sorties;
}

// Intraday maïs CBOT ZC=F — Yahoo est joignable depuis les IP Vercel, donc la
// granularité horaire (range=5d&interval=1h) et minute (range=1d&interval=1m)
// est collectée directement par le cron Vercel, sans runner externe. Renvoie
// des timestamps ISO complets (≠ point quotidien de minuit).
async function fetchYahooIntraday(range: string, interval: string): Promise<{ iso: string; usdParTonne: number; cents: number }[]> {
  const res = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/ZC=F?range=${range}&interval=${interval}`, {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`Yahoo intraday HTTP ${res.status}`);
  const json = await res.json() as {
    chart?: { result?: { timestamp?: number[]; indicators?: { quote?: { close?: (number | null)[] }[] } }[] };
  };
  const r = json.chart?.result?.[0];
  const ts = r?.timestamp ?? [];
  const closes = r?.indicators?.quote?.[0]?.close ?? [];
  const out: { iso: string; usdParTonne: number; cents: number }[] = [];
  for (let i = 0; i < ts.length; i++) {
    const c = closes[i];
    if (c == null || c <= 0) continue;
    out.push({
      iso: new Date(ts[i] * 1000).toISOString(),
      usdParTonne: Math.round((c / 100) * 39.3683 * 100) / 100,
      cents: Math.round(c * 100) / 100,
    });
  }
  return out;
}

// Fallback 1 : FRED (Federal Reserve) — serie PMAIZMTUSDM = "Global price of Maize"
// (donnees IMF redistribuees), CSV public sans cle : USD/tonne, mensuel.
async function fetchFredMaize(): Promise<{ date: string; usdParTonne: number }[]> {
  const res = await fetch("https://fred.stlouisfed.org/graph/fredgraph.csv?id=PMAIZMTUSDM", {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(45_000),
  });
  if (!res.ok) throw new Error(`FRED HTTP ${res.status}`);
  const csv = await res.text();
  const lignes = csv.trim().split("\n").slice(1); // DATE,PMAIZMTUSDM
  const sorties: { date: string; usdParTonne: number }[] = [];
  for (const l of lignes.slice(-72)) {
    const [date, val] = l.split(",");
    const v = parseFloat(val);
    if (!date || !isFinite(v) || v <= 0) continue;
    sorties.push({ date, usdParTonne: v });
  }
  if (sorties.length === 0) throw new Error("CSV FRED vide");
  return sorties;
}

// Fallback 2 : Stooq — corn futures CBOT (ZC), CSV public sans cle ni blocage IP.
// Prix en cents USD par boisseau -> USD/tonne : (cents/100) * 39.3683
async function fetchStooqCorn(): Promise<{ date: string; usdParTonne: number }[]> {
  const res = await fetch("https://stooq.com/q/d/l/?s=zc.f&i=d", {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`Stooq HTTP ${res.status}`);
  const csv = await res.text();
  const lignes = csv.trim().split("\n").slice(1); // Date,Open,High,Low,Close,Volume
  const sorties: { date: string; usdParTonne: number }[] = [];
  for (const l of lignes.slice(-120)) {
    const [date, , , , close] = l.split(",");
    const cents = parseFloat(close);
    if (!date || !isFinite(cents) || cents <= 0) continue;
    sorties.push({ date, usdParTonne: Math.round((cents / 100) * 39.3683 * 100) / 100 });
  }
  if (sorties.length === 0) throw new Error("CSV Stooq vide");
  return sorties;
}

export class UsdaFasConnector implements Connector {
  code = SOURCE_CODE;
  nom = "IMF — Primary Commodity Prices (Maïs mondial)";
  frequenceCron = "0 14 12 * *"; // 12 du mois à 14h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } });
      if (!produit) throw new Error("Produit MAIS_GRAIN introuvable");

      const marche =
        (await prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_USDA" } }).catch(() => null)) ??
        (await prisma.marche.findFirst({ where: { code: { contains: "MAIS" } } }).catch(() => null));

      if (!marche) throw new Error("Aucun marché MAIS trouvé en BD");

      // Prix mais — Yahoo Finance (ZC=F, parité TradingView) en primaire ;
      // fonctionne depuis les IP Vercel contrairement à Stooq/FRED. Repli
      // Stooq → FRED → IMF. Les echecs de repli sont des notes, pas des erreurs.
      let entries: [string, number][] = [];
      let sourceNote = "";
      const notesFallback: string[] = [];

      try {
        const yahoo = await fetchYahooCorn();
        sourceNote = "Yahoo Finance — CBOT ZC=F quotidien (parité TradingView ZC1!)";
        entries = yahoo.map((s) => [s.date, s.usdParTonne] as [string, number]);
      } catch (yahooErr) {
        notesFallback.push(`Yahoo: ${yahooErr instanceof Error ? yahooErr.message.slice(0, 60) : yahooErr}`);
        try {
        const stooq = await fetchStooqCorn();
        sourceNote = "Stooq — CBOT corn futures ZC (converti USD/tonne)";
        entries = stooq.map((s) => [s.date, s.usdParTonne] as [string, number]);
      } catch (stooqErr) {
        notesFallback.push(`Stooq: ${stooqErr instanceof Error ? stooqErr.message.slice(0, 60) : stooqErr}`);
        try {
          const fred = await fetchFredMaize();
          sourceNote = "FRED — Global price of Maize (PMAIZMTUSDM, donnees IMF)";
          entries = fred.map((f) => [f.date, f.usdParTonne] as [string, number]);
        } catch (fredErr) {
          notesFallback.push(`FRED: ${fredErr instanceof Error ? fredErr.message.slice(0, 60) : fredErr}`);
          try {
            const prixAnnuels = await fetchImfCommodityPrices("PMAIZE");
            sourceNote = "IMF Primary Commodity Prices — PMAIZE";
            const currentYear = new Date().getFullYear();
            entries = Object.entries(prixAnnuels).filter(
              ([year, val]) => parseInt(year) >= currentYear - 6 && val > 0
            );
          } catch (imfErr) {
            notesFallback.push(`IMF: ${imfErr instanceof Error ? imfErr.message.slice(0, 60) : imfErr}`);
          }
        }
      }
      }
      if (entries.length === 0) {
        // Les IP partagées Vercel épuisent les quotas Stooq/FRED/IMF — mais les
        // cotations arrivent via GitHub Actions (/api/import/mais). Si des
        // données récentes (< 48h) existent, la source est opérationnelle.
        const recent = await prisma.prixReleve.findFirst({
          where: { sourceId: source.id, dateCollecte: { gte: new Date(Date.now() - 48 * 3600_000) } },
          orderBy: { dateCollecte: "desc" },
        }).catch(() => null);
        if (recent) {
          const fin = new Date();
          await prisma.source.update({
            where: { code: SOURCE_CODE },
            data: { statutDernier: "OK", messageErreur: "Cotations CBOT alimentées via GitHub Actions (IP Vercel limitées par Stooq/FRED)" },
          });
          await prisma.connectorLog.create({
            data: {
              sourceId: source.id, debut, fin, statut: "OK",
              nbImportes: 0, nbErreurs: 0,
              message: "Sources directes limitées — données récentes déjà présentes (import GitHub Actions)",
            },
          }).catch(() => {});
          return { ...resultat, fin };
        }
        resultat.erreurs.push(...notesFallback);
        throw new Error("Aucune source maïs disponible (Stooq, FRED, IMF)");
      }

      for (const [dateStr, valeur] of entries) {
        const dateReleve = dateStr.length === 4
          ? new Date(`${dateStr}-07-01T00:00:00.000Z`)
          : new Date(`${dateStr}T00:00:00.000Z`);

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "SPOT",
              valeur,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `${sourceNote} — ${dateStr}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Prix ${dateStr}: ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      // Intraday maïs (horaire + minute) — collecté directement depuis Vercel
      // via Yahoo (le seul produit avec un marché live). Échec = note, pas erreur.
      for (const { range, interval, typePrix, note } of [
        { range: "5d", interval: "1h", typePrix: "SPOT_1H",   note: "CBOT ZC=F horaire via Yahoo (parité TradingView ZC1!)" },
        { range: "1d", interval: "1m", typePrix: "SPOT_1MIN", note: "CBOT ZC=F minute via Yahoo (parité TradingView ZC1!)" },
      ]) {
        try {
          const barres = await fetchYahooIntraday(range, interval);
          if (barres.length === 0) continue;
          const res = await prisma.prixReleve.createMany({
            data: barres.map((b) => ({
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix,
              valeur: b.usdParTonne,
              devise: "USD",
              unite: "tonne",
              dateReleve: new Date(b.iso),
              fiabilite: "OFFICIEL" as const,
              notes: `${note} — ${b.cents.toFixed(2)} ¢/bu`,
            })),
            skipDuplicates: true,
          });
          resultat.nbImportes += res.count;
        } catch (e) {
          resultat.erreurs.push(`Intraday ${interval}: ${e instanceof Error ? e.message.slice(0, 50) : e}`);
        }
      }

      // Créer une actualité résumé pour les données IMF
      if (entries.length > 0) {
        const filiere = await prisma.filiere.findUnique({ where: { code: "MAIS" } }).catch(() => null);
        if (filiere) {
          const dernierEntry = [...entries].sort(([a], [b]) => b.localeCompare(a))[0];
          const [annee, prix] = dernierEntry;
          try {
            await prisma.actualite.create({
              data: {
                filiereId: filiere.id,
                titre: `Maïs mondial ${annee.slice(0, 10)}: ${prix.toFixed(0)} USD/T`,
                lien: "https://stooq.com/q/?s=zc.f",
                source: sourceNote,
                resume: `Prix mondial du maïs au ${annee.slice(0, 10)} : ${prix.toFixed(2)} USD/tonne. Source : ${sourceNote}.`,
                datePublication: dernierEntry[0].length === 4 ? new Date(`${annee}-07-01T00:00:00.000Z`) : new Date(`${annee}T00:00:00.000Z`),
              },
            });
            resultat.nbImportes++;
          } catch {
            // doublon ignoré
          }
        }
      }

      const fin = new Date();
      // 0 nouvel import sans erreur = dédup active, données déjà à jour → OK
      const statut = resultat.nbErreurs > 0
        ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR")
        : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: statut,
          messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null,
        },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} entrées importées (IMF Commodity Prices)`,
          detail: { erreurs: resultat.erreurs },
        },
      });

      return { ...resultat, fin };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();
      await prisma.source
        .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "ERREUR", messageErreur: msg } })
        .catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
