import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as {
      produitId: string;
      marcheId: string;
      sourceId: string;
      typePrix: string;
      valeur: number;
      devise: string;
      unite: string;
      dateReleve: string;
      fiabilite: string;
      notes?: string;
    };

    const { produitId, marcheId, sourceId, typePrix, valeur, devise, unite, dateReleve, fiabilite, notes } = body;

    if (!produitId || !marcheId || !sourceId || !valeur || !dateReleve) {
      return Response.json({ error: "Champs requis manquants" }, { status: 400 });
    }

    if (isNaN(valeur) || valeur <= 0) {
      return Response.json({ error: "Valeur invalide" }, { status: 400 });
    }

    const releve = await prisma.prixReleve.create({
      data: {
        produitId,
        marcheId,
        sourceId,
        typePrix: typePrix ?? "SPOT",
        valeur,
        devise: devise ?? "XOF",
        unite: unite ?? "tonne",
        dateReleve: new Date(dateReleve),
        fiabilite: fiabilite ?? "INDICATIF",
        notes: notes || null,
      },
    });

    return Response.json(releve, { status: 201 });
  } catch (err) {
    return Response.json(
      { error: err instanceof Error ? err.message : "Erreur serveur" },
      { status: 500 }
    );
  }
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const produitCode = searchParams.get("produit");
  const limit = parseInt(searchParams.get("limit") ?? "50");

  const where = produitCode ? { produit: { code: produitCode } } : {};

  const releves = await prisma.prixReleve.findMany({
    where,
    orderBy: { dateReleve: "desc" },
    take: Math.min(limit, 200),
    include: {
      produit: { select: { code: true, nom: true } },
      marche: { select: { code: true, nom: true } },
      source: { select: { code: true } },
    },
  });

  return Response.json(releves);
}
