import { CONNECTEURS } from "@/lib/connectors";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";
export const maxDuration = 60; // Hobby plan max (300 only on Pro)

export async function GET(req: Request) {
  // CRON_SECRET auto-set by Vercel for cron jobs — only enforce if present
  const cronSecret = process.env.CRON_SECRET;
  const authHeader = req.headers.get("authorization");
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const results = [];

  for (const connecteur of CONNECTEURS) {
    try {
      // Each connector handles its own logging internally
      const result = await connecteur.run();
      const succes = result.nbErreurs === 0;
      results.push({ code: connecteur.code, succes, nbImportes: result.nbImportes });
    } catch (err) {
      results.push({ code: connecteur.code, succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
    }
  }

  return Response.json({ ok: true, results });
}
