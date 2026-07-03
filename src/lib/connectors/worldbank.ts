// Connecteur World Bank — Commodity Price Data (Pink Sheet)
// Source : https://api.worldbank.org/v2/ — Licence CC-BY 4.0 — PUBLIC
// Fréquence : mensuelle

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

// World Bank Global Economic Monitor Commodities — maize price USD/tonne monthly
// Correct indicator: PMAIZMMT (no .USD suffix — currency is built-in to the series)
const INDICATEUR_MAIS = "PMAIZMMT";
const SOURCE_CODE = "WORLD_BANK_PINK";

interface WBDataPoint {
  date: string; // "2024M11"
  value: number | null;
}

function parseDate(wbDate: string): Date | null {
  const matchMois = wbDate.match(/^(\d{4})M(\d{2})$/);
  if (matchMois) {
    return new Date(`${matchMois[1]}-${matchMois[2]}-01T00:00:00.000Z`);
  }
  const matchAn = wbDate.match(/^(\d{4})$/);
  if (matchAn) {
    return new Date(`${matchAn[1]}-01-01T00:00:00.000Z`);
  }
  return null;
}

async function fetchWBData(url: string): Promise<WBDataPoint[]> {
  const res = await fetch(url, {
    headers: { "Accept": "application/json", "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`API World Bank — HTTP ${res.status}`);
  const json = await res.json() as [unknown, WBDataPoint[]];
  return Array.isArray(json) && Array.isArray(json[1]) ? json[1] : [];
}

export class WorldBankConnector implements Connector {
  code = SOURCE_CODE;
  nom = "World Bank — Commodity Price Data (Pink Sheet)";
  frequenceCron = "0 6 1 * *"; // 1er du mois à 6h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source.update({
      where: { code: SOURCE_CODE },
      data: { statutDernier: "EN_COURS", derniereExecution: debut },
    });

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } });
      if (!produit) throw new Error("Produit MAIS_GRAIN introuvable en BD");

      const marche = await prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_WB" } });
      if (!marche) throw new Error("Marché MONDIAL_MAIS_WB introuvable en BD");

      // World Bank API — /country/all/indicator/{id} for global commodity series
      // mrv=60 = last 60 monthly values
      // Pink Sheet series live in the GEM Commodities database (source=21)
      const urls = [
        `https://api.worldbank.org/v2/en/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60&source=21`,
        `https://api.worldbank.org/v2/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60&source=21`,
        `https://api.worldbank.org/v2/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60`,
        `https://api.worldbank.org/v2/en/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60`,
      ];
      let donnees: WBDataPoint[] = [];
      for (const u of urls) {
        try {
          donnees = await fetchWBData(u);
          if (donnees.length > 0) break;
        } catch { /* essayer l'URL suivante */ }
      }

      if (donnees.length === 0) {
        throw new Error(`World Bank API returned 0 data points for ${INDICATEUR_MAIS}`);
      }

      for (const point of donnees) {
        if (point.value === null) continue;

        const dateReleve = parseDate(point.date);
        if (!dateReleve) {
          resultat.erreurs.push(`Date non parseable : ${point.date}`);
          resultat.nbErreurs++;
          continue;
        }

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "SPOT",
              valeur: point.value,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `World Bank Pink Sheet — ${INDICATEUR_MAIS} — ${point.date}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Erreur insertion ${point.date} : ${msg}`);
            resultat.nbErreurs++;
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
          message: `${resultat.nbImportes} relevés importés`,
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
