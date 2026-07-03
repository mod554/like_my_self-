// Shared setup logic — idempotent migrate + seed
// $executeRawUnsafe via @prisma/adapter-pg uses extended query protocol (one statement only),
// so we must run each DDL statement individually.
//
// For Supabase: set DIRECT_URL to the direct connection (port 5432) for DDL operations.
// DATABASE_URL can be the transaction pooler (port 6543) for regular queries.

import { prisma } from "./db";
import { Client as PgClient } from "pg";

const DDL_STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS "Filiere" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "description" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Filiere_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Filiere_code_key" ON "Filiere"("code")`,

  `CREATE TABLE IF NOT EXISTS "Zone" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    CONSTRAINT "Zone_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Zone_code_key" ON "Zone"("code")`,

  `CREATE TABLE IF NOT EXISTS "Source" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "endpoint" TEXT,
    "frequence" TEXT,
    "fiabiliteDefaut" TEXT NOT NULL,
    "licence" TEXT,
    "description" TEXT,
    "derniereExecution" TIMESTAMP(3),
    "statutDernier" TEXT,
    "messageErreur" TEXT,
    "actif" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Source_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Source_code_key" ON "Source"("code")`,

  `CREATE TABLE IF NOT EXISTS "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "motDePasse" TEXT NOT NULL,
    "role" TEXT NOT NULL DEFAULT 'LECTEUR',
    "actif" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "User_email_key" ON "User"("email")`,

  `CREATE TABLE IF NOT EXISTS "Produit" (
    "id" TEXT NOT NULL,
    "filiereId" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "estDerive" BOOLEAN NOT NULL DEFAULT false,
    "parentId" TEXT,
    "uniteRef" TEXT NOT NULL,
    "descriptionQualite" TEXT,
    "saisonnalite" JSONB,
    "chaineDValeur" JSONB,
    "cadreReglementaire" TEXT,
    "acteurs" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Produit_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Produit_code_key" ON "Produit"("code")`,
  `CREATE INDEX IF NOT EXISTS "Produit_filiereId_idx" ON "Produit"("filiereId")`,

  `CREATE TABLE IF NOT EXISTS "Marche" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "nom" TEXT NOT NULL,
    "zoneId" TEXT NOT NULL,
    "devise" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "description" TEXT,
    "actif" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Marche_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "Marche_code_key" ON "Marche"("code")`,

  `CREATE TABLE IF NOT EXISTS "PrixReleve" (
    "id" TEXT NOT NULL,
    "produitId" TEXT NOT NULL,
    "marcheId" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "typePrix" TEXT NOT NULL,
    "echeance" TEXT,
    "valeur" DECIMAL(18,6) NOT NULL,
    "devise" TEXT NOT NULL,
    "unite" TEXT NOT NULL,
    "dateReleve" TIMESTAMP(3) NOT NULL,
    "dateCollecte" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "fiabilite" TEXT NOT NULL,
    "notes" TEXT,
    CONSTRAINT "PrixReleve_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "PrixReleve_produitId_marcheId_sourceId_dateReleve_typePrix_key" ON "PrixReleve"("produitId","marcheId","sourceId","dateReleve","typePrix")`,
  `CREATE INDEX IF NOT EXISTS "PrixReleve_produitId_marcheId_dateReleve_idx" ON "PrixReleve"("produitId","marcheId","dateReleve")`,
  `CREATE INDEX IF NOT EXISTS "PrixReleve_dateReleve_idx" ON "PrixReleve"("dateReleve")`,
  `CREATE INDEX IF NOT EXISTS "PrixReleve_sourceId_idx" ON "PrixReleve"("sourceId")`,

  `CREATE TABLE IF NOT EXISTS "StructureCout" (
    "id" TEXT NOT NULL,
    "produitId" TEXT NOT NULL,
    "sourceId" TEXT,
    "maillon" TEXT NOT NULL,
    "poste" TEXT NOT NULL,
    "montant" DECIMAL(18,4) NOT NULL,
    "devise" TEXT NOT NULL,
    "unite" TEXT NOT NULL,
    "periode" TEXT,
    "fiabilite" TEXT NOT NULL,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "StructureCout_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "StructureCout_produitId_idx" ON "StructureCout"("produitId")`,

  `CREATE TABLE IF NOT EXISTS "ConnectorLog" (
    "id" TEXT NOT NULL,
    "sourceId" TEXT NOT NULL,
    "debut" TIMESTAMP(3) NOT NULL,
    "fin" TIMESTAMP(3),
    "statut" TEXT NOT NULL,
    "nbImportes" INTEGER NOT NULL DEFAULT 0,
    "nbErreurs" INTEGER NOT NULL DEFAULT 0,
    "message" TEXT,
    "detail" JSONB,
    CONSTRAINT "ConnectorLog_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "ConnectorLog_sourceId_debut_idx" ON "ConnectorLog"("sourceId","debut")`,

  `CREATE TABLE IF NOT EXISTS "Actualite" (
    "id" TEXT NOT NULL,
    "filiereId" TEXT,
    "titre" TEXT NOT NULL,
    "lien" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "resume" TEXT,
    "datePublication" TIMESTAMP(3) NOT NULL,
    "dateCollecte" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Actualite_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "Actualite_filiereId_datePublication_idx" ON "Actualite"("filiereId","datePublication")`,
  `CREATE INDEX IF NOT EXISTS "Actualite_lien_idx" ON "Actualite"("lien")`,

  `CREATE TABLE IF NOT EXISTS "TauxChange" (
    "id" TEXT NOT NULL,
    "deviseSrc" TEXT NOT NULL,
    "deviseDest" TEXT NOT NULL,
    "taux" DECIMAL(18,8) NOT NULL,
    "dateReleve" TIMESTAMP(3) NOT NULL,
    "sourceCode" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "TauxChange_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE UNIQUE INDEX IF NOT EXISTS "TauxChange_deviseSrc_deviseDest_dateReleve_sourceCode_key" ON "TauxChange"("deviseSrc","deviseDest","dateReleve","sourceCode")`,
  `CREATE INDEX IF NOT EXISTS "TauxChange_deviseSrc_deviseDest_dateReleve_idx" ON "TauxChange"("deviseSrc","deviseDest","dateReleve")`,

  `CREATE TABLE IF NOT EXISTS "Alerte" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "filiereId" TEXT,
    "produitId" TEXT,
    "marcheId" TEXT,
    "typeCondition" TEXT NOT NULL,
    "valeurSeuil" DECIMAL(18,4),
    "variationPct" DECIMAL(8,4),
    "devise" TEXT,
    "unite" TEXT,
    "actif" BOOLEAN NOT NULL DEFAULT true,
    "derniereNotif" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Alerte_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "Alerte_userId_idx" ON "Alerte"("userId")`,

  `CREATE TABLE IF NOT EXISTS "AnalyseInvestissement" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "produitId" TEXT,
    "titre" TEXT NOT NULL,
    "description" TEXT,
    "hypotheses" JSONB NOT NULL,
    "resultats" JSONB,
    "scenarios" JSONB,
    "statut" TEXT NOT NULL DEFAULT 'BROUILLON',
    "devise" TEXT NOT NULL DEFAULT 'USD',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "AnalyseInvestissement_pkey" PRIMARY KEY ("id")
  )`,
  `CREATE INDEX IF NOT EXISTS "AnalyseInvestissement_userId_idx" ON "AnalyseInvestissement"("userId")`,
  `CREATE INDEX IF NOT EXISTS "AnalyseInvestissement_produitId_idx" ON "AnalyseInvestissement"("produitId")`,

  // Foreign keys — ignore duplicate_object errors
  `DO $$ BEGIN ALTER TABLE "Produit" ADD CONSTRAINT "Produit_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Produit" ADD CONSTRAINT "Produit_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES "Produit"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Marche" ADD CONSTRAINT "Marche_zoneId_fkey" FOREIGN KEY ("zoneId") REFERENCES "Zone"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_marcheId_fkey" FOREIGN KEY ("marcheId") REFERENCES "Marche"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "StructureCout" ADD CONSTRAINT "StructureCout_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "StructureCout" ADD CONSTRAINT "StructureCout_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "ConnectorLog" ADD CONSTRAINT "ConnectorLog_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Actualite" ADD CONSTRAINT "Actualite_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_marcheId_fkey" FOREIGN KEY ("marcheId") REFERENCES "Marche"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "AnalyseInvestissement" ADD CONSTRAINT "AnalyseInvestissement_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
  `DO $$ BEGIN ALTER TABLE "AnalyseInvestissement" ADD CONSTRAINT "AnalyseInvestissement_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE SET NULL ON UPDATE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; END $$`,
];

const FILIERES = [
  { code: "MAIS",  nom: "Maïs",         description: "Filière maïs — commodity internationale (CBOT/CME)" },
  { code: "CAJOU", nom: "Cajou",        description: "Filière cajou/anacarde — Côte d'Ivoire & Afrique de l'Ouest" },
  { code: "COLA",  nom: "Noix de Cola", description: "Filière noix de cola — marché régional AOF" },
];

const SOURCES = [
  { code: "WORLD_BANK_PINK",     nom: "World Bank — Pink Sheet",                        type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",   description: "Prix mensuels des matières premières — source de référence mondiale" },
  { code: "FAO_FPMA",            nom: "FAO — FPMA Food Price Monitoring",               type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "HEBDO",     description: "Prix alimentaires en Afrique de l'Ouest — FAO FPMA Tool" },
  { code: "USDA_FAS_PSD",        nom: "IMF — Primary Commodity Prices (maïs mondial)",  type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "MENSUEL",   description: "IMF Primary Commodity Prices — maïs mondial" },
  { code: "CONSEIL_ANACARDE_CI", nom: "Conseil Anacarde CI — Prix bord-champ",          type: "HTML", fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN", description: "Prix bord-champ RCN Côte d'Ivoire via FAOSTAT" },
  { code: "RESIMAO",             nom: "RESIMAO — Systèmes d'Information des Marchés",   type: "HTML", fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "Prix collectés sur les marchés de détail et de gros en Afrique de l'Ouest" },
  { code: "INDEXMUNDI",          nom: "IndexMundi — Commodity Prices",                  type: "HTML", fiabiliteDefaut: "INDICATIF", frequence: "HEBDO",     description: "Prix historiques commodités — maïs, cajou" },
  { code: "RSS_NEWS_AGRI",       nom: "Agrégateur RSS — Actualités agricoles",          type: "RSS",  fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "15 flux RSS — FAO, USDA, World Bank, Africa Report…" },
  { code: "GDELT_NEWS",          nom: "GDELT — Actualités mondiales agricoles",         type: "API",  fiabiliteDefaut: "INDICATIF", frequence: "QUOTIDIEN", description: "GDELT DOC 2.0 — actualités mondiales 65+ langues, maïs/cajou/cola, temps quasi réel" },
  { code: "TAUX_CHANGE_LIVE",    nom: "Taux de change live — USD/XOF, EUR/USD",        type: "API",  fiabiliteDefaut: "OFFICIEL",  frequence: "QUOTIDIEN", description: "Taux de change USD/XOF, EUR/USD — ECB via open.er-api.com" },
];

const ZONES = [
  { code: "MONDIAL",       nom: "Marché mondial",     type: "REGION" },
  { code: "AFRIQUE_OUEST", nom: "Afrique de l'Ouest", type: "REGION" },
  { code: "COTE_IVOIRE",   nom: "Côte d'Ivoire",      type: "PAYS" },
  { code: "BURKINA",       nom: "Burkina Faso",        type: "PAYS" },
  { code: "MALI",          nom: "Mali",                type: "PAYS" },
  { code: "SENEGAL",       nom: "Sénégal",             type: "PAYS" },
  { code: "BENIN",         nom: "Bénin",               type: "PAYS" },
  { code: "TOGO",          nom: "Togo",                type: "PAYS" },
  { code: "GHANA",         nom: "Ghana",               type: "PAYS" },
  { code: "NIGERIA",       nom: "Nigeria",             type: "PAYS" },
  { code: "NIGER",         nom: "Niger",               type: "PAYS" },
];

const PRODUITS = [
  { code: "MAIS_GRAIN",  nom: "Maïs grain",        filiereCode: "MAIS",  uniteRef: "tonne", estDerive: false, description: "Maïs grain sec — prix CBOT/CME et marchés AOF" },
  { code: "CAJOU_RCN",   nom: "Cajou RCN",          filiereCode: "CAJOU", uniteRef: "tonne", estDerive: false, description: "Noix de cajou brute (Raw Cashew Nut) — bord-champ CI" },
  { code: "COLA_ROUGE",  nom: "Noix de cola rouge", filiereCode: "COLA",  uniteRef: "kg",    estDerive: false, description: "Noix de cola rouge (Cola nitida) — marché régional AOF" },
];

const MARCHES = [
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
  { code: "LAGOS_COLA",         nom: "Lagos — Cola",                      zoneCode: "NIGERIA",       devise: "NGN", type: "GROSSISTE" },
  { code: "ABIDJAN_COLA",       nom: "Abidjan — Cola",                    zoneCode: "COTE_IVOIRE",   devise: "XOF", type: "GROSSISTE" },
  { code: "ACCRA_COLA",         nom: "Accra — Cola",                      zoneCode: "GHANA",         devise: "GHS", type: "GROSSISTE" },
  { code: "COTONOU_COLA",       nom: "Cotonou — Cola",                    zoneCode: "BENIN",         devise: "XOF", type: "GROSSISTE" },
  { code: "DAKAR_COLA",         nom: "Dakar — Cola",                      zoneCode: "SENEGAL",       devise: "XOF", type: "GROSSISTE" },
];

export async function runMigrate(): Promise<void> {
  // Prefer DIRECT_URL (Supabase direct port 5432) for DDL — avoids pooler limitations
  const directUrl = process.env.DIRECT_URL ?? process.env.DATABASE_URL;
  if (!directUrl) throw new Error("DATABASE_URL non défini");

  // Use a raw pg.Client for DDL so it bypasses the Prisma adapter's extended query protocol
  const client = new PgClient({ connectionString: directUrl });
  let errors = 0;
  try {
    await client.connect();
    for (const sql of DDL_STATEMENTS) {
      try {
        await client.query(sql);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (!msg.includes("already exists") && !msg.includes("duplicate_object")) {
          console.error("[setup] DDL error:", msg.slice(0, 200));
          errors++;
        }
      }
    }
  } finally {
    await client.end().catch(() => null);
  }
  console.log(`[setup] migrate: tables created/verified (${errors} unexpected errors)`);
}

export async function runInit(): Promise<{ created: number; errors: number }> {
  let created = 0;
  let errors = 0;

  async function tryCreate<T>(fn: () => Promise<T>): Promise<boolean> {
    try { await fn(); created++; return true; }
    catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (!msg.includes("Unique constraint") && !msg.includes("already exists")) {
        console.error("[setup] init error:", msg.slice(0, 150));
        errors++;
      }
      return false;
    }
  }

  for (const f of FILIERES) {
    const exists = await prisma.filiere.findUnique({ where: { code: f.code } }).catch(() => null);
    if (!exists) await tryCreate(() => prisma.filiere.create({ data: f }));
  }
  for (const s of SOURCES) {
    const exists = await prisma.source.findUnique({ where: { code: s.code } }).catch(() => null);
    if (!exists) await tryCreate(() => prisma.source.create({ data: { ...s, actif: true, statutDernier: "INCONNU" } }));
  }
  for (const z of ZONES) {
    const exists = await prisma.zone.findUnique({ where: { code: z.code } }).catch(() => null);
    if (!exists) await tryCreate(() => prisma.zone.create({ data: z }));
  }
  for (const p of PRODUITS) {
    const exists = await prisma.produit.findUnique({ where: { code: p.code } }).catch(() => null);
    if (!exists) {
      const filiere = await prisma.filiere.findUnique({ where: { code: p.filiereCode } }).catch(() => null);
      if (filiere) {
        await tryCreate(() => prisma.produit.create({
          data: { code: p.code, nom: p.nom, uniteRef: p.uniteRef, estDerive: p.estDerive, descriptionQualite: p.description, filiereId: filiere.id },
        }));
      }
    }
  }
  for (const m of MARCHES) {
    const exists = await prisma.marche.findUnique({ where: { code: m.code } }).catch(() => null);
    if (!exists) {
      const zone = await prisma.zone.findUnique({ where: { code: m.zoneCode } }).catch(() => null);
      if (zone) {
        await tryCreate(() => prisma.marche.create({
          data: { code: m.code, nom: m.nom, zoneId: zone.id, devise: m.devise, type: m.type, actif: true },
        }));
      }
    }
  }

  console.log(`[setup] init: ${created} created, ${errors} errors`);
  return { created, errors };
}
