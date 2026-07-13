// Cron principal — déclenche tous les connecteurs séquentiellement
// Gardé pour compatibilité — préférer /api/cron/prix et /api/cron/taux
export const dynamic = "force-dynamic";
export const maxDuration = 60;

import { CONNECTEURS } from "@/lib/connectors";
import { prisma } from "@/lib/db";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Hygiène avant collecte : statuts EN_COURS zombies (connecteur tué par le
  // budget serverless) → ERREUR, et purge des barres intraday anciennes
  // (1min > 7 jours, 1h > 60 jours) pour contenir la taille de la base.
  await prisma.source.updateMany({
    where: { statutDernier: "EN_COURS", derniereExecution: { lt: new Date(Date.now() - 20 * 60_000) } },
    data: { statutDernier: "ERREUR", messageErreur: "Interrompu — budget d'exécution serverless dépassé" },
  }).catch(() => {});
  await prisma.prixReleve.deleteMany({
    where: { typePrix: "SPOT_1MIN", dateReleve: { lt: new Date(Date.now() - 7 * 86_400_000) } },
  }).catch(() => {});
  await prisma.prixReleve.deleteMany({
    where: { typePrix: "SPOT_1H", dateReleve: { lt: new Date(Date.now() - 60 * 86_400_000) } },
  }).catch(() => {});

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
