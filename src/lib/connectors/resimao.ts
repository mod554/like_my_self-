// Connecteur RESIMAO / WFP VAM — Prix marchés Afrique de l'Ouest
// Source primaire : WFP VAM API v2 (https://api.vam.wfp.org/v2/Markets/FoodPrices)
// Source secondaire : RESIMAO HTML (https://www.resimao.org) — fallback
// Fréquence : hebdomadaire (mercredi)

import * as cheerio from "cheerio";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "RESIMAO";
const BASE_URL = "https://www.resimao.org";

// WFP VAM API v2 — correct endpoint as of 2025
// GET /v2/Markets/FoodPrices?CountryCode={alpha2}&page=1&pageSize=500
const WFP_API = "https://api.vam.wfp.org";

// ISO alpha-2 country codes (WFP API uses alpha-2, not ISO3)
const WFP_COUNTRIES = [
  { alpha2: "CI", name: "Côte d'Ivoire" },
  { alpha2: "BF", name: "Burkina Faso" },
  { alpha2: "ML", name: "Mali" },
  { alpha2: "SN", name: "Sénégal" },
  { alpha2: "BJ", name: "Bénin" },
  { alpha2: "TG", name: "Togo" },
  { alpha2: "GH", name: "Ghana" },
  { alpha2: "NG", name: "Nigeria" },
  { alpha2: "NE", name: "Niger" },
];

interface WfpPrice {
  commodityName: string;
  marketName: string;
  priceFlagName?: string;
  priceTypeName?: string;
  currencyName?: string;
  unit: string;
  price: number;
  date: string;
}

interface WfpPricesResponse {
  items?: WfpPrice[];
  data?: WfpPrice[];
  records?: WfpPrice[];
  value?: WfpPrice[];
}

interface MarcheReleve {
  origine?: string; // "WFP/HDX" | "WFP API" | "RESIMAO"
  pays: string;
  marche: string;
  produit: string;
  prix: number;
  devise: string;
  unite: string;
  date: Date;
}

const PRODUIT_MAP: Record<string, string> = {
  "maïs": "MAIS_GRAIN",
  "mais": "MAIS_GRAIN",
  "corn": "MAIS_GRAIN",
  "maize": "MAIS_GRAIN",
  "noix de cajou": "CAJOU_RCN",
  "anacarde": "CAJOU_RCN",
  "cashew": "CAJOU_RCN",
  "cola": "COLA_ROUGE",
  "kola": "COLA_ROUGE",
};

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

        const devise = paysRaw.toLowerCase().includes("ghana") ? "GHS"
          : paysRaw.toLowerCase().includes("nigeria") ? "NGN"
          : "XOF";

        const uniteRaw = colonnes.unite >= 0 ? cells[colonnes.unite] : "kg";
        const unite = uniteRaw.toLowerCase().includes("tonne") || uniteRaw.toLowerCase().includes("100kg") ? "tonne" : "kg";

        let date = new Date();
        if (colonnes.date >= 0 && cells[colonnes.date]) {
          const raw = cells[colonnes.date];
          const matchDMY = raw.match(/(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})/);
          if (matchDMY) {
            date = new Date(`${matchDMY[3]}-${matchDMY[2].padStart(2, "0")}-${matchDMY[1].padStart(2, "0")}T12:00:00.000Z`);
          }
        }

        releves.push({ pays: paysRaw, marche: marcheRaw, produit: produitRaw, prix: valeur, devise, unite, date });
      });
  });

  return releves;
}

// WFP VAM API v2 — fetch food prices per country
async function fetchWfpPrices(alpha2: string): Promise<WfpPrice[]> {
  try {
    const url = `${WFP_API}/v2/Markets/FoodPrices?CountryCode=${alpha2}&page=1&pageSize=500`;
    const res = await fetch(url, {
      headers: { "Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/136.0.0.0" },
      signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok) return [];
    const data = await res.json() as WfpPricesResponse;
    const prices = data?.value ?? data?.items ?? data?.data ?? data?.records ?? [];
    return prices as WfpPrice[];
  } catch {
    return [];
  }
}

// Strategy 1bis : HDX (Humanitarian Data Exchange) — CSV publics des prix
// alimentaires WFP, sans clé API. L'URL du CSV est résolue dynamiquement via
// l'API CKAN. Rotation de 2 pays par run pour tenir le budget 60s serverless.
const HDX_DATASETS: { slug: string; pays: string; devise: string }[] = [
  { slug: "wfp-food-prices-for-burkina-faso",  pays: "Burkina Faso",  devise: "XOF" },
  { slug: "wfp-food-prices-for-mali",          pays: "Mali",          devise: "XOF" },
  { slug: "wfp-food-prices-for-senegal",       pays: "Sénégal",       devise: "XOF" },
  { slug: "wfp-food-prices-for-benin",         pays: "Bénin",         devise: "XOF" },
  { slug: "wfp-food-prices-for-niger",         pays: "Niger",         devise: "XOF" },
  { slug: "wfp-food-prices-for-cote-d-ivoire", pays: "Côte d'Ivoire", devise: "XOF" },
  { slug: "wfp-food-prices-for-togo",          pays: "Togo",          devise: "XOF" },
  { slug: "wfp-food-prices-for-ghana",         pays: "Ghana",         devise: "GHS" },
];

async function fetchHdxCsvUrl(slug: string): Promise<string | null> {
  try {
    const res = await fetch(`https://data.humdata.org/api/3/action/package_show?id=${slug}`, {
      headers: { "Accept": "application/json", "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(12_000),
    });
    if (!res.ok) return null;
    const json = await res.json() as { result?: { resources?: { url?: string; format?: string }[] } };
    const csv = (json.result?.resources ?? []).find((r) => (r.format ?? "").toUpperCase() === "CSV");
    return csv?.url ?? null;
  } catch {
    return null;
  }
}

async function fetchHdxPrices(dataset: { slug: string; pays: string; devise: string }): Promise<MarcheReleve[]> {
  const csvUrl = await fetchHdxCsvUrl(dataset.slug);
  if (!csvUrl) return [];
  try {
    const res = await fetch(csvUrl, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(20_000),
    });
    if (!res.ok) return [];
    const csv = await res.text();
    const lignes = csv.split("\n");
    // En-tête HDX : date,admin1,admin2,market,latitude,longitude,category,commodity,unit,priceflag,pricetype,currency,price,usdprice
    const header = (lignes[0] ?? "").toLowerCase().split(",");
    const iDate = header.indexOf("date");
    const iMarket = header.indexOf("market");
    const iCommodity = header.indexOf("commodity");
    const iUnit = header.indexOf("unit");
    const iCurrency = header.indexOf("currency");
    const iPrice = header.indexOf("price");
    if (iDate < 0 || iCommodity < 0 || iPrice < 0) return [];

    const seuil = new Date();
    seuil.setMonth(seuil.getMonth() - 18); // 18 derniers mois seulement
    const sorties: MarcheReleve[] = [];
    // Les CSV HDX sont triés chronologiquement — on lit depuis la fin
    for (let i = lignes.length - 1; i > 1 && sorties.length < 400; i--) {
      const cells = lignes[i].split(",");
      if (cells.length <= iPrice) continue;
      const commodity = (cells[iCommodity] ?? "").toLowerCase();
      if (!commodity.includes("maize") && !commodity.includes("maïs") && !commodity.includes("cashew")) continue;
      const date = new Date(cells[iDate]);
      if (isNaN(date.getTime()) || date < seuil) continue;
      const prix = parseFloat(cells[iPrice]);
      if (!isFinite(prix) || prix <= 0) continue;
      sorties.push({
        origine: "WFP/HDX",
        pays: dataset.pays,
        marche: (cells[iMarket] ?? "").toLowerCase(),
        produit: commodity,
        prix,
        devise: (cells[iCurrency] ?? dataset.devise).toUpperCase() || dataset.devise,
        unite: (cells[iUnit] ?? "").toLowerCase().includes("kg") ? "kg" : "tonne",
        date,
      });
    }
    return sorties;
  } catch {
    return [];
  }
}

async function fetchResimaoHtml(): Promise<MarcheReleve[]> {
  const urlsEssai = [
    `${BASE_URL}/prix`,
    `${BASE_URL}/prix-marches`,
    `${BASE_URL}/marches`,
    `${BASE_URL}/donnees/prix`,
    `${BASE_URL}/fr/prix`,
    BASE_URL,
  ];
  for (const url of urlsEssai) {
    try {
      const res = await fetch(url, {
        headers: {
          "Accept": "text/html,application/xhtml+xml",
          "Accept-Language": "fr-FR,fr;q=0.9",
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0",
        },
        signal: AbortSignal.timeout(30_000),
      });
      if (!res.ok) continue;
      const html = await res.text();
      if (html.length > 500) {
        const releves = parsePrixResimao(html);
        if (releves.length > 0) return releves;
      }
    } catch {
      continue;
    }
  }
  return [];
}

function wfpPriceToReleve(p: WfpPrice, country: { name: string }): MarcheReleve {
  const produitRaw = (p.commodityName ?? "").toLowerCase();
  const marcheRaw = (p.marketName ?? "").toLowerCase();
  const devise = country.name.includes("Ghana") ? "GHS"
    : country.name.includes("Nigeria") ? "NGN"
    : "XOF";
  const unite = (p.unit ?? "").toLowerCase().includes("kg") ? "kg" : "tonne";
  return {
    origine: "WFP API",
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

      // Strategy 1 : HDX (CSV publics WFP, sans clé) — rotation de 2 pays
      // par run (jour de l'année) pour tenir le budget serverless 60s
      let releves: MarcheReleve[] = [];
      const jour = Math.floor(Date.now() / 86_400_000);
      const paires = [
        HDX_DATASETS[(jour * 2) % HDX_DATASETS.length],
        HDX_DATASETS[(jour * 2 + 1) % HDX_DATASETS.length],
      ];
      for (const dataset of paires) {
        releves.push(...await fetchHdxPrices(dataset));
      }

      // Strategy 2 : WFP VAM API v2 (nécessite désormais une clé — souvent vide)
      if (releves.length === 0) {
        for (const country of WFP_COUNTRIES.slice(0, 3)) {
          const wfpPrices = await fetchWfpPrices(country.alpha2);
          releves.push(...wfpPrices.filter((p) => p.price > 0).map((p) => wfpPriceToReleve(p, country)));
        }
      }

      // Strategy 3: RESIMAO HTML fallback
      if (releves.length === 0) {
        releves = await fetchResimaoHtml();
      }

      for (const releve of releves) {
        let produitCode: string | null = null;
        for (const [key, val] of Object.entries(PRODUIT_MAP)) {
          if (releve.produit.includes(key)) { produitCode = val; break; }
        }
        if (!produitCode) continue;

        let marcheCode: string | null = null;
        const produitMap = MARCHE_PRODUIT_MAP[produitCode] ?? MARCHE_MAP;
        for (const [key, val] of Object.entries(produitMap)) {
          if (releve.marche.includes(key) || releve.pays.toLowerCase().includes(key)) {
            marcheCode = val; break;
          }
        }
        // Fallback : marchés secondaires (Bobo-Dioulasso, Sikasso…) rattachés
        // au marché national — les CSV WFP couvrent bien plus que les capitales
        if (!marcheCode && produitCode === "MAIS_GRAIN") {
          const paysL = releve.pays.toLowerCase();
          const PAYS_MARCHE: Record<string, string> = {
            "burkina": "OUAGA_MAIS", "mali": "BAMAKO_MAIS", "sénégal": "DAKAR_MAIS",
            "senegal": "DAKAR_MAIS", "bénin": "COTONOU_MAIS", "benin": "COTONOU_MAIS",
            "niger": "NIAMEY_MAIS", "ivoire": "ABIDJAN_MAIS", "togo": "LOME_MAIS",
            "ghana": "ACCRA_MAIS", "nigeria": "LAGOS_MAIS",
          };
          for (const [key, val] of Object.entries(PAYS_MARCHE)) {
            if (paysL.includes(key)) { marcheCode = val; break; }
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
              notes: `${releve.origine ?? "RESIMAO"} — ${releve.pays} — ${releve.marche}`,
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
      // 0 nouvel import : ERREUR seulement si on n'a rien pu télécharger ;
      // si des relevés ont été lus mais tous dédupliqués, c'est OK
      const statut = resultat.nbErreurs > 0
        ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR")
        : releves.length === 0 ? "ERREUR" : "OK";
      const messageErreur = statut === "ERREUR" && releves.length === 0
        ? "0 relevés téléchargés — HDX, WFP API et RESIMAO indisponibles"
        : resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null;

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur },
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
