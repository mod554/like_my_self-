"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  code?: string;
  compact?: boolean;
}

export function InitBddButton() {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const router = useRouter();

  async function init() {
    setLoading(true);
    setMsg(null);
    setIsError(false);
    try {
      const res = await fetch("/api/init", { method: "POST" });
      const data = await res.json() as { ok: boolean; summary: string; errors: string[] };
      setIsError(!data.ok);
      setMsg(data.summary);
      if (data.ok) router.refresh();
    } catch {
      setIsError(true);
      setMsg("Erreur réseau");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
      {msg && (
        <span style={{
          fontSize: 11, fontFamily: "monospace",
          color: isError ? "#E05252" : "#4A9B6F",
          background: isError ? "rgba(224,82,82,0.08)" : "rgba(74,155,111,0.1)",
          padding: "4px 10px", borderRadius: "6px",
        }}>
          {isError ? "✗" : "✓"} {msg}
        </span>
      )}
      <button
        onClick={init}
        disabled={loading}
        style={{
          display: "flex", alignItems: "center", gap: "6px",
          padding: "8px 16px", borderRadius: "8px", cursor: loading ? "not-allowed" : "pointer",
          background: loading ? "var(--bg-elevated)" : "rgba(0,61,46,0.08)",
          color: loading ? "var(--text-muted)" : "var(--ag-forest)",
          border: "1px solid rgba(0,61,46,0.2)",
          fontSize: 13, fontWeight: 600,
          transition: "all 150ms ease",
        }}
      >
        {loading ? "⏳ Initialisation…" : "⚙ Initialiser la BDD"}
      </button>
    </div>
  );
}

export default function ConnecteurActions({ code, compact = false }: Props) {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();

  async function trigger() {
    setLoading(true);
    setMsg(null);
    try {
      if (code) {
        // Single connector — one request
        const res = await fetch("/api/connectors", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        const data = await res.json() as { nbImportes?: number; erreur?: string };
        setMsg(data.erreur ? `Erreur: ${data.erreur}` : `${data.nbImportes ?? 0} entrées importées`);
      } else {
        // All connectors — run each individually in parallel to avoid single-request timeout
        const { CONNECTEUR_CODES } = await import("@/lib/connectors/codes");
        const results = await Promise.allSettled(
          CONNECTEUR_CODES.map((code) =>
            fetch("/api/connectors", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ code }),
            }).then((r) => r.json() as Promise<{ nbImportes?: number; code?: string }>)
          )
        );
        const total = results.reduce((sum, r) => sum + (r.status === "fulfilled" ? (r.value?.nbImportes ?? 0) : 0), 0);
        const errors = results.filter((r) => r.status === "rejected").length;
        setMsg(errors > 0 ? `${total} importées — ${errors} erreurs` : `${total} entrées importées`);
      }
      router.refresh();
    } catch {
      setMsg("Erreur réseau");
    } finally {
      setLoading(false);
    }
  }

  if (compact) {
    return (
      <button
        onClick={trigger}
        disabled={loading}
        style={{
          fontSize: 10, fontFamily: "monospace", letterSpacing: "0.05em",
          padding: "3px 10px", borderRadius: "4px", cursor: loading ? "not-allowed" : "pointer",
          background: loading ? "var(--bg-elevated)" : "rgba(146,186,89,0.1)",
          color: loading ? "var(--text-muted)" : "var(--ag-lime)",
          border: "1px solid rgba(146,186,89,0.25)",
          transition: "all 150ms ease",
        }}
      >
        {loading ? "…" : "▶ Run"}
      </button>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
      {msg && (
        <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)", background: "rgba(146,186,89,0.1)", padding: "4px 10px", borderRadius: "6px" }}>
          ✓ {msg}
        </span>
      )}
      <button
        onClick={trigger}
        disabled={loading}
        style={{
          display: "flex", alignItems: "center", gap: "6px",
          padding: "8px 16px", borderRadius: "8px", cursor: loading ? "not-allowed" : "pointer",
          background: loading ? "var(--bg-elevated)" : "rgba(146,186,89,0.12)",
          color: loading ? "var(--text-muted)" : "var(--ag-lime)",
          border: "1px solid rgba(146,186,89,0.3)",
          fontSize: 13, fontWeight: 600,
          transition: "all 150ms ease",
        }}
      >
        <span>{loading ? "⏳" : "▶"}</span>
        {loading ? "Collecte en cours…" : "Lancer tous les connecteurs"}
      </button>
    </div>
  );
}
