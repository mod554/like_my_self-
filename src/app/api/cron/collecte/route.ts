// Cron principal — déclenche tous les connecteurs séquentiellement
// Gardé pour compatibilité — préférer /api/cron/prix et /api/cron/taux
export const dynamic = "force-dynamic";
export const maxDuration = 60;

import { CONNECTEURS } from "@/lib/connectors";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const results = await Promise.allSettled(CONNECTEURS.map((c) => c.run()));

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    results: results.map((r, i) => ({
      code: CONNECTEURS[i].code,
      succes: r.status === "fulfilled" && r.value.nbErreurs === 0,
      nbImportes: r.status === "fulfilled" ? r.value.nbImportes : 0,
    })),
  });
}
