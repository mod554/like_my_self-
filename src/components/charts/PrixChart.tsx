"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { format } from "date-fns";
import { fr } from "date-fns/locale";

interface DataPoint {
  date: string;
  valeur: number;
  devise: string;
}

interface PrixChartProps {
  data: DataPoint[];
  couleur?: string;
  titre?: string;
  unite?: string;
  devise?: string;
}

function formatVal(v: number) {
  if (v >= 1000) return v.toLocaleString("fr-FR", { maximumFractionDigits: 0 });
  return v.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

function makeTooltip(couleur: string) {
  return function CustomTooltip({ active, payload, label }: {
    active?: boolean; payload?: Array<{ value: number; payload: DataPoint }>; label?: string;
  }) {
    if (!active || !payload?.length) return null;
    const point = payload[0];
    return (
      <div
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
          borderRadius: "8px",
          padding: "10px 14px",
          fontSize: 12,
          fontFamily: "monospace",
          boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
        }}
      >
        <div style={{ color: "var(--text-muted)", marginBottom: "4px" }}>{label}</div>
        <div style={{ color: couleur, fontWeight: 700, fontSize: 16 }}>
          {formatVal(point.value)}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 10 }}>{point.payload.devise}</div>
      </div>
    );
  };
}

export default function PrixChart({ data, couleur = "#92BA59", titre, unite, devise }: PrixChartProps) {
  const CustomTooltip = makeTooltip(couleur);
  if (!data.length) {
    return (
      <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
          Aucune donnée — déclenchez un connecteur
        </p>
      </div>
    );
  }

  const valeurs = data.map((d) => d.valeur);
  const min = Math.min(...valeurs);
  const max = Math.max(...valeurs);
  const avg = valeurs.reduce((a, b) => a + b, 0) / valeurs.length;
  const derniere = valeurs[valeurs.length - 1];
  const premiere = valeurs[0];
  const variation = premiere !== 0 ? ((derniere - premiere) / premiere) * 100 : 0;

  return (
    <div>
      {titre && (
        <div style={{ marginBottom: "12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: 12, color: "var(--text-secondary)", fontWeight: 600 }}>{titre}</span>
          <div style={{ display: "flex", gap: "16px", fontSize: 11, fontFamily: "monospace" }}>
            <span style={{ color: "var(--text-muted)" }}>Min: <span style={{ color: couleur }}>{formatVal(min)}</span></span>
            <span style={{ color: "var(--text-muted)" }}>Moy: <span style={{ color: couleur }}>{formatVal(avg)}</span></span>
            <span style={{ color: "var(--text-muted)" }}>Max: <span style={{ color: couleur }}>{formatVal(max)}</span></span>
            <span style={{ color: variation >= 0 ? "var(--data-up)" : "var(--data-down)" }}>
              {variation >= 0 ? "+" : ""}{variation.toFixed(1)}%
            </span>
          </div>
        </div>
      )}
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${couleur.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={couleur} stopOpacity={0.25} />
              <stop offset="100%" stopColor={couleur} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 9, fill: "var(--text-muted)", fontFamily: "monospace" }}
            tickLine={false}
            axisLine={{ stroke: "var(--border-subtle)" }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 9, fill: "var(--text-muted)", fontFamily: "monospace" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={formatVal}
            width={60}
          />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine
            y={avg}
            stroke={couleur}
            strokeDasharray="4 4"
            strokeOpacity={0.4}
          />
          <Area
            type="monotone"
            dataKey="valeur"
            stroke={couleur}
            strokeWidth={2}
            fill={`url(#grad-${couleur.replace("#", "")})`}
            dot={false}
            activeDot={{ r: 4, fill: couleur, stroke: "var(--bg-base)", strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
      {(unite || devise) && (
        <div style={{ textAlign: "right", fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)", marginTop: "4px" }}>
          {devise} / {unite}
        </div>
      )}
    </div>
  );
}
