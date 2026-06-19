// Connecteur RESIMAO — Réseau des Systèmes d'Information de Marché en Afrique de l'Ouest
// Source : https://www.resimao.org — HTML scraping
// Fréquence : hebdomadaire (mercredi)
// Couverture : Prix marchés Afrique de l'Ouest — maïs, mil, sorgho (et cola parfois)

import * as cheerio from "cheerio";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "RESIMAO";
const BASE_URL = "https://www.resimao.org";

async function fetchHtml(url: string): Promise<string> {
  const response = await fetch(url, {
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "fr-FR,fr;q=0.9",
      "User-Agent": "Mozilla/5.0 (compatible; LikeMyself-AgriBot/1.0)",
    },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} — ${url}`);
  return response.text();
}

interface MarcheReleve {
  pays: string;
  marche: string;
  produit: string;
  prix: number;
  devise: string;
  unite: string;
  date: Date;
}

// Mapping produits RESIMAO → codes BD
const PRODUIT_MAP: Record<string, string> = {
  "maïs": "MAIS_GRAIN",
  "mais": "MAIS_GRAIN",
  "corn": "MAIS_GRAIN",
  "maize": "MAIS_GRAIN",
  "noix de cajou": "CAJOU_RCN",
  "anacarde": "CAJOU_RCN",
  "cola": "COLA_ROUGE",
  "kola": "COLA_ROUGE",
};

// Mapping marchés RESIMAO → codes BD (principaux)
const MARCHE_MAP: Record<string, string> = {
  "abidjan": "ABIDJAN_MAIS",
  "ouagadougou": "OUAGA_MAIS",
  "bamako": "BAMAKO_MAIS",
  "niamey": "NIAMEY_MAIS",
  "dakar": "DAKAR_MAIS",
  "lomé": "LOME_MAIS",
  "cotonou": "COTONOU_MAIS",
  "lagos": "LAGOS_MAIS",
  "accra": "ACCRA_MAIS",
};

function parsePrixResimao(html: string): MarcheReleve[] {
  const $ = cheerio.load(html);
  const releves: MarcheReleve[] = [];

  // Tableaux de prix
  $("table").each((_i, table) => {
    const headers: string[] = [];
    $(table)
      .find("th, thead td")
      .each((_j, th) => { headers.push($(th).text().trim().toLowerCase()); });

    const colonnes = {
      pays: headers.findIndex((h) => h.includes("pays") || h.includes("country")),
      marche: headers.findIndex((h) => h.includes("marché") || h.includes("marche") || h.includes("market")),
      produit: headers.findIndex((h) => h.includes("produit") || h.includes("commodity")),
      prix: headers.findIndex((h) => h.includes("prix") || h.includes("price")),
      unite: headers.findIndex((h) => h.includes("unité") || h.includes("unit")),
      date: headers.findIndex((h) => h.includes("date") || h.includes("période")),
    };

    if (colonnes.prix === -1) return;

    $(table)
      .find("tbody tr")
      .each((_j, tr) => {
        const cells = $(tr)
          .find("td")
          .map((_k, td) => $(td).text().trim())
          .get();
        if (cells.length === 0) return;

        const rawPrix = cells[colonnes.prix]?.replace(/[^\d,.]/g, "").replace(",", ".");
        const valeur = parseFloat(rawPrix ?? "");
        if (isNaN(valeur) || valeur <= 0) return;

        const produitRaw = (colonnes.produit >= 0 ? cells[colonnes.produit] : "").toLowerCase();
        const marcheRaw = (colonnes.marche >= 0 ? cells[colonnes.marche] : "").toLowerCase();
        const paysRaw = colonnes.pays >= 0 ? cells[colonnes.pays] : "";

        // Déterminer la devise selon le pays
        const devise = paysRaw.toLowerCase().includes("ghana") ? "GHS"
          : paysRaw.toLowerCase().includes("nigeria") ? "NGN"
          : "XOF";

        // Unité
        const uniteRaw = colonnes.unite >= 0 ? cells[colonnes.unite] : "kg";
        const unite = uniteRaw.toLowerCase().includes("tonne") || uniteRaw.toLowerCase().includes("100kg") ? "tonne" : "kg";

        // Date
        let date = new Date();
        if (colonnes.date >= 0 && cells[colonnes.date]) {
          const raw = cells[colonnes.date];
          const matchDMY = raw.match(/(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})/);
          if (matchDMY) {
            date = new Date(`${matchDMY[3]}-${matchDMY[2].padStart(2, "0")}-${matchDMY[1].padStart(2, "0")}T12:00:00.000Z`);
          }
        }

        releves.push({
          pays: paysRaw,
          marche: marcheRaw,
          produit: produitRaw,
          prix: valeur,
          devise,
          unite,
          date,
        });
      });
  });

  return releves;
}

export class ResimaoConnector implements Connector {
  code = SOURCE_CODE;
  nom = "RESIMAO — Systèmes d'Information de Marché Afrique de l'Ouest";
  frequenceCron = "0 10 * * 3"; // Mercredi 10h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      // Pages potentielles avec données de prix
      const urlsEssai = [
        `${BASE_URL}/prix`,
        `${BASE_URL}/prix-marches`,
        `${BASE_URL}/marches`,
        `${BASE_URL}/donnees/prix`,
        `${BASE_URL}/fr/prix`,
        BASE_URL,
      ];

      let releves: MarcheReleve[] = [];

      for (const url of urlsEssai) {
        try {
          const html = await fetchHtml(url);
          releves = parsePrixResimao(html);
          if (releves.length > 0) break;
        } catch {
          continue;
        }
      }

      for (const releve of releves) {
        // Trouver le produit correspondant
        let produitCode: string | null = null;
        for (const [key, val] of Object.entries(PRODUIT_MAP)) {
          if (releve.produit.includes(key)) {
            produitCode = val;
            break;
          }
        }
        if (!produitCode) continue;

        // Trouver le marché correspondant
        let marcheCode: string | null = null;
        for (const [key, val] of Object.entries(MARCHE_MAP)) {
          if (releve.marche.includes(key) || releve.pays.toLowerCase().includes(key)) {
            marcheCode = val;
            break;
          }
        }
        if (!marcheCode) continue;

        const [produit, marche] = await Promise.all([
          prisma.produit.findUnique({ where: { code: produitCode } }),
          prisma.marche.findUnique({ where: { code: marcheCode } }),
        ]);

        if (!produit || !marche) continue;

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "DETAIL",
              valeur: releve.prix,
              devise: releve.devise,
              unite: releve.unite,
              dateReleve: releve.date,
              fiabilite: "INDICATIF",
              notes: `RESIMAO — ${releve.pays} — ${releve.marche}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`${releve.marche} ${releve.produit}: ${msg}`);
            resultat.nbErreurs++;
          }
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
