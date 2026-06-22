import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";

const SOURCES_INIT = [
  { code: "WORLD_BANK_PINK",     nom: "World Bank — Pink Sheet",                        type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",   description: "Prix mensuels des matières premières — source de référence mondiale" },
  { code: "FAO_FPMA",            nom: "FAO — FPMA Food Price Monitoring",               type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "HEBDO",     description: "Prix alimentaires en Afrique de l'Ouest — FAO FPMA Tool" },
  { code: "USDA_FAS_PSD",        nom: "IMF — Primary Commodity Prices (maïs mondial)",  type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",   description: "IMF Primary Commodity Prices — maïs mondial" },
  { code: "CONSEIL_ANACARDE_CI", nom: "Conseil Anacarde CI — Prix bord-champ",          type: "HTML", fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN", description: "Prix bord-champ RCN Côte d'Ivoire via FAOSTAT" },
  { code: "RESIMAO",             nom: "RESIMAO — Systèmes d'Information des Marchés",   type: "HTML", fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "Prix collectés sur les marchés de détail et de gros en Afrique de l'Ouest" },
  { code: "INDEXMUNDI",          nom: "IndexMundi — Commodity Prices",                  type: "HTML", fiabiliteDefaut: "INDICATIF", frequence: "HEBDO",     description: "Prix historiques commodités — maïs, cajou" },
  { code: "RSS_NEWS_AGRI",       nom: "Agrégateur RSS — Actualités agricoles",          type: "RSS",  fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "15 flux RSS — FAO, USDA, World Bank, Africa Report…" },
  { code: "TAUX_CHANGE_LIVE",    nom: "Taux de change live — USD/XOF, EUR/USD",        type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN", description: "Taux de change USD/XOF, EUR/USD — ECB via open.er-api.com" },
];

const FILIERES_INIT = [
  { code: "MAIS",  nom: "Maïs",         description: "Filière maïs — commodity internationale (CBOT/CME)" },
  { code: "CAJOU", nom: "Cajou",        description: "Filière cajou/anacarde — Côte d'Ivoire & Afrique de l'Ouest" },
  { code: "COLA",  nom: "Noix de Cola", description: "Filière noix de cola — marché régional AOF" },
];

const ZONES_INIT = [
  { code: "MONDIAL",      nom: "Marché mondial",              type: "REGION" },
  { code: "AFRIQUE_OUEST", nom: "Afrique de l'Ouest",         type: "REGION" },
  { code: "COTE_IVOIRE",  nom: "Côte d'Ivoire",               type: "PAYS" },
  { code: "BURKINA",      nom: "Burkina Faso",                 type: "PAYS" },
  { code: "MALI",         nom: "Mali",                         type: "PAYS" },
  { code: "SENEGAL",      nom: "Sénégal",                      type: "PAYS" },
  { code: "BENIN",        nom: "Bénin",                        type: "PAYS" },
  { code: "TOGO",         nom: "Togo",                         type: "PAYS" },
  { code: "GHANA",        nom: "Ghana",                        type: "PAYS" },
  { code: "NIGERIA",      nom: "Nigeria",                      type: "PAYS" },
  { code: "NIGER",        nom: "Niger",                        type: "PAYS" },
];

// Marchés requis par les connecteurs (zoneCode référencé)
const MARCHES_INIT = [
  { code: "MONDIAL_MAIS_WB",    nom: "Marché mondial maïs (World Bank)",  zoneCode: "MONDIAL",       devise: "USD", type: "BOURSE" },
  { code: "MONDE_MAIS_FAO",     nom: "Marché mondial maïs (FAO)",         zoneCode: "MONDIAL",       devise: "USD", type: "BOURSE" },
  { code: "MONDIAL_MAIS_USDA",  nom: "Marché mondial maïs (IMF/USDA)",    zoneCode: "MONDIAL",       devise: "USD", type: "BOURSE" },
  { code: "ABIDJAN_RCN",        nom: "Abidjan — Cajou RCN",               zoneCode: "COTE_IVOIRE",   devise: "XOF", type: "FOB" },
  { code: "ABIDJAN_MAIS",       nom: "Abidjan — Maïs",                    zoneCode: "COTE_IVOIRE",   devise: "XOF", type: "GROSSISTE" },
  { code: "OUAGA_MAIS",         nom: "Ouagadougou — Maïs",                zoneCode: "BURKINA",       devise: "XOF", type: "GROSSISTE" },
  { code: "BAMAKO_MAIS",        nom: "Bamako — Maïs",                     zoneCode: "MALI",          devise: "XOF", type: "GROSSISTE" },
  { code: "DAKAR_MAIS",         nom: "Dakar — Maïs",                      zoneCode: "SENEGAL",       devise: "XOF", type: "GROSSISTE" },
  { code: "COTONOU_MAIS",       nom: "Cotonou — Maïs",                    zoneCode: "BENIN",         devise: "XOF", type: "GROSSISTE" },
  { code: "LOME_MAIS",          nom: "Lomé — Maïs",                       zoneCode: "TOGO",          devise: "XOF", type: "GROSSISTE" },
  { code: "ACCRA_MAIS",         nom: "Accra — Maïs",                      zoneCode: "GHANA",         devise: "GHS", type: "GROSSISTE" },
  { code: "LAGOS_MAIS",         nom: "Lagos — Maïs",                      zoneCode: "NIGERIA",       devise: "NGN", type: "GROSSISTE" },
  { code: "NIAMEY_MAIS",        nom: "Niamey — Maïs",                     zoneCode: "NIGER",         devise: "XOF", type: "GROSSISTE" },
];

// Produits requis par les connecteurs (filiereCode référencé)
const PRODUITS_INIT = [
  { code: "MAIS_GRAIN",  nom: "Maïs grain",        filiereCode: "MAIS",  uniteRef: "tonne", estDerive: false, description: "Maïs grain sec — prix CBOT/CME et marchés AOF" },
  { code: "CAJOU_RCN",   nom: "Cajou RCN",          filiereCode: "CAJOU", uniteRef: "tonne", estDerive: false, description: "Noix de cajou brute (Raw Cashew Nut) — bord-champ CI" },
  { code: "COLA_ROUGE",  nom: "Noix de cola rouge", filiereCode: "COLA",  uniteRef: "kg",    estDerive: false, description: "Noix de cola rouge (Cola nitida) — marché régional AOF" },
];

async function upsertByCode<T extends { code: string }>(
  label: string,
  items: T[],
  finder: (code: string) => Promise<unknown>,
  creator: (item: T) => Promise<unknown>,
  created: string[],
  existing: string[],
  errors: string[],
) {
  for (const item of items) {
    try {
      const exists = await finder(item.code);
      if (!exists) {
        await creator(item);
        created.push(`${label}: ${item.code}`);
      } else {
        existing.push(`${label}: ${item.code}`);
      }
    } catch (e) {
      errors.push(`${label} ${item.code}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }
}

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("authorization");
  const adminKey = process.env.ADMIN_SECRET ?? process.env.CRON_SECRET;
  if (adminKey && authHeader !== `Bearer ${adminKey}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const created: string[] = [];
  const existing: string[] = [];
  const errors: string[] = [];

  // 1. Filières
  await upsertByCode("Filière", FILIERES_INIT,
    (code) => prisma.filiere.findUnique({ where: { code } }),
    (f) => prisma.filiere.create({ data: f }),
    created, existing, errors,
  );

  // 2. Sources
  await upsertByCode("Source", SOURCES_INIT,
    (code) => prisma.source.findUnique({ where: { code } }),
    (s) => prisma.source.create({ data: { ...s, actif: true, statutDernier: "INCONNU" } }),
    created, existing, errors,
  );

  // 3. Zones
  await upsertByCode("Zone", ZONES_INIT,
    (code) => prisma.zone.findUnique({ where: { code } }),
    (z) => prisma.zone.create({ data: z }),
    created, existing, errors,
  );

  // 4. Produits (nécessite filière existante)
  for (const p of PRODUITS_INIT) {
    try {
      const exists = await prisma.produit.findUnique({ where: { code: p.code } });
      if (!exists) {
        const filiere = await prisma.filiere.findUnique({ where: { code: p.filiereCode } });
        if (!filiere) { errors.push(`Produit ${p.code}: filière ${p.filiereCode} introuvable`); continue; }
        await prisma.produit.create({
          data: {
            code: p.code, nom: p.nom, uniteRef: p.uniteRef,
            estDerive: p.estDerive, descriptionQualite: p.description,
            filiereId: filiere.id,
          },
        });
        created.push(`Produit: ${p.code}`);
      } else {
        existing.push(`Produit: ${p.code}`);
      }
    } catch (e) {
      errors.push(`Produit ${p.code}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // 5. Marchés (nécessite zone existante)
  for (const m of MARCHES_INIT) {
    try {
      const exists = await prisma.marche.findUnique({ where: { code: m.code } });
      if (!exists) {
        const zone = await prisma.zone.findUnique({ where: { code: m.zoneCode } });
        if (!zone) { errors.push(`Marché ${m.code}: zone ${m.zoneCode} introuvable`); continue; }
        await prisma.marche.create({
          data: { code: m.code, nom: m.nom, zoneId: zone.id, devise: m.devise, type: m.type, actif: true },
        });
        created.push(`Marché: ${m.code}`);
      } else {
        existing.push(`Marché: ${m.code}`);
      }
    } catch (e) {
      errors.push(`Marché ${m.code}: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  return Response.json({
    ok: errors.length === 0,
    created, existing, errors,
    summary: `${created.length} créés, ${existing.length} existants, ${errors.length} erreurs`,
  });
}

export async function GET() {
  const [filieres, sources, produits, marches] = await Promise.all([
    prisma.filiere.count(),
    prisma.source.count(),
    prisma.produit.count(),
    prisma.marche.count(),
  ]);
  const pret = filieres >= 3 && sources >= 8 && produits >= 3 && marches >= 5;
  return Response.json({
    filieres, sources, produits, marches, pret,
    message: pret
      ? "BDD initialisée — prête pour la collecte"
      : "BDD non initialisée — appeler POST /api/init",
  });
}
