interface AfricaGroLogoProps {
  size?: "sm" | "md" | "lg";
  variant?: "full" | "icon" | "wordmark";
  className?: string;
}

const sizes = {
  sm: { icon: 28, text: 14, sub: 8 },
  md: { icon: 36, text: 18, sub: 10 },
  lg: { icon: 48, text: 24, sub: 12 },
};

export default function AfricaGroLogo({
  size = "md",
  variant = "full",
  className = "",
}: AfricaGroLogoProps) {
  const s = sizes[size];

  const Icon = (
    <svg
      width={s.icon}
      height={s.icon}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Background circle */}
      <rect width="48" height="48" rx="10" fill="#003D2E" />
      {/* Leaf shape (left petal) */}
      <path
        d="M14 34 C14 34 10 22 18 14 C18 14 18 28 14 34Z"
        fill="#92BA59"
        opacity="0.9"
      />
      {/* Grain stalk (center) */}
      <path
        d="M24 38 L24 16"
        stroke="#D9EDD9"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {/* Grain heads */}
      <ellipse cx="24" cy="13" rx="4" ry="6" fill="#D9EDD9" opacity="0.95" />
      <ellipse cx="19" cy="18" rx="3" ry="5" fill="#92BA59" opacity="0.8" transform="rotate(-25 19 18)" />
      <ellipse cx="29" cy="18" rx="3" ry="5" fill="#6B760D" opacity="0.8" transform="rotate(25 29 18)" />
      {/* Leaf right */}
      <path
        d="M34 34 C34 34 38 22 30 14 C30 14 30 28 34 34Z"
        fill="#6B760D"
        opacity="0.85"
      />
      {/* Partners badge */}
      <rect x="15" y="36" width="18" height="7" rx="3.5" fill="#92BA59" opacity="0.95" />
      <text
        x="24"
        y="41.5"
        textAnchor="middle"
        fontSize="4.5"
        fontFamily="Ubuntu, sans-serif"
        fontWeight="700"
        fill="#003D2E"
        letterSpacing="0.5"
      >
        PARTNERS
      </text>
    </svg>
  );

  if (variant === "icon") return <span className={className}>{Icon}</span>;

  return (
    <span
      className={`inline-flex items-center gap-2.5 ${className}`}
      style={{ lineHeight: 1 }}
    >
      {Icon}
      {variant === "full" && (
        <span style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
          <span
            style={{
              fontSize: s.text,
              fontFamily: "var(--font-ubuntu, 'Ubuntu', sans-serif)",
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "-0.01em",
              lineHeight: 1,
            }}
          >
            <span style={{ color: "var(--ag-lime)" }}>A</span>FRICA
            <span style={{ color: "var(--ag-lime)" }}> G</span>RO
            <span
              style={{
                fontSize: s.text * 0.55,
                color: "var(--ag-lime)",
                verticalAlign: "super",
                fontWeight: 400,
              }}
            >
              ®
            </span>
          </span>
          <span
            style={{
              fontSize: s.sub,
              fontFamily: "monospace",
              color: "var(--text-muted)",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              lineHeight: 1,
            }}
          >
            Partners
          </span>
        </span>
      )}
    </span>
  );
}
