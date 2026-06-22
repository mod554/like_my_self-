import { CONNECTEURS } from "@/lib/connectors";
import { prisma } from "@/lib/db";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const results = [];

  for (const connecteur of CONNECTEURS) {
    try {
      const result = await connecteur.run();
      const succes = result.nbErreurs === 0;

      const source = await prisma.source.findFirst({ where: { code: connecteur.code } });
      if (source) {
        await Promise.all([
          prisma.connectorLog.create({
            data: {
              sourceId: source.id,
              debut: result.debut,
              fin: result.fin,
              statut: succes ? "OK" : "ERREUR",
              nbImportes: result.nbImportes,
              nbErreurs: result.nbErreurs,
              message: succes
                ? `OK — ${result.nbImportes} éléments importés`
                : result.erreurs.join("; "),
            },
          }),
          prisma.source.update({
            where: { id: source.id },
            data: {
              derniereExecution: result.fin,
              statutDernier: succes ? "OK" : "ERREUR",
              messageErreur: succes ? null : result.erreurs[0] ?? null,
            },
          }),
        ]);
      }

      results.push({ code: connecteur.code, succes, nbImportes: result.nbImportes });
    } catch (err) {
      results.push({ code: connecteur.code, succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
    }
  }

  return Response.json({ ok: true, results });
}
