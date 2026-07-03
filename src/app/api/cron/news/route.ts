// Cron news + taux — RSS actualités et taux de change
// Déclenché toutes les 5 minutes (Pro) ou toutes les heures (Hobby)
export const dynamic = "force-dynamic";
export const maxDuration = 55;

import { RssNewsConnector } from "@/lib/connectors/rss-news";
import { GdeltNewsConnector } from "@/lib/connectors/gdelt-news";
import { TauxChangeLiveConnector } from "@/lib/connectors/taux-change";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const results = await Promise.allSettled([
    new TauxChangeLiveConnector().run(),
    new RssNewsConnector().run(),
    new GdeltNewsConnector().run(),
  ]);
  const codes = ["TAUX_CHANGE_LIVE", "RSS_NEWS_AGRI", "GDELT_NEWS"];

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    results: results.map((r, i) =>
      r.status === "fulfilled"
        ? { code: codes[i], succes: r.value.nbErreurs === 0, nbImportes: r.value.nbImportes }
        : { code: codes[i], succes: false, erreur: String(r.reason) }
    ),
  });
}
