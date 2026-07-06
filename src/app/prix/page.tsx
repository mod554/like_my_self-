export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import PrixForm from "@/components/prix/PrixForm";
import Link from "next/link";

export default async function PrixPage() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let produits: any[] = [], marches: any[] = [], sources: any[] = [], derniers: any[] = [];
  try {
    [produits, marches, sources] = await Promise.all([
      prisma.produit.findMany({ orderBy: [{ filiere: { code: "asc" } }, { code: "asc" }], include: { filiere: { select: { code: true, nom: true } } } }),
      prisma.marche.findMany({ orderBy: { code: "asc" }, include: { zone: { select: { nom: true } } } }),
      prisma.source.findMany({ where: { actif: true, type: "MANUEL" }, orderBy: { code: "asc" } }),
    ]);
    derniers = await prisma.prixReleve.findMany({
      where: { fiabilite: { not: "EXEMPLE" } },
      orderBy: { dateCollecte: "desc" },
      take: 20,
      include: {
        produit: { select: { code: true, nom: true, filiere: { select: { code: true } } } },
        marche: { select: { code: true, nom: true } },
        source: { select: { code: true } },
      },
    });
  } catch (e) {
    console.error("PrixPage DB error:", e);
  }

  const FILIERE_COLOR: Record<string, string> = { MAIS: "#92BA59", CAJOU: "#B89B3A", COLA: "#8A9E1A" };

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Header */}
        <div style={{ marginBottom: "28px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "10px" }}>
            <p className="ag-section-label" style={{ marginBottom: "6px" }}>Phase 2 · Saisie des prix</p>
            <a
              href="/api/export"
              download
              style={{
                display: "inline-flex", alignItems: "center", gap: "6px",
                padding: "7px 14px", borderRadius: "8px", textDecoration: "none",
                background: "rgba(0,61,46,0.85)", color: "#FFFFFF",
                border: "1px solid rgba(90,138,42,0.4)",
                fontSize: 12, fontWeight: 600,
              }}
            >
              ⬇ Exporter Excel (prix + taux + sources)
            </a>
          </div>
          <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", margin: 0 }}>
            Saisie manuelle &amp; import CSV
          </h1>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "400px 1fr", gap: "20px", alignItems: "start" }}>

          {/* Formulaire saisie */}
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Nouveau relevé de prix</p>
              </div>
              <div style={{ padding: "20px" }}>
                <PrixForm produits={produits} marches={marches} sources={sources} />
              </div>
            </div>

            {/* Info CSV */}
            <div style={{
              padding: "16px 20px", borderRadius: "10px",
              background: "rgba(107,118,13,0.08)", border: "1px solid rgba(107,118,13,0.25)",
              borderLeft: "3px solid var(--ag-olive)",
            }}>
              <p className="ag-section-label" style={{ marginBottom: "8px" }}>Import CSV (Phase 2+)</p>
              <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6, margin: 0 }}>
                Format attendu : <span style={{ fontFamily: "monospace", color: "var(--ag-lime)" }}>produit_code, marche_code, date, valeur, devise, unite</span>
                <br />Bientôt disponible avec validation et aperçu avant import.
              </p>
            </div>
          </div>

          {/* Derniers relevés */}
          <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
            <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <p className="ag-section-label">Derniers relevés saisis</p>
              <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)" }}>{derniers.length} récents</span>
            </div>
            {derniers.length === 0 ? (
              <div style={{ padding: "24px", textAlign: "center" }}>
                <p style={{ fontSize: 13, color: "var(--text-muted)", fontFamily: "monospace" }}>
                  Aucun relevé — utilisez le formulaire ou{" "}
                  <Link href="/collecte" style={{ color: "var(--ag-lime)", textDecoration: "none" }}>déclenchez un connecteur</Link>
                </p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="ag-table">
                  <thead>
                    <tr>
                      <th>Produit</th><th>Marché</th>
                      <th style={{ textAlign: "right" }}>Valeur</th>
                      <th>Devise</th><th>Date</th><th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {derniers.map((r) => {
                      const accent = FILIERE_COLOR[r.produit.filiere.code] ?? "var(--ag-lime)";
                      return (
                        <tr key={r.id}>
                          <td>
                            <div style={{ fontSize: 10, fontFamily: "monospace", color: accent }}>{r.produit.code}</div>
                            <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{r.produit.nom.slice(0, 24)}</div>
                          </td>
                          <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>{r.marche.code}</td>
                          <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: accent }}>
                            {Number(r.valeur).toLocaleString("fr-FR", { maximumFractionDigits: 2 })}
                          </td>
                          <td style={{ fontFamily: "monospace" }}>{r.devise}</td>
                          <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                            {new Date(r.dateReleve).toLocaleDateString("fr-FR")}
                          </td>
                          <td style={{ fontFamily: "monospace", fontSize: 10, color: "var(--text-muted)" }}>{r.source.code}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
