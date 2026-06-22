export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import { NextRequest } from "next/server";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ code: string }> }
) {
  const { code } = await params;

  const filiere = await prisma.filiere.findUnique({
    where: { code: code.toUpperCase() },
    include: {
      produits: {
        orderBy: [{ estDerive: "asc" }, { code: "asc" }],
        include: {
          _count: { select: { prixReleves: true, structuresCout: true } },
        },
      },
      actualites: {
        orderBy: { datePublication: "desc" },
        take: 5,
      },
    },
  });

  if (!filiere) {
    return Response.json({ error: "Filière introuvable" }, { status: 404 });
  }

  return Response.json(filiere);
}
