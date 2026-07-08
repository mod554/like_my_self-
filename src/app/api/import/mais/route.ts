export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/mais — reçoit des cotations maïs (USD/tonne) collectées
// côté GitHub Actions (IP propre, contrairement aux IP partagées Vercel qui
// épuisent les quotas Stooq/FRED). Protégé par CRON_SECRET si défini.

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface PointPrix {
  date: string;   // "2026-07-04" (quotidien) ou ISO complet "2026-07-04T14:30:00Z" (intraday)
  usd: number;    // USD par tonne
  cents?: number; // cotation d'origine en cents USD / boisseau (parité TradingView)
}

// typePrix acceptés : SPOT (quotidien) + intraday horaire/minute.
// Un typePrix distinct évite toute collision avec le point quotidien de minuit.
const TYPES_PRIX = new Set(["SPOT", "SPOT_1H", "SPOT_1MIN"]);

// Accepte "YYYY-MM-DD" (→ minuit UTC) ou un ISO complet avec heure (intraday).
function versDate(v: string): Date | null {
  const iso = v.includes("T") ? v : `${v}T00:00:00.000Z`;
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
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
    const body = await req.json() as { points?: PointPrix[]; sourceNote?: string; sourceCode?: string; typePrix?: string };
    // Sources autorisées pour cet import (liste blanche)
    const sourceCode = ["YAHOO_FINANCE", "USDA_FAS_PSD"].includes(body.sourceCode ?? "")
      ? (body.sourceCode as string)
      : "USDA_FAS_PSD";
    const typePrix = TYPES_PRIX.has(body.typePrix ?? "") ? (body.typePrix as string) : "SPOT";
    // Intraday : on peut recevoir des centaines de barres 1min → plafond plus large
    const limite = typePrix === "SPOT" ? 200 : 500;
    const points = (body.points ?? []).filter(
      (p) => p?.date && isFinite(p.usd) && p.usd > 0 && p.usd < 10_000
    ).slice(0, limite);
    if (points.length === 0) {
      return Response.json({ error: "Aucun point valide" }, { status: 400 });
    }

    const [produit, marche, source] = await Promise.all([
      prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } }),
      prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_USDA" } }),
      prisma.source.findUnique({ where: { code: sourceCode } }),
    ]);
    if (!produit || !marche || !source) {
      return Response.json({ error: "Référentiel incomplet — lancer /api/init" }, { status: 503 });
    }

    const note = (body.sourceNote ?? "CBOT ZC via GitHub Actions").slice(0, 120);
    const data = points
      .map((p) => {
        const dateReleve = versDate(p.date);
        if (!dateReleve) return null;
        return {
          produitId: produit.id,
          marcheId: marche.id,
          sourceId: source.id,
          typePrix,
          valeur: p.usd,
          devise: "USD",
          unite: "tonne",
          dateReleve,
          fiabilite: "OFFICIEL",
          notes: p.cents ? `${note} — ${p.cents.toFixed(2)} ¢/bu (cotation brute, parité TradingView ZC1!)` : note,
        };
      })
      .filter((d): d is NonNullable<typeof d> => d !== null);
    if (data.length === 0) {
      return Response.json({ error: "Aucune date valide" }, { status: 400 });
    }
    const res = await prisma.prixReleve.createMany({ data, skipDuplicates: true });

    await prisma.source.update({
      where: { code: sourceCode },
      data: { statutDernier: "OK", derniereExecution: new Date(), messageErreur: null },
    }).catch(() => {});

    return Response.json({ ok: true, importes: res.count, recus: points.length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
