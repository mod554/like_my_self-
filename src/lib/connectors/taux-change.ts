// Connecteur Taux de Change en temps réel
// Source : open.er-api.com (ExchangeRate-API — free tier, ECB data)
//          + frankfurter.app (ECB official, backup)
// Fréquence : toutes les heures
// Couverture : USD/XOF, EUR/USD, USD/NGN, USD/GHS, USD/GBP + paires inversées

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "TAUX_CHANGE_LIVE";

// XOF est légalement ancré à EUR : 1 EUR = 655.957 XOF (fixe depuis 1999)
const XOF_PER_EUR_FIXE = 655.957;

// Devises à collecter (relative à USD)
const DEVISES_CIBLES = ["EUR", "XOF", "NGN", "GHS", "GBP", "JPY", "CNY"];

interface ErApiResponse {
  result: string;
  base_code: string;
  rates: Record<string, number>;
  time_last_update_utc?: string;
}

interface FrankfurterResponse {
  base: string;
  rates: Record<string, number>;
  date: string;
}

async function fetchRatesOpenErApi(base: string): Promise<Record<string, number> | null> {
  const url = `https://open.er-api.com/v6/latest/${base}`;
  const res = await fetch(url, {
    headers: { "User-Agent": "AfricaGro-AgriTerminal/1.0" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) return null;
  const json = (await res.json()) as ErApiResponse;
  if (json.result !== "success") return null;
  return json.rates;
}

async function fetchRatesFrankfurter(base: string, targets: string[]): Promise<Record<string, number> | null> {
  const t = targets.filter((c) => c !== "XOF").join(","); // Frankfurter ne supporte pas XOF
  if (!t) return null;
  const url = `https://api.frankfurter.app/latest?from=${base}&to=${t}`;
  const res = await fetch(url, {
    headers: { "User-Agent": "AfricaGro-AgriTerminal/1.0" },
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) return null;
  const json = (await res.json()) as FrankfurterResponse;
  return json.rates ?? null;
}

export class TauxChangeLiveConnector implements Connector {
  code = SOURCE_CODE;
  nom = "Taux de change en temps réel — ECB / open.er-api.com";
  frequenceCron = "0 * * * *"; // Toutes les heures

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const dateReleve = new Date();
      dateReleve.setMinutes(0, 0, 0); // Arrondi à l'heure

      // Tenter open.er-api.com (principal), puis frankfurter.app (backup)
      let ratesFromUsd = await fetchRatesOpenErApi("USD");
      if (!ratesFromUsd) {
        // Backup: frankfurter.app (ECB officiel, ne couvre pas XOF/NGN)
        const fr = await fetchRatesFrankfurter("USD", ["EUR", "GBP", "JPY", "CNY", "GHS"]);
        ratesFromUsd = fr;
      }

      if (!ratesFromUsd) {
        throw new Error("Impossible de récupérer les taux (open.er-api et frankfurter.app indisponibles)");
      }

      // XOF : calculé via EUR si non disponible directement
      if (!ratesFromUsd["XOF"] && ratesFromUsd["EUR"]) {
        // 1 USD = x EUR → 1 USD = x * 655.957 XOF
        ratesFromUsd["XOF"] = ratesFromUsd["EUR"] * XOF_PER_EUR_FIXE;
      }
      // Fallback XOF fixe si toujours manquant
      if (!ratesFromUsd["XOF"]) {
        // 1 EUR ≈ 1.09 USD → 1 USD ≈ 655.957/1.09 ≈ 601.8 XOF
        ratesFromUsd["XOF"] = XOF_PER_EUR_FIXE / 1.09;
      }

      // Paires à stocker (src → dest → valeur)
      const paires: Array<{ src: string; dest: string; taux: number }> = [];

      for (const devise of DEVISES_CIBLES) {
        const rate = ratesFromUsd[devise];
        if (!rate || !isFinite(rate) || rate <= 0) continue;

        // USD → devise
        paires.push({ src: "USD", dest: devise, taux: rate });
        // devise → USD
        paires.push({ src: devise, dest: "USD", taux: 1 / rate });
      }

      // EUR → XOF fixe légal
      paires.push({ src: "EUR", dest: "XOF", taux: XOF_PER_EUR_FIXE });
      paires.push({ src: "XOF", dest: "EUR", taux: 1 / XOF_PER_EUR_FIXE });

      // EUR → USD via le taux USD→EUR inversé
      if (ratesFromUsd["EUR"]) {
        paires.push({ src: "EUR", dest: "USD", taux: 1 / ratesFromUsd["EUR"] });
        paires.push({ src: "USD", dest: "EUR", taux: ratesFromUsd["EUR"] });
      }

      for (const p of paires) {
        try {
          await prisma.tauxChange.upsert({
            where: {
              deviseSrc_deviseDest_dateReleve_sourceCode: {
                deviseSrc: p.src,
                deviseDest: p.dest,
                dateReleve: dateReleve,
                sourceCode: SOURCE_CODE,
              },
            },
            update: { taux: p.taux },
            create: {
              deviseSrc: p.src,
              deviseDest: p.dest,
              taux: p.taux,
              dateReleve,
              sourceCode: SOURCE_CODE,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          resultat.erreurs.push(`${p.src}/${p.dest}: ${msg}`);
          resultat.nbErreurs++;
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs[0] : null },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin: new Date(), statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} taux importés`,
          detail: { taux: paires.slice(0, 6), erreurs: resultat.erreurs },
        },
      });

      return { ...resultat, fin };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();
      await prisma.source
        .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "ERREUR", messageErreur: msg } })
        .catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
