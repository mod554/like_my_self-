export const dynamic = "force-dynamic";
export const maxDuration = 60;

// GET /api/firecrawl/test — diagnostic de l'intégration Firecrawl.
//
// Sans paramètre : indique si la clé est configurée et quelles cibles sont
// câblées. Avec `?url=…` : effectue un vrai scrape et renvoie ce qui revient
// (statut HTTP de la page, état du cache, taille du markdown, extraction JSON).
// C'est le smoke test à lancer juste après avoir ajouté FIRECRAWL_API_KEY.

import { type NextRequest } from "next/server";
import { scraper, firecrawlActif, firecrawlSelfHosted, FirecrawlIndisponible, resumeFraicheur } from "@/lib/firecrawl";

const CIBLES_CONNUES: Record<string, { url: string; note: string }> = {
  simagri: {
    url: "https://www.simagri-ci.info/prices-entries-grids",
    note: "prix marchés vivriers ivoiriens (bouclier anti-bot Anubis)",
  },
  selina: {
    url: "https://www.selinawamucii.com/insights/prices/ghana/kola-nuts/",
    note: "prix cola Ghana — gabarit que la regex og:description ratait",
  },
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const cible = searchParams.get("cible");
  const urlParam = searchParams.get("url");
  const url = urlParam ?? (cible ? CIBLES_CONNUES[cible]?.url : undefined);

  if (!firecrawlActif()) {
    return Response.json({
      ok: false,
      configure: false,
      message:
        "Firecrawl non configuré. Deux options (Vercel → Settings → Environment Variables) : FIRECRAWL_API_KEY=fc-… pour le cloud, ou FIRECRAWL_API_URL=http://… pour une instance auto-hébergée démarrée avec USE_DB_AUTHENTICATION=false (aucune clé requise).",
      ciblesDisponibles: Object.entries(CIBLES_CONNUES).map(([k, v]) => ({ cible: k, ...v })),
    }, { status: 503 });
  }

  if (!url) {
    return Response.json({
      ok: true,
      configure: true,
      mode: firecrawlSelfHosted() ? "self-hosted" : "cloud",
      message: "Firecrawl configuré. Ajouter ?cible=simagri|selina ou ?url=… pour lancer un scrape réel.",
      ciblesDisponibles: Object.entries(CIBLES_CONNUES).map(([k, v]) => ({ cible: k, ...v })),
    });
  }

  const debut = Date.now();
  try {
    const res = await scraper<Record<string, unknown>>(url, {
      prompt: "Extraire les prix affichés sur la page avec leur produit, leur marché ou pays, leur unité et leur date.",
      onlyMainContent: false,
      maxAge: 0, // smoke test : on veut la preuve d'un scrape live
      proxy: "auto",
      blockAds: true,
      timeout: 45_000,
      timeoutMs: 55_000,
    });

    return Response.json({
      ok: true,
      configure: true,
      url,
      dureeMs: Date.now() - debut,
      fraicheur: resumeFraicheur(res.metadata),
      metadata: res.metadata,
      markdownLongueur: res.markdown?.length ?? 0,
      markdownExtrait: res.markdown?.slice(0, 400) ?? null,
      extraction: res.json ?? null,
    });
  } catch (e) {
    const indisponible = e instanceof FirecrawlIndisponible;
    return Response.json({
      ok: false,
      configure: !indisponible,
      url,
      dureeMs: Date.now() - debut,
      erreur: e instanceof Error ? e.message : String(e),
    }, { status: indisponible ? 503 : 502 });
  }
}
