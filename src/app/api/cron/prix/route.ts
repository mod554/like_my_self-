// Cron données prix — connecteurs marchés (WorldBank, FAO, IMF, IndexMundi, RESIMAO, ConseilAnacarde)
// Déclenché toutes les heures par Vercel Cron (Pro) ou une fois par jour (Hobby)
export const dynamic = "force-dynamic";
export const maxDuration = 60;

import { WorldBankConnector } from "@/lib/connectors/worldbank";
import { FaoFpmaConnector } from "@/lib/connectors/fao-fpma";
import { UsdaFasConnector } from "@/lib/connectors/usda-fas";
import { ConseilAnacardeCiConnector } from "@/lib/connectors/conseil-anacarde";
import { ResimaoConnector } from "@/lib/connectors/resimao";
import { IndexMundiConnector } from "@/lib/connectors/indexmundi";

export async function GET(req: Request) {
  const authHeader = req.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  // Run all price connectors in parallel (each has its own 60s budget)
  const connectors = [
    new WorldBankConnector(),
    new FaoFpmaConnector(),
    new UsdaFasConnector(),
    new ConseilAnacardeCiConnector(),
    new ResimaoConnector(),
    new IndexMundiConnector(),
  ];

  const results = await Promise.allSettled(connectors.map((c) => c.run()));

  return Response.json({
    ok: true,
    ts: new Date().toISOString(),
    results: results.map((r, i) => ({
      code: connectors[i].code,
      succes: r.status === "fulfilled" && r.value.nbErreurs === 0,
      nbImportes: r.status === "fulfilled" ? r.value.nbImportes : 0,
      erreur: r.status === "rejected" ? (r.reason instanceof Error ? r.reason.message : String(r.reason)) : undefined,
    })),
  });
}
