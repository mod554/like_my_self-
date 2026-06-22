export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";

// Retourne les derniers taux de change disponibles en BD
// + fallback ECB live si la BD n'a pas de taux récent (< 2h)
export async function GET() {
  const now = new Date();
  const deuxHeuresAvant = new Date(now.getTime() - 2 * 60 * 60 * 1000);

  // Paires de devises à retourner
  const paires = [
    { src: "USD", dest: "XOF" },
    { src: "USD", dest: "EUR" },
    { src: "EUR", dest: "USD" },
    { src: "EUR", dest: "XOF" },
    { src: "USD", dest: "NGN" },
    { src: "USD", dest: "GHS" },
  ];

  const result: Record<string, { taux: number; source: string; date: string }> = {};

  for (const { src, dest } of paires) {
    const row = await prisma.tauxChange.findFirst({
      where: { deviseSrc: src, deviseDest: dest },
      orderBy: { dateReleve: "desc" },
    });

    if (row) {
      result[`${src}/${dest}`] = {
        taux: Number(row.taux),
        source: row.sourceCode,
        date: row.dateReleve.toISOString(),
      };
    }
  }

  // Si taux USD/XOF manquant ou vieux, calculer via EUR fixe
  const xofEntry = result["USD/XOF"];
  if (!xofEntry || new Date(xofEntry.date) < deuxHeuresAvant) {
    const eurUsd = result["EUR/USD"]?.taux ?? 1.09;
    const xofPerUsd = 655.957 / eurUsd;
    result["USD/XOF"] = { taux: xofPerUsd, source: "CALCULE_EUR_XOF", date: now.toISOString() };
    result["EUR/XOF"] = { taux: 655.957, source: "FIXE_LEGAL", date: now.toISOString() };
  }

  // Récupérer aussi en temps réel depuis frankfurter si pas assez frais
  const hasRecent = Object.values(result).some(
    (v) => new Date(v.date) > deuxHeuresAvant
  );

  if (!hasRecent) {
    try {
      const res = await fetch("https://api.frankfurter.app/latest?from=USD&to=EUR,GBP,NGN,GHS", {
        signal: AbortSignal.timeout(8_000),
      });
      if (res.ok) {
        const data = await res.json() as { rates: Record<string, number>; date: string };
        for (const [dest, taux] of Object.entries(data.rates)) {
          result[`USD/${dest}`] = { taux: Number(taux), source: "FRANKFURTER_LIVE", date: new Date().toISOString() };
        }
        const eurRate = data.rates["EUR"];
        if (eurRate) {
          result["USD/XOF"] = { taux: 655.957 / eurRate, source: "CALCULE_EUR_XOF", date: new Date().toISOString() };
          result["EUR/USD"] = { taux: 1 / eurRate, source: "FRANKFURTER_LIVE", date: new Date().toISOString() };
        }
      }
    } catch {
      // Échec silencieux — les valeurs BD sont déjà dans result
    }
  }

  return Response.json({
    ok: true,
    ts: now.toISOString(),
    taux: result,
  });
}
