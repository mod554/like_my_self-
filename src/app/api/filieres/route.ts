export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import { NextRequest } from "next/server";

export async function GET(_req: NextRequest) {
  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      _count: { select: { produits: true, actualites: true } },
    },
  });
  return Response.json(filieres);
}
