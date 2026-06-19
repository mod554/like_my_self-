// Connecteur USDA FAS PSD Online — Production, Supply & Distribution
// Source : https://apps.fas.usda.gov/psdonline/api/ — Domaine public US gov
// Fréquence : mensuelle (WASDE publié ~10 du mois)
// Couverture : Maïs — offre/demande mondiale, production pays

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "USDA_FAS_PSD";

// Codes USDA FAS PSD
const COMMODITY_CORN = "0440000"; // Corn
const ATTRIBUTE_PRODUCTION = "28"; // Production
const ATTRIBUTE_EXPORTS = "88"; // Total Exports
const ATTRIBUTE_IMPORTS = "57"; // Total Imports
const ATTRIBUTE_PRICE_PRODUCER = "135"; // Producer Price (USD/tonne)

interface PsdDataPoint {
  commodityCode: string;
  countryCode: string;
  countryName: string;
  marketYear: number;
  calendarYear: number;
  month: number;
  attributeId: number;
  attributeName: string;
  unitId: string;
  unitDescription: string;
  value: number;
}

async function fetchPsdData(commodity: string, attributeId: string, year?: number): Promise<PsdDataPoint[]> {
  const currentYear = new Date().getFullYear();
  const fromYear = year ?? currentYear - 5;

  const url = `https://apps.fas.usda.gov/psdonline/api/psd/commodity/${commodity}/attribute/${attributeId}/yearStart/${fromYear}/yearEnd/${currentYear}`;
  const response = await fetch(url, {
    headers: { Accept: "application/json", "User-Agent": "LikeMyself-AgriTerminal/1.0" },
    signal: AbortSignal.timeout(60_000),
  });

  if (!response.ok) throw new Error(`USDA FAS HTTP ${response.status}`);
  const json = await response.json();
  return Array.isArray(json) ? json : [];
}

export class UsdaFasConnector implements Connector {
  code = SOURCE_CODE;
  nom = "USDA FAS — PSD Online Corn Supply & Demand";
  frequenceCron = "0 14 12 * *"; // 12 du mois à 14h UTC (après WASDE ~12h)

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

      const marche = await prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_USDA" } });
      if (!marche) throw new Error("Marché MONDIAL_MAIS_USDA introuvable");

      // Prix producteur US (proxy prix CBOT)
      try {
        const prixData = await fetchPsdData(COMMODITY_CORN, ATTRIBUTE_PRICE_PRODUCER);
        const usData = prixData.filter((d) => d.countryCode === "US" && d.value > 0);

        for (const point of usData) {
          const dateReleve = new Date(`${point.calendarYear}-${String(point.month).padStart(2, "0")}-01T00:00:00.000Z`);
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
                notes: `USDA FAS PSD — ${point.attributeName} — MY${point.marketYear}`,
              },
            });
            resultat.nbImportes++;
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            if (!msg.includes("Unique constraint")) {
              resultat.erreurs.push(`Prix ${point.calendarYear}-${point.month}: ${msg}`);
              resultat.nbErreurs++;
            }
          }
        }
      } catch (err: unknown) {
        resultat.erreurs.push(`Prix: ${err instanceof Error ? err.message : String(err)}`);
        resultat.nbErreurs++;
      }

      // Production mondiale — résumé annuel en actualité
      try {
        const prodData = await fetchPsdData(COMMODITY_CORN, ATTRIBUTE_PRODUCTION);
        const topPays = ["US", "CN", "BR", "AR", "UA"];
        const currentYear = new Date().getFullYear();
        const recents = prodData.filter((d) => topPays.includes(d.countryCode) && d.marketYear >= currentYear - 1 && d.value > 0);

        if (recents.length > 0) {
          const filiere = await prisma.filiere.findUnique({ where: { code: "MAIS" } });
          if (filiere) {
            const resume = recents
              .map((d) => `${d.countryName} MY${d.marketYear}: ${d.value.toLocaleString("fr")} ${d.unitDescription ?? "kMT"}`)
              .join(" · ");

            await prisma.actualite.create({
              data: {
                filiereId: filiere.id,
                titre: `USDA PSD — Production maïs mondiale MY${currentYear}`,
                lien: "https://apps.fas.usda.gov/psdonline/",
                source: "USDA FAS PSD Online",
                resume,
                datePublication: new Date(),
              },
            });
            resultat.nbImportes++;
          }
        }
      } catch (err: unknown) {
        resultat.erreurs.push(`Production: ${err instanceof Error ? err.message : String(err)}`);
        resultat.nbErreurs++;
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} entrées importées`,
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
