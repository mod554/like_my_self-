import { prisma } from "@/lib/db";
import { NextRequest } from "next/server";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ code: string }> }
) {
  const { code } = await params;

  const produit = await prisma.produit.findUnique({
    where: { code: code.toUpperCase() },
    include: {
      filiere: true,
      parent: { select: { code: true, nom: true } },
      derives: { orderBy: { code: "asc" }, select: { id: true, code: true, nom: true, uniteRef: true, descriptionQualite: true } },
      prixReleves: {
        orderBy: { dateReleve: "desc" },
        take: 20,
        include: {
          marche: { select: { code: true, nom: true, type: true } },
          source: { select: { code: true, nom: true } },
        },
      },
      structuresCout: {
        orderBy: [{ maillon: "asc" }, { poste: "asc" }],
        include: {
          source: { select: { code: true, nom: true } },
        },
      },
    },
  });

  if (!produit) {
    return Response.json({ error: "Produit introuvable" }, { status: 404 });
  }

  return Response.json(produit);
}
