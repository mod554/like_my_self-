// GET /api/connectors — liste tous les connecteurs avec leur statut en BD
// POST /api/connectors — déclenche un ou tous les connecteurs

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { CONNECTEURS, getConnecteur } from "@/lib/connectors";

export async function GET() {
  const sources = await prisma.source.findMany({
    orderBy: { code: "asc" },
    include: {
      _count: { select: { prixReleves: true, logs: true } },
      logs: { orderBy: { debut: "desc" }, take: 1 },
    },
  });

  const connecteurs = CONNECTEURS.map((c) => {
    const source = sources.find((s) => s.code === c.code);
    return {
      code: c.code,
      nom: c.nom,
      frequenceCron: c.frequenceCron,
      enBase: !!source,
      statut: source?.statutDernier ?? "INCONNU",
      derniereExecution: source?.derniereExecution ?? null,
      messageErreur: source?.messageErreur ?? null,
      nbPrixReleves: source?._count.prixReleves ?? 0,
      nbLogs: source?._count.logs ?? 0,
      dernierLog: source?.logs[0] ?? null,
    };
  });

  return Response.json({ connecteurs, total: connecteurs.length });
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({})) as { code?: string; tous?: boolean };

  if (body.tous) {
    // Lancer tous les connecteurs séquentiellement (ne pas surcharger les APIs)
    const resultats = [];
    for (const connecteur of CONNECTEURS) {
      try {
        const resultat = await connecteur.run();
        resultats.push({ code: connecteur.code, ...resultat });
      } catch (err) {
        resultats.push({
          code: connecteur.code,
          erreur: err instanceof Error ? err.message : String(err),
        });
      }
    }
    return Response.json({ resultats });
  }

  if (body.code) {
    const connecteur = getConnecteur(body.code);
    if (!connecteur) {
      return Response.json({ error: `Connecteur "${body.code}" introuvable` }, { status: 404 });
    }
    try {
      const resultat = await connecteur.run();
      return Response.json(resultat);
    } catch (err) {
      return Response.json(
        { error: err instanceof Error ? err.message : String(err) },
        { status: 500 }
      );
    }
  }

  return Response.json({ error: "Fournir { code: '...' } ou { tous: true }" }, { status: 400 });
}
