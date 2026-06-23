// Connecteur FAOSTAT — Prix producteurs céréales Afrique de l'Ouest
// Source : https://fenixservices.fao.org/faostat/api/v1/ — Licence FAO Open Data — PUBLIC
// Fréquence : hebdomadaire (données FAOSTAT mises à jour ~trimestriellement)
// Couverture : Prix producteurs maïs (USD/tonne) — Afrique de l'Ouest

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";
import { fetchJson } from "./http";

const SOURCE_CODE = "FAO_FPMA";

// FAOSTAT API — Domaine public FAO
// area codes: 107=Côte d'Ivoire, 68=Burkina Faso, 195=Mali, 288=Sénégal, 29=Bénin, 284=Togo, 100=Ghana, 159=Niger
// item 56 = Maize (Corn)
// element 5532 = Producer Price (USD/tonne)
const FAOSTAT_BASE = "https://fenixservices.fao.org/faostat/api/v1/en/data/PP";
const AREA_CODES = [107, 68, 195, 288, 29, 284, 100];

const AREA_NAMES: Record<number, string> = {
  107: "Côte d'Ivoire",
  68: "Burkina Faso",
  195: "Mali",
  288: "Sénégal",
  29: "Bénin",
  284: "Togo",
  100: "Ghana",
};

interface FaostatRecord {
  "Area Code": number;
  Area: string;
  "Item Code": number;
  Item: string;
  "Element Code": number;
  Element: string;
  "Year Code": number;
  Year: number;
  Unit: string;
  Value: number | null;
  Flag?: string;
}

interface FaostatResponse {
  data: FaostatRecord[];
}

async function fetchFaostatPrices(): Promise<FaostatRecord[]> {
  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: 6 }, (_, i) => currentYear - 5 + i).join(",");
  const areas = AREA_CODES.join(",");

  const params = new URLSearchParams({
    area: areas,
    item: "56", // Maize
    element: "5532", // Producer Price USD/tonne
    year: years,
    type: "datasets",
    output_type: "json",
  });

  const url = `${FAOSTAT_BASE}?${params}`;
  const json = await fetchJson<FaostatResponse>(url, { timeoutMs: 45_000, retries: 3 });
  return json.data ?? [];
}

export class FaoFpmaConnector implements Connector {
  code = SOURCE_CODE;
  nom = "FAO STAT — Prix producteurs maïs Afrique de l'Ouest";
  frequenceCron = "0 8 * * 4"; // Jeudi 8h UTC

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

      const records = await fetchFaostatPrices();

      for (const rec of records) {
        if (rec.Value === null || rec.Value <= 0) continue;

        const areaCode = rec["Area Code"];
        const year = rec.Year ?? rec["Year Code"];
        if (!year) continue;

        const dateReleve = new Date(`${year}-07-01T00:00:00.000Z`); // mid-year for annual

        // Find or use default market
        const marcheCode = `MONDE_MAIS_FAO`;
        const marche = await prisma.marche
          .findUnique({ where: { code: marcheCode } })
          .catch(() => null);

        // Fallback to any world maize market
        const marcheAlt = marche ?? await prisma.marche
          .findFirst({ where: { code: { contains: "MAIS" } } })
          .catch(() => null);

        if (!marcheAlt) continue;

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marcheAlt.id,
              sourceId: source.id,
              typePrix: "SPOT",
              valeur: rec.Value,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `FAOSTAT PP — ${AREA_NAMES[areaCode] ?? rec.Area} ${year}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`${rec.Area} ${year}: ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      const fin = new Date();
      const statut =
        resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR"
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
          sourceId: source.id,
          debut,
          fin,
          statut,
          nbImportes: resultat.nbImportes,
          nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} prix producteurs importés (FAOSTAT)`,
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
