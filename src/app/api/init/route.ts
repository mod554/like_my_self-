// POST /api/init — initialise les enregistrements Source et Filière nécessaires
// À appeler UNE FOIS après le premier déploiement

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

const SOURCES_INIT = [
  { code: "WORLD_BANK_PINK",      nom: "World Bank — Pink Sheet",                   type: "API",   fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",    description: "Prix mensuels des matières premières — source de référence mondiale" },
  { code: "FAO_FPMA",             nom: "FAO — FPMA Food Price Monitoring",          type: "API",   fiabiliteDefaut: "OFFICIEL",  frequence: "HEBDO",      description: "Prix alimentaires en Afrique de l'Ouest — FAO FPMA Tool" },
  { code: "USDA_FAS",             nom: "USDA — Foreign Agricultural Service",       type: "API",   fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",    description: "Données WASDE, PSD — production, consommation, commerce mondiale" },
  { code: "CONSEIL_ANACARDE_CI",  nom: "Conseil Anacarde CI — Prix bord-champ",     type: "HTML",  fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN",  description: "Prix bord-champ RCN Côte d'Ivoire fixés par le Conseil du Coton et de l'Anacarde" },
  { code: "RESIMAO",              nom: "RESIMAO — Systèmes d'Information des Marchés AOF", type: "HTML", fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "Prix collectés sur les marchés de détail et de gros en Afrique de l'Ouest" },
  { code: "INDEXMUNDI",           nom: "IndexMundi — Commodity Prices",             type: "HTML",  fiabiliteDefaut: "INDICATIF", frequence: "HEBDO",      description: "Prix historiques commodités — maïs, cajou, noix de cola" },
  { code: "RSS_NEWS_AGRI",        nom: "Agrégateur RSS — Actualités agricoles",     type: "RSS",   fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN",  description: "15 flux RSS — FAO, USDA, World Bank, Africa Report, Jeune Afrique…" },
  { code: "TAUX_CHANGE_LIVE",     nom: "Taux de change live — USD/XOF, EUR/USD",   type: "API",   fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN",  description: "Taux de change USD/XOF, EUR/USD, USD/NGN — ECB via open.er-api.com" },
];

const FILIERES_INIT = [
  { code: "MAIS",  nom: "Maïs",         description: "Filière maïs — commodity internationale (CBOT/CME)" },
  { code: "CAJOU", nom: "Cajou",        description: "Filière cajou/anacarde — Côte d'Ivoire & Afrique de l'Ouest" },
  { code: "COLA",  nom: "Noix de Cola", description: "Filière noix de cola — marché régional AOF" },
];

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("authorization");
  const adminKey = process.env.ADMIN_SECRET ?? process.env.CRON_SECRET;
  if (adminKey && authHeader !== `Bearer ${adminKey}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const created: string[] = [];
  const existing: string[] = [];
  const errors: string[] = [];

  for (const f of FILIERES_INIT) {
    try {
      const exists = await prisma.filiere.findUnique({ where: { code: f.code } });
      if (!exists) {
        await prisma.filiere.create({ data: f });
        created.push(`Filière: ${f.code}`);
      } else {
        existing.push(`Filière: ${f.code}`);
      }
    } catch (e) {
      errors.push(`Filière ${f.code}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  for (const s of SOURCES_INIT) {
    try {
      const exists = await prisma.source.findUnique({ where: { code: s.code } });
      if (!exists) {
        await prisma.source.create({
          data: {
            code: s.code,
            nom: s.nom,
            type: s.type,
            fiabiliteDefaut: s.fiabiliteDefaut,
            frequence: s.frequence,
            description: s.description,
            actif: true,
            statutDernier: "INCONNU",
          },
        });
        created.push(`Source: ${s.code}`);
      } else {
        existing.push(`Source: ${s.code}`);
      }
    } catch (e) {
      errors.push(`Source ${s.code}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return Response.json({
    ok: errors.length === 0,
    created,
    existing,
    errors,
    summary: `${created.length} créés, ${existing.length} existants, ${errors.length} erreurs`,
  });
}

export async function GET() {
  const [filieres, sources] = await Promise.all([
    prisma.filiere.count(),
    prisma.source.count(),
  ]);
  return Response.json({
    filieres,
    sources,
    pret: filieres >= 3 && sources >= 8,
    message: filieres >= 3 && sources >= 8
      ? "BDD initialisée — prête pour la collecte"
      : "BDD non initialisée — appeler POST /api/init",
  });
}
