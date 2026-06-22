"use client";

import { useEffect, useState, useCallback, useRef } from "react";

interface NewsItem {
  id: string;
  titre: string;
  lien: string;
  source: string;
  resume: string | null;
  datePublication: string;
  dateCollecte: string;
  filiere: { code: string; nom: string } | null;
}

interface Props {
  initialNews: NewsItem[];
  filiere?: string;
  limit?: number;
  refreshInterval?: number; // ms, défaut 5 minutes
}

const FILIERE_COLOR: Record<string, string> = {
  MAIS:  "#92BA59",
  CAJOU: "#B89B3A",
  COLA:  "#8A9E1A",
};

const FILIERE_ICON: Record<string, string> = {
  MAIS: "🌽",
  CAJOU: "🥜",
  COLA: "🌰",
};

function timeAgo(date: string): string {
  const diff = Date.now() - new Date(date).getTime();
  const mins = Math.floor(diff / 60000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);
  if (days > 0) return `il y a ${days}j`;
  if (hrs > 0) return `il y a ${hrs}h`;
  if (mins > 0) return `il y a ${mins}min`;
  return "à l'instant";
}

export default function LiveNewsFeed({
  initialNews,
  filiere,
  limit = 50,
  refreshInterval = 5 * 60 * 1000,
}: Props) {
  const [news, setNews] = useState<NewsItem[]>(initialNews);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [newCount, setNewCount] = useState(0);
  const prevLiens = useRef(new Set(initialNews.map((n) => n.id)));

  const fetchNews = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (filiere) params.set("filiere", filiere);
      const res = await fetch(`/api/news?${params}`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json() as { news: NewsItem[] };
      const nouvellesActus = data.news.filter((n) => !prevLiens.current.has(n.id));
      setNewCount((c) => c + nouvellesActus.length);
      nouvellesActus.forEach((n) => prevLiens.current.add(n.id));
      setNews(data.news);
      setLastRefresh(new Date());
    } catch {
      // Silencieux — on garde les données précédentes
    } finally {
      setLoading(false);
    }
  }, [filiere, limit]);

  useEffect(() => {
    const interval = setInterval(fetchNews, refreshInterval);
    return () => clearInterval(interval);
  }, [fetchNews, refreshInterval]);

  const handleRefresh = () => {
    setNewCount(0);
    fetchNews();
  };

  return (
    <div>
      {/* Header fil d'actualité */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "12px", flexWrap: "wrap", gap: "8px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span className="ag-status-dot" />
          <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)", letterSpacing: "0.08em" }}>
            LIVE
          </span>
          <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "monospace" }}>
            · {news.length} articles · actualisation {Math.round(refreshInterval / 60000)}min
          </span>
          {newCount > 0 && (
            <span style={{
              fontSize: 10, fontFamily: "monospace",
              background: "rgba(146,186,89,0.15)", color: "var(--ag-lime)",
              border: "1px solid rgba(146,186,89,0.3)",
              padding: "1px 6px", borderRadius: "10px",
            }}>
              +{newCount} nouveau{newCount > 1 ? "x" : ""}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "monospace" }}>
            {lastRefresh.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
          </span>
          <button
            onClick={handleRefresh}
            disabled={loading}
            style={{
              fontSize: 10, fontFamily: "monospace", cursor: "pointer",
              background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)",
              color: loading ? "var(--text-muted)" : "var(--ag-lime)",
              padding: "3px 10px", borderRadius: "4px",
              transition: "all 150ms",
            }}
          >
            {loading ? "…" : "↻ Actualiser"}
          </button>
        </div>
      </div>

      {/* Liste des articles */}
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {news.length === 0 && (
          <div style={{ padding: "24px", textAlign: "center" }}>
            <p style={{ fontSize: 13, color: "var(--text-muted)", fontFamily: "monospace" }}>
              Aucune actualité disponible — déclenchez la collecte pour importer des articles.
            </p>
          </div>
        )}
        {news.map((a) => {
          const fc = a.filiere?.code ?? "";
          const accent = FILIERE_COLOR[fc] ?? "var(--ag-lime)";
          const icon = FILIERE_ICON[fc] ?? "📰";

          return (
            <a
              key={a.id}
              href={a.lien}
              target="_blank"
              rel="noopener noreferrer"
              style={{ textDecoration: "none", display: "block" }}
            >
              <div
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-subtle)",
                  borderLeft: `3px solid ${accent}`,
                  borderRadius: "6px",
                  padding: "12px 14px",
                  transition: "all 150ms",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.background = "var(--bg-surface)";
                  (e.currentTarget as HTMLDivElement).style.borderColor = accent;
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.background = "var(--bg-elevated)";
                  (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-subtle)";
                  (e.currentTarget as HTMLDivElement).style.borderLeftColor = accent;
                }}
              >
                <div style={{ display: "flex", alignItems: "flex-start", gap: "10px" }}>
                  <span style={{ fontSize: 16, flexShrink: 0, marginTop: "1px" }}>{icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: 13, fontWeight: 600, color: "var(--text-primary)",
                      lineHeight: 1.4, marginBottom: "4px",
                      overflow: "hidden", display: "-webkit-box",
                      WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                    }}>
                      {a.titre}
                    </div>
                    {a.resume && (
                      <div style={{
                        fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.5,
                        marginBottom: "6px",
                        overflow: "hidden", display: "-webkit-box",
                        WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
                      }}>
                        {a.resume}
                      </div>
                    )}
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 9, fontFamily: "monospace", color: accent }}>
                        {a.filiere?.nom ?? "Général"}
                      </span>
                      <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace" }}>·</span>
                      <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)" }}>
                        {a.source}
                      </span>
                      <span style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace" }}>·</span>
                      <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)" }}>
                        {timeAgo(a.datePublication)}
                      </span>
                    </div>
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-muted)", flexShrink: 0, marginTop: "2px" }}>↗</span>
                </div>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}
