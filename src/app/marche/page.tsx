export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";
import PrixChartWrapper from "@/components/charts/PrixChartWrapper";

// Mapping filière → couleur accent
const FILIERE_COLOR: Record<string, string> = {
  MAIS:  "#92BA59",
  CAJOU: "#B89B3A",
  COLA:  "#8A9E1A",
};
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
      actualites: {
        orderBy: { datePublication: "desc" },
        take: 8,
        select: { id: true, titre: true, lien: true, source: true, datePublication: true },
      },
    },
  });
  return filieres;
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
  const filieres = await getMarketData();

  // Toutes actualités confondues
  const allActus = filieres
    .flatMap((f) => f.actualites.map((a) => ({ ...a, filiereNom: f.nom, filiereCode: f.code })))
    .sort((a, b) => new Date(b.datePublication).getTime() - new Date(a.datePublication).getTime())
    .slice(0, 10);

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
          </div>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            <span className="ag-status-dot" />
            <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)" }}>DONNÉES EN TEMPS RÉEL</span>
          </div>
        </div>

        {/* KPI strip — un par filière × produit principal */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px", marginBottom: "24px" }}>
          {filieres.map((f) => {
            const accent = FILIERE_COLOR[f.code] ?? "var(--ag-lime)";
            return f.produits.map((p) => {
              const last = p.prixReleves[0];
              const variation = calcVariation(p.prixReleves);
              const hausse = variation !== null && variation >= 0;
              return (
                <Link key={p.id} href={`/referentiel/${f.code.toLowerCase()}/${p.code.toLowerCase()}`} style={{ textDecoration: "none" }}>
                  <div
                    className="ag-kpi"
                    style={{ borderLeft: `3px solid ${accent}`, cursor: "pointer" }}
                  >
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "16px", alignItems: "start" }}>

          {/* Charts */}
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
                  <div
                    key={p.id}
                    style={{
                      background: "var(--bg-surface)", border: "1px solid var(--border-subtle)",
                      borderRadius: "10px", overflow: "hidden",
                    }}
                  >
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

            {/* Heatmap variation 30 derniers jours (simulé via table) */}
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
                    ).slice(0, 15).map((r, i) => (
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

          {/* Actualités sidebar */}
          <div
            style={{
              background: "var(--bg-surface)", border: "1px solid var(--border-subtle)",
              borderRadius: "10px", overflow: "hidden", position: "sticky", top: "80px",
            }}
          >
            <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", gap: "8px" }}>
              <span className="ag-status-dot" />
              <p className="ag-section-label">Fil d&apos;actualité</p>
            </div>

            {allActus.length === 0 ? (
              <div style={{ padding: "24px 18px", textAlign: "center" }}>
                <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
                  Déclenchez le connecteur RSS
                </p>
                <Link href="/collecte" style={{ fontSize: 11, color: "var(--ag-lime)", textDecoration: "none", display: "block", marginTop: "8px" }}>
                  → Page collecte
                </Link>
              </div>
            ) : (
              <div>
                {allActus.map((a, i) => {
                  const accent = FILIERE_COLOR[a.filiereCode] ?? "var(--ag-lime)";
                  return (
                    <div
                      key={a.id}
                      style={{
                        padding: "12px 18px",
                        borderBottom: i < allActus.length - 1 ? "1px solid var(--border-subtle)" : "none",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "5px" }}>
                        <span style={{ fontSize: 10, color: accent }}>{FILIERE_ICON[a.filiereCode]}</span>
                        <span style={{ fontSize: 9, fontFamily: "monospace", color: accent, background: `${accent}18`, padding: "1px 5px", borderRadius: "3px" }}>
                          {a.filiereNom}
                        </span>
                        <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)", marginLeft: "auto" }}>
                          {new Date(a.datePublication).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })}
                        </span>
                      </div>
                      <a href={a.lien} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
                        <p style={{
                          fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.4, margin: 0,
                          display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden",
                        }}>
                          {a.titre}
                        </p>
                      </a>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
