// Connecteur RESIMAO / WFP VAM — Prix marchés Afrique de l'Ouest
// Source primaire : WFP VAM API (https://api.vam.wfp.org) — données JSON fiables
// Source secondaire : RESIMAO HTML (https://www.resimao.org) — fallback
// Stratégie : API JSON avant HTML scraping (anti-pattern évité: scraper quand API existe)
// Fréquence : hebdomadaire (mercredi)

import * as cheerio from "cheerio";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";
import { fetchJson, fetchHtmlFallback } from "./http";

const SOURCE_CODE = "RESIMAO";
const BASE_URL = "https://www.resimao.org";

// WFP VAM API — données prix alimentaires Afrique de l'Ouest
// https://api.vam.wfp.org — licence ouverte WFP
const WFP_API = "https://api.vam.wfp.org";

// ISO3 country codes for West Africa
const WFP_COUNTRIES = [
  { iso3: "CIV", name: "Côte d'Ivoire" },
  { iso3: "BFA", name: "Burkina Faso" },
  { iso3: "MLI", name: "Mali" },
  { iso3: "SEN", name: "Sénégal" },
  { iso3: "BEN", name: "Bénin" },
  { iso3: "TGO", name: "Togo" },
  { iso3: "GHA", name: "Ghana" },
  { iso3: "NGA", name: "Nigeria" },
  { iso3: "NER", name: "Niger" },
];

interface WfpMarket {
  marketId: number;
  marketName: string;
  admin1Name: string;
}

interface WfpPrice {
  commodityName: string;
  marketName: string;
  priceFlagName: string;
  priceTypeName: string;
  currencyName: string;
  unit: string;
  price: number;
  date: string; // ISO date
}

interface WfpPricesResponse {
  items?: WfpPrice[];
  data?: WfpPrice[];
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

// Mapping produit+marché → code BD (clé = "produit:marche")
const MARCHE_PRODUIT_MAP: Record<string, Record<string, string>> = {
  "MAIS_GRAIN": {
    "abidjan": "ABIDJAN_MAIS",
    "ouagadougou": "OUAGA_MAIS",
    "bamako": "BAMAKO_MAIS",
    "niamey": "NIAMEY_MAIS",
    "dakar": "DAKAR_MAIS",
    "lomé": "LOME_MAIS",
    "lome": "LOME_MAIS",
    "cotonou": "COTONOU_MAIS",
    "lagos": "LAGOS_MAIS",
    "accra": "ACCRA_MAIS",
  },
  "CAJOU_RCN": {
    "abidjan": "ABIDJAN_RCN",
  },
  "COLA_ROUGE": {
    "lagos": "LAGOS_COLA",
    "abidjan": "ABIDJAN_COLA",
    "accra": "ACCRA_COLA",
    "cotonou": "COTONOU_COLA",
    "dakar": "DAKAR_COLA",
  },
};

// Fallback map (mais only) kept for compatibility
const MARCHE_MAP: Record<string, string> = {
  "abidjan": "ABIDJAN_MAIS",
  "ouagadougou": "OUAGA_MAIS",
  "bamako": "BAMAKO_MAIS",
  "niamey": "NIAMEY_MAIS",
  "dakar": "DAKAR_MAIS",
  "lomé": "LOME_MAIS",
  "lome": "LOME_MAIS",
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

// WFP VAM API — fetch prices for a country (maize + cashew commodities)
async function fetchWfpPrices(iso3: string): Promise<WfpPrice[]> {
  try {
    // WFP food prices endpoint — returns recent retail prices per market
    const url = `${WFP_API}/v2/food_prices/${iso3}.json?commodity_name=Maize&commodity_name=Cashew+Nuts&commodity_name=Kola`;
    const data = await fetchJson<WfpPricesResponse>(url, { timeoutMs: 20_000, retries: 2 });
    return (data?.items ?? data?.data ?? []) as WfpPrice[];
  } catch {
    // Try alternate endpoint format
    try {
      const url2 = `${WFP_API}/FoodPrices/${iso3}?product=Maize`;
      const data2 = await fetchJson<WfpPricesResponse>(url2, { timeoutMs: 20_000, retries: 1 });
      return (data2?.items ?? data2?.data ?? []) as WfpPrice[];
    } catch {
      return [];
    }
  }
}

function wfpPriceToReleve(p: WfpPrice, country: { name: string }): MarcheReleve {
  const produitRaw = (p.commodityName ?? "").toLowerCase();
  const marcheRaw = (p.marketName ?? "").toLowerCase();
  const devise = country.name.includes("Ghana") ? "GHS"
    : country.name.includes("Nigeria") ? "NGN"
    : "XOF";
  const unite = (p.unit ?? "").toLowerCase().includes("kg") ? "kg" : "tonne";
  return {
    pays: country.name,
    marche: marcheRaw,
    produit: produitRaw,
    prix: p.price,
    devise,
    unite,
    date: p.date ? new Date(p.date) : new Date(),
  };
}

export class ResimaoConnector implements Connector {
  code = SOURCE_CODE;
  nom = "RESIMAO / WFP VAM — Prix marchés Afrique de l'Ouest";
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

      // Strategy 1: WFP VAM API (JSON — more reliable than HTML scraping)
      let releves: MarcheReleve[] = [];
      for (const country of WFP_COUNTRIES) {
        try {
          const wfpPrices = await fetchWfpPrices(country.iso3);
          releves.push(...wfpPrices.filter((p) => p.price > 0).map((p) => wfpPriceToReleve(p, country)));
        } catch {
          continue;
        }
      }

      // Strategy 2: RESIMAO HTML fallback (if WFP returned nothing)
      if (releves.length === 0) {
        const urlsEssai = [
          `${BASE_URL}/prix`,
          `${BASE_URL}/prix-marches`,
          `${BASE_URL}/marches`,
          `${BASE_URL}/donnees/prix`,
          `${BASE_URL}/fr/prix`,
          BASE_URL,
        ];
        const result = await fetchHtmlFallback(urlsEssai, { retries: 2 });
        if (result) releves = parsePrixResimao(result.html);
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

        // Trouver le marché correspondant selon le produit
        let marcheCode: string | null = null;
        const produitMap = MARCHE_PRODUIT_MAP[produitCode] ?? MARCHE_MAP;
        for (const [key, val] of Object.entries(produitMap)) {
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
