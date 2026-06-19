import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";
import bcrypt from "bcryptjs";
import "dotenv/config";

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL ?? "" });
const prisma = new PrismaClient({ adapter });

async function main() {
  console.log("🌱 Démarrage du seed...");

  // ─── Zones géographiques ─────────────────────────────────────────────────
  const zones = await Promise.all([
    prisma.zone.upsert({
      where: { code: "MONDIAL" },
      update: {},
      create: { code: "MONDIAL", nom: "Mondial", type: "REGION" },
    }),
    prisma.zone.upsert({
      where: { code: "US" },
      update: {},
      create: { code: "US", nom: "États-Unis", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "CI" },
      update: {},
      create: { code: "CI", nom: "Côte d'Ivoire", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "NG" },
      update: {},
      create: { code: "NG", nom: "Nigeria", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "GH" },
      update: {},
      create: { code: "GH", nom: "Ghana", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "CM" },
      update: {},
      create: { code: "CM", nom: "Cameroun", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "UEMOA" },
      update: {},
      create: { code: "UEMOA", nom: "UEMOA", type: "REGION" },
    }),
    prisma.zone.upsert({
      where: { code: "VN" },
      update: {},
      create: { code: "VN", nom: "Vietnam", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "IN" },
      update: {},
      create: { code: "IN", nom: "Inde", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "BF" },
      update: {},
      create: { code: "BF", nom: "Burkina Faso", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "ML" },
      update: {},
      create: { code: "ML", nom: "Mali", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "NE" },
      update: {},
      create: { code: "NE", nom: "Niger", type: "PAYS" },
    }),
    prisma.zone.upsert({
      where: { code: "SN" },
      update: {},
      create: { code: "SN", nom: "Sénégal", type: "PAYS" },
    }),
  ]);

  const zoneMap = Object.fromEntries(zones.map((z) => [z.code, z]));
  console.log(`  ✓ ${zones.length} zones`);

  // ─── Marchés ──────────────────────────────────────────────────────────────
  const marches = await Promise.all([
    prisma.marche.upsert({
      where: { code: "CME_MAIS" },
      update: {},
      create: {
        code: "CME_MAIS",
        nom: "CME/CBOT — Maïs futures",
        zoneId: zoneMap.US.id,
        devise: "USD",
        type: "BOURSE",
        description: "Chicago Board of Trade — contrats futures maïs (ZC)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "CI_MAIS_GROS" },
      update: {},
      create: {
        code: "CI_MAIS_GROS",
        nom: "Abidjan — Maïs gros",
        zoneId: zoneMap.CI.id,
        devise: "XOF",
        type: "GROSSISTE",
        description: "Marché de gros Abidjan (données RESIMAO/FPMA)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "CI_RCN_FOB" },
      update: {},
      create: {
        code: "CI_RCN_FOB",
        nom: "Côte d'Ivoire — RCN FOB",
        zoneId: zoneMap.CI.id,
        devise: "USD",
        type: "FOB",
        description:
          "Prix FOB noix brutes cajou Abidjan (Conseil Coton-Anacarde)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "CI_RCN_BORD_CHAMP" },
      update: {},
      create: {
        code: "CI_RCN_BORD_CHAMP",
        nom: "Côte d'Ivoire — RCN bord-champ",
        zoneId: zoneMap.CI.id,
        devise: "XOF",
        type: "SPOT_DOMESTIQUE",
        description:
          "Prix bord-champ RCN fixé campagne par le Conseil Coton-Anacarde",
      },
    }),
    prisma.marche.upsert({
      where: { code: "VN_AMANDE_W320" },
      update: {},
      create: {
        code: "VN_AMANDE_W320",
        nom: "Vietnam — Amande W320",
        zoneId: zoneMap.VN.id,
        devise: "USD",
        type: "FOB",
        description:
          "Prix FOB amandes cajou W320 Vietnam (sources VINACAS/commerciales)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "NG_COLA_LAGOS" },
      update: {},
      create: {
        code: "NG_COLA_LAGOS",
        nom: "Lagos — Cola (marché gros)",
        zoneId: zoneMap.NG.id,
        devise: "NGN",
        type: "GROSSISTE",
        description:
          "Marché de gros Lagos — noix de cola (données RESIMAO/observatoires)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "CI_COLA_ABIDJAN" },
      update: {},
      create: {
        code: "CI_COLA_ABIDJAN",
        nom: "Abidjan — Cola (marché gros)",
        zoneId: zoneMap.CI.id,
        devise: "XOF",
        type: "GROSSISTE",
        description:
          "Marché de gros Abidjan — noix de cola (données RESIMAO/observatoires)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "MONDIAL_MAIS_WB" },
      update: {},
      create: {
        code: "MONDIAL_MAIS_WB",
        nom: "Prix mondial maïs (Banque Mondiale)",
        zoneId: zoneMap.MONDIAL.id,
        devise: "USD",
        type: "SPOT_DOMESTIQUE",
        description:
          "Prix maïs US (Gulf) — World Bank Commodity Price Data (Pink Sheet)",
      },
    }),
    prisma.marche.upsert({
      where: { code: "MONDE_MAIS_FAO" },
      update: {},
      create: {
        code: "MONDE_MAIS_FAO",
        nom: "Prix mondial maïs (FAO FPMA)",
        zoneId: zoneMap.MONDIAL.id,
        devise: "USD",
        type: "SPOT_DOMESTIQUE",
        description: "Prix maïs mondial — FAO Food Price Monitoring and Analysis",
      },
    }),
    prisma.marche.upsert({
      where: { code: "ABIDJAN_RCN_FAO" },
      update: {},
      create: {
        code: "ABIDJAN_RCN_FAO",
        nom: "Abidjan — RCN cajou (FAO FPMA)",
        zoneId: zoneMap.CI.id,
        devise: "USD",
        type: "FOB",
        description: "Prix RCN cajou Abidjan — FAO FPMA",
      },
    }),
    prisma.marche.upsert({
      where: { code: "ABIDJAN_RCN" },
      update: {},
      create: {
        code: "ABIDJAN_RCN",
        nom: "Abidjan — RCN cajou",
        zoneId: zoneMap.CI.id,
        devise: "XOF",
        type: "SPOT_DOMESTIQUE",
        description: "Prix bord-champ RCN cajou Côte d'Ivoire",
      },
    }),
    prisma.marche.upsert({
      where: { code: "MONDIAL_MAIS_USDA" },
      update: {},
      create: {
        code: "MONDIAL_MAIS_USDA",
        nom: "Prix mondial maïs (USDA FAS)",
        zoneId: zoneMap.MONDIAL.id,
        devise: "USD",
        type: "SPOT_DOMESTIQUE",
        description: "Prix producteur maïs US — USDA FAS PSD Online",
      },
    }),
    // Marchés RESIMAO Afrique de l'Ouest — maïs
    prisma.marche.upsert({
      where: { code: "ABIDJAN_MAIS" },
      update: {},
      create: {
        code: "ABIDJAN_MAIS",
        nom: "Abidjan — Maïs (RESIMAO)",
        zoneId: zoneMap.CI.id,
        devise: "XOF",
        type: "GROSSISTE",
        description: "Prix maïs marché Abidjan — RESIMAO",
      },
    }),
    prisma.marche.upsert({
      where: { code: "LAGOS_MAIS" },
      update: {},
      create: {
        code: "LAGOS_MAIS",
        nom: "Lagos — Maïs (RESIMAO)",
        zoneId: zoneMap.NG.id,
        devise: "NGN",
        type: "GROSSISTE",
        description: "Prix maïs marché Lagos — RESIMAO",
      },
    }),
    prisma.marche.upsert({
      where: { code: "ACCRA_MAIS" },
      update: {},
      create: {
        code: "ACCRA_MAIS",
        nom: "Accra — Maïs (RESIMAO)",
        zoneId: zoneMap.GH.id,
        devise: "GHS",
        type: "GROSSISTE",
        description: "Prix maïs marché Accra — RESIMAO",
      },
    }),
  ]);

  const marcheMap = Object.fromEntries(marches.map((m) => [m.code, m]));
  console.log(`  ✓ ${marches.length} marchés`);

  // ─── Sources ──────────────────────────────────────────────────────────────
  const sources = await Promise.all([
    prisma.source.upsert({
      where: { code: "WORLD_BANK_PINK" },
      update: {},
      create: {
        code: "WORLD_BANK_PINK",
        nom: "World Bank — Commodity Price Data (Pink Sheet)",
        type: "API",
        endpoint:
          "https://api.worldbank.org/v2/en/indicator/PMAIZMMT.USD?downloadformat=csv",
        frequence: "MENSUEL",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC (CC-BY 4.0)",
        description:
          "Prix mensuels des matières premières — source de référence mondiale",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "FAO_FPMA" },
      update: {},
      create: {
        code: "FAO_FPMA",
        nom: "FAO — FPMA (Food Price Monitoring and Analysis)",
        type: "API",
        endpoint: "https://fpma.fao.org/giews/fpma/tool/",
        frequence: "HEBDO",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC",
        description:
          "Prix domestiques et de marché par pays — FAO GIEWS/FPMA",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "USDA_WASDE" },
      update: {},
      create: {
        code: "USDA_WASDE",
        nom: "USDA — WASDE (World Agricultural Supply and Demand Estimates)",
        type: "CSV",
        endpoint: "https://apps.fas.usda.gov/psdonline/app/index.html",
        frequence: "MENSUEL",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC (données gouvernementales US)",
        description:
          "Bilans offre/demande mondiaux maïs et céréales — rapport mensuel USDA",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "CME_FUTURES" },
      update: {},
      create: {
        code: "CME_FUTURES",
        nom: "CME Group — Futures maïs (ZC)",
        type: "API",
        endpoint: "https://www.cmegroup.com/",
        frequence: "QUOTIDIEN",
        fiabiliteDefaut: "OFFICIEL",
        licence:
          "PAYANT — licence temps réel requise (~1 500 USD/mois). Données différées J-10 disponibles via Yahoo Finance (usage non commercial).",
        description:
          "Contrats futures maïs CBOT (ZC) — données temps réel sous licence commerciale",
        actif: false,
      },
    }),
    prisma.source.upsert({
      where: { code: "CONSEIL_ANACARDE_CI" },
      update: {},
      create: {
        code: "CONSEIL_ANACARDE_CI",
        nom: "Conseil Coton et de l'Anacarde — Côte d'Ivoire",
        type: "MANUEL",
        frequence: "MENSUEL",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC (données publiées)",
        description:
          "Prix bord-champ RCN et données de campagne cajou CI — saisie manuelle depuis publications officielles",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "RESIMAO" },
      update: {},
      create: {
        code: "RESIMAO",
        nom: "RESIMAO — Réseau des Systèmes d'Information de Marchés en Afrique de l'Ouest",
        type: "API",
        endpoint: "https://www.resimao.org/",
        frequence: "HEBDO",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC",
        description:
          "Prix marchés domestiques Afrique de l'Ouest — maïs, cola, vivriers",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "MANUEL" },
      update: {},
      create: {
        code: "MANUEL",
        nom: "Saisie manuelle",
        type: "MANUEL",
        frequence: "MANUEL",
        fiabiliteDefaut: "INDICATIF",
        licence: "N/A",
        description: "Données saisies manuellement ou importées via CSV/Excel",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "USDA_FAS_PSD" },
      update: {},
      create: {
        code: "USDA_FAS_PSD",
        nom: "USDA FAS — PSD Online (Production, Supply & Distribution)",
        type: "API",
        endpoint: "https://apps.fas.usda.gov/psdonline/api/",
        frequence: "MENSUEL",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC (données gouvernementales US)",
        description: "Bilans offre/demande maïs mondial — API JSON USDA FAS PSD Online",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "RSS_NEWS_AGRI" },
      update: {},
      create: {
        code: "RSS_NEWS_AGRI",
        nom: "Agrégateur RSS — Actualités agricoles mondiales",
        type: "RSS",
        endpoint: "multiple — FAO, USDA, Reuters, ACP-EU",
        frequence: "QUOTIDIEN",
        fiabiliteDefaut: "INDICATIF",
        licence: "PUBLIC (flux RSS ouverts)",
        description: "Actualités maïs, cajou, cola — flux RSS FAO News, USDA, Reuters Commodities",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "INDEXMUNDI" },
      update: {},
      create: {
        code: "INDEXMUNDI",
        nom: "IndexMundi — Prix historiques commodités",
        type: "API",
        endpoint: "https://www.indexmundi.com/commodities/",
        frequence: "MENSUEL",
        fiabiliteDefaut: "INDICATIF",
        licence: "PUBLIC (données consolidées libres)",
        description: "Séries historiques prix maïs et cajou USD/tonne — 10 ans",
        actif: true,
      },
    }),
    prisma.source.upsert({
      where: { code: "SEED_EXEMPLE" },
      update: {},
      create: {
        code: "SEED_EXEMPLE",
        nom: "Données d'exemple (seed)",
        type: "MANUEL",
        frequence: "MANUEL",
        fiabiliteDefaut: "EXEMPLE",
        licence: "N/A",
        description:
          "⚠️ DONNÉES D'EXEMPLE — ordres de grandeur plausibles pour démonstration uniquement. Ne pas utiliser pour des décisions réelles.",
        actif: true,
      },
    }),
  ]);

  const sourceMap = Object.fromEntries(sources.map((s) => [s.code, s]));
  console.log(`  ✓ ${sources.length} sources`);

  // ─── Filières ─────────────────────────────────────────────────────────────
  const filiereMais = await prisma.filiere.upsert({
    where: { code: "MAIS" },
    update: {},
    create: {
      code: "MAIS",
      nom: "Maïs",
      description:
        "Céréale commodity cotée (CME/CBOT, ticker ZC). Marché international actif avec données abondantes : futures, spot, bilans offre/demande USDA, prix domestiques FAO/RESIMAO.",
    },
  });

  const filiereCajou = await prisma.filiere.upsert({
    where: { code: "CAJOU" },
    update: {},
    create: {
      code: "CAJOU",
      nom: "Noix de cajou (anacarde)",
      description:
        "Marché international actif mais non coté (pas de bourse à terme). Prix indicatifs RCN (noix brute) et amandes (W320, W240…). Données partielles, souvent commerciales. Principaux exportateurs Afrique (CI, Tanzanie, Mozambique) vers Vietnam/Inde.",
    },
  });

  const filiereCola = await prisma.filiere.upsert({
    where: { code: "COLA" },
    update: {},
    create: {
      code: "COLA",
      nom: "Noix de cola",
      description:
        "Marché essentiellement régional (Afrique de l'Ouest + diaspora). Pas de référence mondiale cotée. Données : prix de marchés régionaux, volumes nationaux, flux transfrontaliers via RESIMAO/observatoires nationaux.",
    },
  });

  console.log("  ✓ 3 filières (MAIS, CAJOU, COLA)");

  // ─── Produits — Maïs ─────────────────────────────────────────────────────
  const maisGrain = await prisma.produit.upsert({
    where: { code: "MAIS_GRAIN" },
    update: {},
    create: {
      filiereId: filiereMais.id,
      code: "MAIS_GRAIN",
      nom: "Maïs grain",
      estDerive: false,
      uniteRef: "tonne",
      descriptionQualite: "Maïs jaune US Grade #2 (référence CME/CBOT)",
      saisonnalite: {
        US: { debut: "septembre", fin: "octobre", note: "récolte principale" },
        CI: {
          debut: "août",
          fin: "septembre",
          note: "grande saison (sud CI)",
        },
        UEMOA: {
          debut: "septembre",
          fin: "novembre",
          note: "saison principale",
        },
      },
      chaineDValeur: {
        etapes: [
          "Production agricole",
          "Collecte / séchage",
          "Stockage",
          "Transformation (mouture, amidonnerie…)",
          "Distribution nationale",
          "Export (FOB / CIF)",
        ],
      },
      cadreReglementaire:
        "USDA (normes qualité US) ; Codex Alimentarius ; réglementations phytosanitaires UE/pays importateurs ; UEMOA (TEC, taxes communautaires)",
      acteurs:
        "Producteurs agricoles, collecteurs/commerçants, transformateurs (meuniers, amidonneries), négociants céréaliers, exportateurs, offices publics (ONASA en CI…)",
    },
  });

  const maisDerivesData = [
    {
      code: "MAIS_FARINE",
      nom: "Farine de maïs",
      descriptionQualite: "Farine blanche ou jaune, différents calibres",
      uniteRef: "tonne",
    },
    {
      code: "MAIS_SEMOULE",
      nom: "Semoule de maïs (gritz)",
      descriptionQualite: "Gritz brassicoles ou alimentaires",
      uniteRef: "tonne",
    },
    {
      code: "MAIS_AMIDON",
      nom: "Amidon de maïs",
      descriptionQualite: "Amidon natif ou modifié",
      uniteRef: "tonne",
    },
    {
      code: "MAIS_GLUTEN",
      nom: "Gluten feed / Corn Gluten Meal",
      descriptionQualite: "Co-produit amidonnerie, aliment bétail",
      uniteRef: "tonne",
    },
    {
      code: "MAIS_ALIM_BETAIL",
      nom: "Aliment bétail (base maïs)",
      descriptionQualite: "Composé maïs + soja + minéraux",
      uniteRef: "tonne",
    },
    {
      code: "MAIS_ETHANOL",
      nom: "Éthanol (maïs)",
      descriptionQualite: "Bioéthanol carburant ou industriel",
      uniteRef: "litre",
    },
    {
      code: "MAIS_HUILE",
      nom: "Huile de maïs",
      descriptionQualite: "Huile alimentaire raffinée",
      uniteRef: "litre",
    },
  ];

  for (const d of maisDerivesData) {
    await prisma.produit.upsert({
      where: { code: d.code },
      update: {},
      create: {
        filiereId: filiereMais.id,
        parentId: maisGrain.id,
        estDerive: true,
        ...d,
      },
    });
  }
  console.log(`  ✓ Maïs : 1 produit principal + ${maisDerivesData.length} dérivés`);

  // ─── Produits — Cajou ─────────────────────────────────────────────────────
  const cajouRCN = await prisma.produit.upsert({
    where: { code: "CAJOU_RCN" },
    update: {},
    create: {
      filiereId: filiereCajou.id,
      code: "CAJOU_RCN",
      nom: "Noix de cajou brute (RCN — Raw Cashew Nut)",
      estDerive: false,
      uniteRef: "tonne",
      descriptionQualite:
        "RCN : noix brute non décortiquée. Qualité évaluée en Out-Turn Rate (OTR, kg amandes/tonne RCN). Standard CI : OTR ≥ 48 lbs/80 kg sac.",
      saisonnalite: {
        CI: {
          debut: "mars",
          fin: "juin",
          note: "campagne principale mars-juin ; ouverture officielle mars",
        },
        GH: { debut: "mars", fin: "mai" },
        TZ: { debut: "janvier", fin: "mars", note: "Tanzania" },
        VN: { debut: "mars", fin: "mai", note: "production locale faible" },
      },
      chaineDValeur: {
        etapes: [
          "Production (vergers anacardiers)",
          "Collecte bord-champ",
          "Achat pisteurs / commerçants",
          "Collecte centres agréés",
          "Export RCN (FOB) → Vietnam, Inde principaux acheteurs",
          "Transformation locale (décorticage, séchage, calibrage)",
          "Export amandes (W320, W240, etc.)",
        ],
      },
      cadreReglementaire:
        "Conseil du Coton et de l'Anacarde (CI) : fixation prix bord-champ, agrément exportateurs, barème de prélèvements. Normes qualité : Codex Alimentarius, réglementations phytosanitaires UE/US.",
      acteurs:
        "Producteurs (petits exploitants 90%+), pisteurs/collecteurs, acheteurs agréés, exportateurs RCN, transformateurs locaux (unités de décorticage), importateurs Vietnam/Inde",
    },
  });

  const cajouDerivesData = [
    {
      code: "CAJOU_W320",
      nom: "Amande cajou W320",
      descriptionQualite:
        "320 amandes entières blanches par livre — calibre standard le plus échangé mondialement",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_W240",
      nom: "Amande cajou W240",
      descriptionQualite:
        "240 amandes/lb — calibre premium, prix plus élevé que W320",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_W180",
      nom: "Amande cajou W180 (Jumbo)",
      descriptionQualite: "180 amandes/lb — grand calibre premium",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_WW450",
      nom: "Amande cajou WW450",
      descriptionQualite: "Entières blanchies, petites — calibre économique",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_BRISURES",
      nom: "Brisures d'amande cajou (LWP/SWP/BB)",
      descriptionQualite:
        "Demi-amandes (LWP), quarts (SWP) et brisures (BB) — coproduits transformation",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_CNSL",
      nom: "Huile de coque cajou (CNSL)",
      descriptionQualite:
        "Cashew Nut Shell Liquid — usage industriel (résines, friction, peintures)",
      uniteRef: "tonne",
    },
    {
      code: "CAJOU_POMME_JUS",
      nom: "Jus / Sirop de pomme de cajou",
      descriptionQualite:
        "Coproduit transformation — fruit du cajou (faible valorisation actuelle en Afrique)",
      uniteRef: "litre",
    },
  ];

  for (const d of cajouDerivesData) {
    await prisma.produit.upsert({
      where: { code: d.code },
      update: {},
      create: {
        filiereId: filiereCajou.id,
        parentId: cajouRCN.id,
        estDerive: true,
        ...d,
      },
    });
  }
  console.log(`  ✓ Cajou : 1 produit principal + ${cajouDerivesData.length} dérivés`);

  // ─── Produits — Cola ──────────────────────────────────────────────────────
  const colaNoix = await prisma.produit.upsert({
    where: { code: "COLA_NOIX" },
    update: {},
    create: {
      filiereId: filiereCola.id,
      code: "COLA_NOIX",
      nom: "Noix de cola fraîche",
      estDerive: false,
      uniteRef: "kg",
      descriptionQualite:
        "Principalement Kola nitida (cola blanche/rouge, 2 cotylédons) et Kola acuminata. Évaluée sur fraîcheur, couleur, absence de moisissures. Marché essentiellement régional Afrique de l'Ouest.",
      saisonnalite: {
        CI: {
          debut: "octobre",
          fin: "janvier",
          note: "principale récolte ; petite saison juillet-août",
        },
        GH: { debut: "novembre", fin: "janvier" },
        NG: { debut: "octobre", fin: "décembre", note: "principal marché de consommation" },
      },
      chaineDValeur: {
        etapes: [
          "Production (arbres kolatiers, zones forestières)",
          "Collecte bord-champ",
          "Commerçantes grossistes locales (rôle central)",
          "Transport vers marchés urbains / zones Sahel",
          "Exportation informelle transfrontalière (NG, BF, MLI, SN…)",
          "Vente au détail / usage cérémoniel et social",
        ],
        note: "Marché majoritairement informel, flux transfrontaliers importants non comptabilisés dans statistiques officielles",
      },
      cadreReglementaire:
        "Réglementations phytosanitaires nationales. Classement CITES non applicable. Fiscalité informelle aux frontières. Pas de standard international unifié.",
      acteurs:
        "Producteurs (petits agriculteurs zones forestières CI/GH), collectrices villageoises, grossistes (souvent femmes), transporteurs, revendeurs urbains, exportateurs informels vers zone Sahel/Nigeria",
    },
  });

  const colaDerivesData = [
    {
      code: "COLA_SECHE",
      nom: "Cola séchée",
      descriptionQualite:
        "Noix séchée — meilleure conservation, perd arôme mais valorisable à distance",
      uniteRef: "kg",
    },
    {
      code: "COLA_PATE",
      nom: "Pâte de cola",
      descriptionQualite:
        "Broyage humide — usage traditionnel et artisanal ; base extraits",
      uniteRef: "kg",
    },
    {
      code: "COLA_EXTRAIT",
      nom: "Extrait de cola",
      descriptionQualite:
        "Extrait standardisé en caféine/théobromine — usage agroalimentaire (boissons) et pharmaceutique",
      uniteRef: "kg",
    },
    {
      code: "COLA_POUDRE",
      nom: "Poudre de cola",
      descriptionQualite:
        "Cola lyophilisée ou séchée-moulue — usage compléments alimentaires",
      uniteRef: "kg",
    },
  ];

  for (const d of colaDerivesData) {
    await prisma.produit.upsert({
      where: { code: d.code },
      update: {},
      create: {
        filiereId: filiereCola.id,
        parentId: colaNoix.id,
        estDerive: true,
        ...d,
      },
    });
  }
  console.log(`  ✓ Cola : 1 produit principal + ${colaDerivesData.length} dérivés`);

  // ─── Taux de change de référence ─────────────────────────────────────────
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  await prisma.tauxChange.upsert({
    where: {
      deviseSrc_deviseDest_dateReleve_sourceCode: {
        deviseSrc: "EUR",
        deviseDest: "XOF",
        dateReleve: today,
        sourceCode: "FIXE_LEGAL",
      },
    },
    update: {},
    create: {
      deviseSrc: "EUR",
      deviseDest: "XOF",
      taux: 655.957,
      dateReleve: today,
      sourceCode: "FIXE_LEGAL",
    },
  });

  await prisma.tauxChange.upsert({
    where: {
      deviseSrc_deviseDest_dateReleve_sourceCode: {
        deviseSrc: "XOF",
        deviseDest: "EUR",
        dateReleve: today,
        sourceCode: "FIXE_LEGAL",
      },
    },
    update: {},
    create: {
      deviseSrc: "XOF",
      deviseDest: "EUR",
      taux: 1 / 655.957,
      dateReleve: today,
      sourceCode: "FIXE_LEGAL",
    },
  });

  console.log("  ✓ Taux de change EUR/XOF (fixe légal)");

  // ─── Prix d'exemple ⚠️ ──────────────────────────────────────────────────
  const seedSource = sourceMap.SEED_EXEMPLE;
  const note = "⚠️ DONNÉES D'EXEMPLE — ordre de grandeur plausible uniquement";

  const prixExemples = [
    // Maïs CME (approx. niveaux 2024, USD/boisseau)
    {
      produit: maisGrain,
      marche: marcheMap.CME_MAIS,
      typePrix: "FUTURE",
      valeur: 4.45,
      devise: "USD",
      unite: "bushel",
      echeance: "2025-03",
      dateReleve: new Date("2025-01-15"),
    },
    {
      produit: maisGrain,
      marche: marcheMap.CME_MAIS,
      typePrix: "FUTURE",
      valeur: 4.58,
      devise: "USD",
      unite: "bushel",
      echeance: "2025-07",
      dateReleve: new Date("2025-01-15"),
    },
    {
      produit: maisGrain,
      marche: marcheMap.CME_MAIS,
      typePrix: "FUTURE",
      valeur: 4.72,
      devise: "USD",
      unite: "bushel",
      echeance: "2025-12",
      dateReleve: new Date("2025-01-15"),
    },
    // Maïs World Bank mensuel (USD/tonne)
    {
      produit: maisGrain,
      marche: marcheMap.MONDIAL_MAIS_WB,
      typePrix: "SPOT",
      valeur: 175.2,
      devise: "USD",
      unite: "tonne",
      dateReleve: new Date("2024-11-01"),
    },
    {
      produit: maisGrain,
      marche: marcheMap.MONDIAL_MAIS_WB,
      typePrix: "SPOT",
      valeur: 168.5,
      devise: "USD",
      unite: "tonne",
      dateReleve: new Date("2024-12-01"),
    },
    // Maïs Abidjan (XOF/kg)
    {
      produit: maisGrain,
      marche: marcheMap.CI_MAIS_GROS,
      typePrix: "GROS",
      valeur: 140,
      devise: "XOF",
      unite: "kg",
      dateReleve: new Date("2025-01-10"),
    },
    // RCN CI bord-champ (XOF/kg)
    {
      produit: cajouRCN,
      marche: marcheMap.CI_RCN_BORD_CHAMP,
      typePrix: "BORD_CHAMP",
      valeur: 350,
      devise: "XOF",
      unite: "kg",
      dateReleve: new Date("2024-04-01"),
    },
    // RCN CI FOB (USD/tonne)
    {
      produit: cajouRCN,
      marche: marcheMap.CI_RCN_FOB,
      typePrix: "FOB",
      valeur: 1050,
      devise: "USD",
      unite: "tonne",
      dateReleve: new Date("2024-04-01"),
    },
    // Amande W320 Vietnam FOB (USD/tonne)
    {
      produit: await prisma.produit.findUnique({ where: { code: "CAJOU_W320" } }),
      marche: marcheMap.VN_AMANDE_W320,
      typePrix: "FOB",
      valeur: 6800,
      devise: "USD",
      unite: "tonne",
      dateReleve: new Date("2025-01-10"),
    },
    // Cola Lagos grossiste (NGN/kg)
    {
      produit: colaNoix,
      marche: marcheMap.NG_COLA_LAGOS,
      typePrix: "GROS",
      valeur: 2800,
      devise: "NGN",
      unite: "kg",
      dateReleve: new Date("2025-01-10"),
    },
    // Cola Abidjan grossiste (XOF/kg)
    {
      produit: colaNoix,
      marche: marcheMap.CI_COLA_ABIDJAN,
      typePrix: "GROS",
      valeur: 900,
      devise: "XOF",
      unite: "kg",
      dateReleve: new Date("2025-01-10"),
    },
  ];

  for (const p of prixExemples) {
    if (!p.produit) continue;
    await prisma.prixReleve.create({
      data: {
        produitId: p.produit.id,
        marcheId: p.marche.id,
        sourceId: seedSource.id,
        typePrix: p.typePrix,
        echeance: p.echeance ?? null,
        valeur: p.valeur,
        devise: p.devise,
        unite: p.unite,
        dateReleve: p.dateReleve,
        fiabilite: "EXEMPLE",
        notes: note,
      },
    });
  }
  console.log(`  ✓ ${prixExemples.length} relevés de prix d'exemple`);

  // ─── Structures de coûts d'exemple ⚠️ ───────────────────────────────────
  const coutsExemples = [
    // Cajou RCN CI — structure coût transformation locale
    {
      produit: cajouRCN,
      maillon: "TRANSFORMATION",
      poste: "matiere_premiere_rcn",
      montant: 1050,
      devise: "USD",
      unite: "par_tonne_rcn",
      periode: "2024-2025",
    },
    {
      produit: cajouRCN,
      maillon: "TRANSFORMATION",
      poste: "main_oeuvre",
      montant: 85,
      devise: "USD",
      unite: "par_tonne_rcn",
      periode: "2024-2025",
    },
    {
      produit: cajouRCN,
      maillon: "TRANSFORMATION",
      poste: "energie",
      montant: 45,
      devise: "USD",
      unite: "par_tonne_rcn",
      periode: "2024-2025",
    },
    {
      produit: cajouRCN,
      maillon: "TRANSFORMATION",
      poste: "emballage_logistique",
      montant: 30,
      devise: "USD",
      unite: "par_tonne_rcn",
      periode: "2024-2025",
    },
    // Maïs CI — structure collecte
    {
      produit: maisGrain,
      maillon: "COLLECTE",
      poste: "achat_bord_champ",
      montant: 115,
      devise: "XOF",
      unite: "par_kg",
      periode: "2024-2025",
    },
    {
      produit: maisGrain,
      maillon: "COLLECTE",
      poste: "transport_vers_marche",
      montant: 12,
      devise: "XOF",
      unite: "par_kg",
      periode: "2024-2025",
    },
    {
      produit: maisGrain,
      maillon: "COLLECTE",
      poste: "pertes_sechage_stockage",
      montant: 8,
      devise: "XOF",
      unite: "par_kg",
      periode: "2024-2025",
    },
  ];

  for (const c of coutsExemples) {
    await prisma.structureCout.create({
      data: {
        produitId: c.produit.id,
        sourceId: seedSource.id,
        maillon: c.maillon,
        poste: c.poste,
        montant: c.montant,
        devise: c.devise,
        unite: c.unite,
        periode: c.periode,
        fiabilite: "EXEMPLE",
        notes: note,
      },
    });
  }
  console.log(`  ✓ ${coutsExemples.length} postes de coûts d'exemple`);

  // ─── Actualités d'exemple ─────────────────────────────────────────────────
  const actualites = [
    {
      filiereId: filiereCajou.id,
      titre: "Côte d'Ivoire : ouverture de la campagne anacarde 2025 fixée au 1er mars",
      lien: "https://exemple.com/actu-cajou-ci-2025",
      source: "Conseil Coton et de l'Anacarde (CI) — communiqué officiel",
      resume:
        "Le prix bord-champ du RCN est fixé à 350 FCFA/kg pour la campagne 2025. L'objectif de production est de 1,2 million de tonnes.",
      datePublication: new Date("2025-02-15"),
    },
    {
      filiereId: filiereMais.id,
      titre: "USDA WASDE Janvier 2025 : production mondiale maïs revue en hausse",
      lien: "https://exemple.com/wasde-jan-2025",
      source: "USDA — World Agricultural Supply and Demand Estimates",
      resume:
        "La production mondiale de maïs 2024/25 est estimée à 1 228 Mt (+8 Mt vs. décembre). Stocks finaux en légère hausse.",
      datePublication: new Date("2025-01-10"),
    },
    {
      filiereId: filiereCola.id,
      titre: "Nigeria : hausse des prix de la noix de cola liée à la dépréciation du naira",
      lien: "https://exemple.com/cola-nigeria-naira",
      source: "RESIMAO — Bulletin mensuel marchés Afrique de l'Ouest",
      resume:
        "Les prix du kola à Lagos ont augmenté de 15 % en glissement annuel en termes nominaux, mais sont stables en USD en raison de la dépréciation du naira.",
      datePublication: new Date("2025-01-20"),
    },
  ];

  for (const a of actualites) {
    await prisma.actualite.create({ data: a });
  }
  console.log(`  ✓ ${actualites.length} actualités d'exemple`);

  // ─── Utilisateur admin ────────────────────────────────────────────────────
  const hashedPwd = await bcrypt.hash("admin123!", 12);
  await prisma.user.upsert({
    where: { email: "admin@terminal-agri.local" },
    update: {},
    create: {
      email: "admin@terminal-agri.local",
      nom: "Administrateur",
      motDePasse: hashedPwd,
      role: "ADMIN",
    },
  });
  console.log("  ✓ Utilisateur admin (admin@terminal-agri.local / admin123!)");

  console.log("\n✅ Seed terminé avec succès !");
  console.log(
    "⚠️  Les données de prix et coûts sont des EXEMPLES — ne pas utiliser pour des décisions réelles."
  );
}

main()
  .catch((e) => {
    console.error("❌ Erreur seed :", e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
