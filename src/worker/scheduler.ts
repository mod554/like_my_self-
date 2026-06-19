// Worker de planification des connecteurs
// Lancement : npx tsx src/worker/scheduler.ts

import cron from "node-cron";
import { WorldBankConnector } from "@/lib/connectors/worldbank";
import type { Connector } from "@/lib/connectors/base";

const CONNECTEURS: Connector[] = [new WorldBankConnector()];

console.log("🕐 Scheduler démarré — connecteurs actifs :");
for (const c of CONNECTEURS) {
  console.log(`   [${c.code}] cron: ${c.frequenceCron}`);

  cron.schedule(c.frequenceCron, async () => {
    console.log(`\n⏳ [${c.code}] Démarrage à ${new Date().toISOString()}`);
    try {
      const result = await c.run();
      console.log(
        `✅ [${c.code}] Terminé : ${result.nbImportes} importés, ${result.nbErreurs} erreurs`
      );
      if (result.erreurs.length > 0) {
        console.warn("  Erreurs :", result.erreurs);
      }
    } catch (err) {
      console.error(`❌ [${c.code}] Erreur fatale :`, err);
    }
  });
}

// Permettre un lancement manuel via argument
const arg = process.argv[2];
if (arg === "--run-now") {
  const code = process.argv[3];
  const connecteur = code
    ? CONNECTEURS.find((c) => c.code === code)
    : CONNECTEURS[0];

  if (!connecteur) {
    console.error(`Connecteur "${code}" introuvable`);
    process.exit(1);
  }

  console.log(`\n▶  Exécution immédiate : ${connecteur.code}`);
  connecteur.run().then((r) => {
    console.log("Résultat :", r);
    process.exit(0);
  });
}
