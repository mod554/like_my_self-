export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";
import PrixChartWrapper from "@/components/charts/PrixChartWrapper";
import LiveNewsFeed from "@/components/live/LiveNewsFeed";

const FILIERE_COLOR: Record<string, string> = { MAIS: "#92BA59", CAJOU: "#B89B3A", COLA: "#8A9E1A" };
const FILIERE_ICON: Record<string, string> = { MAIS: "🌽", CAJOU: "🥜", COLA: "🌰" };

async function getMarketData() {
  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      produits: {
        where: { estDerive: false },
        select: {
          id: true, code: true, nom: true, uniteRef: true,
          prixReleves: {
            orderBy: { dateReleve: "desc" },
            take: 60,
            include: { marche: { select: { code: true, nom: true } } },
          },
        },
      },
    },
  });

  // Fil d'actualité : 60 articles pour affichage initial (client en demandera plus)
  const news = await prisma.actualite.findMany({
    orderBy: { datePublication: "desc" },
    take: 60,
    include: {
      filiere: { select: { code: true, nom: true } },
    },
  });

  return { filieres, news };
}

function formatPrix(v: unknown, devise: string) {
  const n = Number(v);
  const f = n >= 1000
    ? n.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
    : n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return `${f} ${devise}`;
}

function calcVariation(releves: Array<{ valeur: unknown }>) {
  if (releves.length < 2) return null;
  const last = Number(releves[0].valeur);
  const prev = Number(releves[1].valeur);
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

export default async function MarchePage() {
  const { filieres, news } = await getMarketData();

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Header */}
        <div style={{ marginBottom: "28px", display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <p className="ag-section-label" style={{ marginBottom: "6px" }}>Terminal de marché · AfricaGro Partners</p>
            <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", margin: 0 }}>
              Tableau de bord des prix
            </h1>
            <p style={{ marginTop: "6px", fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
              Prix en temps réel · Taux de change mis à jour chaque heure · Actualités toutes les 5 minutes
            </p>
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span className="ag-status-dot" />
            <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)" }}>DONNÉES EN TEMPS RÉEL</span>
          </div>
        </div>

        {/* KPI strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px", marginBottom: "24px" }}>
          {filieres.map((f) => {
            const accent = FILIERE_COLOR[f.code] ?? "var(--ag-lime)";
            return f.produits.map((p) => {
              const last = p.prixReleves[0];
              const variation = calcVariation(p.prixReleves);
              const hausse = variation !== null && variation >= 0;
              return (
                <Link key={p.id} href={`/referentiel/${f.code.toLowerCase()}/${p.code.toLowerCase()}`} style={{ textDecoration: "none" }}>
                  <div className="ag-kpi" style={{ borderLeft: `3px solid ${accent}`, cursor: "pointer" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                      <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.06em" }}>
                        {FILIERE_ICON[f.code]} {p.code}
                      </span>
                      {variation !== null && (
                        <span style={{
                          fontSize: 11, fontFamily: "monospace", fontWeight: 700,
                          color: hausse ? "var(--data-up)" : "var(--data-down)",
                          background: hausse ? "rgba(146,186,89,0.1)" : "rgba(224,82,82,0.1)",
                          padding: "2px 6px", borderRadius: "4px",
                        }}>
                          {hausse ? "▲" : "▼"} {Math.abs(variation).toFixed(1)}%
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: "4px" }}>{p.nom}</div>
                    {last ? (
                      <>
                        <div style={{ fontSize: 26, fontWeight: 700, color: accent, fontFamily: "monospace", lineHeight: 1 }}>
                          {formatPrix(last.valeur, last.devise)}
                        </div>
                        <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", marginTop: "4px" }}>
                          {last.unite} · {new Date(last.dateReleve).toLocaleDateString("fr-FR")} · {last.typePrix}
                        </div>
                      </>
                    ) : (
                      <div style={{ fontSize: 14, color: "var(--text-muted)", fontFamily: "monospace" }}>— Aucune donnée</div>
                    )}
                  </div>
                </Link>
              );
            });
          })}
        </div>

        {/* Charts + actualités */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: "20px", alignItems: "start" }}>

          {/* Charts + tableau */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {filieres.map((f) => {
              const accent = FILIERE_COLOR[f.code] ?? "var(--ag-lime)";
              return f.produits.slice(0, 2).map((p) => {
                const chartData = [...p.prixReleves]
                  .reverse()
                  .map((r) => ({
                    date: new Date(r.dateReleve).toLocaleDateString("fr-FR", { month: "short", year: "2-digit" }),
                    valeur: Number(r.valeur),
                    devise: r.devise,
                  }));

                return (
                  <div key={p.id} style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
                    <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", gap: "10px" }}>
                      <span style={{ fontSize: 16 }}>{FILIERE_ICON[f.code]}</span>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{p.nom}</div>
                        <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>
                          {f.nom} · {p.prixReleves[0]?.devise ?? "USD"}
                        </div>
                      </div>
                      <Link
                        href={`/referentiel/${f.code.toLowerCase()}/${p.code.toLowerCase()}`}
                        style={{ marginLeft: "auto", fontSize: 11, color: accent, textDecoration: "none", fontFamily: "monospace" }}
                      >
                        Fiche complète →
                      </Link>
                    </div>
                    <div style={{ padding: "16px 20px" }}>
                      <PrixChartWrapper data={chartData} couleur={accent} />
                    </div>
                  </div>
                );
              });
            })}

            {/* Tableau derniers relevés */}
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Derniers relevés toutes filières</p>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="ag-table">
                  <thead>
                    <tr>
                      <th>Produit</th><th>Filière</th><th>Marché</th>
                      <th style={{ textAlign: "right" }}>Prix</th>
                      <th>Devise</th><th>Unité</th><th>Date</th><th>Fiabilité</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filieres.flatMap((f) =>
                      f.produits.flatMap((p) =>
                        p.prixReleves.slice(0, 3).map((r) => ({
                          ...r, produitCode: p.code, produitNom: p.nom, filiereNom: f.nom, filiereCode: f.code,
                          accent: FILIERE_COLOR[f.code] ?? "var(--ag-lime)",
                        }))
                      )
                    ).slice(0, 20).map((r, i) => (
                      <tr key={i}>
                        <td style={{ fontFamily: "monospace", fontWeight: 600, color: r.accent }}>{r.produitCode}</td>
                        <td style={{ fontFamily: "monospace" }}>{FILIERE_ICON[r.filiereCode]} {r.filiereNom}</td>
                        <td style={{ fontFamily: "monospace", color: "var(--text-muted)" }}>{r.marche?.code ?? "—"}</td>
                        <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: r.accent }}>
                          {Number(r.valeur).toLocaleString("fr-FR", { maximumFractionDigits: 2 })}
                        </td>
                        <td style={{ fontFamily: "monospace" }}>{r.devise}</td>
                        <td style={{ fontFamily: "monospace" }}>{r.unite}</td>
                        <td style={{ fontFamily: "monospace", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                          {new Date(r.dateReleve).toLocaleDateString("fr-FR")}
                        </td>
                        <td>
                          <span style={{
                            fontSize: 9, fontFamily: "monospace", padding: "1px 5px", borderRadius: "3px",
                            color: r.fiabilite === "OFFICIEL" ? "#4A9B6F" : r.fiabilite === "INDICATIF" ? "#92BA59" : "#B89B3A",
                            background: r.fiabilite === "OFFICIEL" ? "rgba(74,155,111,0.12)" : "rgba(146,186,89,0.1)",
                          }}>
                            {r.fiabilite}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Fil d'actualité live — auto-refresh 5 minutes */}
          <div style={{ position: "sticky", top: "80px" }}>
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Fil d&apos;actualité en direct</p>
              </div>
              <div style={{ padding: "14px", maxHeight: "calc(100vh - 180px)", overflowY: "auto" }}>
                <LiveNewsFeed
                  initialNews={news.map((a) => ({
                    id: a.id,
                    titre: a.titre,
                    lien: a.lien,
                    source: a.source,
                    resume: a.resume ?? null,
                    datePublication: a.datePublication.toISOString(),
                    dateCollecte: a.dateCollecte.toISOString(),
                    filiere: a.filiere ? { code: a.filiere.code, nom: a.filiere.nom } : null,
                  }))}
                  limit={80}
                  refreshInterval={5 * 60 * 1000}
                />
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
