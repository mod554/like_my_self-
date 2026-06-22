"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import AfricaGroLogo from "@/components/brand/AfricaGroLogo";
import LiveTicker from "@/components/live/LiveTicker";

const NAV = [
  { href: "/referentiel", label: "Référentiel" },
  { href: "/marche",      label: "Marché" },
  { href: "/prix",        label: "Prix" },
  { href: "/collecte",    label: "Collecte" },
  { href: "/analyse",     label: "Analyse" },
];

export default function Header() {
  const pathname = usePathname();

  return (
    <header style={{
      background: "rgba(255,255,255,0.97)",
      borderBottom: "1px solid var(--border-subtle)",
      position: "sticky",
      top: 0,
      zIndex: 50,
      backdropFilter: "blur(16px)",
      boxShadow: "0 1px 8px rgba(0,0,0,0.06)",
    }}>
      {/* Ticker strip — prices live, auto-refresh toutes les 5min */}
      <div style={{
        background: "var(--ag-forest)",
        borderBottom: "1px solid rgba(90,138,42,0.2)",
        padding: "5px 0",
      }}>
        <div className="ag-container">
          <LiveTicker refreshInterval={5 * 60 * 1000} />
        </div>
      </div>

      {/* Main nav */}
      <div className="ag-container" style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 24px",
      }}>
        <Link href="/" style={{ textDecoration: "none" }}>
          <AfricaGroLogo size="sm" />
        </Link>

        <nav style={{ display: "flex", alignItems: "center", gap: "2px" }}>
          {NAV.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link key={item.href} href={item.href} style={{
                padding: "7px 16px",
                borderRadius: "6px",
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? "#FFFFFF" : "var(--text-secondary)",
                background: isActive ? "var(--ag-forest)" : "transparent",
                border: isActive ? "1px solid rgba(0,61,46,0.3)" : "1px solid transparent",
                textDecoration: "none",
                transition: "all 150ms ease",
                letterSpacing: "0.01em",
              }}>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {["USD", "EUR", "XOF"].map((c) => (
            <span key={c} style={{
              padding: "3px 8px",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "4px",
              fontSize: 10,
              fontFamily: "monospace",
              color: "var(--text-muted)",
              letterSpacing: "0.1em",
            }}>{c}</span>
          ))}
        </div>
      </div>
    </header>
  );
}
