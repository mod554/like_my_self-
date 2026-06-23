// Cron news + taux — RSS actualités et taux de change
// Déclenché toutes les 5 minutes (Pro) ou toutes les heures (Hobby)
export const dynamic = "force-dynamic";
export const maxDuration = 55;

import { RssNewsConnector } from "@/lib/connectors/rss-news";
import { TauxChangeLiveConnector } from "@/lib/connectors/taux-change";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const [tauxResult, rssResult] = await Promise.allSettled([
    new TauxChangeLiveConnector().run(),
    new RssNewsConnector().run(),
  ]);

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    results: [
      tauxResult.status === "fulfilled"
        ? { code: "TAUX_CHANGE_LIVE", succes: tauxResult.value.nbErreurs === 0, nbImportes: tauxResult.value.nbImportes }
        : { code: "TAUX_CHANGE_LIVE", succes: false, erreur: String(tauxResult.reason) },
      rssResult.status === "fulfilled"
        ? { code: "RSS_NEWS_AGRI", succes: rssResult.value.nbErreurs === 0, nbImportes: rssResult.value.nbImportes }
        : { code: "RSS_NEWS_AGRI", succes: false, erreur: String(rssResult.reason) },
    ],
  });
}
