import { CONNECTEURS } from "@/lib/connectors";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
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
