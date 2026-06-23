export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  // Run only once per server instance — idempotent DDL + seed (fast, < 5s)
  try {
    const { runMigrate, runInit } = await import("./lib/setup");
    await runMigrate();
    await runInit();
    console.log("[instrumentation] DB ready");
  } catch (e) {
    console.error("[instrumentation] setup failed:", e instanceof Error ? e.message : e);
  }
  // NOTE: connectors are NOT run here — they take > 60s and would timeout
  // They run via: Vercel Cron (vercel.json), UI buttons, or /api/connectors
}
