// Connecteur Selina Wamucii via Firecrawl — prix de référence export cajou & cola
//
// Avant : le runner lisait la balise `og:description` et en tirait le prix à la
// regex `is \$([\d.]+)/kg`. Deux fragilités constatées en production :
//   - selinawamucii.com renvoie 403 aux IP Vercel (dépendance au runner) ;
//   - la page Ghana/cola n'expose pas le prix dans `og:description` (grille au
//     lieu du gabarit standard) → « prix introuvable », 7 cibles sur 8 seulement.
//
// Après : l'extraction structurée lit le prix où qu'il soit dans la page, ce qui
// couvre aussi les gabarits alternatifs.

import { prisma } from "@/lib/db";
import type { Prisma } from "@prisma/client";
import { scraper, firecrawlActif, FirecrawlIndisponible, resumeFraicheur } from "@/lib/firecrawl";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "SELINA_WAMUCII";
const BASE = "https://www.selinawamucii.com/insights/prices";

interface Cible {
  filiere: "CAJOU" | "COLA";
  produitCode: string;
  pays: string;
  zoneCode: string;
  slugPays: string;
  slugProduit: string;
}

const CIBLES: Cible[] = [
  { filiere: "CAJOU", produitCode: "CAJOU_RCN",  pays: "India",    zoneCode: "INDE",     slugPays: "india",    slugProduit: "cashew-nuts" },
  { filiere: "CAJOU", produitCode: "CAJOU_RCN",  pays: "Benin",    zoneCode: "BENIN",    slugPays: "benin",    slugProduit: "cashew-nuts" },
  { filiere: "CAJOU", produitCode: "CAJOU_RCN",  pays: "Ghana",    zoneCode: "GHANA",    slugPays: "ghana",    slugProduit: "cashew-nuts" },
  { filiere: "CAJOU", produitCode: "CAJOU_RCN",  pays: "Nigeria",  zoneCode: "NIGERIA",  slugPays: "nigeria",  slugProduit: "cashew-nuts" },
  { filiere: "COLA",  produitCode: "COLA_ROUGE", pays: "Nigeria",  zoneCode: "NIGERIA",  slugPays: "nigeria",  slugProduit: "kola-nuts" },
  // Gabarit « grille » : c'est la cible que la regex og:description ratait.
  { filiere: "COLA",  produitCode: "COLA_ROUGE", pays: "Ghana",    zoneCode: "GHANA",    slugPays: "ghana",    slugProduit: "kola-nuts" },
];

const SCHEMA = {
  type: "object",
  properties: {
    prixUsdParKg: {
      type: "number",
      description: "Prix courant du produit dans ce pays, en dollars US par kilogramme",
    },
    moisReference: {
      type: "string",
      description: "Mois et année auxquels le prix se rapporte, au format AAAA-MM",
    },
  },
  required: ["prixUsdParKg"],
} as const;

interface ExtraitSelina {
  prixUsdParKg?: number;
  moisReference?: string;
}

/** "2026-07" → 1er du mois ; sinon 1er du mois courant. */
function moisVersDate(mois?: string): Date {
  const m = mois?.match(/^(\d{4})-(\d{2})$/);
  if (m) return new Date(`${m[1]}-${m[2]}-01T00:00:00.000Z`);
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
}

export class SelinaFirecrawlConnector implements Connector {
  code = SOURCE_CODE;
  nom = "Selina Wamucii — prix de référence export cajou & cola (via Firecrawl)";
  frequenceCron = "0 9 * * 1"; // hebdomadaire : la source est mensuelle

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

      const produits = await prisma.produit.findMany({
        where: { code: { in: [...new Set(CIBLES.map((c) => c.produitCode))] } },
      });
      const produitMap = Object.fromEntries(produits.map((p) => [p.code, p.id]));

      const aInserer: Prisma.PrixReleveCreateManyInput[] = [];

      for (const cible of CIBLES) {
        const url = `${BASE}/${cible.slugPays}/${cible.slugProduit}/`;
        try {
          // Source mensuelle : une copie de moins de 3 jours est amplement fraîche.
          const res = await scraper<ExtraitSelina>(url, {
            schema: SCHEMA as unknown as Record<string, unknown>,
            prompt: `Extraire le prix courant du produit « ${cible.slugProduit.replace("-", " ")} » au ${cible.pays}, en USD par kilogramme, ainsi que le mois de référence.`,
            onlyMainContent: true,
            maxAge: 3 * 24 * 60 * 60 * 1000,
            proxy: "auto",
            blockAds: true,
            timeout: 45_000,
            timeoutMs: 60_000,
          });

          const usdKg = res.json?.prixUsdParKg;
          if (!usdKg || !isFinite(usdKg) || usdKg <= 0 || usdKg >= 1000) {
            resultat.erreurs.push(`${cible.filiere}/${cible.pays}: prix absent de l'extraction`);
            resultat.nbErreurs++;
            continue;
          }

          const produitId = produitMap[cible.produitCode];
          if (!produitId) {
            resultat.erreurs.push(`${cible.produitCode} introuvable — lancer /api/init`);
            resultat.nbErreurs++;
            continue;
          }

          const zone = await prisma.zone.upsert({
            where: { code: cible.zoneCode },
            update: {},
            create: { code: cible.zoneCode, nom: cible.pays, type: "PAYS" },
          });
          const marcheCode = `SELINA_${cible.zoneCode}_${cible.filiere}`.slice(0, 40);
          const marche = await prisma.marche.upsert({
            where: { code: marcheCode },
            update: {},
            create: {
              code: marcheCode,
              nom: `${cible.pays} — ${cible.filiere === "CAJOU" ? "cajou" : "cola"} (Selina Wamucii)`,
              zoneId: zone.id,
              devise: "USD",
              type: "FOB",
              description: "Prix de référence export indicatif — Selina Wamucii",
            },
          });

          aInserer.push({
            produitId,
            marcheId: marche.id,
            sourceId: source.id,
            typePrix: "SPOT",
            valeur: Math.round(usdKg * 1000 * 100) / 100, // USD/kg → USD/tonne
            devise: "USD",
            unite: "tonne",
            dateReleve: moisVersDate(res.json?.moisReference),
            fiabilite: "INDICATIF",
            notes: `Selina Wamucii via Firecrawl — ${cible.pays} (${usdKg} USD/kg, ${resumeFraicheur(res.metadata)})`,
          });
        } catch (e) {
          if (e instanceof FirecrawlIndisponible) throw e; // clé/crédits : inutile de continuer
          resultat.erreurs.push(`${cible.filiere}/${cible.pays}: ${e instanceof Error ? e.message.slice(0, 60) : e}`);
          resultat.nbErreurs++;
        }
      }

      if (aInserer.length > 0) {
        const ins = await prisma.prixReleve.createMany({ data: aInserer, skipDuplicates: true });
        resultat.nbImportes += ins.count;
      }

      const fin = new Date();
      const statut = aInserer.length === 0
        ? "ERREUR"
        : resultat.nbErreurs > 0 ? "PARTIEL" : "OK";
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
          message: `${resultat.nbImportes} prix cajou/cola importés (${aInserer.length}/${CIBLES.length} cibles extraites)`,
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
