interface AfricaGroLogoProps {
  size?: "sm" | "md" | "lg";
  variant?: "full" | "icon" | "wordmark";
  className?: string;
  dark?: boolean;
}

const sizes = {
  sm: { h: 32, textH: 22, partnersFontSize: 7 },
  md: { h: 44, textH: 30, partnersFontSize: 9 },
  lg: { h: 64, textH: 44, partnersFontSize: 13 },
};

export default function AfricaGroLogo({
  size = "md",
  variant = "full",
  className = "",
  dark = true,
}: AfricaGroLogoProps) {
  const s = sizes[size];
  const ratio = s.h / 64;

  // Colors matching real logo
  const forestGreen = "#003D2E";
  const oliveGreen = "#6B760D";
  const textColor = dark ? "#FFFFFF" : forestGreen;

  const Icon = (
    <svg
      height={s.h}
      viewBox="0 0 80 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      {/* Large dark green half-circle (right side of icon) */}
      <path d="M40 4 C40 4 72 4 72 32 C72 60 40 60 40 60 L40 4Z" fill={forestGreen} />
      {/* "Partners" text vertical on dark bar */}
      <text
        x="56" y="38"
        textAnchor="middle"
        fontSize="8"
        fontFamily="Ubuntu, sans-serif"
        fontWeight="400"
        fill="white"
        letterSpacing="0.5"
        transform="rotate(-90, 56, 32)"
      >
        Partners
      </text>
      {/* Large olive leaf top-left */}
      <path
        d="M8 8 C8 8 38 8 38 32 C38 32 14 32 8 8Z"
        fill={oliveGreen}
      />
      {/* Small olive leaf bottom-left */}
      <path
        d="M8 38 C8 38 8 60 28 56 C28 56 16 48 8 38Z"
        fill={oliveGreen}
        opacity="0.85"
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
            AFRICA GRO
            <sup style={{ fontSize: s.textH * 0.4, fontWeight: 400, verticalAlign: "super" }}>®</sup>
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
