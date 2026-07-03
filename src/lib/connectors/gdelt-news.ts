// Connecteur GDELT — Global Database of Events, Language, and Tone
// Basé sur le cours "Collections de données d'actualité à grande échelle" :
// GDELT surveille les médias mondiaux dans 65+ langues, mise à jour toutes les 15 min.
// On utilise l'API DOC 2.0 (JSON, gratuite, sans clé) — adaptée au serverless,
// contrairement aux fichiers WARC de Common Crawl qui exigent un traitement batch.
// Doc : https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

import { prisma } from "@/lib/db";
import { fetchJson } from "./http";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "GDELT_NEWS";
const API_BASE = "https://api.gdeltproject.org/api/v2/doc/doc";

interface GdeltArticle {
  url: string;
  title: string;
  seendate: string; // "20240901T120000Z"
  domain: string;
  language: string;
  sourcecountry: string;
}

interface GdeltResponse {
  articles?: GdeltArticle[];
}

// Requêtes GDELT par filière — vocabulaire multilingue (le cours insiste sur le
// filtrage par mots-clés et langue). GDELT exige des requêtes >= 5 caractères
// et les OR doivent être parenthésés.
const REQUETES: { filiereCode: string; query: string }[] = [
  {
    filiereCode: "MAIS",
    query: '(maize OR corn OR "maïs") (price OR market OR harvest OR export OR "Afrique" OR Africa)',
  },
  {
    filiereCode: "CAJOU",
    query: '(cashew OR anacarde OR "noix de cajou" OR "raw cashew nut")',
  },
  {
    filiereCode: "COLA",
    query: '("kola nut" OR "cola nut" OR "noix de cola" OR "bitter kola")',
  },
];

function parseSeendate(s: string): Date {
  // "20240901T120000Z" → ISO
  const m = s.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?$/);
  if (!m) return new Date();
  return new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}Z`);
}

export class GdeltNewsConnector implements Connector {
  code = SOURCE_CODE;
  nom = "GDELT — Actualités mondiales agricoles (65+ langues, temps réel)";
  frequenceCron = "0 * * * *"; // toutes les heures

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD — relancer /api/init`);

      const filieres = await prisma.filiere.findMany({ where: { code: { in: ["MAIS", "CAJOU", "COLA"] } } });
      const filiereMap = Object.fromEntries(filieres.map((f) => [f.code, f.id]));

      for (const { filiereCode, query } of REQUETES) {
        const filiereId = filiereMap[filiereCode];
        if (!filiereId) continue;

        const url =
          `${API_BASE}?query=${encodeURIComponent(query)}` +
          `&mode=ArtList&format=json&maxrecords=75&timespan=7d&sort=DateDesc`;

        let data: GdeltResponse;
        try {
          data = await fetchJson<GdeltResponse>(url, { timeoutMs: 25_000 });
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          resultat.erreurs.push(`GDELT ${filiereCode}: ${msg.slice(0, 80)}`);
          resultat.nbErreurs++;
          continue;
        }

        for (const art of data.articles ?? []) {
          const titre = art.title?.trim();
          const lien = art.url?.trim();
          if (!titre || !lien) continue;

          try {
            const existe = await prisma.actualite.findFirst({
              where: { lien, filiereId },
              select: { id: true },
            });
            if (existe) continue;

            await prisma.actualite.create({
              data: {
                filiereId,
                titre: titre.slice(0, 255),
                lien,
                source: `GDELT · ${art.domain ?? "web"}${art.sourcecountry ? ` (${art.sourcecountry})` : ""}`,
                resume: undefined,
                datePublication: parseSeendate(art.seendate),
              },
            });
            resultat.nbImportes++;
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            if (!msg.includes("Unique constraint")) {
              resultat.erreurs.push(`"${titre.slice(0, 40)}": ${msg.slice(0, 60)}`);
              resultat.nbErreurs++;
            }
          }
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs >= REQUETES.length ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 2).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} articles GDELT importés (${REQUETES.length} filières)`,
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
