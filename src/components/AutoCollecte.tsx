"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const REFRESH_INTERVAL = 30_000; // 30 secondes — affichage
const TAUX_INTERVAL = 60_000;    // 1 minute — collecte taux de change

export default function AutoCollecte() {
  const router = useRouter();
  const [nextRefresh, setNextRefresh] = useState(REFRESH_INTERVAL / 1000);
  const [collecting, setCollecting] = useState(false);
  const [lastCollect, setLastCollect] = useState<string | null>(null);
  const tauxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Countdown display
  useEffect(() => {
    const tick = setInterval(() => {
      setNextRefresh((n) => {
        if (n <= 1) return REFRESH_INTERVAL / 1000;
        return n - 1;
      });
    }, 1_000);
    return () => clearInterval(tick);
  }, []);

  // Page data refresh every 30 seconds
  useEffect(() => {
    const refreshTimer = setInterval(() => {
      router.refresh();
    }, REFRESH_INTERVAL);
    return () => clearInterval(refreshTimer);
  }, [router]);

  // Taux de change auto-collect every 60 seconds
  useEffect(() => {
    async function collectTaux() {
      setCollecting(true);
      try {
        const res = await fetch("/api/connectors", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: "TAUX_CHANGE_LIVE" }),
        });
        const data = await res.json() as { nbImportes?: number; erreur?: string };
        setLastCollect(
          data.erreur ? `⚠ taux: ${data.erreur.slice(0, 40)}` : `✓ ${data.nbImportes ?? 0} taux`
        );
      } catch {
        setLastCollect("⚠ réseau");
      } finally {
        setCollecting(false);
        router.refresh();
      }
    }

    // Run immediately on mount
    collectTaux();

    // Then every 60s
    tauxTimerRef.current = setInterval(collectTaux, TAUX_INTERVAL);
    return () => {
      if (tauxTimerRef.current) clearInterval(tauxTimerRef.current);
    };
  }, [router]);

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "8px",
      fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)",
      background: "rgba(146,186,89,0.06)", border: "1px solid rgba(146,186,89,0.2)",
      borderRadius: "6px", padding: "4px 10px",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: collecting ? "#B89B3A" : "var(--ag-lime)",
        display: "inline-block",
        animation: collecting ? "none" : "pulse 2s infinite",
      }} />
      <span>
        {collecting ? "collecte…" : lastCollect ?? "auto"}
        {" · "}
        <span style={{ color: "var(--ag-olive)" }}>
          maj dans {nextRefresh}s
        </span>
      </span>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
