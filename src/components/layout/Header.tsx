"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import AfricaGroLogo from "@/components/brand/AfricaGroLogo";

const NAV = [
  { href: "/referentiel", label: "Référentiel", active: true,  badge: null },
  { href: "/marche",      label: "Marché",       active: true,  badge: null },
  { href: "/prix",        label: "Prix",          active: true,  badge: null },
  { href: "/collecte",    label: "Collecte",      active: true,  badge: null },
  { href: "/analyse",     label: "Analyse",       active: true,  badge: null },
];

export default function Header() {
  const pathname = usePathname();

  return (
    <header
      style={{
        background: "var(--bg-panel)",
        borderBottom: "1px solid var(--border-subtle)",
        position: "sticky",
        top: 0,
        zIndex: 50,
        backdropFilter: "blur(12px)",
      }}
    >
      {/* Top ticker strip */}
      <div
        style={{
          background: "var(--ag-forest)",
          borderBottom: "1px solid rgba(146,186,89,0.15)",
          padding: "4px 0",
          overflow: "hidden",
        }}
      >
        <div className="ag-container" style={{ display: "flex", alignItems: "center", gap: "32px" }}>
          <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span className="ag-status-dot" />
            <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--ag-lime)", letterSpacing: "0.08em" }}>
              LIVE
            </span>
          </span>
          <div style={{ display: "flex", gap: "24px", fontSize: 11, fontFamily: "monospace", color: "var(--text-secondary)", overflow: "hidden" }}>
            <span>
              <span style={{ color: "var(--text-muted)" }}>ZC — MAIS · </span>
              <span style={{ color: "var(--ag-lime)" }}>USD/T</span>
            </span>
            <span>
              <span style={{ color: "var(--text-muted)" }}>RCN · CAJOU · </span>
              <span style={{ color: "var(--ag-lime)" }}>XOF/KG</span>
            </span>
            <span>
              <span style={{ color: "var(--text-muted)" }}>COLA · AOF · </span>
              <span style={{ color: "var(--ag-lime)" }}>XOF/KG</span>
            </span>
            <span style={{ color: "var(--text-muted)", marginLeft: "auto" }}>
              EUR/XOF · 655.957
            </span>
          </div>
        </div>
      </div>

      {/* Main header */}
      <div
        className="ag-container"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 24px",
        }}
      >
        {/* Logo */}
        <Link href="/" style={{ textDecoration: "none" }}>
          <AfricaGroLogo size="sm" />
        </Link>

        {/* Navigation */}
        <nav style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          {NAV.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
            return item.active ? (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 400,
                  color: isActive ? "var(--ag-lime)" : "var(--text-secondary)",
                  background: isActive ? "rgba(146,186,89,0.1)" : "transparent",
                  border: isActive ? "1px solid rgba(146,186,89,0.2)" : "1px solid transparent",
                  textDecoration: "none",
                  transition: "all 150ms ease",
                  letterSpacing: "0.01em",
                }}
              >
                {item.label}
              </Link>
            ) : (
              <span
                key={item.href}
                title={item.badge ?? ""}
                style={{
                  padding: "6px 14px",
                  borderRadius: "6px",
                  fontSize: 13,
                  color: "var(--text-muted)",
                  cursor: "not-allowed",
                  border: "1px solid transparent",
                  letterSpacing: "0.01em",
                  position: "relative",
                }}
              >
                {item.label}
                {item.badge && (
                  <span
                    style={{
                      position: "absolute",
                      top: "-4px",
                      right: "-2px",
                      fontSize: 8,
                      background: "var(--ag-olive)",
                      color: "var(--text-inverse)",
                      padding: "1px 4px",
                      borderRadius: "4px",
                      fontFamily: "monospace",
                      letterSpacing: "0.05em",
                      opacity: 0.8,
                    }}
                  >
                    {item.badge}
                  </span>
                )}
              </span>
            );
          })}
        </nav>

        {/* Right — currencies */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            fontSize: 11,
            fontFamily: "monospace",
          }}
        >
          {["USD", "EUR", "XOF"].map((c) => (
            <span
              key={c}
              style={{
                padding: "3px 8px",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "4px",
                color: "var(--text-secondary)",
                letterSpacing: "0.08em",
              }}
            >
              {c}
            </span>
          ))}
        </div>
      </div>
    </header>
  );
}
