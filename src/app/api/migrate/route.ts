import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

// Ensures all required tables exist by running a lightweight schema check via Prisma.
// Called after each deployment to handle schema drift without requiring CLI access.
export async function POST(req: NextRequest) {
  const authHeader = req.headers.get("authorization");
  const adminKey = process.env.ADMIN_SECRET ?? process.env.CRON_SECRET;
  if (adminKey && authHeader !== `Bearer ${adminKey}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const checks: string[] = [];
  const errors: string[] = [];

  // Probe each table — if a table is missing Prisma throws P2021 "table does not exist"
  const models = [
    { name: "filiere",     fn: () => prisma.filiere.count() },
    { name: "source",      fn: () => prisma.source.count() },
    { name: "zone",        fn: () => prisma.zone.count() },
    { name: "marche",      fn: () => prisma.marche.count() },
    { name: "produit",     fn: () => prisma.produit.count() },
    { name: "prixReleve",  fn: () => prisma.prixReleve.count() },
    { name: "actualite",   fn: () => prisma.actualite.count() },
    { name: "connectorLog",fn: () => prisma.connectorLog.count() },
    { name: "alerte",      fn: () => prisma.alerte.count() },
  ] as const;

  for (const model of models) {
    try {
      const count = await model.fn();
      checks.push(`${model.name}: ${count} rows`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      errors.push(`${model.name}: ${msg}`);
    }
  }

  return Response.json({
    ok: errors.length === 0,
    checks,
    errors,
    message: errors.length === 0
      ? "All tables accessible"
      : `${errors.length} table(s) missing or inaccessible — run prisma db push`,
  });
}

export async function GET() {
  return POST(new Request("http://localhost/api/migrate", { method: "POST" }) as NextRequest);
}
