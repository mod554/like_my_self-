export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";

const FILIERE_META: Record<string, {
  accent: string; accentBg: string;
  badge: string; badgeBg: string; badgeColor: string;
  ticker: string; icon: string;
}> = {
  MAIS:  {
    accent: "#92BA59", accentBg: "rgba(146,186,89,0.08)",
    badge: "Cotée CME/CBOT", badgeBg: "rgba(74,155,111,0.15)", badgeColor: "#4A9B6F",
    ticker: "ZC", icon: "🌽",
  },
  CAJOU: {
    accent: "#B89B3A", accentBg: "rgba(184,155,58,0.08)",
    badge: "Non cotée", badgeBg: "rgba(184,155,58,0.12)", badgeColor: "#B89B3A",
    ticker: "RCN · W320", icon: "🥜",
  },
  COLA:  {
    accent: "#8A9E1A", accentBg: "rgba(107,118,13,0.08)",
    badge: "Régional AOF", badgeBg: "rgba(107,118,13,0.15)", badgeColor: "#6B760D",
    ticker: "AOF", icon: "🌰",
  },
};

export default async function ReferentielPage() {
  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      produits: { select: { id: true, estDerive: true } },
      _count: { select: { actualites: true } },
    },
  });

  const totalProduits = filieres.reduce((a, f) => a + f.produits.length, 0);

  return (
    <div style={{ flex: 1, padding: "40px 0" }}>
      <div className="ag-container">

        {/* Breadcrumb */}
        <div style={{ marginBottom: "32px" }}>
          <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.08em", marginBottom: "8px" }}>
            AFRICAGRO PARTNERS · TERMINAL MARCHÉ
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
            <div>
              <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", marginBottom: "6px" }}>
                Référentiel des filières
              </h1>
              <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                {filieres.length} filières · {totalProduits} produits &amp; dérivés référencés
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              {["Maïs ZC", "Cajou RCN", "Cola AOF"].map((tag) => (
                <span
                  key={tag}
                  style={{
                    fontSize: 10, fontFamily: "monospace", letterSpacing: "0.08em",
                    padding: "4px 10px", borderRadius: "20px",
                    background: "var(--bg-elevated)", color: "var(--text-secondary)",
                    border: "1px solid var(--border-subtle)",
                  }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* Filières grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "16px" }}>
          {filieres.map((f) => {
            const meta = FILIERE_META[f.code] ?? {
              accent: "var(--ag-lime)", accentBg: "rgba(146,186,89,0.06)",
              badge: f.code, badgeBg: "rgba(90,122,90,0.12)", badgeColor: "#5A7A5A",
              ticker: f.code, icon: "📦",
            };
            const principaux = f.produits.filter((p) => !p.estDerive).length;
            const derives = f.produits.filter((p) => p.estDerive).length;

            return (
              <Link
                key={f.code}
                href={`/referentiel/${f.code.toLowerCase()}`}
                style={{ textDecoration: "none" }}
              >
                <div className="ag-filiere-card">
                  {/* Card accent bar */}
                  <div style={{ height: "3px", background: `linear-gradient(90deg, ${meta.accent}, transparent)` }} />

                  <div style={{ padding: "20px 24px" }}>
                    {/* Header */}
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "14px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <span
                          style={{
                            width: 44, height: 44, borderRadius: "10px",
                            background: meta.accentBg, border: `1px solid ${meta.accent}30`,
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 22,
                          }}
                        >
                          {meta.icon}
                        </span>
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1.2 }}>
                            {f.nom}
                          </div>
                          <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.1em", marginTop: "2px" }}>
                            {meta.ticker}
                          </div>
                        </div>
                      </div>
                      <span
                        style={{
                          fontSize: 10, fontFamily: "monospace", letterSpacing: "0.06em",
                          background: meta.badgeBg, color: meta.badgeColor,
                          padding: "3px 8px", borderRadius: "20px",
                          border: `1px solid ${meta.badgeColor}33`,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {meta.badge}
                      </span>
                    </div>

                    {/* Description */}
                    <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: "16px" }}>
                      {f.description}
                    </p>

                    {/* Stats */}
                    <div
                      style={{
                        display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                        gap: "8px", padding: "12px 0",
                        borderTop: "1px solid var(--border-subtle)",
                        borderBottom: "1px solid var(--border-subtle)",
                        marginBottom: "14px",
                      }}
                    >
                      {[
                        { v: principaux, l: "Produit" + (principaux > 1 ? "s" : "") },
                        { v: derives,    l: "Dérivé" + (derives > 1 ? "s" : "") },
                        { v: f._count.actualites, l: "Actualités" },
                      ].map(({ v, l }) => (
                        <div key={l} style={{ textAlign: "center" }}>
                          <div style={{ fontSize: 20, fontWeight: 700, color: meta.accent, fontFamily: "monospace", lineHeight: 1 }}>
                            {v}
                          </div>
                          <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: "2px", letterSpacing: "0.04em" }}>
                            {l}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Footer action */}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <span style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace" }}>
                        Voir fiche complète
                      </span>
                      <span style={{ fontSize: 13, color: meta.accent, fontWeight: 700 }}>→</span>
                    </div>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>

        {/* Info panel */}
        <div
          style={{
            marginTop: "40px",
            padding: "20px 24px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "10px",
            borderLeft: "3px solid var(--ag-lime)",
          }}
        >
          <div style={{ display: "flex", gap: "32px", flexWrap: "wrap", alignItems: "center" }}>
            <div>
              <p className="ag-section-label" style={{ marginBottom: "4px" }}>Fiabilité des données</p>
              <div style={{ display: "flex", gap: "16px", flexWrap: "wrap" }}>
                {[
                  { label: "OFFICIEL",   color: "#4A9B6F" },
                  { label: "INDICATIF",  color: "#92BA59" },
                  { label: "ESTIMÉ",     color: "#B89B3A" },
                  { label: "EXEMPLE",    color: "#5A7A5A" },
                ].map((b) => (
                  <span key={b.label} style={{ display: "flex", alignItems: "center", gap: "5px", fontSize: 11, color: b.color, fontFamily: "monospace" }}>
                    <span style={{ width: 6, height: 6, borderRadius: "50%", background: b.color, display: "inline-block" }} />
                    {b.label}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace", textAlign: "right" }}>
              <div>Données compilées automatiquement</div>
              <div style={{ color: "var(--ag-lime)" }}>7 sources · Mise à jour continue</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
