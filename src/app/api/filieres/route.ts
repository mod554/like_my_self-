export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import { NextRequest } from "next/server";

export async function GET(_req: NextRequest) {
  try {
    const filieres = await prisma.filiere.findMany({
      orderBy: { code: "asc" },
      include: {
        _count: { select: { produits: true, actualites: true } },
      },
    });
    return Response.json(filieres);
  } catch (e) {
    return Response.json({ error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
