export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";

// Retourne le dernier prix connu pour chaque produit principal
// + variation par rapport au prix précédent
// Utilisé par le ticker en temps réel dans le header
export async function GET() {
  const produits = await prisma.produit.findMany({
    where: { estDerive: false },
    select: {
      code: true,
      nom: true,
      uniteRef: true,
      filiere: { select: { code: true } },
      prixReleves: {
        orderBy: { dateReleve: "desc" },
        take: 2,
        select: {
          valeur: true,
          devise: true,
          unite: true,
          dateReleve: true,
          fiabilite: true,
          typePrix: true,
        },
      },
    },
  });

  // Taux USD/XOF pour normalisation
  const tauxXof = await prisma.tauxChange.findFirst({
    where: { deviseSrc: "USD", deviseDest: "XOF" },
    orderBy: { dateReleve: "desc" },
  }).catch(() => null);
  const xofPerUsd = tauxXof ? Number(tauxXof.taux) : 655.957;

  const ticker = produits.map((p) => {
    const last = p.prixReleves[0];
    const prev = p.prixReleves[1];

    const valeur = last ? Number(last.valeur) : null;
    const valeurPrev = prev ? Number(prev.valeur) : null;

    const variation = valeur && valeurPrev && valeurPrev !== 0
      ? ((valeur - valeurPrev) / valeurPrev) * 100
      : null;

    // Valeur normalisée en USD/T pour affichage uniforme
    let valeurUsd: number | null = null;
    if (valeur && last) {
      const d = last.devise.toUpperCase();
      const u = last.unite.toLowerCase();
      let usd = d === "XOF" ? valeur / xofPerUsd : d === "EUR" ? valeur * 1.09 : valeur;
      if (u === "kg") usd = usd * 1000;
      else if (u.includes("bushel")) usd = usd * 39.37;
      else if (u === "quintal") usd = usd * 10;
      valeurUsd = Math.round(usd * 100) / 100;
    }

    return {
      code: p.code,
      nom: p.nom,
      filiere: p.filiere.code,
      unite: p.uniteRef,
      valeur,
      valeurUsd,
      devise: last?.devise ?? null,
      uniteReleve: last?.unite ?? null,
      variation: variation ? Math.round(variation * 100) / 100 : null,
      hausse: variation !== null ? variation >= 0 : null,
      dateReleve: last?.dateReleve ?? null,
      fiabilite: last?.fiabilite ?? null,
    };
  });

  // Taux de change pour affichage dans le ticker
  const eurUsd = await prisma.tauxChange.findFirst({
    where: { deviseSrc: "EUR", deviseDest: "USD" },
    orderBy: { dateReleve: "desc" },
  }).catch(() => null);

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    ticker,
    taux: {
      USD_XOF: xofPerUsd,
      EUR_USD: eurUsd ? Number(eurUsd.taux) : 1.09,
      EUR_XOF: 655.957,
    },
  });
}
