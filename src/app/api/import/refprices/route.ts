export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/refprices — prix de référence cajou & cola collectés côté
// GitHub Actions (IP propre : Selina Wamucii bloque le proxy/Vercel).
// Source SELINA_WAMUCII : prix indicatifs export USD/kg par pays, MAJ mensuelle.
// Protégé par CRON_SECRET si défini.

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface LigneRef {
  filiere: string;   // CAJOU | COLA
  pays: string;      // "India", "Benin", "Nigeria"…
  usdParKg: number;  // prix indicatif USD/kg
  asOf?: string;     // "2026-07" (mois de référence) ; défaut = mois courant
}

// filière → produit + marché suffixe
const FILIERE_PRODUIT: Record<string, string> = { CAJOU: "CAJOU_RCN", COLA: "COLA_NOIX" };

function normCode(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 30);
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
    const body = await req.json() as { rows?: LigneRef[] };
    const rows = (body.rows ?? []).filter(
      (r) => FILIERE_PRODUIT[r?.filiere] && r?.pays?.trim()
        && isFinite(r.usdParKg) && r.usdParKg > 0 && r.usdParKg < 1000
    ).slice(0, 200);
    if (rows.length === 0) {
      return Response.json({ error: "Aucune ligne valide" }, { status: 400 });
    }

    const source = await prisma.source.upsert({
      where: { code: "SELINA_WAMUCII" },
      update: { derniereExecution: new Date(), statutDernier: "OK", messageErreur: null },
      create: {
        code: "SELINA_WAMUCII",
        nom: "Selina Wamucii — prix de référence export (cajou & cola)",
        type: "MANUEL",
        endpoint: "https://www.selinawamucii.com/insights/prices/",
        frequence: "MENSUEL",
        fiabiliteDefaut: "INDICATIF",
        licence: "PUBLIC",
        description: "Prix indicatifs export USD/kg par pays producteur, mis à jour mensuellement.",
        statutDernier: "OK",
        derniereExecution: new Date(),
      },
    });

    const produits = await prisma.produit.findMany({ where: { code: { in: Object.values(FILIERE_PRODUIT) } } });
    const produitMap = Object.fromEntries(produits.map((p) => [p.code, p.id]));

    // Upsert zones (pays) + marchés (un par pays × filière)
    const marcheMap: Record<string, string> = {};
    for (const r of rows) {
      const paysCode = normCode(r.pays);
      const cle = `${r.filiere}|${paysCode}`;
      if (marcheMap[cle]) continue;
      const zone = await prisma.zone.upsert({
        where: { code: paysCode },
        update: {},
        create: { code: paysCode, nom: r.pays.trim(), type: "PAYS" },
      });
      const marcheCode = `SELINA_${paysCode}_${r.filiere}`.slice(0, 40);
      const m = await prisma.marche.upsert({
        where: { code: marcheCode },
        update: {},
        create: {
          code: marcheCode,
          nom: `${r.pays.trim()} — ${r.filiere === "CAJOU" ? "cajou" : "cola"} (Selina Wamucii)`,
          zoneId: zone.id,
          devise: "USD",
          type: "FOB",
          description: "Prix de référence export indicatif — Selina Wamucii",
        },
      });
      marcheMap[cle] = m.id;
    }

    const now = new Date();
    const data = rows
      .map((r) => {
        const produitId = produitMap[FILIERE_PRODUIT[r.filiere]];
        const marcheId = marcheMap[`${r.filiere}|${normCode(r.pays)}`];
        if (!produitId || !marcheId) return null;
        const m = r.asOf && /^\d{4}-\d{2}$/.test(r.asOf)
          ? new Date(`${r.asOf}-01T00:00:00.000Z`)
          : new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
        return {
          produitId,
          marcheId,
          sourceId: source.id,
          typePrix: "SPOT",
          valeur: Math.round(r.usdParKg * 1000 * 100) / 100, // USD/kg → USD/tonne
          devise: "USD",
          unite: "tonne",
          dateReleve: m,
          fiabilite: "INDICATIF" as const,
          notes: `Selina Wamucii — prix indicatif export ${r.pays.trim()} (${r.usdParKg} USD/kg)`,
        };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);

    const res = await prisma.prixReleve.createMany({ data, skipDuplicates: true });
    return Response.json({ ok: true, importes: res.count, recus: rows.length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
