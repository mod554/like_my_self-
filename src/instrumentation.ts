export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  // Run only once per server instance — idempotent operations (IF NOT EXISTS / findUnique)
  try {
    const { runMigrate, runInit } = await import("./lib/setup");
    await runMigrate();
    await runInit();
  } catch (e) {
    // Non-fatal: log and continue, the app can still serve requests
    console.error("[instrumentation] setup failed:", e instanceof Error ? e.message : e);
  }
}
