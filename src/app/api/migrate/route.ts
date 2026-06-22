import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

// SQL to create all tables if they don't exist — generated from prisma/schema.prisma
// Run this once after deployment when DATABASE_URL was not available at build time.
const CREATE_TABLES_SQL = `
CREATE TABLE IF NOT EXISTS "Filiere" (
  "id" TEXT NOT NULL,
  "code" TEXT NOT NULL,
  "nom" TEXT NOT NULL,
  "description" TEXT,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "Filiere_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "Filiere_code_key" ON "Filiere"("code");

CREATE TABLE IF NOT EXISTS "Zone" (
  "id" TEXT NOT NULL,
  "code" TEXT NOT NULL,
  "nom" TEXT NOT NULL,
  "type" TEXT NOT NULL,
  CONSTRAINT "Zone_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "Zone_code_key" ON "Zone"("code");

CREATE TABLE IF NOT EXISTS "Source" (
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
);
CREATE UNIQUE INDEX IF NOT EXISTS "Source_code_key" ON "Source"("code");

CREATE TABLE IF NOT EXISTS "User" (
  "id" TEXT NOT NULL,
  "email" TEXT NOT NULL,
  "nom" TEXT NOT NULL,
  "motDePasse" TEXT NOT NULL,
  "role" TEXT NOT NULL DEFAULT 'LECTEUR',
  "actif" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "User_email_key" ON "User"("email");

CREATE TABLE IF NOT EXISTS "Produit" (
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
);
CREATE UNIQUE INDEX IF NOT EXISTS "Produit_code_key" ON "Produit"("code");
CREATE INDEX IF NOT EXISTS "Produit_filiereId_idx" ON "Produit"("filiereId");

CREATE TABLE IF NOT EXISTS "Marche" (
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
);
CREATE UNIQUE INDEX IF NOT EXISTS "Marche_code_key" ON "Marche"("code");

CREATE TABLE IF NOT EXISTS "PrixReleve" (
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
);
CREATE INDEX IF NOT EXISTS "PrixReleve_produitId_marcheId_dateReleve_idx" ON "PrixReleve"("produitId","marcheId","dateReleve");
CREATE INDEX IF NOT EXISTS "PrixReleve_dateReleve_idx" ON "PrixReleve"("dateReleve");
CREATE INDEX IF NOT EXISTS "PrixReleve_sourceId_idx" ON "PrixReleve"("sourceId");

CREATE TABLE IF NOT EXISTS "StructureCout" (
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
);
CREATE INDEX IF NOT EXISTS "StructureCout_produitId_idx" ON "StructureCout"("produitId");

CREATE TABLE IF NOT EXISTS "ConnectorLog" (
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
);
CREATE INDEX IF NOT EXISTS "ConnectorLog_sourceId_debut_idx" ON "ConnectorLog"("sourceId","debut");

CREATE TABLE IF NOT EXISTS "Actualite" (
  "id" TEXT NOT NULL,
  "filiereId" TEXT,
  "titre" TEXT NOT NULL,
  "lien" TEXT NOT NULL,
  "source" TEXT NOT NULL,
  "resume" TEXT,
  "datePublication" TIMESTAMP(3) NOT NULL,
  "dateCollecte" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "Actualite_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "Actualite_filiereId_datePublication_idx" ON "Actualite"("filiereId","datePublication");

CREATE TABLE IF NOT EXISTS "TauxChange" (
  "id" TEXT NOT NULL,
  "deviseSrc" TEXT NOT NULL,
  "deviseDest" TEXT NOT NULL,
  "taux" DECIMAL(18,8) NOT NULL,
  "dateReleve" TIMESTAMP(3) NOT NULL,
  "sourceCode" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "TauxChange_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "TauxChange_deviseSrc_deviseDest_dateReleve_sourceCode_key" ON "TauxChange"("deviseSrc","deviseDest","dateReleve","sourceCode");
CREATE INDEX IF NOT EXISTS "TauxChange_deviseSrc_deviseDest_dateReleve_idx" ON "TauxChange"("deviseSrc","deviseDest","dateReleve");

CREATE TABLE IF NOT EXISTS "Alerte" (
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
);
CREATE INDEX IF NOT EXISTS "Alerte_userId_idx" ON "Alerte"("userId");

CREATE TABLE IF NOT EXISTS "AnalyseInvestissement" (
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
);
CREATE INDEX IF NOT EXISTS "AnalyseInvestissement_userId_idx" ON "AnalyseInvestissement"("userId");
CREATE INDEX IF NOT EXISTS "AnalyseInvestissement_produitId_idx" ON "AnalyseInvestissement"("produitId");

-- Foreign keys (add only if not exists — use DO $$ to handle gracefully)
DO $$ BEGIN
  ALTER TABLE "Produit" ADD CONSTRAINT "Produit_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Produit" ADD CONSTRAINT "Produit_parentId_fkey" FOREIGN KEY ("parentId") REFERENCES "Produit"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Marche" ADD CONSTRAINT "Marche_zoneId_fkey" FOREIGN KEY ("zoneId") REFERENCES "Zone"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_marcheId_fkey" FOREIGN KEY ("marcheId") REFERENCES "Marche"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "PrixReleve" ADD CONSTRAINT "PrixReleve_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "StructureCout" ADD CONSTRAINT "StructureCout_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "StructureCout" ADD CONSTRAINT "StructureCout_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "ConnectorLog" ADD CONSTRAINT "ConnectorLog_sourceId_fkey" FOREIGN KEY ("sourceId") REFERENCES "Source"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Actualite" ADD CONSTRAINT "Actualite_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_filiereId_fkey" FOREIGN KEY ("filiereId") REFERENCES "Filiere"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "Alerte" ADD CONSTRAINT "Alerte_marcheId_fkey" FOREIGN KEY ("marcheId") REFERENCES "Marche"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "AnalyseInvestissement" ADD CONSTRAINT "AnalyseInvestissement_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE "AnalyseInvestissement" ADD CONSTRAINT "AnalyseInvestissement_produitId_fkey" FOREIGN KEY ("produitId") REFERENCES "Produit"("id") ON DELETE SET NULL ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
`;

export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("authorization");
  const adminKey = process.env.ADMIN_SECRET ?? process.env.CRON_SECRET;
  if (adminKey && authHeader !== `Bearer ${adminKey}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    await prisma.$executeRawUnsafe(CREATE_TABLES_SQL);

    // Verify tables are accessible
    const counts = await Promise.all([
      prisma.filiere.count().then((n) => `filiere:${n}`),
      prisma.source.count().then((n) => `source:${n}`),
      prisma.zone.count().then((n) => `zone:${n}`),
      prisma.marche.count().then((n) => `marche:${n}`),
      prisma.produit.count().then((n) => `produit:${n}`),
    ]);

    return Response.json({
      ok: true,
      message: "Schema applied — all tables created or already exist",
      counts,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return Response.json({ ok: false, error: msg }, { status: 500 });
  }
}

export async function GET(req: NextRequest) {
  return POST(req);
}
