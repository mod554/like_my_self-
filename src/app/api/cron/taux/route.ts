// Cron ultra-rapide — taux de change uniquement (~2s)
// Déclenché chaque minute par Vercel Cron (Pro) ou toutes les heures (Hobby)
export const dynamic = "force-dynamic";
export const maxDuration = 30;

import { TauxChangeLiveConnector } from "@/lib/connectors/taux-change";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const result = await new TauxChangeLiveConnector().run();
    return Response.json({
      ok: true,
      ts: new Date().toISOString(),
      nbImportes: result.nbImportes,
      nbErreurs: result.nbErreurs,
    });
  } catch (err) {
    return Response.json({ ok: false, error: err instanceof Error ? err.message : String(err) }, { status: 500 });
  }
}
