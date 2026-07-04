export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/mais — reçoit des cotations maïs (USD/tonne) collectées
// côté GitHub Actions (IP propre, contrairement aux IP partagées Vercel qui
// épuisent les quotas Stooq/FRED). Protégé par CRON_SECRET si défini.

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface PointPrix {
  date: string;  // "2026-07-04"
  usd: number;   // USD par tonne
}

export async function POST(req: NextRequest) {
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret) {
    const auth = req.headers.get("authorization");
    if (auth !== `Bearer ${cronSecret}`) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
  }

  try {
    const body = await req.json() as { points?: PointPrix[]; sourceNote?: string };
    const points = (body.points ?? []).filter(
      (p) => p?.date && isFinite(p.usd) && p.usd > 0 && p.usd < 10_000
    ).slice(0, 200);
    if (points.length === 0) {
      return Response.json({ error: "Aucun point valide" }, { status: 400 });
    }

    const [produit, marche, source] = await Promise.all([
      prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } }),
      prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_USDA" } }),
      prisma.source.findUnique({ where: { code: "USDA_FAS_PSD" } }),
    ]);
    if (!produit || !marche || !source) {
      return Response.json({ error: "Référentiel incomplet — lancer /api/init" }, { status: 503 });
    }

    const note = (body.sourceNote ?? "CBOT ZC via GitHub Actions").slice(0, 120);
    const res = await prisma.prixReleve.createMany({
      data: points.map((p) => ({
        produitId: produit.id,
        marcheId: marche.id,
        sourceId: source.id,
        typePrix: "SPOT",
        valeur: p.usd,
        devise: "USD",
        unite: "tonne",
        dateReleve: new Date(`${p.date}T00:00:00.000Z`),
        fiabilite: "OFFICIEL",
        notes: note,
      })),
      skipDuplicates: true,
    });

    await prisma.source.update({
      where: { code: "USDA_FAS_PSD" },
      data: { statutDernier: "OK", derniereExecution: new Date(), messageErreur: null },
    }).catch(() => {});

    return Response.json({ ok: true, importes: res.count, recus: points.length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
