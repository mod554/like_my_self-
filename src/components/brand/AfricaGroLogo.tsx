interface AfricaAgroLogoProps {
  size?: "sm" | "md" | "lg";
  variant?: "full" | "icon" | "wordmark";
  className?: string;
  dark?: boolean;
}

const sizes = {
  sm: { h: 32, textH: 20, partnersFontSize: 7 },
  md: { h: 44, textH: 28, partnersFontSize: 9 },
  lg: { h: 64, textH: 40, partnersFontSize: 12 },
};

export default function AfricaGroLogo({
  size = "md",
  variant = "full",
  className = "",
  dark = false,
}: AfricaAgroLogoProps) {
  const s = sizes[size];

  const forestGreen = "#003D2E";
  const oliveGreen = "#6B760D";
  const textColor = dark ? "#FFFFFF" : forestGreen;

  // Icon: ratio ~200:265 → render at h × (200/265)
  const iconW = Math.round(s.h * (200 / 265));

  const Icon = (
    <svg
      width={iconW}
      height={s.h}
      viewBox="0 0 200 265"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <defs>
        <clipPath id="ag-clip-left">
          <rect x="0" y="0" width="103" height="265" />
        </clipPath>
      </defs>

      {/* Right dark-green tall pill */}
      <rect x="107" y="4" width="88" height="257" rx="44" ry="44" fill={forestGreen} />

      {/* "Partners" vertical text on pill */}
      <text
        x="151"
        y="133"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="21"
        fontFamily="Ubuntu, sans-serif"
        fontWeight="400"
        fill="white"
        letterSpacing="2"
        transform="rotate(-90 151 133)"
      >
        Partners
      </text>

      {/* Large olive circle clipped to left half */}
      <circle cx="52" cy="78" r="78" fill={oliveGreen} clipPath="url(#ag-clip-left)" />

      {/* Bottom-left olive leaf */}
      <path
        d="M 8,263 C 6,235 14,202 40,180 C 62,162 100,158 106,183 C 88,200 50,220 8,263 Z"
        fill={oliveGreen}
      />

      {/* Leaf vein (white) */}
      <path
        d="M 12,258 C 30,226 62,200 100,180 C 96,186 60,212 16,260 Z"
        fill="white"
        opacity="0.5"
      />
    </svg>
  );

  if (variant === "icon") return <span className={className}>{Icon}</span>;

  return (
    <span
      className={`inline-flex items-center gap-2 ${className}`}
      style={{ lineHeight: 1 }}
    >
      {Icon}
      {variant === "full" && (
        <span style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
          <span
            style={{
              fontSize: s.textH,
              fontFamily: "var(--font-ubuntu, 'Ubuntu', sans-serif)",
              fontWeight: 700,
              color: textColor,
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            AFRICA AGRO
          </span>
          <span
            style={{
              fontSize: s.partnersFontSize,
              fontFamily: "var(--font-ubuntu, 'Ubuntu', sans-serif)",
              fontWeight: 400,
              color: dark ? "rgba(255,255,255,0.6)" : oliveGreen,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              lineHeight: 1.2,
            }}
          >
            Partners
          </span>
        </span>
      )}
    </span>
  );
}
