export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/fpma — prix mensuels des marchés locaux AOF collectés côté
// GitHub Actions depuis l'API FAO GIEWS FPMA (fpma.fao.org, publique, JSON).
// Remplace l'ancien pipeline FAOSTAT (mort : HTTP 401 depuis 2026) pour la
// source FAO_FPMA — et en mieux : mensuel/hebdo au lieu d'annuel.
// Protégé par CRON_SECRET si défini.

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface LigneFpma {
  produitCode: string;  // MAIS_GRAIN (extensible)
  marcheNom: string;    // "Abidjan", "Bouaké"…
  iso3: string;         // CIV, BFA, MLI…
  devise: string;       // XOF…
  typePrix: string;     // DETAIL | GROS
  date: string;         // "2026-06-01"
  valeur: number;       // prix par kg en devise locale
}

const PRODUITS_AUTORISES = new Set(["MAIS_GRAIN", "CAJOU_RCN"]);
const TYPES = new Set(["DETAIL", "GROS"]);
// ISO3 → code zone du référentiel
const ZONES_ISO3: Record<string, string> = {
  CIV: "COTE_IVOIRE", BFA: "BURKINA", MLI: "MALI", SEN: "SENEGAL",
  BEN: "BENIN", TGO: "TOGO", GHA: "GHANA", NGA: "NIGERIA", NER: "NIGER",
};

function normCode(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 28);
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
    const body = await req.json() as { rows?: LigneFpma[] };
    const rows = (body.rows ?? []).filter(
      (r) => PRODUITS_AUTORISES.has(r?.produitCode) && TYPES.has(r?.typePrix)
        && ZONES_ISO3[r?.iso3] && r?.marcheNom?.trim()
        && /^\d{4}-\d{2}-\d{2}$/.test(r?.date ?? "")
        && isFinite(r.valeur) && r.valeur > 0 && r.valeur < 1_000_000
    ).slice(0, 2000);
    if (rows.length === 0) {
      return Response.json({ error: "Aucune ligne valide" }, { status: 400 });
    }

    const source = await prisma.source.findUnique({ where: { code: "FAO_FPMA" } });
    if (!source) return Response.json({ error: "Source FAO_FPMA absente — lancer /api/init" }, { status: 503 });

    const produits = await prisma.produit.findMany({ where: { code: { in: [...PRODUITS_AUTORISES] } } });
    const produitMap = Object.fromEntries(produits.map((p) => [p.code, p.id]));

    // Upsert des marchés FPMA (un par marché × pays rencontré)
    const marcheMap: Record<string, string> = {};
    for (const r of rows) {
      const cle = `${r.iso3}|${r.marcheNom.trim().toUpperCase()}`;
      if (marcheMap[cle]) continue;
      const zone = await prisma.zone.findUnique({ where: { code: ZONES_ISO3[r.iso3] } });
      if (!zone) continue;
      const code = `FPMA_${r.iso3}_${normCode(r.marcheNom)}`.slice(0, 40);
      const m = await prisma.marche.upsert({
        where: { code },
        update: {},
        create: {
          code,
          nom: `${r.marcheNom.trim()} (FPMA/GIEWS)`,
          zoneId: zone.id,
          devise: r.devise || "XOF",
          type: "SPOT_DOMESTIQUE",
          description: "Marché physique — FAO GIEWS FPMA (données WFP/instituts nationaux)",
        },
      });
      marcheMap[cle] = m.id;
    }

    const data = rows
      .map((r) => {
        const produitId = produitMap[r.produitCode];
        const marcheId = marcheMap[`${r.iso3}|${r.marcheNom.trim().toUpperCase()}`];
        if (!produitId || !marcheId) return null;
        return {
          produitId,
          marcheId,
          sourceId: source.id,
          typePrix: r.typePrix,
          valeur: r.valeur,
          devise: r.devise || "XOF",
          unite: "kg",
          dateReleve: new Date(`${r.date}T00:00:00.000Z`),
          fiabilite: "OFFICIEL" as const,
          notes: `FAO GIEWS FPMA — ${r.marcheNom.trim()} (${r.iso3}), prix ${r.typePrix === "GROS" ? "de gros" : "de détail"} mensuel`,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    const res = await prisma.prixReleve.createMany({ data, skipDuplicates: true });

    await prisma.source.update({
      where: { code: "FAO_FPMA" },
      data: { statutDernier: "OK", derniereExecution: new Date(), messageErreur: null },
    }).catch(() => {});

    return Response.json({ ok: true, importes: res.count, recus: rows.length, marches: Object.keys(marcheMap).length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
