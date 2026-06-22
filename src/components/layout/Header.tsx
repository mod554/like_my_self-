"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import AfricaGroLogo from "@/components/brand/AfricaGroLogo";

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
      background: "rgba(8,13,10,0.96)",
      borderBottom: "1px solid var(--border-subtle)",
      position: "sticky",
      top: 0,
      zIndex: 50,
      backdropFilter: "blur(16px)",
    }}>
      {/* Ticker strip */}
      <div style={{
        background: "var(--ag-forest)",
        borderBottom: "1px solid rgba(146,186,89,0.12)",
        padding: "5px 0",
      }}>
        <div className="ag-container" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span className="ag-status-dot" />
              <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--ag-lime)", letterSpacing: "0.1em", fontWeight: 700 }}>LIVE</span>
            </span>
            <div style={{ display: "flex", gap: "20px", fontSize: 11, fontFamily: "monospace", color: "var(--text-secondary)" }}>
              <span><span style={{ color: "var(--text-muted)" }}>MAIS · ZC  </span><span style={{ color: "var(--ag-lime)" }}>USD/T</span></span>
              <span><span style={{ color: "var(--text-muted)" }}>CAJOU · RCN  </span><span style={{ color: "var(--ag-lime)" }}>XOF/T</span></span>
              <span><span style={{ color: "var(--text-muted)" }}>COLA · AOF  </span><span style={{ color: "var(--ag-lime)" }}>XOF/KG</span></span>
            </div>
          </div>
          <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)" }}>EUR/XOF · 655.957</span>
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
                border: isActive ? "1px solid rgba(146,186,89,0.2)" : "1px solid transparent",
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
