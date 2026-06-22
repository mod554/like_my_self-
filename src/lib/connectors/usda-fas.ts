// Connecteur IMF Primary Commodity Prices — Maïs mondial
// Source : https://www.imf.org/external/datamapper/api/v1/ — Domaine public FMI
// Fréquence : mensuelle (mise à jour IMF ~fin de mois)
// Couverture : Prix maïs mondial (USD/tonne) + indicateurs agronomiques

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "USDA_FAS_PSD";

// IMF Primary Commodity Prices API (public, no auth required)
// PMAIZE = Maize (corn), USD per metric tonne
// PRAWM = Raw Materials composite index (backup)
const IMF_BASE = "https://www.imf.org/external/datamapper/api/v1";

interface ImfIndicatorValues {
  [countryOrWorld: string]: Record<string, number>;
}

interface ImfResponse {
  values: {
    [indicator: string]: ImfIndicatorValues;
  };
}

async function fetchImfCommodityPrices(indicator: string): Promise<Record<string, number>> {
  const url = `${IMF_BASE}/${indicator}`;
  const response = await fetch(url, {
    headers: { Accept: "application/json", "User-Agent": "AfricaAgro-AgriTerminal/1.0" },
    signal: AbortSignal.timeout(45_000),
  });

  if (!response.ok) throw new Error(`IMF API HTTP ${response.status} — ${indicator}`);

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) {
    throw new Error(`IMF API returned non-JSON (${contentType})`);
  }

  const json = (await response.json()) as ImfResponse;
  // World aggregate is under "WLD" or country-level data
  const indicatorData = json.values?.[indicator];
  if (!indicatorData) throw new Error(`Pas de données IMF pour ${indicator}`);

  // Prefer WLD (world), fallback to first available series
  return indicatorData["WLD"] ?? Object.values(indicatorData)[0] ?? {};
}

export class UsdaFasConnector implements Connector {
  code = SOURCE_CODE;
  nom = "IMF — Primary Commodity Prices (Maïs mondial)";
  frequenceCron = "0 14 12 * *"; // 12 du mois à 14h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } });
      if (!produit) throw new Error("Produit MAIS_GRAIN introuvable");

      const marche =
        (await prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_USDA" } }).catch(() => null)) ??
        (await prisma.marche.findFirst({ where: { code: { contains: "MAIS" } } }).catch(() => null));

      if (!marche) throw new Error("Aucun marché MAIS trouvé en BD");

      // Prix maïs IMF (USD/tonne, annuel)
      const prixAnnuels = await fetchImfCommodityPrices("PMAIZE");

      const currentYear = new Date().getFullYear();
      const entries = Object.entries(prixAnnuels).filter(
        ([year, val]) => parseInt(year) >= currentYear - 6 && val > 0
      );

      for (const [year, valeur] of entries) {
        const dateReleve = new Date(`${year}-07-01T00:00:00.000Z`);

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "SPOT",
              valeur,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `IMF Primary Commodity Prices — PMAIZE — ${year}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Prix ${year}: ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      // Créer une actualité résumé pour les données IMF
      if (entries.length > 0) {
        const filiere = await prisma.filiere.findUnique({ where: { code: "MAIS" } }).catch(() => null);
        if (filiere) {
          const dernierEntry = entries.sort(([a], [b]) => b.localeCompare(a))[0];
          const [annee, prix] = dernierEntry;
          try {
            await prisma.actualite.create({
              data: {
                filiereId: filiere.id,
                titre: `IMF Commodity Prices — Maïs ${annee}: ${prix.toFixed(0)} USD/T`,
                lien: "https://www.imf.org/en/Research/commodity-prices",
                source: "IMF Primary Commodity Prices",
                resume: `Prix mondial du maïs (PMAIZE) en ${annee} : ${prix.toFixed(2)} USD/tonne. Source : FMI.`,
                datePublication: new Date(`${annee}-07-01T00:00:00.000Z`),
              },
            });
            resultat.nbImportes++;
          } catch {
            // doublon ignoré
          }
        }
      }

      const fin = new Date();
      const statut =
        resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR"
        : resultat.nbErreurs > 0 ? "PARTIEL"
        : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: statut,
          messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null,
        },
      });

      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} entrées importées (IMF Commodity Prices)`,
          detail: { erreurs: resultat.erreurs },
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
