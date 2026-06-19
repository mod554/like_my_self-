// Connecteur FAO FPMA — Food Price Monitoring and Analysis
// Source : https://fpma.fao.org/giews/fpma/rest/ — Licence FAO Open Data — PUBLIC
// Fréquence : hebdomadaire (jeudi)
// Couverture : Prix alimentaires Afrique de l'Ouest + maïs mondial

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "FAO_FPMA";

interface FpmaDataPoint {
  date: string; // ISO ou "YYYY-MM-DD"
  price: number;
  currency: string;
  unit: string;
  market?: string;
  commodity?: string;
}

interface FpmaResponse {
  data: FpmaDataPoint[];
  metadata?: {
    total: number;
    commodity?: string;
    country?: string;
  };
}

// Commodities FAO FPMA à surveiller
// ID obtenus via https://fpma.fao.org/giews/fpma/rest/commodities
const COMMODITIES = [
  { fpmaId: 1, code: "MAIS_GRAIN", marcheCode: "MONDE_MAIS_FAO", devise: "USD", unite: "tonne" },
  { fpmaId: 63, code: "CAJOU_RCN", marcheCode: "ABIDJAN_RCN_FAO", devise: "USD", unite: "tonne" },
];

// Pays couverts pour les prix maïs Afrique de l'Ouest
const PAYS_AFRIQUE_OUEST = ["Côte d'Ivoire", "Burkina Faso", "Mali", "Niger", "Sénégal", "Bénin", "Togo", "Ghana", "Nigeria"];

async function fetchFpmaData(commodityId: number, countryId?: number): Promise<FpmaDataPoint[]> {
  const params = new URLSearchParams({
    commodity: String(commodityId),
    format: "json",
    startDate: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000 * 2).toISOString().split("T")[0], // 2 ans
  });
  if (countryId) params.set("country", String(countryId));

  const url = `https://fpma.fao.org/giews/fpma/rest/data/getPrices?${params}`;
  const response = await fetch(url, {
    headers: { Accept: "application/json", "User-Agent": "LikeMyself-AgriTerminal/1.0" },
    signal: AbortSignal.timeout(45_000),
  });

  if (!response.ok) throw new Error(`FAO FPMA HTTP ${response.status} — ${url}`);
  const json = (await response.json()) as FpmaResponse | FpmaDataPoint[];
  return Array.isArray(json) ? json : (json.data ?? []);
}

export class FaoFpmaConnector implements Connector {
  code = SOURCE_CODE;
  nom = "FAO FPMA — Food Price Monitoring and Analysis";
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

      for (const commodity of COMMODITIES) {
        try {
          const produit = await prisma.produit.findUnique({ where: { code: commodity.code } });
          if (!produit) {
            resultat.erreurs.push(`Produit ${commodity.code} introuvable`);
            resultat.nbErreurs++;
            continue;
          }

          const marche = await prisma.marche.findUnique({ where: { code: commodity.marcheCode } });
          if (!marche) {
            resultat.erreurs.push(`Marché ${commodity.marcheCode} introuvable`);
            resultat.nbErreurs++;
            continue;
          }

          const points = await fetchFpmaData(commodity.fpmaId);

          for (const point of points) {
            if (!point.price || isNaN(point.price)) continue;
            const dateReleve = new Date(point.date);
            if (isNaN(dateReleve.getTime())) continue;

            try {
              await prisma.prixReleve.create({
                data: {
                  produitId: produit.id,
                  marcheId: marche.id,
                  sourceId: source.id,
                  typePrix: "SPOT",
                  valeur: point.price,
                  devise: point.currency || commodity.devise,
                  unite: point.unit || commodity.unite,
                  dateReleve,
                  fiabilite: "OFFICIEL",
                  notes: `FAO FPMA — Commodity ${commodity.fpmaId} — ${point.market ?? ""}`,
                },
              });
              resultat.nbImportes++;
            } catch (err: unknown) {
              const msg = err instanceof Error ? err.message : String(err);
              if (!msg.includes("Unique constraint")) {
                resultat.erreurs.push(`${commodity.code} ${point.date}: ${msg}`);
                resultat.nbErreurs++;
              }
            }
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          resultat.erreurs.push(`Commodity ${commodity.fpmaId}: ${msg}`);
          resultat.nbErreurs++;
        }
      }

      const fin = new Date();
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK",
          messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null,
        },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id,
          debut,
          fin,
          statut: resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK",
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
        .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "ERREUR", messageErreur: msg } })
        .catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
