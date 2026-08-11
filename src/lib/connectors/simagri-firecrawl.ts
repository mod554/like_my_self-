// Connecteur SIMAGRI-CI via Firecrawl — prix des marchés vivriers ivoiriens
//
// Avant : le runner GitHub téléchargeait le HTML et le découpait à la regex
// (`<span class="price-item">…`). Deux fragilités : le bouclier anti-bot Anubis
// du site renvoie 403 aux IP Vercel (d'où la dépendance au runner), et la regex
// casse au moindre changement de gabarit.
//
// Après : Firecrawl franchit le bouclier et renvoie directement les relevés
// structurés — le connecteur tourne donc depuis l'app, comme les autres.
//
// Le pas runner reste en place : si FIRECRAWL_API_KEY n'est pas configurée, ce
// connecteur se met en NON_CONFIGURE et rien ne régresse.

import { prisma } from "@/lib/db";
import type { Prisma } from "@prisma/client";
import { scraper, firecrawlActif, FirecrawlIndisponible, resumeFraicheur } from "@/lib/firecrawl";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "SIMAGRI_CI";
const URL_GRILLE = "https://www.simagri-ci.info/prices-entries-grids";

// Le référentiel ne suit que le maïs parmi les vivriers de SIMAGRI.
const PRODUITS_SUIVIS: { motif: RegExp; produitCode: string }[] = [
  { motif: /ma[iï]s/i, produitCode: "MAIS_GRAIN" },
];

const SCHEMA = {
  type: "object",
  properties: {
    releves: {
      type: "array",
      description: "Un élément par ligne de prix affichée sur la page",
      items: {
        type: "object",
        properties: {
          produit: { type: "string", description: "Nom du produit, ex. MAÏS JAUNE" },
          marche: { type: "string", description: "Ville ou marché, ex. BOUAFLE" },
          prixDetail: { type: "number", description: "Prix de détail en FCFA/kg, 0 si absent" },
          prixGros: { type: "number", description: "Prix de gros en FCFA/kg, 0 si absent" },
          date: { type: "string", description: "Date du relevé au format JJ/MM/AAAA si affichée" },
        },
        required: ["produit", "marche"],
      },
    },
  },
  required: ["releves"],
} as const;

interface ReleveSimagri {
  produit?: string;
  marche?: string;
  prixDetail?: number;
  prixGros?: number;
  date?: string;
}

function normCode(s: string): string {
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 34);
}

function parseDateFr(d?: string): Date {
  const m = d?.match(/(\d{2})\/(\d{2})\/(\d{4})/);
  return m ? new Date(`${m[3]}-${m[2]}-${m[1]}T00:00:00.000Z`) : new Date();
}

export class SimagriFirecrawlConnector implements Connector {
  code = SOURCE_CODE;
  nom = "SIMAGRI Côte d'Ivoire — prix marchés vivriers (via Firecrawl)";
  frequenceCron = "0 7 * * *";

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    if (!firecrawlActif()) {
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: "NON_CONFIGURE",
          messageErreur: "FIRECRAWL_API_KEY absente — collecte assurée par le runner GitHub en attendant",
        },
      }).catch(() => {});
      return { ...resultat, fin: new Date(), erreurs: ["FIRECRAWL_API_KEY absente"] };
    }

    await prisma.source.update({
      where: { code: SOURCE_CODE },
      data: { statutDernier: "EN_COURS", derniereExecution: debut },
    }).catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable — lancer /api/init`);

      const zone =
        (await prisma.zone.findUnique({ where: { code: "COTE_IVOIRE" } })) ??
        (await prisma.zone.findUnique({ where: { code: "CI" } }));
      if (!zone) throw new Error("Zone Côte d'Ivoire absente — lancer /api/init");

      // Prix quotidiens : une copie de moins de 6 h reste représentative et
      // évite de repayer un scrape live à chaque passage horaire.
      const res = await scraper<{ releves?: ReleveSimagri[] }>(URL_GRILLE, {
        schema: SCHEMA as unknown as Record<string, unknown>,
        prompt:
          "Extraire toutes les lignes de prix affichées (produit, marché/ville, prix de détail et de gros en FCFA/kg, date). Mettre 0 quand un prix n'est pas affiché.",
        onlyMainContent: false,
        maxAge: 6 * 60 * 60 * 1000,
        proxy: "auto",
        blockAds: true,
        timeout: 60_000,
        timeoutMs: 75_000,
      });

      const releves = res.json?.releves ?? [];
      if (releves.length === 0) {
        throw new Error(`Extraction vide (${resumeFraicheur(res.metadata)}) — gabarit du site probablement modifié`);
      }

      const produits = await prisma.produit.findMany({
        where: { code: { in: PRODUITS_SUIVIS.map((p) => p.produitCode) } },
      });
      const produitMap = Object.fromEntries(produits.map((p) => [p.code, p.id]));

      const marcheCache: Record<string, string> = {};
      const aInserer: Prisma.PrixReleveCreateManyInput[] = [];

      for (const r of releves) {
        const cible = PRODUITS_SUIVIS.find((p) => p.motif.test(r.produit ?? ""));
        const produitId = cible ? produitMap[cible.produitCode] : undefined;
        const marcheNom = (r.marche ?? "").trim();
        if (!produitId || !marcheNom) continue;

        const dateReleve = parseDateFr(r.date);
        const codeMarche = `SIMAGRI_${normCode(marcheNom)}`.slice(0, 40);
        if (!marcheCache[codeMarche]) {
          const m = await prisma.marche.upsert({
            where: { code: codeMarche },
            update: {},
            create: {
              code: codeMarche,
              nom: `${marcheNom.toUpperCase()} (SIMAGRI-CI)`,
              zoneId: zone.id,
              devise: "XOF",
              type: "SPOT_DOMESTIQUE",
              description: "Marché physique ivoirien — relevé SIMAGRI-CI",
            },
          });
          marcheCache[codeMarche] = m.id;
        }

        for (const [typePrix, valeur] of [["DETAIL", r.prixDetail], ["GROS", r.prixGros]] as const) {
          if (!valeur || !isFinite(valeur) || valeur <= 0 || valeur > 100_000) continue;
          aInserer.push({
            produitId,
            marcheId: marcheCache[codeMarche],
            sourceId: source.id,
            typePrix,
            valeur,
            devise: "XOF",
            unite: "kg",
            dateReleve,
            fiabilite: "OFFICIEL",
            notes: `SIMAGRI-CI via Firecrawl — prix ${typePrix === "GROS" ? "de gros" : "de détail"} ${marcheNom} (${resumeFraicheur(res.metadata)})`,
          });
        }
      }

      if (aInserer.length > 0) {
        const ins = await prisma.prixReleve.createMany({ data: aInserer, skipDuplicates: true });
        resultat.nbImportes += ins.count;
      }

      const fin = new Date();
      const statut = aInserer.length === 0 ? "PARTIEL" : "OK";
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: statut,
          messageErreur: aInserer.length === 0
            ? `${releves.length} lignes extraites mais aucune ne concerne un produit suivi`
            : null,
        },
      });
      await prisma.connectorLog.create({
        data: {
          sourceId: source.id, debut, fin, statut,
          nbImportes: resultat.nbImportes, nbErreurs: resultat.nbErreurs,
          message: `${resultat.nbImportes} prix SIMAGRI importés (${releves.length} lignes extraites, ${resumeFraicheur(res.metadata)})`,
          detail: { erreurs: resultat.erreurs.slice(0, 5) },
        },
      }).catch(() => {});

      return { ...resultat, fin };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const fin = new Date();
      await prisma.source.update({
        where: { code: SOURCE_CODE },
        data: {
          statutDernier: err instanceof FirecrawlIndisponible ? "NON_CONFIGURE" : "ERREUR",
          messageErreur: msg.slice(0, 200),
        },
      }).catch(() => {});
      return { ...resultat, nbErreurs: resultat.nbErreurs + 1, erreurs: [...resultat.erreurs, msg], fin };
    }
  }
}
