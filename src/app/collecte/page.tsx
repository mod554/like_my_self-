import { prisma } from "@/lib/db";
import { CONNECTEURS } from "@/lib/connectors";
import ConnecteurActions from "@/components/ConnecteurActions";

async function getConnecteurStatus() {
  const sources = await prisma.source.findMany({
    orderBy: { code: "asc" },
    include: {
      _count: { select: { prixReleves: true, logs: true } },
      logs: { orderBy: { debut: "desc" }, take: 3 },
    },
  });
  return sources;
}

function StatutBadge({ statut }: { statut: string | null }) {
  const map: Record<string, { color: string; bg: string; label: string }> = {
    OK:       { color: "#4A9B6F", bg: "rgba(74,155,111,0.12)",  label: "OK" },
    ERREUR:   { color: "#E05252", bg: "rgba(224,82,82,0.12)",   label: "ERREUR" },
    PARTIEL:  { color: "#B89B3A", bg: "rgba(184,155,58,0.12)",  label: "PARTIEL" },
    EN_COURS: { color: "#92BA59", bg: "rgba(146,186,89,0.12)",  label: "EN COURS" },
    INCONNU:  { color: "#5A7A5A", bg: "rgba(90,122,90,0.12)",   label: "JAMAIS" },
  };
  const s = map[statut ?? "INCONNU"] ?? map.INCONNU;
  return (
    <span
      style={{
        fontSize: 9, fontFamily: "monospace", letterSpacing: "0.06em",
        color: s.color, background: s.bg, border: `1px solid ${s.color}33`,
        padding: "2px 8px", borderRadius: "20px", display: "inline-flex", alignItems: "center", gap: "4px",
      }}
    >
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.color, display: "inline-block" }} />
      {s.label}
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    API: "var(--ag-lime)", HTML: "var(--ag-olive)", RSS: "#6B9AC4", CSV: "#B89B3A", MANUEL: "var(--text-muted)",
  };
  const c = colors[type] ?? "var(--text-muted)";
  return (
    <span style={{ fontSize: 9, fontFamily: "monospace", color: c, background: `${c}18`, border: `1px solid ${c}33`, padding: "1px 6px", borderRadius: "4px" }}>
      {type}
    </span>
  );
}

export default async function CollectePage() {
  const sources = await getConnecteurStatus();

  const sourceMap = Object.fromEntries(sources.map((s) => [s.code, s]));

  const totalReleves = sources.reduce((a, s) => a + s._count.prixReleves, 0);
  const totalOK = sources.filter((s) => s.statutDernier === "OK").length;
  const totalErreur = sources.filter((s) => s.statutDernier === "ERREUR").length;

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Header */}
        <div style={{ marginBottom: "28px" }}>
          <p className="ag-section-label" style={{ marginBottom: "6px" }}>Collecte automatique · AfricaGro Partners</p>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "12px" }}>
            <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", margin: 0 }}>
              Tableau de bord connecteurs
            </h1>
            <ConnecteurActions />
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "12px", marginBottom: "24px" }}>
          {[
            { v: CONNECTEURS.length, l: "Connecteurs", c: "var(--ag-lime)" },
            { v: totalOK, l: "Opérationnels", c: "#4A9B6F" },
            { v: totalErreur, l: "En erreur", c: "#E05252" },
            { v: totalReleves.toLocaleString("fr-FR"), l: "Relevés de prix", c: "var(--ag-lime)" },
          ].map(({ v, l, c }) => (
            <div key={l} className="ag-kpi">
              <div style={{ fontSize: 28, fontWeight: 700, color: c, fontFamily: "monospace", lineHeight: 1, marginBottom: "4px" }}>{v}</div>
              <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>{l}</div>
            </div>
          ))}
        </div>

        {/* Connecteurs table */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden", marginBottom: "24px" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
            <p className="ag-section-label">Connecteurs configurés</p>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="ag-table" style={{ minWidth: 700 }}>
              <thead>
                <tr>
                  <th>Code</th><th>Nom</th><th>Type</th><th>Fréquence cron</th>
                  <th style={{ textAlign: "right" }}>Prix importés</th>
                  <th>Dernier run</th><th>Statut</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                {CONNECTEURS.map((c) => {
                  const src = sourceMap[c.code];
                  return (
                    <tr key={c.code}>
                      <td style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--ag-lime)", fontSize: 10 }}>{c.code}</td>
                      <td style={{ maxWidth: 240 }}>
                        <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 500 }}>{c.nom}</div>
                        {src?.messageErreur && (
                          <div style={{ fontSize: 10, color: "#E05252", marginTop: "2px", fontFamily: "monospace" }} title={src.messageErreur}>
                            ⚠ {src.messageErreur.slice(0, 60)}…
                          </div>
                        )}
                      </td>
                      <td><TypeBadge type={src?.type ?? "API"} /></td>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--ag-olive)" }}>{c.frequenceCron}</td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: "var(--ag-lime)" }}>
                        {src?._count.prixReleves ?? 0}
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                        {src?.derniereExecution
                          ? new Date(src.derniereExecution).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
                          : "—"}
                      </td>
                      <td><StatutBadge statut={src?.statutDernier ?? null} /></td>
                      <td>
                        <ConnecteurActions code={c.code} compact />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Logs récents */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
            <p className="ag-section-label">Logs d&apos;exécution récents</p>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="ag-table" style={{ minWidth: 600 }}>
              <thead>
                <tr>
                  <th>Source</th><th>Début</th><th>Durée</th>
                  <th style={{ textAlign: "right" }}>Importés</th>
                  <th style={{ textAlign: "right" }}>Erreurs</th>
                  <th>Statut</th><th>Message</th>
                </tr>
              </thead>
              <tbody>
                {sources
                  .flatMap((s) => s.logs.map((l) => ({ ...l, sourceCode: s.code })))
                  .sort((a, b) => new Date(b.debut).getTime() - new Date(a.debut).getTime())
                  .slice(0, 20)
                  .map((l) => {
                    const duree = l.fin
                      ? Math.round((new Date(l.fin).getTime() - new Date(l.debut).getTime()) / 1000)
                      : null;
                    return (
                      <tr key={l.id}>
                        <td style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--ag-lime)", fontSize: 10 }}>{l.sourceCode}</td>
                        <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                          {new Date(l.debut).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                        </td>
                        <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>
                          {duree != null ? `${duree}s` : "—"}
                        </td>
                        <td style={{ textAlign: "right", fontFamily: "monospace", color: "var(--data-up)" }}>{l.nbImportes}</td>
                        <td style={{ textAlign: "right", fontFamily: "monospace", color: l.nbErreurs > 0 ? "var(--data-down)" : "var(--text-muted)" }}>
                          {l.nbErreurs}
                        </td>
                        <td><StatutBadge statut={l.statut} /></td>
                        <td style={{ fontSize: 11, color: "var(--text-muted)", maxWidth: 200 }}>
                          {l.message ?? "—"}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>

      </div>
    </div>
  );
}
