export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";

const XOF_PER_USD = 655.957;

async function getAnalyseData() {
  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      produits: {
        where: { estDerive: false },
        include: {
          prixReleves: {
            orderBy: { dateReleve: "desc" },
            take: 12,
            select: { valeur: true, devise: true, unite: true, dateReleve: true, fiabilite: true },
          },
          structuresCout: {
            select: { montant: true, devise: true, unite: true, maillon: true, poste: true },
          },
        },
      },
    },
  });
  return filieres;
}

function calcMarge(
  prix: Array<{ valeur: unknown; devise: string }>,
  couts: Array<{ montant: unknown; devise: string; maillon: string }>
) {
  if (!prix.length) return null;
  const prixUSD = prix.slice(0, 3).reduce((acc, p) => {
    const v = Number(p.valeur);
    const inUSD = p.devise === "XOF" ? v / XOF_PER_USD : v;
    return acc + inUSD;
  }, 0) / Math.min(3, prix.length);

  if (!couts.length) return { prixMoyen: prixUSD, coutTotal: null, marge: null };

  const coutTotal = couts.reduce((acc, c) => {
    const v = Number(c.montant);
    const inUSD = c.devise === "XOF" ? v / XOF_PER_USD : v;
    return acc + inUSD;
  }, 0);

  return {
    prixMoyen: prixUSD,
    coutTotal,
    marge: prixUSD - coutTotal,
    tauxMarge: ((prixUSD - coutTotal) / prixUSD) * 100,
  };
}

function formatUSD(v: number) {
  return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " USD";
}

export default async function AnalysePage() {
  const filieres = await getAnalyseData();

  const FILIERE_COLOR: Record<string, string> = { MAIS: "#92BA59", CAJOU: "#B89B3A", COLA: "#8A9E1A" };
  const FILIERE_ICON: Record<string, string>  = { MAIS: "🌽", CAJOU: "🥜", COLA: "🌰" };

  const analyses = filieres.flatMap((f) =>
    f.produits.map((p) => {
      const marge = calcMarge(p.prixReleves, p.structuresCout);
      return { ...p, filiere: f, marge, accent: FILIERE_COLOR[f.code] ?? "var(--ag-lime)" };
    })
  );

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Header */}
        <div style={{ marginBottom: "28px" }}>
          <p className="ag-section-label" style={{ marginBottom: "6px" }}>Analyse &amp; Investissement · AfricaGro Partners</p>
          <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", margin: 0 }}>
            Opportunités d&apos;investissement
          </h1>
          <p style={{ marginTop: "8px", fontSize: 13, color: "var(--text-secondary)" }}>
            Rentabilité estimée par filière sur la base des prix relevés et structures de coûts disponibles.
            Les marges sont calculées en USD/tonne par défaut.
          </p>
        </div>

        {/* Disclaimer */}
        <div
          style={{
            padding: "14px 20px", borderRadius: "8px", marginBottom: "28px",
            background: "rgba(184,155,58,0.08)", border: "1px solid rgba(184,155,58,0.25)",
            borderLeft: "3px solid #B89B3A",
          }}
        >
          <p style={{ fontSize: 12, color: "#B89B3A", fontFamily: "monospace", margin: 0 }}>
            ⚠ DONNÉES INDICATIVES — Les marges présentées sont calculées à partir de données EXEMPLE et INDICATIF.
            Ne pas utiliser pour des décisions réelles sans validation terrain. Consultez les sources OFFICIEL.
          </p>
        </div>

        {/* Cards analyse par produit */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "16px", marginBottom: "32px" }}>
          {analyses.map((a) => {
            const m = a.marge;
            const hasMarge = m?.marge !== null && m?.marge !== undefined;
            const margePositive = hasMarge && m!.marge! > 0;

            return (
              <div
                key={a.id}
                style={{
                  background: "var(--bg-surface)", border: "1px solid var(--border-subtle)",
                  borderRadius: "10px", overflow: "hidden",
                }}
              >
                <div style={{ height: "3px", background: `linear-gradient(90deg, ${a.accent}, transparent)` }} />
                <div style={{ padding: "20px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
                    <span style={{ fontSize: 22 }}>{FILIERE_ICON[a.filiere.code]}</span>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{a.nom}</div>
                      <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>
                        {a.filiere.nom} · {a.uniteRef}
                      </div>
                    </div>
                    <Link
                      href={`/referentiel/${a.filiere.code.toLowerCase()}/${a.code.toLowerCase()}`}
                      style={{ marginLeft: "auto", fontSize: 10, color: a.accent, textDecoration: "none", fontFamily: "monospace" }}
                    >
                      Fiche →
                    </Link>
                  </div>

                  {/* Métriques */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "16px" }}>
                    <div style={{ background: "var(--bg-elevated)", borderRadius: "6px", padding: "10px" }}>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace", letterSpacing: "0.06em", marginBottom: "4px" }}>PRIX MOYEN</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: a.accent, fontFamily: "monospace" }}>
                        {m?.prixMoyen != null ? formatUSD(m.prixMoyen) : "—"}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: "2px" }}>
                        {a.prixReleves.length} relevé{a.prixReleves.length > 1 ? "s" : ""}
                      </div>
                    </div>
                    <div style={{ background: "var(--bg-elevated)", borderRadius: "6px", padding: "10px" }}>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace", letterSpacing: "0.06em", marginBottom: "4px" }}>COÛTS TOTAUX</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-secondary)", fontFamily: "monospace" }}>
                        {m?.coutTotal != null ? formatUSD(m.coutTotal) : "—"}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: "2px" }}>
                        {a.structuresCout.length} poste{a.structuresCout.length > 1 ? "s" : ""}
                      </div>
                    </div>
                  </div>

                  {/* Marge */}
                  {hasMarge ? (
                    <div
                      style={{
                        padding: "12px 14px", borderRadius: "8px",
                        background: margePositive ? "rgba(74,155,111,0.1)" : "rgba(224,82,82,0.1)",
                        border: `1px solid ${margePositive ? "rgba(74,155,111,0.25)" : "rgba(224,82,82,0.25)"}`,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div>
                          <div style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)", marginBottom: "4px" }}>MARGE BRUTE ESTIMÉE</div>
                          <div style={{ fontSize: 22, fontWeight: 700, fontFamily: "monospace", color: margePositive ? "#4A9B6F" : "#E05252" }}>
                            {margePositive ? "+" : ""}{formatUSD(m!.marge!)}
                          </div>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "monospace", color: margePositive ? "#4A9B6F" : "#E05252" }}>
                            {m!.tauxMarge!.toFixed(1)}%
                          </div>
                          <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace" }}>TAUX DE MARGE</div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "12px 14px", borderRadius: "8px", background: "var(--bg-elevated)", textAlign: "center" }}>
                      <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace", margin: 0 }}>
                        {a.prixReleves.length === 0
                          ? "Aucun prix disponible — déclenchez un connecteur"
                          : "Structure de coûts manquante — saisie manuelle requise"}
                      </p>
                    </div>
                  )}

                  {/* Dérivés */}
                  {a.structuresCout.length > 0 && (
                    <div style={{ marginTop: "12px" }}>
                      <p className="ag-section-label" style={{ marginBottom: "6px" }}>Principaux postes de coût</p>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {a.structuresCout.slice(0, 4).map((c, i) => {
                          const pct = m?.coutTotal ? (Number(c.montant) / (c.devise === "XOF" ? XOF_PER_USD : 1)) / m.coutTotal * 100 : 0;
                          return (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <div style={{ fontSize: 10, color: "var(--text-muted)", width: 100, flexShrink: 0, fontFamily: "monospace" }}>
                                {c.maillon.slice(0, 12)}
                              </div>
                              <div style={{ flex: 1, height: 4, background: "var(--bg-elevated)", borderRadius: "2px", overflow: "hidden" }}>
                                <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: a.accent, borderRadius: "2px" }} />
                              </div>
                              <div style={{ fontSize: 10, color: "var(--text-secondary)", fontFamily: "monospace", width: 40, textAlign: "right" }}>
                                {pct.toFixed(0)}%
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Comparateur récapitulatif */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
            <p className="ag-section-label">Comparateur de rentabilité filières</p>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="ag-table">
              <thead>
                <tr>
                  <th>Filière / Produit</th>
                  <th style={{ textAlign: "right" }}>Prix moyen</th>
                  <th style={{ textAlign: "right" }}>Coûts</th>
                  <th style={{ textAlign: "right" }}>Marge brute</th>
                  <th style={{ textAlign: "right" }}>Taux marge</th>
                  <th>Fiabilité</th>
                  <th>Sources prix</th>
                </tr>
              </thead>
              <tbody>
                {analyses.map((a) => {
                  const m = a.marge;
                  const hasMarge = m?.marge !== null && m?.marge !== undefined;
                  const pos = hasMarge && m!.marge! > 0;
                  const fiabilites = [...new Set(a.prixReleves.map((p) => p.fiabilite))];
                  return (
                    <tr key={a.id}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span>{FILIERE_ICON[a.filiere.code]}</span>
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{a.nom}</div>
                            <div style={{ fontSize: 10, fontFamily: "monospace", color: a.accent }}>{a.code}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", color: a.accent, fontWeight: 700 }}>
                        {m?.prixMoyen != null ? formatUSD(m.prixMoyen) : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", color: "var(--text-secondary)" }}>
                        {m?.coutTotal != null ? formatUSD(m.coutTotal) : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: hasMarge ? (pos ? "#4A9B6F" : "#E05252") : "var(--text-muted)" }}>
                        {hasMarge ? `${pos ? "+" : ""}${formatUSD(m!.marge!)}` : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, fontSize: 14, color: hasMarge ? (pos ? "#4A9B6F" : "#E05252") : "var(--text-muted)" }}>
                        {hasMarge ? `${m!.tauxMarge!.toFixed(1)}%` : "—"}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
                          {fiabilites.map((f) => (
                            <span key={f} style={{
                              fontSize: 8, fontFamily: "monospace", padding: "1px 4px", borderRadius: "3px",
                              color: f === "OFFICIEL" ? "#4A9B6F" : f === "INDICATIF" ? "#92BA59" : "#B89B3A",
                              background: f === "OFFICIEL" ? "rgba(74,155,111,0.12)" : "rgba(146,186,89,0.1)",
                            }}>{f}</span>
                          ))}
                        </div>
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>
                        {a.prixReleves.length} relevés
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
