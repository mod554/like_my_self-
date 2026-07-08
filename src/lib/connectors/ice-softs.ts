// Connecteur ICE Softs — Café Arabica (KC=F) & Cacao (CC=F)
// Source : Yahoo Finance (joignable depuis les IP Vercel). Cultures de rente
// cotées en bourse → quotidien + intraday (1h/1min), parité TradingView.
// Café KC=F : cents USD/livre → USD/tonne. Cacao CC=F : USD/tonne (déjà).

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "ICE_SOFTS";
const LBS_PAR_TONNE = 2204.6226;

interface Instrument {
  ticker: string;       // symbole Yahoo
  produitCode: string;
  marcheCode: string;
  label: string;
  // convertit la clôture brute Yahoo en USD/tonne
  versUsdTonne: (brut: number) => number;
}

const INSTRUMENTS: Instrument[] = [
  {
    ticker: "KC=F", produitCode: "CAFE_ARABICA", marcheCode: "ICE_CAFE",
    label: "Café Arabica ICE KC=F",
    versUsdTonne: (cents) => Math.round((cents / 100) * LBS_PAR_TONNE * 100) / 100, // ¢/lb → USD/t
  },
  {
    ticker: "CC=F", produitCode: "CACAO_FEVE", marcheCode: "ICE_CACAO",
    label: "Cacao ICE CC=F",
    versUsdTonne: (usdTonne) => Math.round(usdTonne * 100) / 100, // déjà USD/tonne
  },
];

interface Barre { iso: string; usdTonne: number; brut: number }

async function fetchYahoo(ticker: string, range: string, interval: string, conv: (b: number) => number): Promise<Barre[]> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${range}&interval=${interval}`;
  const res = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`Yahoo HTTP ${res.status} (${ticker})`);
  const json = await res.json() as {
    chart?: { result?: { timestamp?: number[]; indicators?: { quote?: { close?: (number | null)[] }[] } }[] };
  };
  const r = json.chart?.result?.[0];
  const ts = r?.timestamp ?? [];
  const closes = r?.indicators?.quote?.[0]?.close ?? [];
  const out: Barre[] = [];
  for (let i = 0; i < ts.length; i++) {
    const c = closes[i];
    if (c == null || c <= 0) continue;
    out.push({ iso: new Date(ts[i] * 1000).toISOString(), usdTonne: conv(c), brut: Math.round(c * 100) / 100 });
  }
  return out;
}

export class IceSoftsConnector implements Connector {
  code = SOURCE_CODE;
  nom = "ICE Softs — Café Arabica (KC=F) & Cacao (CC=F) via Yahoo";
  frequenceCron = "0 6 * * *"; // quotidien 6h UTC (déclenché aussi par le runner/booster)

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable — lancer /api/init`);

      // range/interval/typePrix pour quotidien + intraday
      const fenetres: { range: string; interval: string; typePrix: string; note: string }[] = [
        { range: "3mo", interval: "1d", typePrix: "SPOT",      note: "quotidien" },
        { range: "5d",  interval: "1h", typePrix: "SPOT_1H",   note: "horaire" },
        { range: "1d",  interval: "1m", typePrix: "SPOT_1MIN", note: "minute" },
      ];

      for (const inst of INSTRUMENTS) {
        const produit = await prisma.produit.findUnique({ where: { code: inst.produitCode } });
        const marche = await prisma.marche.findUnique({ where: { code: inst.marcheCode } });
        if (!produit || !marche) {
          resultat.erreurs.push(`${inst.label}: produit/marché introuvable — lancer /api/init`);
          resultat.nbErreurs++;
          continue;
        }

        for (const f of fenetres) {
          let barres: Barre[];
          try {
            barres = await fetchYahoo(inst.ticker, f.range, f.interval, inst.versUsdTonne);
          } catch (e) {
            resultat.erreurs.push(`${inst.label} ${f.note}: ${e instanceof Error ? e.message.slice(0, 50) : e}`);
            resultat.nbErreurs++;
            continue;
          }
          if (barres.length === 0) continue;

          // quotidien → date à minuit ; intraday → timestamp complet
          const data = barres.map((b) => ({
            produitId: produit.id,
            marcheId: marche.id,
            sourceId: source.id,
            typePrix: f.typePrix,
            valeur: b.usdTonne,
            devise: "USD",
            unite: "tonne",
            dateReleve: f.interval === "1d" ? new Date(b.iso.slice(0, 10) + "T00:00:00.000Z") : new Date(b.iso),
            fiabilite: "OFFICIEL" as const,
            notes: `${inst.label} ${f.note} via Yahoo (parité TradingView) — ${b.brut}`,
          }));
          try {
            const res = await prisma.prixReleve.createMany({ data, skipDuplicates: true });
            resultat.nbImportes += res.count;
          } catch (err) {
            resultat.erreurs.push(`${inst.label} ${f.note} insert: ${err instanceof Error ? err.message.slice(0, 50) : err}`);
            resultat.nbErreurs++;
          }
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0
        ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR")
        : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} cotations café/cacao importées`,
          detail: { erreurs: resultat.erreurs.slice(0, 5) },
        },
      }).catch(() => {});

      return { ...resultat, fin };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();
      await prisma.source
        .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "ERREUR", messageErreur: msg } })
        .catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
