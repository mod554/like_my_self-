import Link from "next/link";
import AfricaGroLogo from "@/components/brand/AfricaGroLogo";

const FILIERES = [
  {
    code: "mais",
    label: "Maïs",
    ticker: "ZC · CME/CBOT",
    badge: "Cotée bourse",
    badgeBg: "rgba(74,155,111,0.15)",
    badgeColor: "#4A9B6F",
    accent: "#92BA59",
    accentBg: "rgba(146,186,89,0.06)",
    icon: "🌽",
    desc: "Commodity internationale cotée Chicago Board of Trade — futures ZC, données USDA WASDE, FAO FPMA, prix spot mondiaux.",
    stats: [
      { label: "Référence", value: "CBOT ZC" },
      { label: "Devise", value: "USD/T" },
      { label: "Sources", value: "4 actives" },
    ],
    sources: "World Bank · USDA FAS · FAO FPMA · IndexMundi",
  },
  {
    code: "cajou",
    label: "Cajou · Anacarde",
    ticker: "RCN · W320",
    badge: "Non coté",
    badgeBg: "rgba(184,155,58,0.12)",
    badgeColor: "#B89B3A",
    accent: "#B89B3A",
    accentBg: "rgba(184,155,58,0.06)",
    icon: "🥜",
    desc: "Marché actif non coté — prix bord-champ RCN Côte d'Ivoire, amandes W320/W240, chaîne CI → Vietnam/Inde.",
    stats: [
      { label: "Référence", value: "RCN FOB" },
      { label: "Devise", value: "USD/T" },
      { label: "Sources", value: "3 actives" },
    ],
    sources: "Conseil Anacarde CI · FPMA · Manuel",
  },
  {
    code: "cola",
    label: "Noix de Cola",
    ticker: "Régional · AOF",
    badge: "Régional",
    badgeBg: "rgba(107,118,13,0.15)",
    badgeColor: "#6B760D",
    accent: "#8A9E1A",
    accentBg: "rgba(107,118,13,0.06)",
    icon: "🌰",
    desc: "Marché régional Afrique de l'Ouest — pas de cotation mondiale, prix observatoires RESIMAO, Lagos et Abidjan.",
    stats: [
      { label: "Référence", value: "Lagos · ABI" },
      { label: "Devise", value: "XOF · NGN" },
      { label: "Sources", value: "2 actives" },
    ],
    sources: "RESIMAO · Observatoires · Manuel",
  },
];

const METRICS = [
  { label: "Filières couvertes",   value: "3",     sub: "Maïs · Cajou · Cola" },
  { label: "Sources de données",   value: "7",     sub: "API · HTML · RSS" },
  { label: "Collecte auto",        value: "24/7",  sub: "6 connecteurs actifs" },
  { label: "Zones géographiques",  value: "AOF+",  sub: "UEMOA · Monde" },
];

export default function Home() {
  return (
    <div style={{ flex: 1 }}>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section
        style={{
          background: "var(--gradient-hero)",
          borderBottom: "1px solid var(--border-subtle)",
          padding: "64px 0 56px",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Aurora + grain — profondeur studio */}
        <div className="ag-aurora"><span /></div>
        <div className="ag-grain" />

        {/* Background grid decoration */}
        <div
          style={{
            position: "absolute", inset: 0,
            backgroundImage: `
              linear-gradient(rgba(146,186,89,0.03) 1px, transparent 1px),
              linear-gradient(90deg, rgba(146,186,89,0.03) 1px, transparent 1px)
            `,
            backgroundSize: "40px 40px",
            pointerEvents: "none",
          }}
        />

        <div className="ag-container" style={{ position: "relative" }}>
          {/* Brand */}
          <div style={{ marginBottom: "36px" }}>
            <AfricaGroLogo size="lg" />
            <p style={{
              marginTop: "10px", fontSize: 13, color: "var(--ag-olive)",
              fontStyle: "italic", fontFamily: "var(--font-ubuntu, sans-serif)",
              letterSpacing: "0.01em",
            }}>
              Bâtir aujourd&apos;hui, semer l&apos;avenir, récolter la valeur de demain.
            </p>
          </div>

          {/* Tagline */}
          <div style={{ maxWidth: "640px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px" }}>
              <span style={{
                fontSize: 10, fontFamily: "monospace", letterSpacing: "0.15em",
                textTransform: "uppercase", color: "var(--ag-lime)",
                background: "rgba(146,186,89,0.1)", border: "1px solid rgba(146,186,89,0.2)",
                padding: "3px 10px", borderRadius: "20px",
              }}>
                Terminal de marché agricole v1.0
              </span>
            </div>
            <h1 className="font-display" style={{
              fontSize: "clamp(26px,3.5vw,42px)", color: "var(--text-primary)",
              lineHeight: 1.15, marginBottom: "16px",
            }}>
              Veille de marché &amp;{" "}
              <span className="ag-gradient-text">analyse d&apos;investissement</span>{" "}
              pour les filières africaines
            </h1>
            <p style={{ fontSize: 15, color: "var(--text-secondary)", lineHeight: 1.7, maxWidth: "560px" }}>
              Données agrégées en temps réel depuis les sources mondiales — World Bank, USDA, FAO FPMA,
              RESIMAO, Conseil Anacarde CI. Référentiel normalisé, prix historiques, analyses filière.
            </p>
          </div>

          {/* Hero CTA */}
          <div style={{ display: "flex", gap: "12px", marginTop: "32px", flexWrap: "wrap" }}>
            <Link
              href="/referentiel"
              style={{
                display: "inline-flex", alignItems: "center", gap: "8px",
                padding: "12px 24px", borderRadius: "8px",
                background: "var(--gradient-lime)", color: "var(--text-inverse)",
                fontWeight: 700, fontSize: 14, textDecoration: "none",
                boxShadow: "0 4px 16px rgba(146,186,89,0.3)",
                transition: "all 200ms ease",
              }}
            >
              Accéder au référentiel →
            </Link>
            <Link
              href="/referentiel/mais"
              style={{
                display: "inline-flex", alignItems: "center", gap: "8px",
                padding: "12px 24px", borderRadius: "8px",
                background: "var(--bg-elevated)", color: "var(--text-secondary)",
                border: "1px solid var(--border-default)",
                fontWeight: 500, fontSize: 14, textDecoration: "none",
                transition: "all 200ms ease",
              }}
            >
              Filière Maïs ZC
            </Link>
          </div>
        </div>
      </section>

      {/* ── Metrics bar ─────────────────────────────────────────────────── */}
      <section
        style={{
          background: "var(--bg-surface)",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div
          className="ag-container"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: "0",
          }}
        >
          {METRICS.map((m, i) => (
            <div
              key={m.label}
              style={{
                padding: "20px 24px",
                borderRight: i < METRICS.length - 1 ? "1px solid var(--border-subtle)" : "none",
              }}
            >
              <div
                style={{
                  fontSize: 28, fontWeight: 700, color: "var(--ag-lime)",
                  fontFamily: "var(--font-ubuntu-mono, monospace)", lineHeight: 1,
                  marginBottom: "4px",
                }}
              >
                {m.value}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600, marginBottom: "2px" }}>{m.label}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace" }}>{m.sub}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Filières ─────────────────────────────────────────────────────── */}
      <section style={{ padding: "48px 0" }}>
        <div className="ag-container">
          <div style={{ marginBottom: "32px" }}>
            <p className="ag-section-label" style={{ marginBottom: "8px" }}>Filières couvertes</p>
            <h2 className="font-display" style={{ fontSize: 22, color: "var(--text-primary)" }}>
              Sélectionnez un marché
            </h2>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "16px",
            }}
          >
            {FILIERES.map((f) => (
              <Link
                key={f.code}
                href={`/referentiel/${f.code}`}
                style={{ textDecoration: "none", display: "block" }}
              >
                <div
                  className="ag-filiere-card"
                  style={{ padding: "24px" }}
                >
                  {/* Card header */}
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: "16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                      <span style={{ fontSize: 28 }}>{f.icon}</span>
                      <div>
                        <div style={{ fontSize: 17, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1.2 }}>
                          {f.label}
                        </div>
                        <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.08em", marginTop: "2px" }}>
                          {f.ticker}
                        </div>
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: 10, fontFamily: "monospace", letterSpacing: "0.06em",
                        background: f.badgeBg, color: f.badgeColor,
                        padding: "3px 10px", borderRadius: "20px",
                        border: `1px solid ${f.badgeColor}33`,
                      }}
                    >
                      {f.badge}
                    </span>
                  </div>

                  {/* Description */}
                  <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: "20px" }}>
                    {f.desc}
                  </p>

                  {/* Stats row */}
                  <div
                    style={{
                      display: "grid", gridTemplateColumns: "repeat(3,1fr)",
                      gap: "8px", marginBottom: "16px",
                    }}
                  >
                    {f.stats.map((s) => (
                      <div
                        key={s.label}
                        style={{
                          background: f.accentBg, borderRadius: "6px",
                          padding: "8px", textAlign: "center",
                        }}
                      >
                        <div style={{ fontSize: 13, fontWeight: 700, color: f.accent, fontFamily: "monospace" }}>{s.value}</div>
                        <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase", marginTop: "2px" }}>{s.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* Footer */}
                  <div
                    style={{
                      borderTop: "1px solid var(--border-subtle)",
                      paddingTop: "12px",
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                    }}
                  >
                    <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>
                      {f.sources}
                    </span>
                    <span style={{ fontSize: 12, color: f.accent, fontWeight: 600 }}>
                      Explorer →
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ── Architecture sources ──────────────────────────────────────────── */}
      <section
        style={{
          padding: "40px 0 48px",
          background: "var(--bg-surface)",
          borderTop: "1px solid var(--border-subtle)",
        }}
      >
        <div className="ag-container">
          <p className="ag-section-label" style={{ marginBottom: "24px" }}>Sources de données automatisées</p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "12px",
            }}
          >
            {[
              { name: "World Bank Pink Sheet", type: "API REST", freq: "Mensuel", status: "OK", filiere: "Maïs" },
              { name: "FAO FPMA",              type: "API REST", freq: "Hebdo",   status: "OK", filiere: "Maïs · Cajou" },
              { name: "USDA FAS PSD Online",   type: "API REST", freq: "Mensuel", status: "OK", filiere: "Maïs" },
              { name: "Conseil Anacarde CI",   type: "HTML",     freq: "Bi-hebdo", status: "OK", filiere: "Cajou" },
              { name: "RESIMAO",               type: "HTML",     freq: "Hebdo",   status: "OK", filiere: "Maïs · Cola" },
              { name: "RSS Agri (FAO/Reuters)", type: "RSS",     freq: "6h",      status: "OK", filiere: "Toutes" },
              { name: "IndexMundi",            type: "HTML",     freq: "Mensuel", status: "OK", filiere: "Maïs · Cajou" },
            ].map((src) => (
              <div
                key={src.name}
                className="ag-kpi"
                style={{ padding: "14px 16px" }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "8px" }}>
                  <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.06em" }}>
                    {src.type}
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: 10, color: "var(--data-up)", fontFamily: "monospace" }}>
                    <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--data-up)", display: "inline-block" }} />
                    {src.status}
                  </span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: "4px" }}>
                  {src.name}
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "monospace" }}>{src.filiere}</span>
                  <span style={{ fontSize: 10, color: "var(--ag-olive)", fontFamily: "monospace" }}>{src.freq}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

    </div>
  );
}
