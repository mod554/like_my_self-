// Diagnostic endpoint — checks DB connection, table existence, and reference data counts
// GET /api/diagnostic — returns full system health status

export const dynamic = "force-dynamic";
export const maxDuration = 30;

import { prisma } from "@/lib/db";

export async function GET() {
  const checks: Record<string, unknown> = {
    ts: new Date().toISOString(),
    env: {
      DATABASE_URL: process.env.DATABASE_URL ? "SET" : "MISSING",
      CRON_SECRET: process.env.CRON_SECRET ? "SET" : "NOT_SET",
      ADMIN_SECRET: process.env.ADMIN_SECRET ? "SET" : "NOT_SET",
      NODE_ENV: process.env.NODE_ENV,
    },
  };

  // Test DB connection
  try {
    await prisma.$queryRaw`SELECT 1`;
    checks.db_connection = "OK";
  } catch (e) {
    checks.db_connection = `FAILED: ${e instanceof Error ? e.message : String(e)}`;
    return Response.json(checks, { status: 503 });
  }

  // Test each table
  const tableChecks: Record<string, unknown> = {};
  const tables = [
    { name: "Filiere", fn: () => prisma.filiere.count() },
    { name: "Zone", fn: () => prisma.zone.count() },
    { name: "Source", fn: () => prisma.source.count() },
    { name: "Produit", fn: () => prisma.produit.count() },
    { name: "Marche", fn: () => prisma.marche.count() },
    { name: "PrixReleve", fn: () => prisma.prixReleve.count() },
    { name: "TauxChange", fn: () => prisma.tauxChange.count() },
    { name: "Actualite", fn: () => prisma.actualite.count() },
    { name: "ConnectorLog", fn: () => prisma.connectorLog.count() },
  ];

  for (const t of tables) {
    try {
      tableChecks[t.name] = await t.fn();
    } catch (e) {
      tableChecks[t.name] = `ERROR: ${e instanceof Error ? e.message.split("\n")[0] : String(e)}`;
    }
  }
  checks.tables = tableChecks;

  // Check sources status
  try {
    const sources = await prisma.source.findMany({
      select: { code: true, statutDernier: true, derniereExecution: true, messageErreur: true },
    });
    checks.sources = sources;
  } catch (e) {
    checks.sources = `ERROR: ${e instanceof Error ? e.message : String(e)}`;
  }

  const allTablesOk = Object.values(tableChecks).every((v) => typeof v === "number");
  const hasData = typeof tableChecks.PrixReleve === "number" && tableChecks.PrixReleve > 0;

  checks.status = allTablesOk ? (hasData ? "HEALTHY" : "TABLES_OK_NO_DATA") : "TABLES_MISSING";
  checks.action_needed = allTablesOk
    ? (hasData ? "None" : "Click 'Lancer tous les connecteurs' to collect data")
    : "Click 'Initialiser la BDD' first, then run connectors";

  return Response.json(checks, { status: allTablesOk ? 200 : 503 });
}
