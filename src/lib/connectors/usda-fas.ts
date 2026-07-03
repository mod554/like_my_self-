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

// Fallback : Stooq — corn futures CBOT (ZC), CSV public sans cle ni blocage IP.
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

      // Prix mais : IMF d'abord, sinon Stooq (l'IMF bloque certaines IP cloud)
      let entries: [string, number][] = [];
      let sourceNote = "IMF Primary Commodity Prices — PMAIZE";
      try {
        const prixAnnuels = await fetchImfCommodityPrices("PMAIZE");
        const currentYear = new Date().getFullYear();
        entries = Object.entries(prixAnnuels).filter(
          ([year, val]) => parseInt(year) >= currentYear - 6 && val > 0
        );
      } catch (imfErr) {
        resultat.erreurs.push(`IMF indisponible: ${imfErr instanceof Error ? imfErr.message.slice(0, 60) : imfErr}`);
        const stooq = await fetchStooqCorn();
        sourceNote = "Stooq — CBOT corn futures ZC (converti USD/tonne)";
        entries = stooq.map((s) => [s.date, s.usdParTonne] as [string, number]);
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
                titre: `IMF Commodity Prices — Maïs ${annee}: ${prix.toFixed(0)} USD/T`,
                lien: "https://www.imf.org/en/Research/commodity-prices",
                source: "IMF Primary Commodity Prices",
                resume: `Prix mondial du maïs (PMAIZE) en ${annee} : ${prix.toFixed(2)} USD/tonne. Source : FMI.`,
                datePublication: new Date(`${annee}-07-01T00:00:00.000Z`),
              },
            });
            resultat.nbImportes++;
          } catch {
            // doublon ignoré
          }
        }
      }

      const fin = new Date();
      const statut = resultat.nbImportes === 0 ? "ERREUR"
        : resultat.nbErreurs > 0 ? "PARTIEL"
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
