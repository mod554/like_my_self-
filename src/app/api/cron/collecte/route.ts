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

      await prisma.connectorLog.create({
        data: {
          sourceId: (await prisma.source.findFirst({ where: { code: connecteur.code } }))?.id ?? "",
          statut: result.succes ? "OK" : "ERREUR",
          nbPrixCollectes: result.prixAjoutes,
          nbActualites: result.actualitesAjoutees,
          message: result.succes ? `OK — ${result.prixAjoutes} prix, ${result.actualitesAjoutees} actualités` : result.erreur,
          dateDebut: new Date(),
          dateFin: new Date(),
        },
      });

      results.push({ code: connecteur.code, succes: result.succes, prixAjoutes: result.prixAjoutes });
    } catch (err) {
      results.push({ code: connecteur.code, succes: false, erreur: err instanceof Error ? err.message : "Erreur" });
    }
  }

  return Response.json({ ok: true, results });
}
