// Cron rapide — news + taux de change
// Déclenché toutes les 5 minutes par Vercel Cron (Pro) ou 30 minutes (Free)
// Exécute uniquement les connecteurs légers : RSS news + taux de change

export const dynamic = "force-dynamic";
export const maxDuration = 60;

import { prisma } from "@/lib/db";
import { RssNewsConnector } from "@/lib/connectors/rss-news";
import { TauxChangeLiveConnector } from "@/lib/connectors/taux-change";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const results = [];

  // Taux de change (rapide, ~2s)
  try {
    const taux = new TauxChangeLiveConnector();
    const r = await taux.run();
    const source = await prisma.source.findFirst({ where: { code: taux.code } });
    if (source) {
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id,
          debut: r.debut,
          fin: r.fin,
          statut: r.nbErreurs === 0 ? "OK" : r.nbImportes > 0 ? "PARTIEL" : "ERREUR",
          nbImportes: r.nbImportes,
          nbErreurs: r.nbErreurs,
          message: r.nbErreurs === 0 ? `OK — ${r.nbImportes} taux importés` : r.erreurs.join("; "),
        },
      });
    }
    results.push({ code: taux.code, succes: r.nbErreurs === 0, nbImportes: r.nbImportes });
  } catch (err) {
    results.push({ code: "TAUX_CHANGE_LIVE", succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
  }

  // Actualités RSS (15 sources, ~15-20s)
  try {
    const rss = new RssNewsConnector();
    const r = await rss.run();
    const source = await prisma.source.findFirst({ where: { code: rss.code } });
    if (source) {
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id,
          debut: r.debut,
          fin: r.fin,
          statut: r.nbErreurs === 0 ? "OK" : r.nbImportes > 0 ? "PARTIEL" : "ERREUR",
          nbImportes: r.nbImportes,
          nbErreurs: r.nbErreurs,
          message: r.nbErreurs === 0 ? `OK — ${r.nbImportes} articles` : r.erreurs.slice(0, 2).join("; "),
        },
      });
    }
    results.push({ code: rss.code, succes: r.nbErreurs === 0, nbImportes: r.nbImportes });
  } catch (err) {
    results.push({ code: "RSS_NEWS_AGRI", succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
  }

  return Response.json({ ok: true, ts: new Date().toISOString(), results });
}
