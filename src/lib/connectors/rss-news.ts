// Connecteur RSS — Agrégateur d'actualités agricoles (maïs, cajou, cola)
// Sources : FAO News, Reuters Commodities, USDA RSS, OCA Cajou, West Africa Commodities
// Fréquence : toutes les 6h

import Parser from "rss-parser";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "RSS_NEWS_AGRI";

interface FluxRSS {
  url: string;
  source: string;
  filieres: string[]; // codes filières concernées
  fiabilite: string;
}

const FLUX_RSS: FluxRSS[] = [
  {
    url: "https://www.fao.org/news/rss-feed/en",
    source: "FAO — Food and Agriculture Organization",
    filieres: ["MAIS", "CAJOU"],
    fiabilite: "OFFICIEL",
  },
  {
    url: "https://www.usda.gov/rss/home.rss",
    source: "USDA — United States Department of Agriculture",
    filieres: ["MAIS"],
    fiabilite: "OFFICIEL",
  },
  {
    url: "https://www.reuters.com/news/archive/commoditiesNews.rss",
    source: "Reuters Commodities",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://agritrade.cta.int/Agriculture/Commodities/Cashew-nuts.html?output=rss",
    source: "ACP-EU Trade — Cashew",
    filieres: ["CAJOU"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.ifoam.bio/rss.xml",
    source: "IFOAM — Organic Agriculture",
    filieres: ["MAIS", "CAJOU"],
    fiabilite: "INDICATIF",
  },
];

// Mots-clés pour filtrer les articles pertinents par filière
const KEYWORDS: Record<string, string[]> = {
  MAIS: ["maïs", "mais", "corn", "maize", "céréales", "cereals", "coton", "CBOT", "grain"],
  CAJOU: ["cajou", "cashew", "anacarde", "RCN", "noix de cajou", "Côte d'Ivoire cajou"],
  COLA: ["cola", "kola", "kola nut", "noix de cola", "West Africa"],
};

function articleConcerneFilieres(titre: string, contenu: string, filieresCibles: string[]): string[] {
  const texte = `${titre} ${contenu}`.toLowerCase();
  return filieresCibles.filter((code) => {
    const mots = KEYWORDS[code] ?? [];
    return mots.some((mot) => texte.includes(mot.toLowerCase()));
  });
};

export class RssNewsConnector implements Connector {
  code = SOURCE_CODE;
  nom = "Agrégateur RSS — Actualités agricoles mondiales";
  frequenceCron = "0 */6 * * *"; // Toutes les 6h

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const filieres = await prisma.filiere.findMany({ where: { code: { in: ["MAIS", "CAJOU", "COLA"] } } });
      const filiereMap = Object.fromEntries(filieres.map((f) => [f.code, f.id]));

      const parser = new Parser({
        timeout: 30_000,
        headers: { "User-Agent": "LikeMyself-AgriTerminal/1.0 RSS Reader" },
        customFields: { item: ["summary", "description"] },
      });

      for (const flux of FLUX_RSS) {
        try {
          const feed = await parser.parseURL(flux.url);

          for (const item of feed.items ?? []) {
            const titre = item.title ?? "";
            const contenu = item.contentSnippet ?? item.summary ?? item.content ?? "";
            const lien = item.link ?? "";
            const datePublication = item.pubDate ? new Date(item.pubDate) : new Date();

            if (!titre || !lien) continue;

            // Filtrer par mots-clés
            const filieresConcernees = articleConcerneFilieres(titre, contenu, flux.filieres);
            if (filieresConcernees.length === 0) continue;

            // Créer une actualité par filière concernée
            for (const filiereCode of filieresConcernees) {
              const filiereId = filiereMap[filiereCode];
              if (!filiereId) continue;

              try {
                await prisma.actualite.create({
                  data: {
                    filiereId,
                    titre: titre.slice(0, 255),
                    lien,
                    source: flux.source,
                    resume: contenu.slice(0, 500) || undefined,
                    datePublication,
                  },
                });
                resultat.nbImportes++;
              } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                // Ignorer les doublons (même lien + même filière)
                if (!msg.includes("Unique constraint") && !msg.includes("duplicate")) {
                  resultat.erreurs.push(`Article "${titre.slice(0, 50)}": ${msg}`);
                  resultat.nbErreurs++;
                }
              }
            }
          }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          resultat.erreurs.push(`Flux ${flux.source}: ${msg}`);
          resultat.nbErreurs++;
        }
      }

      const fin = new Date();
      const statut = resultat.nbErreurs > 0 && resultat.nbImportes === 0 ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 3).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} articles importés`,
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
