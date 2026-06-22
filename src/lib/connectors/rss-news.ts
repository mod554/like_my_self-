// Connecteur RSS — Agrégateur d'actualités agricoles (maïs, cajou, cola, AOF)
// Sources : 15+ flux RSS publics — FAO, USDA, World Bank, Reuters, Africa Report…
// Fréquence : toutes les 30 minutes

import Parser from "rss-parser";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "RSS_NEWS_AGRI";

interface FluxRSS {
  url: string;
  source: string;
  filieres: string[]; // codes filières — [] = toutes
  fiabilite: string;
  timeout?: number;
}

// 15 flux RSS couvrant agriculture, marchés de matières premières, Afrique de l'Ouest
const FLUX_RSS: FluxRSS[] = [
  // ── Institutions internationales ──────────────────────────────────────────
  {
    url: "https://www.fao.org/news/rss-feed/en",
    source: "FAO — Food and Agriculture Organization",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "OFFICIEL",
  },
  {
    url: "https://www.usda.gov/rss/home.rss",
    source: "USDA — United States Department of Agriculture",
    filieres: ["MAIS"],
    fiabilite: "OFFICIEL",
  },
  {
    url: "https://www.worldbank.org/en/news/rss.xml",
    source: "World Bank — News",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "OFFICIEL",
  },
  {
    url: "https://www.ifad.org/en/web/guest/news-rss",
    source: "IFAD — International Fund for Agricultural Development",
    filieres: ["MAIS", "CAJOU"],
    fiabilite: "OFFICIEL",
  },
  // ── Marchés & commodités ──────────────────────────────────────────────────
  {
    url: "https://feeds.content.dowjones.io/public/rss/mw_realestate",
    source: "MarketWatch — Commodities",
    filieres: ["MAIS", "CAJOU"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://agfax.com/feed/",
    source: "AgFax — Agriculture News",
    filieres: ["MAIS"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.agriculture.com/rss.xml",
    source: "Agriculture.com — Farm News",
    filieres: ["MAIS"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.grain.org/en/article/feed",
    source: "GRAIN — Agriculture & Biodiversity",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "INDICATIF",
  },
  // ── Afrique ───────────────────────────────────────────────────────────────
  {
    url: "https://www.theafricareport.com/feed",
    source: "The Africa Report",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.businessamlive.com/feed/",
    source: "Business AM Live — Nigeria",
    filieres: ["COLA", "CAJOU"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.graphic.com.gh/rss/news.rss",
    source: "Daily Graphic — Ghana",
    filieres: ["CAJOU", "COLA", "MAIS"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.jeuneafrique.com/feed/",
    source: "Jeune Afrique",
    filieres: ["MAIS", "CAJOU", "COLA"],
    fiabilite: "INDICATIF",
  },
  // ── Environnement & durabilité ────────────────────────────────────────────
  {
    url: "https://news.mongabay.com/feed/",
    source: "Mongabay — Environmental News",
    filieres: ["CAJOU", "COLA"],
    fiabilite: "INDICATIF",
  },
  {
    url: "https://www.ifpri.org/rss.xml",
    source: "IFPRI — Food Policy Research",
    filieres: ["MAIS", "CAJOU"],
    fiabilite: "OFFICIEL",
  },
  // ── Sécurité alimentaire & prix ───────────────────────────────────────────
  {
    url: "https://reliefweb.int/updates/rss.xml?search[primary_country]=CIV",
    source: "ReliefWeb — Côte d'Ivoire",
    filieres: ["CAJOU", "COLA"],
    fiabilite: "OFFICIEL",
  },
];

// Mots-clés pour filtrer les articles pertinents par filière
const KEYWORDS: Record<string, string[]> = {
  MAIS: [
    "maïs", "mais", "corn", "maize", "céréales", "cereals",
    "CBOT", "grain", "wheat", "soy", "soja", "feed grain",
    "crop", "harvest", "récolte", "agriculture", "farming",
    "food security", "sécurité alimentaire", "WASDE", "USDA",
  ],
  CAJOU: [
    "cajou", "cashew", "anacarde", "RCN", "noix de cajou",
    "Côte d'Ivoire", "W320", "W240", "kernel", "amande",
    "nut", "nuts", "noix", "West Africa nuts",
  ],
  COLA: [
    "cola", "kola", "kola nut", "noix de cola", "bitter kola",
    "West Africa", "Afrique de l'Ouest", "Nigeria agriculture",
    "Lagos market", "marché Lagos",
  ],
};

function articleConcerneFilieres(titre: string, contenu: string, filieresCibles: string[]): string[] {
  const texte = `${titre} ${contenu}`.toLowerCase();
  return filieresCibles.filter((code) => {
    const mots = KEYWORDS[code] ?? [];
    return mots.some((mot) => texte.includes(mot.toLowerCase()));
  });
}

export class RssNewsConnector implements Connector {
  code = SOURCE_CODE;
  nom = "Agrégateur RSS — 15 sources · actualités agricoles mondiales & AOF";
  frequenceCron = "*/30 * * * *"; // Toutes les 30 minutes

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
        timeout: 20_000,
        headers: {
          "User-Agent": "AfricaAgro-AgriTerminal/1.0 RSS Reader (+https://africaagro.com)",
          "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
        customFields: { item: ["summary", "description", "media:description"] },
      });

      for (const flux of FLUX_RSS) {
        try {
          const feed = await parser.parseURL(flux.url);

          for (const item of feed.items ?? []) {
            const titre = item.title?.trim() ?? "";
            const contenu = item.contentSnippet ?? item.summary ?? item.content ?? "";
            const lien = item.link?.trim() ?? "";
            const datePublication = item.pubDate ? new Date(item.pubDate) : new Date();

            if (!titre || !lien) continue;

            // Filtrer par mots-clés
            const filieresConcernees = articleConcerneFilieres(titre, contenu, flux.filieres);
            // Si aucun match ET la source est généraliste (pas de filieres spécifiques), skip
            if (filieresConcernees.length === 0) continue;

            for (const filiereCode of filieresConcernees) {
              const filiereId = filiereMap[filiereCode];
              if (!filiereId) continue;

              // Anti-doublon : vérifier si cet article existe déjà pour cette filière
              const existe = await prisma.actualite.findFirst({
                where: { lien, filiereId },
                select: { id: true },
              });
              if (existe) continue;

              try {
                await prisma.actualite.create({
                  data: {
                    filiereId,
                    titre: titre.slice(0, 255),
                    lien,
                    source: flux.source,
                    resume: contenu.slice(0, 600) || undefined,
                    datePublication,
                  },
                });
                resultat.nbImportes++;
              } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                if (!msg.includes("Unique constraint")) {
                  resultat.erreurs.push(`"${titre.slice(0, 40)}": ${msg}`);
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
      const statut = resultat.nbErreurs === FLUX_RSS.length ? "ERREUR" : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";

      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: { statutDernier: statut, messageErreur: resultat.erreurs.length > 0 ? resultat.erreurs.slice(0, 2).join(" | ") : null },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} articles importés (${FLUX_RSS.length} sources)`,
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
