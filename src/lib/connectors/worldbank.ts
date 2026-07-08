// Connecteur World Bank — Commodity Price Data (Pink Sheet)
// Source : https://api.worldbank.org/v2/ — Licence CC-BY 4.0 — PUBLIC
// Fréquence : mensuelle

import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

// World Bank Global Economic Monitor Commodities — maize price USD/tonne monthly
// Correct indicator: PMAIZMMT (no .USD suffix — currency is built-in to the series)
const INDICATEUR_MAIS = "PMAIZMMT";
const SOURCE_CODE = "WORLD_BANK_PINK";

interface WBDataPoint {
  date: string; // "2024M11"
  value: number | null;
}

function parseDate(wbDate: string): Date | null {
  const matchMois = wbDate.match(/^(\d{4})M(\d{2})$/);
  if (matchMois) {
    return new Date(`${matchMois[1]}-${matchMois[2]}-01T00:00:00.000Z`);
  }
  const matchAn = wbDate.match(/^(\d{4})$/);
  if (matchAn) {
    return new Date(`${matchAn[1]}-01-01T00:00:00.000Z`);
  }
  return null;
}

// Fallback : le Pink Sheet officiel (XLSX mensuel) — l'API v2 ne sert plus
// les series commodities. Feuille "Monthly Prices", colonne "Maize".
const PINK_SHEET_XLSX =
  "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx";

// Cible d'une série Pink Sheet : produit/marché en base + matcheur de colonne
// + facteur de conversion vers USD/tonne (les unités du Pink Sheet varient :
// maïs/huile de palme en $/mt ; caoutchouc en $/kg → ×1000).
interface CiblePink {
  produitCode: string;
  marcheCode: string;
  colonneMatch: RegExp; // testé sur l'en-tête de colonne
  facteurTonne: number; // multiplie la valeur brute pour obtenir USD/tonne
  label: string;
}

const CIBLES_PINK: CiblePink[] = [
  { produitCode: "HUILE_PALME", marcheCode: "MONDIAL_PALME_WB", colonneMatch: /palm\s*oil/i,               facteurTonne: 1,    label: "Huile de palme" },
  { produitCode: "CAOUTCHOUC",  marcheCode: "MONDIAL_HEVEA_WB", colonneMatch: /rubber.*(tsr20|rss3|sgp)/i, facteurTonne: 1000, label: "Caoutchouc" },
];

// Charge le classeur Pink Sheet une seule fois et renvoie la feuille mensuelle.
async function chargerFeuillePink() {
  const ExcelJS = (await import("exceljs")).default;
  const res = await fetch(PINK_SHEET_XLSX, {
    headers: { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" },
    signal: AbortSignal.timeout(45_000),
  });
  if (!res.ok) throw new Error(`Pink Sheet XLSX HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(buf as unknown as ArrayBuffer);
  const feuille = wb.getWorksheet("Monthly Prices") ?? wb.worksheets[0];
  if (!feuille) throw new Error("Feuille Monthly Prices introuvable");
  return feuille;
}

type FeuillePink = Awaited<ReturnType<typeof chargerFeuillePink>>;

// Extrait une colonne du Pink Sheet par regex d'en-tête → points bruts.
function extrairePinkSheet(feuille: FeuillePink, colonneMatch: RegExp): WBDataPoint[] {
  let col = -1;
  for (let r = 1; r <= 10 && col < 0; r++) {
    feuille.getRow(r).eachCell((cell, c) => {
      const v = String(cell.value ?? "").trim();
      if (col < 0 && colonneMatch.test(v)) col = c;
    });
  }
  if (col < 0) return [];
  const points: WBDataPoint[] = [];
  feuille.eachRow((row) => {
    const dateCell = String(row.getCell(1).value ?? "");
    if (!/^\d{4}M\d{2}$/.test(dateCell)) return;
    const val = Number(row.getCell(col).value);
    if (isFinite(val) && val > 0) points.push({ date: dateCell, value: val });
  });
  return points.slice(-60);
}

async function fetchPinkSheetMaize(): Promise<WBDataPoint[]> {
  const feuille = await chargerFeuillePink();
  const points = extrairePinkSheet(feuille, /^maize$/i);
  if (points.length === 0) throw new Error("Colonne Maize introuvable dans le Pink Sheet");
  return points;
}

async function fetchWBData(url: string): Promise<WBDataPoint[]> {
  const res = await fetch(url, {
    headers: { "Accept": "application/json", "User-Agent": "Mozilla/5.0" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) throw new Error(`API World Bank — HTTP ${res.status}`);
  const json = await res.json() as [unknown, WBDataPoint[]];
  return Array.isArray(json) && Array.isArray(json[1]) ? json[1] : [];
}

export class WorldBankConnector implements Connector {
  code = SOURCE_CODE;
  nom = "World Bank — Commodity Price Data (Pink Sheet)";
  frequenceCron = "0 6 1 * *"; // 1er du mois à 6h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source.update({
      where: { code: SOURCE_CODE },
      data: { statutDernier: "EN_COURS", derniereExecution: debut },
    });

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "MAIS_GRAIN" } });
      if (!produit) throw new Error("Produit MAIS_GRAIN introuvable en BD");

      const marche = await prisma.marche.findUnique({ where: { code: "MONDIAL_MAIS_WB" } });
      if (!marche) throw new Error("Marché MONDIAL_MAIS_WB introuvable en BD");

      // World Bank API — /country/all/indicator/{id} for global commodity series
      // mrv=60 = last 60 monthly values
      // Pink Sheet series live in the GEM Commodities database (source=21)
      const urls = [
        `https://api.worldbank.org/v2/en/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60&source=21`,
        `https://api.worldbank.org/v2/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60&source=21`,
        `https://api.worldbank.org/v2/country/all/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60`,
        `https://api.worldbank.org/v2/en/indicator/${INDICATEUR_MAIS}?format=json&mrv=60&per_page=60`,
      ];
      let donnees: WBDataPoint[] = [];
      for (const u of urls) {
        try {
          donnees = await fetchWBData(u);
          if (donnees.length > 0) break;
        } catch { /* essayer l'URL suivante */ }
      }

      if (donnees.length === 0) {
        // API v2 ne sert plus les commodities — lire le Pink Sheet XLSX officiel
        donnees = await fetchPinkSheetMaize();
      }
      if (donnees.length === 0) {
        throw new Error(`Aucune donnee World Bank (API + Pink Sheet XLSX) pour ${INDICATEUR_MAIS}`);
      }

      for (const point of donnees) {
        if (point.value === null) continue;

        const dateReleve = parseDate(point.date);
        if (!dateReleve) {
          resultat.erreurs.push(`Date non parseable : ${point.date}`);
          resultat.nbErreurs++;
          continue;
        }

        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: "SPOT",
              valeur: point.value,
              devise: "USD",
              unite: "tonne",
              dateReleve,
              fiabilite: "OFFICIEL",
              notes: `World Bank Pink Sheet — ${INDICATEUR_MAIS} — ${point.date}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Erreur insertion ${point.date} : ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      // Huile de palme + caoutchouc — mêmes séries mensuelles Pink Sheet
      try {
        const feuille = await chargerFeuillePink();
        for (const cible of CIBLES_PINK) {
          const prod = await prisma.produit.findUnique({ where: { code: cible.produitCode } });
          const mar = await prisma.marche.findUnique({ where: { code: cible.marcheCode } });
          if (!prod || !mar) {
            resultat.erreurs.push(`${cible.label}: produit/marché absent — lancer /api/init`);
            resultat.nbErreurs++;
            continue;
          }
          const pts = extrairePinkSheet(feuille, cible.colonneMatch);
          if (pts.length === 0) {
            resultat.erreurs.push(`${cible.label}: colonne introuvable dans le Pink Sheet`);
            resultat.nbErreurs++;
            continue;
          }
          const data = pts
            .map((p) => {
              const d = parseDate(p.date);
              if (!d || p.value === null) return null;
              return {
                produitId: prod.id, marcheId: mar.id, sourceId: source.id,
                typePrix: "SPOT", valeur: Math.round(p.value * cible.facteurTonne * 100) / 100,
                devise: "USD", unite: "tonne", dateReleve: d, fiabilite: "OFFICIEL" as const,
                notes: `World Bank Pink Sheet — ${cible.label} — ${p.date}`,
              };
            })
            .filter((x): x is NonNullable<typeof x> => x !== null);
          const r = await prisma.prixReleve.createMany({ data, skipDuplicates: true });
          resultat.nbImportes += r.count;
        }
      } catch (e) {
        resultat.erreurs.push(`Pink Sheet palme/hévéa: ${e instanceof Error ? e.message.slice(0, 60) : e}`);
        resultat.nbErreurs++;
      }

      const fin = new Date();
      // 0 nouvel import sans erreur = dédup active, données déjà à jour → OK
      const statut = resultat.nbErreurs > 0
        ? (resultat.nbImportes > 0 ? "PARTIEL" : "ERREUR")
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
          message: `${resultat.nbImportes} relevés importés`,
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
