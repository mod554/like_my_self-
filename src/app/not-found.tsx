import Link from "next/link";

export default function NotFound() {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "64px 24px",
        minHeight: "60vh",
      }}
    >
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <div
          style={{
            fontSize: 10,
            fontFamily: "monospace",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            marginBottom: "16px",
          }}
        >
          404 · Page introuvable
        </div>
        <h2
          className="font-display"
          style={{ fontSize: 22, color: "var(--text-primary)", marginBottom: "12px" }}
        >
          Cette page n&apos;existe pas
        </h2>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-secondary)",
            lineHeight: 1.6,
            marginBottom: "24px",
          }}
        >
          La page demandée est introuvable. Elle a peut-être été déplacée ou supprimée.
        </p>
        <Link
          href="/"
          style={{
            display: "inline-block",
            padding: "10px 24px",
            borderRadius: "8px",
            fontWeight: 700,
            fontSize: 13,
            background: "var(--gradient-lime)",
            color: "var(--text-inverse)",
            textDecoration: "none",
            boxShadow: "0 2px 12px rgba(90,138,42,0.2)",
          }}
        >
          Retour à l&apos;accueil
        </Link>
      </div>
    </div>
  );
}
