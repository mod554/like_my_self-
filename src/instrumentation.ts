export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  try {
    const { runMigrate, runInit } = await import("./lib/setup");
    await runMigrate();
    await runInit();
  } catch (e) {
    console.error("[instrumentation] setup failed:", e instanceof Error ? e.message : e);
    return;
  }

  // Trigger all connectors on cold start if no price data exists yet
  try {
    const { prisma } = await import("./lib/db");
    const count = await prisma.prixReleve.count();
    if (count === 0) {
      console.log("[instrumentation] no price data found — triggering all connectors");
      const { CONNECTEURS } = await import("./lib/connectors");
      for (const connector of CONNECTEURS) {
        try {
          const res = await connector.run();
          console.log(`[instrumentation] ${connector.code}: ${res.nbImportes} imported, ${res.nbErreurs} errors`);
        } catch (e) {
          console.error(`[instrumentation] ${connector.code} failed:`, e instanceof Error ? e.message : e);
        }
      }
    }
  } catch (e) {
    console.error("[instrumentation] connector auto-run failed:", e instanceof Error ? e.message : e);
  }
}
