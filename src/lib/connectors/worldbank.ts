// Connecteur World Bank — Commodity Price Data (Pink Sheet)
// Source : https://api.worldbank.org/v2/ — Licence CC-BY 4.0 — PUBLIC
// Fréquence : mensuelle

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const INDICATEUR_MAIS = "PMAIZMMT.USD"; // Prix maïs US (USD/tonne, mensuel)
const SOURCE_CODE = "WORLD_BANK_PINK";

interface WBDataPoint {
  date: string; // "2024M11"
  value: number | null;
}

interface WBResponse {
  data: WBDataPoint[];
}

function parseDate(wbDate: string): Date | null {
  // Format : "2024M11" ou "2024"
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

export class WorldBankConnector implements Connector {
  code = SOURCE_CODE;
  nom = "World Bank — Commodity Price Data (Pink Sheet)";
  frequenceCron = "0 6 1 * *"; // 1er du mois à 6h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    // Marquer la source en cours
    await prisma.source.update({
      where: { code: SOURCE_CODE },
      data: { statutDernier: "EN_COURS", derniereExecution: debut },
    });

    try {
      const source = await prisma.source.findUnique({
        where: { code: SOURCE_CODE },
      });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({
        where: { code: "MAIS_GRAIN" },
      });
      if (!produit) throw new Error("Produit MAIS_GRAIN introuvable en BD");

      const marche = await prisma.marche.findUnique({
        where: { code: "MONDIAL_MAIS_WB" },
      });
      if (!marche) throw new Error("Marché MONDIAL_MAIS_WB introuvable en BD");

      // Appel API World Bank — 5 dernières années
      const url = `https://api.worldbank.org/v2/en/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60`;
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(30_000),
      });

      if (!response.ok) {
        throw new Error(`API World Bank — HTTP ${response.status}`);
      }

      const json = await response.json();
      // L'API World Bank renvoie [metadata, data]
      const donnees: WBDataPoint[] = Array.isArray(json) ? json[1] ?? [] : [];

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
          // Ignorer les doublons (contrainte unique non posée ici, mais possible)
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Erreur insertion ${point.date} : ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      const fin = new Date();
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: resultat.nbErreurs > 0 ? "PARTIEL" : "OK",
          messageErreur:
            resultat.erreurs.length > 0
              ? resultat.erreurs.slice(0, 3).join(" | ")
              : null,
        },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id,
          debut,
          fin,
          statut: resultat.nbErreurs > 0 ? "PARTIEL" : "OK",
          nbImportes: resultat.nbImportes,
          nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} relevés importés`,
          detail: { erreurs: resultat.erreurs },
        },
      });

      return { ...resultat, fin };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();

      await prisma.source
        .update({
          where: { code: SOURCE_CODE },
          data: { statutDernier: "ERREUR", messageErreur: msg },
        })
        .catch(() => {});

      return {
        ...resultat,
        nbErreurs: resultat.nbErreurs + 1,
        erreurs: [...resultat.erreurs, msg],
        fin,
      };
    }
  }
}
