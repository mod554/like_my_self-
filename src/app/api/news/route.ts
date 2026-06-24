export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import { NextRequest } from "next/server";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const filiere = searchParams.get("filiere"); // optionnel : MAIS | CAJOU | COLA
  const limit = Math.min(parseInt(searchParams.get("limit") ?? "50"), 100);

  try {
  const news = await prisma.actualite.findMany({
    where: filiere ? { filiere: { code: filiere.toUpperCase() } } : undefined,
    orderBy: { datePublication: "desc" },
    take: limit,
    include: {
      filiere: { select: { code: true, nom: true } },
    },
  });

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    count: news.length,
    news: news.map((a) => ({
      id: a.id,
      titre: a.titre,
      lien: a.lien,
      source: a.source,
      resume: a.resume,
      datePublication: a.datePublication,
      dateCollecte: a.dateCollecte,
      filiere: a.filiere ? { code: a.filiere.code, nom: a.filiere.nom } : null,
    })),
  });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e), news: [] }, { status: 503 });
  }
}
