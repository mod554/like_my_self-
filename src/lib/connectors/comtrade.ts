// Connecteur UN Comtrade — valeurs unitaires d'export (prix FOB implicites)
// Source : https://comtradeapi.un.org/public/v1/preview — données douanières
// officielles des Nations Unies, sans clé. Fiabilité : OFFICIEL, fréquence annuelle.
// Prix = primaryValue (USD) / netWgt (kg) * 1000 → USD/tonne.
// Couvre le cajou brut (HS 080131) et la noix de cola (HS 080270) — les deux
// matières premières sans série de prix dans les autres sources automatisables.

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "COMTRADE_UN";
const API = "https://comtradeapi.un.org/public/v1/preview/C/A/HS";

interface ComtradeRow {
  period: number | string;
  primaryValue: number | null;
  netWgt: number | null;
  partnerCode: number;
}

interface Cible {
  produitCode: string;
  marcheCode: string;
  reporterCode: number; // code pays ONU M49
  cmdCode: string;      // code HS
  label: string;
}

const CIBLES: Cible[] = [
  { produitCode: "CAJOU_RCN",  marcheCode: "ABIDJAN_RCN",  reporterCode: 384, cmdCode: "080131", label: "Cajou RCN CIV" },
  { produitCode: "COLA_ROUGE", marcheCode: "ABIDJAN_COLA", reporterCode: 384, cmdCode: "080270", label: "Cola CIV" },
  { produitCode: "COLA_ROUGE", marcheCode: "LAGOS_COLA",   reporterCode: 566, cmdCode: "080270", label: "Cola NGA" },
  { produitCode: "COLA_NOIX",  marcheCode: "ABIDJAN_COLA", reporterCode: 384, cmdCode: "080270", label: "Cola (noix fraîche) CIV — valeur unitaire export HS080270" },
];

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function fetchUnitValue(reporter: number, cmd: string, annee: number): Promise<number | null> {
  const url = `${API}?reporterCode=${reporter}&period=${annee}&cmdCode=${cmd}&flowCode=X&partnerCode=0`;
  const res = await fetch(url, {
    headers: {
      "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120",
      "Accept": "application/json",
    },
    signal: AbortSignal.timeout(20_000),
  });
  if (res.status === 429) throw new Error("429 rate limit Comtrade");
  if (!res.ok) throw new Error(`Comtrade HTTP ${res.status}`);
  const json = await res.json() as { data?: ComtradeRow[] };
  const row = (json.data ?? []).find((r) => Number(r.partnerCode) === 0) ?? (json.data ?? [])[0];
  if (!row?.primaryValue || !row?.netWgt || row.netWgt <= 0) return null;
  return Math.round((row.primaryValue / row.netWgt) * 1000 * 100) / 100;
}

export class ComtradeConnector implements Connector {
  code = SOURCE_CODE;
  nom = "UN Comtrade — Valeurs unitaires export cajou & cola (FOB, officiel ONU)";
  frequenceCron = "0 6 * * *"; // quotidien — remplit progressivement l'historique

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD — relancer /api/init`);

      const anneeCourante = new Date().getFullYear();
      // 2 années récentes + 1 année d'archive tournante — l'historique 8 ans se
      // complète au fil des runs quotidiens sans dépasser le rate limit Comtrade
      const archive = anneeCourante - 3 - (new Date().getDate() % 5);
      const annees = [anneeCourante - 1, anneeCourante - 2, archive];

      for (const cible of CIBLES) {
        const produit = await prisma.produit.findUnique({ where: { code: cible.produitCode } });
        const marche = await prisma.marche.findUnique({ where: { code: cible.marcheCode } });
        if (!produit || !marche) {
          resultat.erreurs.push(`${cible.label}: produit/marché introuvable en BD`);
          resultat.nbErreurs++;
          continue;
        }

        for (const annee of annees) {
          // Déjà en base pour cette année ? — évite un appel API inutile
          const dateReleve = new Date(`${annee}-07-01T00:00:00.000Z`);
          const existe = await prisma.prixReleve.findFirst({
            where: { produitId: produit.id, marcheId: marche.id, sourceId: source.id, dateReleve },
            select: { id: true },
          });
          if (existe) continue;

          let usdParTonne: number | null = null;
          try {
            usdParTonne = await fetchUnitValue(cible.reporterCode, cible.cmdCode, annee);
          } catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            resultat.erreurs.push(`${cible.label} ${annee}: ${msg.slice(0, 60)}`);
            resultat.nbErreurs++;
            if (msg.includes("429")) await pause(5_000);
            continue;
          } finally {
            await pause(2_500); // pacing rate limit Comtrade public
          }
          if (usdParTonne === null || usdParTonne <= 0) continue;

          try {
            await prisma.prixReleve.create({
              data: {
                produitId: produit.id,
                marcheId: marche.id,
                sourceId: source.id,
                typePrix: "FOB",
                valeur: usdParTonne,
                devise: "USD",
                unite: "tonne",
                dateReleve,
                fiabilite: "OFFICIEL",
                notes: `UN Comtrade — valeur unitaire export HS ${cible.cmdCode} ${annee} (monde)`,
              },
            });
            resultat.nbImportes++;
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            if (!msg.includes("Unique constraint")) {
              resultat.erreurs.push(`${cible.label} ${annee}: ${msg.slice(0, 60)}`);
              resultat.nbErreurs++;
            }
          }
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "PARTIEL"
        : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 2).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} valeurs unitaires Comtrade importées`,
          detail: { erreurs: resultat.erreurs.slice(0, 5) },
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
