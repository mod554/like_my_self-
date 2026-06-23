// Connecteur FAOSTAT — Prix producteurs anacarde (cajou) Afrique de l'Ouest
// Source : https://fenixservices.fao.org/faostat/api/v1/ — Licence FAO Open Data — PUBLIC
// Fréquence : bi-hebdomadaire (lundi + jeudi)
// Couverture : Prix producteurs cajou RCN (noix brute) — Côte d'Ivoire + région AOF

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";
import { fetchJson } from "./http";

const SOURCE_CODE = "CONSEIL_ANACARDE_CI";

// FAOSTAT API — Domaine public FAO
// item 217 = Cashew nuts, with shell (anacarde RCN)
// element 5532 = Producer Price (USD/tonne)
// area 107 = Côte d'Ivoire, 29 = Bénin, 276 = Guinée-Bissau, 159 = Niger, 288 = Sénégal, 83 = Cameroun
const FAOSTAT_BASE = "https://fenixservices.fao.org/faostat/api/v1/en/data/PP";
const AREA_CODES_CAJOU = [107, 29, 276, 288, 83];

const AREA_NAMES: Record<number, string> = {
  107: "Côte d'Ivoire",
  29: "Bénin",
  276: "Guinée-Bissau",
  288: "Sénégal",
  83: "Cameroun",
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

async function fetchFaostatCashewPrices(): Promise<FaostatRecord[]> {
  const currentYear = new Date().getFullYear();
  const years = Array.from({ length: 7 }, (_, i) => currentYear - 6 + i).join(",");
  const areas = AREA_CODES_CAJOU.join(",");

  const params = new URLSearchParams({
    area: areas,
    item: "217", // Cashew nuts with shell
    element: "5532", // Producer Price USD/tonne
    year: years,
    type: "datasets",
    output_type: "json",
  });

  const url = `${FAOSTAT_BASE}?${params}`;
  const json = await fetchJson<FaostatResponse>(url, { timeoutMs: 45_000, retries: 3 });
  return json.data ?? [];
}

export class ConseilAnacardeCiConnector implements Connector {
  code = SOURCE_CODE;
  nom = "FAOSTAT — Prix producteurs anacarde (cajou) AOF";
  frequenceCron = "0 9 * * 1,4"; // Lundi et jeudi 9h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "CAJOU_RCN" } });
      if (!produit) throw new Error("Produit CAJOU_RCN introuvable");

      const marche =
        (await prisma.marche.findUnique({ where: { code: "ABIDJAN_RCN" } }).catch(() => null)) ??
        (await prisma.marche.findFirst({ where: { code: { contains: "CAJOU" } } }).catch(() => null)) ??
        (await prisma.marche.findFirst({ where: { code: { contains: "RCN" } } }).catch(() => null));

      if (!marche) throw new Error("Aucun marché CAJOU/RCN trouvé en BD");

      const records = await fetchFaostatCashewPrices();

      for (const rec of records) {
        if (rec.Value === null || rec.Value <= 0) continue;

        const year = rec.Year ?? rec["Year Code"];
        if (!year) continue;

        const areaCode = rec["Area Code"];
        const dateReleve = new Date(`${year}-04-01T00:00:00.000Z`); // campagne cajou ~avril

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "BORD_CHAMP",
              valeur: rec.Value,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `FAOSTAT PP — Cajou — ${AREA_NAMES[areaCode] ?? rec.Area} ${year}`,
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

      // Actualité résumé cajou si données disponibles
      if (records.length > 0) {
        const ciData = records
          .filter((r) => r["Area Code"] === 107 && r.Value !== null)
          .sort((a, b) => (b.Year ?? 0) - (a.Year ?? 0));

        if (ciData.length > 0) {
          const last = ciData[0];
          const filiere = await prisma.filiere.findUnique({ where: { code: "CAJOU" } }).catch(() => null);
          if (filiere) {
            try {
              await prisma.actualite.create({
                data: {
                  filiereId: filiere.id,
                  titre: `FAOSTAT — Prix cajou Côte d'Ivoire ${last.Year}: ${last.Value?.toFixed(0)} USD/T`,
                  lien: "https://www.fao.org/faostat/en/#data/PP",
                  source: "FAO STAT",
                  resume: `Prix producteur anacarde (RCN) Côte d'Ivoire ${last.Year} : ${last.Value?.toFixed(2)} USD/tonne. Source : FAO STAT.`,
                  datePublication: new Date(`${last.Year}-04-01T00:00:00.000Z`),
                },
              });
              resultat.nbImportes++;
            } catch {
              // doublon ignoré
            }
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
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} prix cajou importés (FAOSTAT)`,
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
