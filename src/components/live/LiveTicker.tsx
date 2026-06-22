"use client";

import { useEffect, useState, useCallback } from "react";

interface TickerItem {
  code: string;
  nom: string;
  filiere: string;
  unite: string;
  valeur: number | null;
  valeurUsd: number | null;
  devise: string | null;
  uniteReleve: string | null;
  variation: number | null;
  hausse: boolean | null;
  dateReleve: string | null;
  fiabilite: string | null;
}

interface TauxItem {
  USD_XOF: number;
  EUR_USD: number;
  EUR_XOF: number;
}

interface TickerData {
  ticker: TickerItem[];
  taux: TauxItem;
  ts: string;
}

interface Props {
  initialData?: TickerData | null;
  refreshInterval?: number; // ms, défaut 5 minutes
}

function fmt(v: number | null, devise: string | null): string {
  if (v === null) return "—";
  const n = v >= 10000 ? v.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
    : v >= 100 ? v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })
    : v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return devise ? `${n} ${devise}` : n;
}

export default function LiveTicker({ initialData, refreshInterval = 5 * 60 * 1000 }: Props) {
  const [data, setData] = useState<TickerData | null>(initialData ?? null);
  const [pulse, setPulse] = useState(false);

  const fetchTicker = useCallback(async () => {
    try {
      const res = await fetch("/api/ticker", { cache: "no-store" });
      if (!res.ok) return;
      const json = await res.json() as TickerData;
      setData(json);
      setPulse(true);
      setTimeout(() => setPulse(false), 800);
    } catch {
      // Silencieux
    }
  }, []);

  useEffect(() => {
    const interval = setInterval(fetchTicker, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchTicker, refreshInterval]);

  const items = data?.ticker ?? [];
  const taux = data?.taux;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
      <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
        <span
          className="ag-status-dot"
          style={pulse ? { boxShadow: "0 0 6px #92BA59", transform: "scale(1.3)", background: "#92BA59" } : { background: "#92BA59" }}
        />
        <span style={{ fontSize: 10, fontFamily: "monospace", color: "#92BA59", letterSpacing: "0.1em", fontWeight: 700 }}>
          LIVE
        </span>
      </span>

      <div style={{ display: "flex", gap: "20px", fontSize: 11, fontFamily: "monospace", color: "rgba(255,255,255,0.75)", flexWrap: "wrap" }}>
        {items.length === 0 ? (
          <>
            <span><span style={{ color: "rgba(255,255,255,0.5)" }}>MAIS · ZC  </span><span style={{ color: "#92BA59" }}>—</span></span>
            <span><span style={{ color: "rgba(255,255,255,0.5)" }}>CAJOU · RCN  </span><span style={{ color: "#92BA59" }}>—</span></span>
            <span><span style={{ color: "rgba(255,255,255,0.5)" }}>COLA · AOF  </span><span style={{ color: "#92BA59" }}>—</span></span>
          </>
        ) : (
          items.map((item) => {
            const color = item.hausse === true ? "#92BA59" : item.hausse === false ? "#E05252" : "#92BA59";
            const arrow = item.hausse === true ? "▲" : item.hausse === false ? "▼" : "";
            return (
              <span key={item.code} style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span style={{ color: "rgba(255,255,255,0.5)" }}>
                  {item.filiere} · {item.code}
                </span>
                <span style={{ color }}>
                  {arrow} {item.valeurUsd != null ? `${item.valeurUsd.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} USD/T` : fmt(item.valeur, item.devise)}
                </span>
                {item.variation !== null && (
                  <span style={{ fontSize: 9, color, opacity: 0.8 }}>
                    ({item.variation > 0 ? "+" : ""}{item.variation.toFixed(1)}%)
                  </span>
                )}
              </span>
            );
          })
        )}
      </div>

      {taux && (
        <span style={{ fontSize: 10, fontFamily: "monospace", color: "rgba(255,255,255,0.5)", marginLeft: "auto" }}>
          EUR/XOF · {taux.EUR_XOF.toFixed(3)}
          {" · "}EUR/USD · {(1 / taux.EUR_USD).toFixed(4)}
        </span>
      )}
    </div>
  );
}
