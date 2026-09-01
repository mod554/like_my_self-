export const dynamic = "force-dynamic";
export const maxDuration = 60;

// POST /api/import/news — reçoit des actualités collectées côté GitHub Actions
// (IP propre : les IP partagées Vercel sont bloquées par Google News RSS).
// Protégé par CRON_SECRET si défini. Déduplication par lien + filière.

import { type NextRequest } from "next/server";
import { prisma } from "@/lib/db";

interface ArticleIn {
  titre: string;
  lien: string;
  source: string;
  filiere: string;   // MAIS | CAJOU | COLA | CAFE | CACAO | PALMIER | HEVEA
  resume?: string;
  datePublication?: string; // ISO
}

export async function POST(req: NextRequest) {
  const cronSecret = process.env.CRON_SECRET;
  if (cronSecret) {
    const auth = req.headers.get("authorization");
    if (auth !== `Bearer ${cronSecret}`) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
  }

  try {
    const body = await req.json() as { articles?: ArticleIn[]; sourceCode?: string };
    // Source dont le statut sera mis à jour (le runner collecte pour plusieurs
    // sources : Google News → RSS_NEWS_AGRI, GDELT → GDELT_NEWS).
    const sourceCode = ["RSS_NEWS_AGRI", "GDELT_NEWS"].includes(body.sourceCode ?? "")
      ? (body.sourceCode as string)
      : "RSS_NEWS_AGRI";
    // Cap large + entrelacement par filière : avec 7 filières × 2 langues, un
    // simple slice(0, 300) coupait la queue (café/cacao/palme/hévéa). On
    // entrelace pour garantir une couverture équitable de toutes les filières.
    const valides = (body.articles ?? []).filter((a) => a?.titre?.trim() && a?.lien?.trim() && a?.filiere);
    const parFiliere = new Map<string, ArticleIn[]>();
    for (const a of valides) {
      const arr = parFiliere.get(a.filiere) ?? [];
      arr.push(a);
      parFiliere.set(a.filiere, arr);
    }
    const articles: ArticleIn[] = [];
    const liensVus = new Set<string>(); // un même article dans 2 requêtes filière = 1 seule ligne
    const listes = [...parFiliere.values()];
    for (let i = 0; articles.length < 900; i++) {
      let ajoute = false;
      for (const l of listes) {
        if (!l[i]) continue;
        ajoute = true;
        const lien = l[i].lien.trim();
        if (liensVus.has(lien)) continue;
        liensVus.add(lien);
        articles.push(l[i]);
      }
      if (!ajoute) break;
    }
    if (articles.length === 0) {
      return Response.json({ error: "Aucun article valide" }, { status: 400 });
    }

    // Toutes les filières (maïs, cajou, cola + cultures de rente café/cacao/
    // palmier/hévéa) — ouvert aux nouvelles filières sans liste en dur.
    const filieres = await prisma.filiere.findMany();
    const filiereMap = Object.fromEntries(filieres.map((f) => [f.code, f.id]));

    // Liens déjà présents (dédup) — une seule requête
    const liens = [...new Set(articles.map((a) => a.lien.trim()))];
    const dejaVus = new Set(
      (await prisma.actualite.findMany({ where: { lien: { in: liens } }, select: { lien: true } }))
        .map((a) => a.lien)
    );

    const aInserer = articles
      .filter((a) => filiereMap[a.filiere] && !dejaVus.has(a.lien.trim()))
      .map((a) => ({
        filiereId: filiereMap[a.filiere],
        titre: a.titre.trim().slice(0, 255),
        lien: a.lien.trim(),
        source: a.source?.slice(0, 120) || "Google News",
        resume: a.resume?.slice(0, 600) || undefined,
        datePublication: a.datePublication ? new Date(a.datePublication) : new Date(),
      }));

    let importes = 0;
    if (aInserer.length > 0) {
      const res = await prisma.actualite.createMany({ data: aInserer, skipDuplicates: true });
      importes = res.count;
    }

    await prisma.source.update({
      where: { code: sourceCode },
      data: { statutDernier: "OK", derniereExecution: new Date(), messageErreur: null },
    }).catch(() => {});

    return Response.json({ ok: true, importes, recus: articles.length });
  } catch (e) {
    return Response.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
