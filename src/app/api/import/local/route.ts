export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/local — reçoit des prix locaux (marchés physiques) collectés
// côté GitHub Actions (IP propre : le bouclier anti-bot Anubis de SIMAGRI-CI
// bloque le proxy/Vercel). Protégé par CRON_SECRET si défini.
// Source SIMAGRI-CI : prix vivriers ivoiriens en FCFA/kg (détail & gros).

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface LigneLocale {
  produitCode: string;   // MAIS_GRAIN (seule filière suivie ici)
  marche: string;        // "BOUAFLE", "KONG", "BOUAKE"…
  typePrix: string;      // DETAIL | GROS
  valeur: number;        // FCFA/kg
  date?: string;         // "2026-07-06" (ISO) ; défaut = aujourd'hui
}

const PRODUITS_AUTORISES = new Set(["MAIS_GRAIN"]);
const TYPES = new Set(["DETAIL", "GROS"]);

function normCode(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
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
    const body = await req.json() as { rows?: LigneLocale[] };
    const rows = (body.rows ?? []).filter(
      (r) => PRODUITS_AUTORISES.has(r?.produitCode) && TYPES.has(r?.typePrix)
        && r?.marche?.trim() && isFinite(r.valeur) && r.valeur > 0 && r.valeur < 100_000
    ).slice(0, 300);
    if (rows.length === 0) {
      return Response.json({ error: "Aucune ligne valide" }, { status: 400 });
    }

    // Zone Côte d'Ivoire — le seed historique l'a créée sous "CI", /api/init
    // sous "COTE_IVOIRE" : on accepte les deux, et on crée "CI" en dernier
    // recours pour rester robuste sur une base vierge.
    const zone =
      (await prisma.zone.findUnique({ where: { code: "CI" } })) ??
      (await prisma.zone.findUnique({ where: { code: "COTE_IVOIRE" } })) ??
      (await prisma.zone.create({ data: { code: "CI", nom: "Côte d'Ivoire", type: "PAYS" } }));

    const source = await prisma.source.upsert({
      where: { code: "SIMAGRI_CI" },
      update: { derniereExecution: new Date(), statutDernier: "OK", messageErreur: null },
      create: {
        code: "SIMAGRI_CI",
        nom: "SIMAGRI Côte d'Ivoire — prix marchés vivriers (détail & gros)",
        type: "MANUEL",
        endpoint: "https://www.simagri-ci.info/prices-entries-grids",
        frequence: "QUOTIDIEN",
        fiabiliteDefaut: "OFFICIEL",
        licence: "PUBLIC",
        description: "Prix physiques FCFA/kg relevés sur les marchés ivoiriens (Bouaflé, Kong, Bouaké…).",
        statutDernier: "OK",
        derniereExecution: new Date(),
      },
    });

    const produits = await prisma.produit.findMany({ where: { code: { in: [...PRODUITS_AUTORISES] } } });
    const produitMap = Object.fromEntries(produits.map((p) => [p.code, p.id]));

    // Upsert des marchés SIMAGRI (un par ville rencontrée)
    const marchesUniques = [...new Set(rows.map((r) => r.marche.trim().toUpperCase()))];
    const marcheMap: Record<string, string> = {};
    for (const nomMarche of marchesUniques) {
      const code = `SIMAGRI_${normCode(nomMarche)}`;
      const m = await prisma.marche.upsert({
        where: { code },
        update: {},
        create: {
          code,
          nom: `${nomMarche} (SIMAGRI-CI)`,
          zoneId: zone.id,
          devise: "XOF",
          type: "SPOT_DOMESTIQUE",
          description: "Marché physique ivoirien — relevé SIMAGRI-CI",
        },
      });
      marcheMap[nomMarche] = m.id;
    }

    const data = rows
      .map((r) => {
        const produitId = produitMap[r.produitCode];
        const marcheId = marcheMap[r.marche.trim().toUpperCase()];
        if (!produitId || !marcheId) return null;
        const d = r.date && /^\d{4}-\d{2}-\d{2}$/.test(r.date) ? new Date(`${r.date}T00:00:00.000Z`) : new Date();
        return {
          produitId,
          marcheId,
          sourceId: source.id,
          typePrix: r.typePrix,
          valeur: r.valeur,
          devise: "XOF",
          unite: "kg",
          dateReleve: d,
          fiabilite: "OFFICIEL" as const,
          notes: `SIMAGRI-CI — prix ${r.typePrix === "GROS" ? "de gros" : "de détail"} ${r.marche.trim()}`,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    const res = await prisma.prixReleve.createMany({ data, skipDuplicates: true });

    return Response.json({ ok: true, importes: res.count, recus: rows.length, marches: marchesUniques.length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
