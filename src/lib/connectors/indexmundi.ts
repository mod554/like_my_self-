// Connecteur IndexMundi — Données historiques prix commodités
// Source : https://www.indexmundi.com — HTML scraping (données historiques libres)
// Fréquence : mensuelle
// Couverture : Maïs (prix USD/MT mensuel), Cajou (prix USD/MT annuel)

import * as cheerio from "cheerio";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "INDEXMUNDI";

const MOIS_FR: Record<string, number> = {
  jan: 1, fév: 2, feb: 2, mar: 3, avr: 4, apr: 4, mai: 5, may: 5,
  jun: 6, jui: 6, jul: 7, août: 8, aug: 8, sep: 9, oct: 10, nov: 11, déc: 12, dec: 12,
};

interface CommoditePage {
  url: string;
  produitCode: string;
  marcheCode: string;
  devise: string;
  unite: string;
  fiabilite: string;
}

const PAGES: CommoditePage[] = [
  {
    url: "https://www.indexmundi.com/commodities/?commodity=corn&months=120",
    produitCode: "MAIS_GRAIN",
    marcheCode: "MONDIAL_MAIS_WB",
    devise: "USD",
    unite: "tonne",
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.indexmundi.com/commodities/?commodity=cashew-nuts&months=120",
    produitCode: "CAJOU_RCN",
    marcheCode: "ABIDJAN_RCN",
    devise: "USD",
    unite: "tonne",
    fiabilite: "INDICATIF",
  },
];

async function fetchHtml(url: string): Promise<string> {
  const response = await fetch(url, {
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "en-US,en;q=0.9",
      "User-Agent": "Mozilla/5.0 (compatible; LikeMyself-AgriBot/1.0)",
    },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} — ${url}`);
  return response.text();
}

interface DataPoint {
  date: Date;
  valeur: number;
}

function parseIndexMundi(html: string): DataPoint[] {
  const $ = cheerio.load(html);
  const points: DataPoint[] = [];

  // IndexMundi affiche un tableau avec colonnes Mois | Prix
  $("table").each((_i, table) => {
    const headers: string[] = [];
    $(table)
      .find("th")
      .each((_j, th) => { headers.push($(th).text().trim().toLowerCase()); });

    // Chercher colonnes date/prix
    const dateIdx = headers.findIndex((h) => h.includes("month") || h.includes("date") || h.includes("mois"));
    const prixIdx = headers.findIndex((h) => h.includes("price") || h.includes("prix") || h.includes("usd"));

    if (prixIdx === -1 && dateIdx === -1) return;

    $(table)
      .find("tbody tr, tr")
      .each((_j, tr) => {
        const cells = $(tr)
          .find("td")
          .map((_k, td) => $(td).text().trim())
          .get();
        if (cells.length < 2) return;

        const rawDate = cells[dateIdx >= 0 ? dateIdx : 0];
        const rawPrix = cells[prixIdx >= 0 ? prixIdx : 1];

        const valeur = parseFloat(rawPrix?.replace(/[^\d.]/g, "") ?? "");
        if (isNaN(valeur) || valeur <= 0) return;

        // Parser "Jan 2020", "January 2020", "2020-01", "01/2020"
        let date: Date | null = null;

        const matchMonthYear = rawDate?.match(/([a-zéû]+)[\s.\-]+(\d{4})/i);
        const matchYearDash = rawDate?.match(/(\d{4})[/\-](\d{1,2})/);
        const matchSlash = rawDate?.match(/(\d{1,2})[/](\d{4})/);

        if (matchMonthYear) {
          const mois = MOIS_FR[matchMonthYear[1].toLowerCase().slice(0, 3)];
          if (mois) date = new Date(`${matchMonthYear[2]}-${String(mois).padStart(2, "0")}-01T00:00:00.000Z`);
        } else if (matchYearDash) {
          date = new Date(`${matchYearDash[1]}-${matchYearDash[2].padStart(2, "0")}-01T00:00:00.000Z`);
        } else if (matchSlash) {
          date = new Date(`${matchSlash[2]}-${matchSlash[1].padStart(2, "0")}-01T00:00:00.000Z`);
        }

        if (!date || isNaN(date.getTime())) return;
        points.push({ date, valeur });
      });
  });

  return points;
}

export class IndexMundiConnector implements Connector {
  code = SOURCE_CODE;
  nom = "IndexMundi — Prix historiques commodités agricoles";
  frequenceCron = "0 7 5 * *"; // 5 du mois à 7h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      for (const page of PAGES) {
        try {
          const [produit, marche] = await Promise.all([
            prisma.produit.findUnique({ where: { code: page.produitCode } }),
            prisma.marche.findUnique({ where: { code: page.marcheCode } }),
          ]);

          if (!produit) {
            resultat.erreurs.push(`Produit ${page.produitCode} introuvable`);
            resultat.nbErreurs++;
            continue;
          }
          if (!marche) {
            resultat.erreurs.push(`Marché ${page.marcheCode} introuvable`);
            resultat.nbErreurs++;
            continue;
          }

          const html = await fetchHtml(page.url);
          const points = parseIndexMundi(html);

          for (const point of points) {
            try {
              await prisma.prixReleve.create({
                data: {
                  produitId: produit.id,
                  marcheId: marche.id,
                  sourceId: source.id,
                  typePrix: "SPOT",
                  valeur: point.valeur,
                  devise: page.devise,
                  unite: page.unite,
                  dateReleve: point.date,
                  fiabilite: page.fiabilite,
                  notes: `IndexMundi — ${page.produitCode}`,
                },
              });
              resultat.nbImportes++;
            } catch (err: unknown) {
              const msg = err instanceof Error ? err.message : String(err);
              if (!msg.includes("Unique constraint")) {
                resultat.erreurs.push(`${page.produitCode} ${point.date.toISOString().split("T")[0]}: ${msg}`);
                resultat.nbErreurs++;
              }
            }
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          resultat.erreurs.push(`Page ${page.produitCode}: ${msg}`);
          resultat.nbErreurs++;
        }
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
          message: `${resultat.nbImportes} relevés historiques importés`,
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
