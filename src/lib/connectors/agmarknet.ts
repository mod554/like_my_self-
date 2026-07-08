// Connecteur AGMARKNET (Inde) — prix quotidiens du cajou sur les mandis
// Source : data.gov.in « Current Daily Price of Various Commodities (Mandi) »
// Commodity = "Cashewnuts". Prix en INR/quintal → USD/tonne (taux INR/USD fixe,
// noté). Chaque (mandi × variété) devient une série de marché distincte.

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "AGMARKNET_INDIA";
const RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070";
// Clé publique de démonstration data.gov.in (surchargée par AGMARKNET_KEY si défini)
const DEMO_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b";
// Taux INR→USD indicatif (pas de série INR dans le module taux) — noté dans les prix
const INR_PAR_USD = 83;

interface RecAgm {
  market?: string; variety?: string; state?: string;
  arrival_date?: string; // "08/07/2026"
  modal_price?: number | string;
}

function normCode(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 34);
}

function parseDateInde(d: string): Date | null {
  const m = d?.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  return m ? new Date(`${m[3]}-${m[2]}-${m[1]}T00:00:00.000Z`) : null;
}

export class AgmarknetConnector implements Connector {
  code = SOURCE_CODE;
  nom = "AGMARKNET Inde — prix cajou quotidiens (mandis)";
  frequenceCron = "0 8 * * *"; // quotidien

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable — lancer /api/init`);
      const produit = await prisma.produit.findUnique({ where: { code: "CAJOU_RCN" } });
      const zone = await prisma.zone.findUnique({ where: { code: "INDE" } });
      if (!produit || !zone) throw new Error("Produit CAJOU_RCN ou zone INDE absent — lancer /api/init");

      // Auto-nettoyage : le produit est le cajou BRUT (RCN). On purge d'éventuels
      // relevés « kernel » (variété non-raw, ex. Mumbai « Other » à ~13 500 $/t)
      // importés avant ce filtre, qui fausseraient les statistiques RCN.
      await prisma.prixReleve.deleteMany({
        where: { sourceId: source.id, NOT: { notes: { contains: "Raw" } } },
      }).catch(() => {});

      const key = process.env.AGMARKNET_KEY || DEMO_KEY;
      const url = `https://api.data.gov.in/resource/${RESOURCE}?api-key=${key}&format=json&limit=100&filters%5Bcommodity%5D=Cashewnuts`;
      const res = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "Accept": "application/json" },
        signal: AbortSignal.timeout(25_000),
      });
      if (!res.ok) throw new Error(`data.gov.in HTTP ${res.status}`);
      const json = await res.json() as { records?: RecAgm[] };
      const records = json.records ?? [];

      for (const r of records) {
        const modal = Number(r.modal_price);
        const dateReleve = parseDateInde(r.arrival_date ?? "");
        const mandi = (r.market ?? "").trim();
        const variete = (r.variety ?? "NA").trim();
        if (!isFinite(modal) || modal <= 0 || !dateReleve || !mandi) continue;
        // Produit = cajou BRUT (RCN) → on ne garde que les variétés « raw ».
        // Les variétés transformées (kernel/« Other », ~13 500 $/t) sont ignorées.
        if (!/raw/i.test(variete)) continue;

        // INR/quintal → USD/tonne : ×10 (quintal→tonne) puis ÷ taux INR/USD
        const usdTonne = Math.round((modal * 10 / INR_PAR_USD) * 100) / 100;
        const marcheCode = `AGM_${normCode(mandi)}_${normCode(variete)}`.slice(0, 40);

        const marche = await prisma.marche.upsert({
          where: { code: marcheCode },
          update: {},
          create: {
            code: marcheCode,
            nom: `${mandi} — cajou ${variete} (AGMARKNET)`,
            zoneId: zone.id, devise: "USD", type: "GROSSISTE",
            description: `Mandi indien ${r.state ?? ""} — cajou (AGMARKNET/data.gov.in)`.trim(),
          },
        });

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id, marcheId: marche.id, sourceId: source.id,
              typePrix: "GROS", valeur: usdTonne, devise: "USD", unite: "tonne",
              dateReleve, fiabilite: "OFFICIEL",
              notes: `AGMARKNET ${mandi} (${variete}) — ${modal} INR/quintal @ ${INR_PAR_USD} INR/USD — ${r.arrival_date}`,
            },
          });
          resultat.nbImportes++;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) { resultat.erreurs.push(`${mandi}: ${msg.slice(0, 50)}`); resultat.nbErreurs++; }
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0 ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR") : "OK";
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 2).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} prix cajou mandis indiens (${records.length} relevés reçus)`,
          detail: { erreurs: resultat.erreurs.slice(0, 5) },
        },
      }).catch(() => {});

      return { ...resultat, fin };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();
      await prisma.source
        .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "ERREUR", messageErreur: msg } })
        .catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
