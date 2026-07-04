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
  preFiltre?: boolean;
}

// Flux RSS — Google News en tête (stable, jamais bloqué, requêtes ciblées par filière)
// + quelques flux institutionnels encore actifs. preFiltre=true : la requête du flux
// est déjà thématique, on n'applique pas le filtre par mots-clés.
const FLUX_RSS: FluxRSS[] = [
  // ── Google News — requêtes ciblées (fr + en) ─────────────────────────────
  {
    url: "https://news.google.com/rss/search?q=maize%20OR%20corn%20price%20africa&hl=en-US&gl=US&ceid=US:en",
    source: "Google News — Maize/Corn Africa",
    filieres: ["MAIS"], fiabilite: "INDICATIF", preFiltre: true,
  },
  {
    url: "https://news.google.com/rss/search?q=ma%C3%AFs%20prix%20afrique&hl=fr&gl=FR&ceid=FR:fr",
    source: "Google News — Maïs Afrique (fr)",
    filieres: ["MAIS"], fiabilite: "INDICATIF", preFiltre: true,
  },
  {
    url: "https://news.google.com/rss/search?q=cashew%20OR%20anacarde%20price&hl=en-US&gl=US&ceid=US:en",
    source: "Google News — Cashew/Anacarde",
    filieres: ["CAJOU"], fiabilite: "INDICATIF", preFiltre: true,
  },
  {
    url: "https://news.google.com/rss/search?q=noix%20de%20cajou%20c%C3%B4te%20d%27ivoire&hl=fr&gl=FR&ceid=FR:fr",
    source: "Google News — Cajou CI (fr)",
    filieres: ["CAJOU"], fiabilite: "INDICATIF", preFiltre: true,
  },
  {
    url: "https://news.google.com/rss/search?q=%22kola%20nut%22%20OR%20%22noix%20de%20cola%22&hl=en-US&gl=US&ceid=US:en",
    source: "Google News — Kola nut",
    filieres: ["COLA"], fiabilite: "INDICATIF", preFiltre: true,
  },
  {
    url: "https://news.google.com/rss/search?q=agriculture%20afrique%20de%20l%27ouest%20march%C3%A9&hl=fr&gl=FR&ceid=FR:fr",
    source: "Google News — Agriculture AOF (fr)",
    filieres: ["MAIS", "CAJOU", "COLA"], fiabilite: "INDICATIF",
  },
  // ── Institutions (flux encore actifs) ────────────────────────────────────
  {
    // L'ancien flux FAO (fao.org/newsroom/rss) renvoie 404 — remplacé par
    // UN News rubrique Food & Agriculture (contenu FAO/PAM inclus)
    url: "https://news.google.com/rss/search?q=FAO%20OR%20%22food%20prices%22%20agriculture%20africa&hl=en-US&gl=US&ceid=US:en",
    source: "Google News — FAO & Food Prices Africa (en)",
    filieres: ["MAIS", "CAJOU", "COLA"], fiabilite: "OFFICIEL",
  },
  {
    url: "https://news.mongabay.com/feed/",
    source: "Mongabay — Environmental News",
    filieres: ["CAJOU", "COLA"], fiabilite: "INDICATIF",
  },
  {
    // AgFax coupe la connexion (ECONNRESET) depuis les datacenters — remplacé
    // par AllAfrica Agriculture (agrégateur presse africaine, pertinent AOF)
    url: "https://allafrica.com/tools/headlines/rdf/agriculture/headlines.rdf",
    source: "AllAfrica — Agriculture",
    filieres: ["MAIS", "CAJOU", "COLA"], fiabilite: "INDICATIF",
  },
];

// Mots-clés pour filtrer les articles pertinents par filière
// Mots-clés SPÉCIFIQUES à chaque filière — les termes génériques
// ("agriculture", "crop", "nut", "West Africa"…) provoquaient des
// fausses attributions : un article générique était taggé MAIS/CAJOU/COLA.
const KEYWORDS: Record<string, string[]> = {
  MAIS: [
    "maïs", "corn", "maize", "céréale", "cereal",
    "CBOT", "feed grain", "WASDE",
  ],
  CAJOU: [
    "cajou", "cashew", "anacarde", "RCN", "noix de cajou",
    "W320", "W240",
  ],
  COLA: [
    "kola", "kola nut", "cola nut", "noix de cola", "bitter kola",
    "cola nitida",
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

      // Fetch all feeds in parallel with individual timeouts
      const feedResults = await Promise.allSettled(
        FLUX_RSS.map((flux) => parser.parseURL(flux.url).then((feed) => ({ flux, feed })))
      );

      for (const [idx, feedResult] of feedResults.entries()) {
        if (feedResult.status === "rejected") {
          const msg = feedResult.reason instanceof Error ? feedResult.reason.message : String(feedResult.reason);
          resultat.erreurs.push(`Flux "${FLUX_RSS[idx].source}": ${msg.slice(0, 60)}`);
          resultat.nbErreurs++;
          continue;
        }

        const { flux, feed } = feedResult.value;
        // Collecte puis insertion groupee (createMany) — un create par article
        // depasse le budget 60s serverless avec des dizaines de flux
        const candidats: { filiereId: string; titre: string; lien: string; source: string; resume?: string; datePublication: Date }[] = [];
        for (const item of (feed.items ?? []).slice(0, 40)) {
          const titre = item.title?.trim() ?? "";
          const contenu = item.contentSnippet ?? item.summary ?? item.content ?? "";
          const lien = item.link?.trim() ?? "";
          const datePublication = item.pubDate ? new Date(item.pubDate) : new Date();
          if (!titre || !lien) continue;

          const filieresConcernees = flux.preFiltre
            ? flux.filieres
            : articleConcerneFilieres(titre, contenu, flux.filieres);
          for (const filiereCode of filieresConcernees) {
            const filiereId = filiereMap[filiereCode];
            if (!filiereId) continue;
            candidats.push({
              filiereId,
              titre: titre.slice(0, 255),
              lien,
              source: flux.source,
              resume: contenu.slice(0, 600) || undefined,
              datePublication,
            });
          }
        }
        if (candidats.length > 0) {
          const dejaVus = new Set(
            (await prisma.actualite.findMany({
              where: { lien: { in: [...new Set(candidats.map((c) => c.lien))] } },
              select: { lien: true, filiereId: true },
            })).map((a) => `${a.lien}|${a.filiereId}`)
          );
          const aInserer = candidats.filter((c) => !dejaVus.has(`${c.lien}|${c.filiereId}`));
          if (aInserer.length > 0) {
            try {
              const res = await prisma.actualite.createMany({ data: aInserer, skipDuplicates: true });
              resultat.nbImportes += res.count;
            } catch (err: unknown) {
              resultat.erreurs.push(`Insert ${flux.source}: ${err instanceof Error ? err.message.slice(0, 60) : err}`);
              resultat.nbErreurs++;
            }
          }
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
