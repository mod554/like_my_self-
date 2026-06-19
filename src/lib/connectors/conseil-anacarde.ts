// Connecteur Conseil du Coton et de l'Anacarde (Côte d'Ivoire)
// Source : https://www.conseilcoton-anacarde.ci — HTML scraping
// Fréquence : bi-hebdomadaire (lundi + jeudi)
// Couverture : Prix d'achat bord-champ cajou RCN (noix brute) Côte d'Ivoire

import * as cheerio from "cheerio";
import { prisma } from "@/lib/db";
import type { Connector, ConnectorResult } from "./base";
import { creerResultatVide } from "./base";

const SOURCE_CODE = "CONSEIL_ANACARDE_CI";
const BASE_URL = "https://www.conseilcoton-anacarde.ci";

async function fetchHtml(url: string): Promise<string> {
  const response = await fetch(url, {
    headers: {
      Accept: "text/html,application/xhtml+xml",
      "Accept-Language": "fr-FR,fr;q=0.9",
      "User-Agent": "Mozilla/5.0 (compatible; LikeMyself-AgriBot/1.0)",
    },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} — ${url}`);
  return response.text();
}

interface PrixBordChamp {
  date: Date;
  valeur: number;
  devise: string;
  zone?: string;
  type: string; // BORD_CHAMP | FOB
}

function parsePrixCajou(html: string): PrixBordChamp[] {
  const $ = cheerio.load(html);
  const prix: PrixBordChamp[] = [];

  // Pattern 1 : tableau avec en-têtes "Date | Prix | Zone"
  $("table").each((_i, table) => {
    const headers: string[] = [];
    $(table)
      .find("th")
      .each((_j, th) => { headers.push($(th).text().trim().toLowerCase()); });

    const dateIdx = headers.findIndex((h) => h.includes("date") || h.includes("période"));
    const prixIdx = headers.findIndex((h) => h.includes("prix") || h.includes("fcfa") || h.includes("xof") || h.includes("cfa"));
    const zoneIdx = headers.findIndex((h) => h.includes("zone") || h.includes("région"));

    if (prixIdx === -1) return; // pas un tableau de prix

    $(table)
      .find("tbody tr")
      .each((_j, tr) => {
        const cells = $(tr)
          .find("td")
          .map((_k, td) => $(td).text().trim())
          .get();
        if (cells.length === 0) return;

        const rawPrix = cells[prixIdx]?.replace(/[^\d,.]/g, "").replace(",", ".");
        const valeur = parseFloat(rawPrix ?? "");
        if (isNaN(valeur) || valeur <= 0) return;

        // Tenter de parser la date
        let date = new Date();
        if (dateIdx >= 0 && cells[dateIdx]) {
          const raw = cells[dateIdx];
          // Formats : "15/01/2025", "janvier 2025", "2025-01-15"
          const matchDMY = raw.match(/(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})/);
          const matchYMD = raw.match(/(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})/);
          if (matchDMY) {
            date = new Date(`${matchDMY[3]}-${matchDMY[2].padStart(2, "0")}-${matchDMY[1].padStart(2, "0")}T12:00:00.000Z`);
          } else if (matchYMD) {
            date = new Date(`${matchYMD[1]}-${matchYMD[2].padStart(2, "0")}-${matchYMD[3].padStart(2, "0")}T12:00:00.000Z`);
          }
        }

        prix.push({
          date,
          valeur,
          devise: "XOF",
          zone: zoneIdx >= 0 ? cells[zoneIdx] : undefined,
          type: "BORD_CHAMP",
        });
      });
  });

  // Pattern 2 : paragraphes avec regex "Prix bord champ : 350 FCFA/kg"
  if (prix.length === 0) {
    const bodyText = $("body").text();
    const matches = bodyText.matchAll(/prix[^:]*:\s*(\d[\d\s]*(?:[,.]\d+)?)\s*(?:fcfa|xof|f\s*cfa)/gi);
    for (const m of matches) {
      const valeur = parseFloat(m[1].replace(/\s/g, "").replace(",", "."));
      if (!isNaN(valeur) && valeur > 0) {
        prix.push({ date: new Date(), valeur, devise: "XOF", type: "BORD_CHAMP" });
      }
    }
  }

  return prix;
}

// Extraire les actualités cajou de la page
function parseActualites(html: string, filiereId: string) {
  const $ = cheerio.load(html);
  const articles: Array<{ titre: string; lien: string; resume?: string; date: Date }> = [];

  // Liens d'articles courants
  $("article, .post, .news-item, .actualite").each((_i, el) => {
    const titre = $(el).find("h2, h3, .titre, .title").first().text().trim();
    const href = $(el).find("a").first().attr("href");
    const resume = $(el).find("p, .excerpt, .resume").first().text().trim().slice(0, 500);
    if (!titre || !href) return;

    const lien = href.startsWith("http") ? href : `${BASE_URL}${href}`;
    articles.push({ titre, lien, resume, date: new Date() });
  });

  return articles;
}

export class ConseilAnacardeCiConnector implements Connector {
  code = SOURCE_CODE;
  nom = "Conseil du Coton et de l'Anacarde CI — Prix bord-champ cajou";
  frequenceCron = "0 9 * * 1,4"; // Lundi et jeudi 9h UTC

  async run(): Promise<ConnectorResult> {
    const debut = new Date();
    const resultat = creerResultatVide(SOURCE_CODE, debut);

    await prisma.source
      .update({ where: { code: SOURCE_CODE }, data: { statutDernier: "EN_COURS", derniereExecution: debut } })
      .catch(() => {});

    try {
      const source = await prisma.source.findUnique({ where: { code: SOURCE_CODE } });
      if (!source) throw new Error(`Source ${SOURCE_CODE} introuvable en BD`);

      const produit = await prisma.produit.findUnique({ where: { code: "CAJOU_RCN" } });
      if (!produit) throw new Error("Produit CAJOU_RCN introuvable");

      const marche = await prisma.marche.findUnique({ where: { code: "ABIDJAN_RCN" } });
      if (!marche) throw new Error("Marché ABIDJAN_RCN introuvable");

      const filiere = await prisma.filiere.findUnique({ where: { code: "CAJOU" } });

      // Page principale prix
      const urlsPrix = [
        `${BASE_URL}/prix`,
        `${BASE_URL}/prix-bord-champ`,
        `${BASE_URL}/marche/prix`,
        `${BASE_URL}/anacarde/prix`,
      ];

      let htmlPrix = "";
      for (const url of urlsPrix) {
        try {
          htmlPrix = await fetchHtml(url);
          break;
        } catch {
          continue;
        }
      }

      if (!htmlPrix) {
        // Fallback : page d'accueil
        htmlPrix = await fetchHtml(BASE_URL);
      }

      const prix = parsePrixCajou(htmlPrix);
      for (const p of prix) {
        if (isNaN(p.date.getTime())) continue;
        try {
          await prisma.prixReleve.create({
            data: {
              produitId: produit.id,
              marcheId: marche.id,
              sourceId: source.id,
              typePrix: p.type,
              valeur: p.valeur,
              devise: p.devise,
              unite: "kg",
              dateReleve: p.date,
              fiabilite: "OFFICIEL",
              notes: `Conseil Anacarde CI${p.zone ? ` — ${p.zone}` : ""}`,
            },
          });
          resultat.nbImportes++;
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          if (!msg.includes("Unique constraint")) {
            resultat.erreurs.push(`Prix ${p.date.toISOString().split("T")[0]}: ${msg}`);
            resultat.nbErreurs++;
          }
        }
      }

      // Actualités
      if (filiere) {
        const urlsActu = [`${BASE_URL}/actualites`, `${BASE_URL}/news`, BASE_URL];
        for (const url of urlsActu) {
          try {
            const html = await fetchHtml(url);
            const articles = parseActualites(html, filiere.id);
            for (const a of articles) {
              try {
                await prisma.actualite.create({
                  data: {
                    filiereId: filiere.id,
                    titre: a.titre.slice(0, 255),
                    lien: a.lien,
                    source: "Conseil du Coton et de l'Anacarde CI",
                    resume: a.resume,
                    datePublication: a.date,
                  },
                });
                resultat.nbImportes++;
              } catch {
                // doublon ignoré
              }
            }
            if (articles.length > 0) break;
          } catch {
            continue;
          }
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
          message: `${resultat.nbImportes} entrées importées`,
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
