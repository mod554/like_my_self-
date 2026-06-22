"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

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
          Erreur serveur
          {error.digest && (
            <span style={{ marginLeft: 8, color: "var(--data-down)" }}>
              · #{error.digest}
            </span>
          )}
        </div>
        <h2
          className="font-display"
          style={{ fontSize: 22, color: "var(--text-primary)", marginBottom: "12px" }}
        >
          Cette page n&apos;a pas pu se charger
        </h2>
        <p
          style={{
            fontSize: 13,
            color: "var(--text-secondary)",
            lineHeight: 1.6,
            marginBottom: "24px",
          }}
        >
          Une erreur s&apos;est produite lors du rendu. Cela peut être dû à une connexion
          base de données temporaire ou à des données manquantes.
        </p>
        <div style={{ display: "flex", gap: "12px", justifyContent: "center", flexWrap: "wrap" }}>
          <button
            onClick={reset}
            style={{
              padding: "10px 20px",
              borderRadius: "8px",
              fontWeight: 700,
              fontSize: 13,
              cursor: "pointer",
              background: "var(--gradient-lime)",
              color: "var(--text-inverse)",
              border: "none",
              boxShadow: "0 2px 12px rgba(90,138,42,0.2)",
            }}
          >
            Réessayer
          </button>
          <Link
            href="/"
            style={{
              padding: "10px 20px",
              borderRadius: "8px",
              fontSize: 13,
              color: "var(--text-secondary)",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-default)",
              textDecoration: "none",
            }}
          >
            Accueil
          </Link>
        </div>
      </div>
    </div>
  );
}
