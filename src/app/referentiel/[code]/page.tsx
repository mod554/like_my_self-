export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";
import { notFound } from "next/navigation";

const FILIERE_META: Record<string, {
  accent: string; accentBg: string; accentBorder: string;
  badge: string; badgeBg: string; badgeColor: string;
  ticker: string; icon: string; gradient: string;
}> = {
  MAIS:  {
    accent: "#92BA59", accentBg: "rgba(146,186,89,0.08)", accentBorder: "rgba(146,186,89,0.2)",
    badge: "Cotée CME/CBOT", badgeBg: "rgba(74,155,111,0.15)", badgeColor: "#4A9B6F",
    ticker: "ZC · CBOT", icon: "🌽",
    gradient: "linear-gradient(135deg, rgba(146,186,89,0.12) 0%, transparent 60%)",
  },
  CAJOU: {
    accent: "#B89B3A", accentBg: "rgba(184,155,58,0.08)", accentBorder: "rgba(184,155,58,0.2)",
    badge: "Non cotée", badgeBg: "rgba(184,155,58,0.12)", badgeColor: "#B89B3A",
    ticker: "RCN · W320", icon: "🥜",
    gradient: "linear-gradient(135deg, rgba(184,155,58,0.12) 0%, transparent 60%)",
  },
  COLA:  {
    accent: "#8A9E1A", accentBg: "rgba(107,118,13,0.08)", accentBorder: "rgba(107,118,13,0.2)",
    badge: "Régional AOF", badgeBg: "rgba(107,118,13,0.15)", badgeColor: "#6B760D",
    ticker: "AOF", icon: "🌰",
    gradient: "linear-gradient(135deg, rgba(107,118,13,0.12) 0%, transparent 60%)",
  },
};

export default async function FilierePage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;

  let filiere: Awaited<ReturnType<typeof prisma.filiere.findUnique>> = null;
  try {
    filiere = await prisma.filiere.findUnique({
      where: { code: code.toUpperCase() },
      include: {
        produits: {
          orderBy: [{ estDerive: "asc" }, { code: "asc" }],
          include: {
            _count: { select: { prixReleves: true } },
            derives: { select: { id: true } },
          },
        },
        actualites: {
          orderBy: { datePublication: "desc" },
          take: 6,
        },
      },
    });
  } catch (e) {
    console.error("FilierePage DB error:", e);
  }

  if (!filiere) notFound();

  const principaux = filiere.produits.filter((p) => !p.estDerive);
  const derives = filiere.produits.filter((p) => p.estDerive);
  const meta = FILIERE_META[filiere.code] ?? {
    accent: "var(--ag-lime)", accentBg: "rgba(146,186,89,0.06)", accentBorder: "rgba(146,186,89,0.15)",
    badge: filiere.code, badgeBg: "rgba(90,122,90,0.12)", badgeColor: "#5A7A5A",
    ticker: filiere.code, icon: "📦", gradient: "",
  };

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Breadcrumb */}
        <div style={{ marginBottom: "24px", display: "flex", alignItems: "center", gap: "6px", fontSize: 12, fontFamily: "monospace", color: "var(--text-muted)" }}>
          <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Africa Agro</Link>
          <span style={{ color: "var(--border-default)" }}>›</span>
          <Link href="/referentiel" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Référentiel</Link>
          <span style={{ color: "var(--border-default)" }}>›</span>
          <span style={{ color: "var(--ag-lime)" }}>{filiere.nom}</span>
        </div>

        {/* Hero filière */}
        <div
          style={{
            background: `var(--bg-surface)`,
            border: "1px solid var(--border-subtle)",
            borderRadius: "12px",
            overflow: "hidden",
            marginBottom: "24px",
            position: "relative",
          }}
        >
          {/* Top accent bar */}
          <div style={{ height: "3px", background: `linear-gradient(90deg, ${meta.accent}, ${meta.accent}44, transparent)` }} />

          {/* Background gradient overlay */}
          <div style={{ position: "absolute", inset: 0, background: meta.gradient, pointerEvents: "none" }} />

          <div style={{ padding: "28px 32px", position: "relative" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "16px" }}>

              <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
                <span
                  style={{
                    width: 56, height: 56, borderRadius: "14px", fontSize: 28,
                    background: meta.accentBg, border: `1px solid ${meta.accentBorder}`,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  {meta.icon}
                </span>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
                    <span
                      style={{
                        fontSize: 10, fontFamily: "monospace", letterSpacing: "0.08em",
                        padding: "2px 8px", borderRadius: "20px",
                        background: "var(--bg-elevated)", color: meta.accent,
                        border: `1px solid ${meta.accentBorder}`,
                      }}
                    >
                      {meta.ticker}
                    </span>
                    <span
                      style={{
                        fontSize: 10, fontFamily: "monospace", letterSpacing: "0.06em",
                        background: meta.badgeBg, color: meta.badgeColor,
                        padding: "2px 8px", borderRadius: "20px",
                        border: `1px solid ${meta.badgeColor}33`,
                      }}
                    >
                      {meta.badge}
                    </span>
                  </div>
                  <h1 className="font-display" style={{ fontSize: 26, color: "var(--text-primary)", margin: 0, lineHeight: 1.1 }}>
                    {filiere.nom}
                  </h1>
                </div>
              </div>

              {/* Quick stats */}
              <div style={{ display: "flex", gap: "24px", flexWrap: "wrap" }}>
                {[
                  { v: principaux.length, l: "Produits" },
                  { v: derives.length,    l: "Dérivés" },
                  { v: filiere.actualites.length, l: "Actualités" },
                ].map(({ v, l }) => (
                  <div key={l} style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 24, fontWeight: 700, color: meta.accent, fontFamily: "monospace", lineHeight: 1 }}>{v}</div>
                    <div style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: "0.05em", marginTop: "3px" }}>{l}</div>
                  </div>
                ))}
              </div>
            </div>

            <p style={{ marginTop: "16px", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7, maxWidth: "800px" }}>
              {filiere.description}
            </p>
          </div>
        </div>

        {/* Main content */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: "20px", alignItems: "start" }}>

          {/* Left — produits */}
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>

            {/* Produits principaux */}
            <div
              style={{
                background: "var(--bg-surface)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "10px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  padding: "14px 20px",
                  borderBottom: "1px solid var(--border-subtle)",
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                }}
              >
                <p className="ag-section-label">Produits principaux</p>
                <span style={{ fontSize: 11, fontFamily: "monospace", color: meta.accent }}>
                  {principaux.length} produit{principaux.length > 1 ? "s" : ""}
                </span>
              </div>
              <div style={{ padding: "8px" }}>
                {principaux.map((p) => (
                  <Link
                    key={p.code}
                    href={`/referentiel/${code.toLowerCase()}/${p.code.toLowerCase()}`}
                    style={{ textDecoration: "none", display: "block" }}
                  >
                    <div
                      style={{
                        display: "flex", alignItems: "center", justifyContent: "space-between",
                        padding: "12px 14px", borderRadius: "8px",
                        transition: "all 150ms ease",
                        cursor: "pointer",
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-elevated)"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <span
                          style={{
                            fontSize: 9, fontFamily: "monospace", letterSpacing: "0.08em",
                            color: meta.accent, background: meta.accentBg,
                            border: `1px solid ${meta.accentBorder}`,
                            padding: "2px 6px", borderRadius: "4px",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {p.code}
                        </span>
                        <span style={{ fontSize: 14, color: "var(--text-primary)", fontWeight: 500 }}>{p.nom}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
                        <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--text-muted)" }}>
                          {p._count.prixReleves} prix
                        </span>
                        {p.derives.length > 0 && (
                          <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--text-muted)" }}>
                            {p.derives.length} dérivés
                          </span>
                        )}
                        <span style={{ color: meta.accent, fontSize: 14 }}>›</span>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>

            {/* Dérivés */}
            {derives.length > 0 && (
              <div
                style={{
                  background: "var(--bg-surface)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "10px",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    padding: "14px 20px",
                    borderBottom: "1px solid var(--border-subtle)",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                  }}
                >
                  <p className="ag-section-label">Dérivés &amp; transformés</p>
                  <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-olive)" }}>
                    {derives.length} produit{derives.length > 1 ? "s" : ""}
                  </span>
                </div>
                <div style={{ padding: "8px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "4px" }}>
                  {derives.map((p) => (
                    <Link
                      key={p.code}
                      href={`/referentiel/${code.toLowerCase()}/${p.code.toLowerCase()}`}
                      style={{ textDecoration: "none" }}
                    >
                      <div
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "10px 14px", borderRadius: "8px",
                          transition: "background 150ms ease",
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.background = "var(--bg-elevated)"; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--ag-olive)", background: "rgba(107,118,13,0.1)", padding: "1px 5px", borderRadius: "3px" }}>
                            {p.code}
                          </span>
                          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{p.nom}</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>{p._count.prixReleves}</span>
                          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>›</span>
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right — actualités */}
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "10px",
              overflow: "hidden",
              position: "sticky",
              top: "80px",
            }}
          >
            <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", gap: "8px" }}>
              <span className="ag-status-dot" />
              <p className="ag-section-label">Actualités récentes</p>
            </div>

            {filiere.actualites.length === 0 ? (
              <div style={{ padding: "24px 18px", textAlign: "center" }}>
                <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
                  Aucune actualité
                </p>
                <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: "4px" }}>
                  Déclenchez la collecte RSS
                </p>
              </div>
            ) : (
              <div>
                {filiere.actualites.map((a, i) => (
                  <div
                    key={a.id}
                    style={{
                      padding: "14px 18px",
                      borderBottom: i < filiere.actualites.length - 1 ? "1px solid var(--border-subtle)" : "none",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                      <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>
                        {new Date(a.datePublication).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })}
                      </span>
                      <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--ag-olive)", background: "rgba(107,118,13,0.1)", padding: "1px 5px", borderRadius: "3px" }}>
                        {a.source.split(" ")[0]}
                      </span>
                    </div>
                    <a
                      href={a.lien}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ textDecoration: "none" }}
                    >
                      <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5, margin: 0, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                        {a.titre}
                      </p>
                    </a>
                  </div>
                ))}
              </div>
            )}

            <div style={{ padding: "12px 18px", borderTop: "1px solid var(--border-subtle)", background: "var(--bg-panel)" }}>
              <Link
                href="/collecte"
                style={{ fontSize: 10, fontFamily: "monospace", color: "var(--ag-olive)", textDecoration: "none", letterSpacing: "0.06em" }}
              >
                → Gérer la collecte automatique
              </Link>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
