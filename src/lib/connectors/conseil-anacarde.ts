// Connecteur FAOSTAT — Prix producteurs anacarde (cajou) Afrique de l'Ouest
// Source : https://fenixservices.fao.org/faostat/api/v1/ — Licence FAO Open Data — PUBLIC
// Fréquence : bi-hebdomadaire (lundi + jeudi)
// Couverture : Prix producteurs cajou RCN (noix brute) — Côte d'Ivoire + région AOF

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "CONSEIL_ANACARDE_CI";

// FAOSTAT API — Domaine public FAO
// item 217 = Cashew nuts, with shell (anacarde RCN)
// element 5532 = Producer Price (USD/tonne)
// area 107 = Côte d'Ivoire, 29 = Bénin, 276 = Guinée-Bissau, 159 = Niger, 288 = Sénégal, 83 = Cameroun
const FAOSTAT_BASE = "https://faostatservices.fao.org/api/v1/en/data/PP";
const FAOSTAT_BASE_V2 = "https://fenixservices.fao.org/faostat/api/v1/en/data/PP";
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

  for (const base of [FAOSTAT_BASE, FAOSTAT_BASE_V2]) {
    try {
      const url = `${base}?${params}`;
      // FAOSTAT exige une authentification depuis 2026 (HTTP 401) — clé
      // optionnelle via FAOSTAT_KEY ; timeout court, les miroirs étant morts.
      const headers: Record<string, string> = { "Accept": "application/json", "User-Agent": "Mozilla/5.0" };
      if (process.env.FAOSTAT_KEY) headers["Authorization"] = `Bearer ${process.env.FAOSTAT_KEY}`;
      const response = await fetch(url, {
        headers,
        signal: AbortSignal.timeout(12_000),
      });
      if (!response.ok) continue;
      const json = await response.json() as FaostatResponse;
      const data = json.data ?? [];
      if (data.length > 0) return data;
    } catch {
      continue;
    }
  }
  return [];
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

        // Fiabilité selon le flag FAOSTAT : A = officiel, E = estimation FAO,
        // I = valeur imputée. Sans flag officiel → ESTIME, pas OFFICIEL.
        const flag = (rec.Flag ?? "").toUpperCase();
        const fiabilite = flag === "A" || flag === "" ? "OFFICIEL" : "ESTIME";

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
              fiabilite,
              notes: `FAOSTAT PP (prix producteur annuel, moyenne nationale) — Cajou — ${AREA_NAMES[areaCode] ?? rec.Area} ${year}${flag ? ` [flag ${flag}]` : ""}`,
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
            // Pas de contrainte unique sur Actualite → vérifier l'existence
            // avant d'insérer (sinon chaque run ajoutait un doublon au fil).
            const titre = `FAOSTAT — Prix cajou Côte d'Ivoire ${last.Year}: ${last.Value?.toFixed(0)} USD/T`;
            const lien = "https://www.fao.org/faostat/en/#data/PP";
            const deja = await prisma.actualite.findFirst({ where: { lien, titre }, select: { id: true } }).catch(() => null);
            if (!deja) {
              await prisma.actualite.create({
                data: {
                  filiereId: filiere.id,
                  titre,
                  lien,
                  source: "FAO STAT",
                  resume: `Prix producteur anacarde (RCN) Côte d'Ivoire ${last.Year} : ${last.Value?.toFixed(2)} USD/tonne. Source : FAO STAT.`,
                  datePublication: new Date(`${last.Year}-04-01T00:00:00.000Z`),
                },
              }).catch(() => {});
              resultat.nbImportes++;
            }
          }
        }
      }

      const fin = new Date();
      // 0 nouvel import sans erreur = dédup active, données déjà à jour → OK.
      // MAIS une réponse FAOSTAT totalement vide = API indisponible (ex. 401
      // « Missing Authorization Header » depuis 2026) → ERREUR, pas un faux OK.
      const statut = records.length === 0
        ? "ERREUR"
        : resultat.nbErreurs > 0
          ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR")
          : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: statut,
          messageErreur: records.length === 0
            ? "FAOSTAT indisponible (API désormais sous authentification) — aucune donnée reçue"
            : resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null,
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
