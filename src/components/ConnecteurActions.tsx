"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  code?: string;
  compact?: boolean;
}

export default function ConnecteurActions({ code, compact = false }: Props) {
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const router = useRouter();

  async function trigger() {
    setLoading(true);
    setMsg(null);
    try {
      const body = code ? { code } : { tous: true };
      const res = await fetch("/api/connectors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json() as { nbImportes?: number; resultats?: Array<{ code: string; nbImportes?: number }> };
      if (data.resultats) {
        const total = data.resultats.reduce((a, r) => a + (r.nbImportes ?? 0), 0);
        setMsg(`${total} entrées importées`);
      } else {
        setMsg(`${data.nbImportes ?? 0} entrées importées`);
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
