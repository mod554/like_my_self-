// Cron rapide — news + taux de change
// Déclenché toutes les 5 minutes par Vercel Cron (Pro) ou 30 minutes (Free)
// Exécute uniquement les connecteurs légers : RSS news + taux de change

export const dynamic = "force-dynamic";
export const maxDuration = 55; // Hobby plan max 60s — leave margin

import { RssNewsConnector } from "@/lib/connectors/rss-news";
import { TauxChangeLiveConnector } from "@/lib/connectors/taux-change";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Each connector handles its own logging internally — run in parallel
  const [tauxResult, rssResult] = await Promise.allSettled([
    new TauxChangeLiveConnector().run(),
    new RssNewsConnector().run(),
  ]);

  const results = [
    tauxResult.status === "fulfilled"
      ? { code: "TAUX_CHANGE_LIVE", succes: tauxResult.value.nbErreurs === 0, nbImportes: tauxResult.value.nbImportes }
      : { code: "TAUX_CHANGE_LIVE", succes: false, erreur: tauxResult.reason instanceof Error ? tauxResult.reason.message : "Erreur" },
    rssResult.status === "fulfilled"
      ? { code: "RSS_NEWS_AGRI", succes: rssResult.value.nbErreurs === 0, nbImportes: rssResult.value.nbImportes }
      : { code: "RSS_NEWS_AGRI", succes: false, erreur: rssResult.reason instanceof Error ? rssResult.reason.message : "Erreur" },
  ];

  return Response.json({ ok: true, ts: new Date().toISOString(), results });
}
