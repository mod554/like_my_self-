// Carte réseau animée des marchés AOF — SVG pur, zéro dépendance.
// Nœuds pulsants (places de marché) reliés par des flux de données animés
// vers le hub mondial. Composant serveur — les animations sont en SMIL/CSS.

const NOEUDS: { id: string; x: number; y: number; label: string; d?: number }[] = [
  { id: "DKR", x: 42,  y: 96,  label: "Dakar",       d: 0.0 },
  { id: "BKO", x: 118, y: 92,  label: "Bamako",      d: 0.4 },
  { id: "OUA", x: 168, y: 104, label: "Ouagadougou", d: 0.8 },
  { id: "NIM", x: 216, y: 88,  label: "Niamey",      d: 1.2 },
  { id: "ABJ", x: 132, y: 176, label: "Abidjan",     d: 1.6 },
  { id: "ACC", x: 176, y: 184, label: "Accra",       d: 2.0 },
  { id: "LOS", x: 236, y: 168, label: "Lagos",       d: 2.4 },
];

const HUB = { x: 320, y: 60, label: "CBOT · Monde" };

function arc(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2;
  const my = Math.min(y1, y2) - 34;
  return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`;
}

export default function AfricaMarketMap() {
  return (
    <svg
      viewBox="0 0 380 230"
      role="img"
      aria-label="Réseau des marchés agricoles d'Afrique de l'Ouest"
      style={{ width: "100%", height: "auto", display: "block" }}
    >
      <defs>
        <radialGradient id="agm-node" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#5A8A2A" />
          <stop offset="100%" stopColor="#003D2E" />
        </radialGradient>
        <linearGradient id="agm-flux" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="rgba(90,138,42,0)" />
          <stop offset="50%" stopColor="rgba(90,138,42,0.65)" />
          <stop offset="100%" stopColor="rgba(0,61,46,0)" />
        </linearGradient>
      </defs>

      {/* Flux de données : arcs pointillés animés vers le hub mondial */}
      {NOEUDS.map((n) => (
        <path
          key={`flux-${n.id}`}
          d={arc(n.x, n.y, HUB.x, HUB.y)}
          fill="none"
          stroke="url(#agm-flux)"
          strokeWidth="1.1"
          strokeDasharray="3 6"
          opacity="0.8"
        >
          <animate
            attributeName="stroke-dashoffset"
            from="54"
            to="0"
            dur="3.2s"
            begin={`${n.d ?? 0}s`}
            repeatCount="indefinite"
          />
        </path>
      ))}

      {/* Liaisons terrestres discrètes entre places voisines */}
      {[["DKR","BKO"],["BKO","OUA"],["OUA","NIM"],["BKO","ABJ"],["ABJ","ACC"],["ACC","LOS"],["OUA","ACC"]].map(([a, b]) => {
        const na = NOEUDS.find((n) => n.id === a)!;
        const nb = NOEUDS.find((n) => n.id === b)!;
        return (
          <line
            key={`${a}-${b}`}
            x1={na.x} y1={na.y} x2={nb.x} y2={nb.y}
            stroke="rgba(90,138,42,0.18)"
            strokeWidth="1"
          />
        );
      })}

      {/* Particules de données circulant vers le hub (animateMotion sur les arcs) */}
      {NOEUDS.map((n) => (
        <circle key={`part-${n.id}`} r="1.6" fill="#B8912E" opacity="0.9">
          <animateMotion
            dur="3.4s"
            begin={`${(n.d ?? 0) + 0.6}s`}
            repeatCount="indefinite"
            path={arc(n.x, n.y, HUB.x, HUB.y)}
          />
          <animate attributeName="opacity" values="0;0.9;0.9;0" keyTimes="0;0.15;0.8;1" dur="3.4s" begin={`${(n.d ?? 0) + 0.6}s`} repeatCount="indefinite" />
        </circle>
      ))}

      {/* Nœuds de marché pulsants */}
      {NOEUDS.map((n) => (
        <g key={n.id}>
          <circle cx={n.x} cy={n.y} r="10" fill="rgba(90,138,42,0.12)">
            <animate attributeName="r" values="7;13;7" dur="3s" begin={`${n.d ?? 0}s`} repeatCount="indefinite" />
            <animate attributeName="opacity" values="0.7;0.15;0.7" dur="3s" begin={`${n.d ?? 0}s`} repeatCount="indefinite" />
          </circle>
          <circle cx={n.x} cy={n.y} r="3.4" fill="url(#agm-node)" stroke="#FFFFFF" strokeWidth="1" />
          <text
            x={n.x} y={n.y + 15}
            textAnchor="middle"
            style={{ fontSize: 7, fontFamily: "monospace", fill: "var(--text-muted)", letterSpacing: "0.04em" }}
          >
            {n.label}
          </text>
        </g>
      ))}

      {/* Hub mondial */}
      <g>
        <rect x={HUB.x - 34} y={HUB.y - 11} width="68" height="22" rx="11"
          fill="rgba(0,61,46,0.92)" stroke="rgba(90,138,42,0.5)" strokeWidth="1" />
        <circle cx={HUB.x - 24} cy={HUB.y} r="2.6" fill="#92BA59">
          <animate attributeName="opacity" values="1;0.3;1" dur="1.6s" repeatCount="indefinite" />
        </circle>
        <text x={HUB.x + 4} y={HUB.y + 2.6} textAnchor="middle"
          style={{ fontSize: 7.5, fontFamily: "monospace", fill: "#EDF4ED", letterSpacing: "0.06em" }}>
          {HUB.label}
        </text>
      </g>
    </svg>
  );
}
