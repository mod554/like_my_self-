"use client";

// Rafraîchissement d'affichage global — toutes les 30 secondes, la plateforme
// recharge les données serveur (router.refresh) pour afficher les derniers prix
// collectés. La collecte réelle se fait à la cadence de chaque source (café/
// cacao intraday, cajou quotidien, palme/hévéa mensuel) ; ici on ne fait que
// ré-afficher. Un petit badge discret indique le compte à rebours.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const REFRESH_MS = 30_000;

export default function AutoRefresh() {
  const router = useRouter();
  const [reste, setReste] = useState(REFRESH_MS / 1000);

  useEffect(() => {
    const refresh = setInterval(() => router.refresh(), REFRESH_MS);
    const tick = setInterval(() => setReste((n) => (n <= 1 ? REFRESH_MS / 1000 : n - 1)), 1_000);
    return () => { clearInterval(refresh); clearInterval(tick); };
  }, [router]);

  return (
    <div
      title="Les prix affichés se rafraîchissent automatiquement toutes les 30 secondes"
      style={{
        position: "fixed", bottom: 14, right: 14, zIndex: 50,
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10, fontFamily: "monospace", color: "var(--text-muted, #7a7a70)",
        background: "rgba(146,186,89,0.10)", border: "1px solid rgba(146,186,89,0.25)",
        borderRadius: 999, padding: "4px 10px", backdropFilter: "blur(4px)",
      }}
    >
      <span style={{
        width: 6, height: 6, borderRadius: "50%", background: "var(--ag-lime, #92BA59)",
        display: "inline-block", animation: "agpulse 2s infinite",
      }} />
      <span>maj auto · {reste}s</span>
      <style>{`@keyframes agpulse { 0%,100%{opacity:1} 50%{opacity:.4} }`}</style>
    </div>
  );
}
