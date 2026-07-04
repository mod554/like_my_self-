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
    // GDELT rejette les mots uniques entre guillemets dans un bloc OR
    query: '(maize OR corn) (price OR market OR harvest OR export OR africa OR afrique)',
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

      // SEQUENTIEL avec espacement : GDELT limite les requetes rapprochees
      // depuis une meme IP (HTTP 429 en parallele). 3 requetes espacees de 4s
      // + un retry apres 10s si 429 — reste bien sous le budget 60s serverless.
      const attendre = (ms: number) => new Promise((r) => setTimeout(r, ms));
      const reponses: Array<{ filiereCode: string; data?: GdeltResponse; erreur?: string }> = [];
      const budgetMs = 32_000; // garde-fou : la route entière doit tenir sous 60s
      for (const [i, { filiereCode, query }] of REQUETES.entries()) {
        if (Date.now() - debut.getTime() > budgetMs) {
          reponses.push({ filiereCode, erreur: "budget temps épuisé — au prochain run" });
          continue;
        }
        if (i > 0) await attendre(2_500);
        const url =
          `${API_BASE}?query=${encodeURIComponent(query)}` +
          `&mode=ArtList&format=json&maxrecords=40&timespan=3d&sort=DateDesc`;
        try {
          reponses.push({ filiereCode, data: await fetchJson<GdeltResponse>(url, { timeoutMs: 12_000, retries: 0 }) });
        } catch (e) {
          // 429 = rate-limit temporaire GDELT — le cron quotidien réessaiera
          reponses.push({ filiereCode, erreur: (e instanceof Error ? e.message : String(e)).slice(0, 80) });
        }
      }

      for (const rep of reponses) {
        const filiereId = filiereMap[rep.filiereCode];
        if (!filiereId) continue;
        if ("erreur" in rep && rep.erreur) {
          resultat.erreurs.push(`GDELT ${rep.filiereCode}: ${rep.erreur}`);
          resultat.nbErreurs++;
          continue;
        }
        const data = (rep as { data: GdeltResponse }).data;

        // Insertion groupee — un create par article depasse les 60s serverless
        const dejaVus = new Set(
          (await prisma.actualite.findMany({
            where: { filiereId, lien: { in: (data.articles ?? []).map((a) => a.url?.trim()).filter(Boolean) as string[] } },
            select: { lien: true },
          })).map((a) => a.lien)
        );
        const aInserer = (data.articles ?? [])
          .filter((a) => a.title?.trim() && a.url?.trim() && !dejaVus.has(a.url.trim()))
          .map((a) => ({
            filiereId,
            titre: a.title.trim().slice(0, 255),
            lien: a.url.trim(),
            source: `GDELT · ${a.domain ?? "web"}${a.sourcecountry ? ` (${a.sourcecountry})` : ""}`,
            datePublication: parseSeendate(a.seendate),
          }));
        if (aInserer.length > 0) {
          try {
            const res = await prisma.actualite.createMany({ data: aInserer, skipDuplicates: true });
            resultat.nbImportes += res.count;
          } catch (err: unknown) {
            resultat.erreurs.push(`Insert ${rep.filiereCode}: ${err instanceof Error ? err.message.slice(0, 60) : err}`);
            resultat.nbErreurs++;
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
