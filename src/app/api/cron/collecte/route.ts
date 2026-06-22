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
        await prisma.connectorLog.create({
          data: {
            sourceId: source.id,
            statut: succes ? "OK" : "ERREUR",
            nbPrixCollectes: result.nbImportes,
            nbActualites: 0,
            message: succes
              ? `OK — ${result.nbImportes} éléments importés`
              : result.erreurs.join("; "),
            dateDebut: result.debut,
            dateFin: result.fin,
          },
        });
      }

      results.push({ code: connecteur.code, succes, nbImportes: result.nbImportes });
    } catch (err) {
      results.push({ code: connecteur.code, succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
    }
  }

  return Response.json({ ok: true, results });
}
