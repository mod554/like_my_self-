import type { Metadata } from "next";
import { Ubuntu, Ubuntu_Mono } from "next/font/google";
import "./globals.css";
import Header from "@/components/layout/Header";

const ubuntu = Ubuntu({
  weight: ["300", "400", "500", "700"],
  variable: "--font-ubuntu",
  subsets: ["latin"],
  display: "swap",
});

const ubuntuMono = Ubuntu_Mono({
  weight: ["400", "700"],
  variable: "--font-ubuntu-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "AfricaGro Partners — Terminal de marché agricole",
  description:
    "Plateforme de veille, prix et analyse d'investissement pour les filières maïs, cajou et cola en Afrique de l'Ouest.",
  keywords: "agriculture, cajou, maïs, cola, Afrique Ouest, marché, investissement, prix",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr" className={`${ubuntu.variable} ${ubuntuMono.variable} h-full`}>
      <body style={{ fontFamily: "var(--font-ubuntu, 'Ubuntu', system-ui, sans-serif)" }}>
        <Header />
        <main className="flex-1 flex flex-col">{children}</main>
        <footer style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <div className="ag-container" style={{ padding: "16px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span className="ag-section-label">© 2026 AfricaGro Partners · Terminal v1.0</span>
            <span className="ag-section-label">USD · EUR · XOF · GHS · NGN</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
