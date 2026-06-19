export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import Link from "next/link";
import { notFound } from "next/navigation";

const FIABILITE: Record<string, { label: string; color: string; bg: string; border: string }> = {
  OFFICIEL:  { label: "Officiel",   color: "#4A9B6F", bg: "rgba(74,155,111,0.12)",  border: "rgba(74,155,111,0.25)" },
  INDICATIF: { label: "Indicatif",  color: "#92BA59", bg: "rgba(146,186,89,0.10)",  border: "rgba(146,186,89,0.22)" },
  ESTIME:    { label: "Estimé",     color: "#B89B3A", bg: "rgba(184,155,58,0.10)",  border: "rgba(184,155,58,0.22)" },
  EXEMPLE:   { label: "Exemple ⚠️", color: "#5A7A5A", bg: "rgba(90,122,90,0.10)",   border: "rgba(90,122,90,0.20)"  },
};

function BadgeFiabilite({ niveau }: { niveau: string }) {
  const s = FIABILITE[niveau] ?? FIABILITE.EXEMPLE;
  return (
    <span
      style={{
        fontSize: 9, fontFamily: "monospace", letterSpacing: "0.05em",
        padding: "2px 6px", borderRadius: "4px",
        color: s.color, background: s.bg, border: `1px solid ${s.border}`,
        whiteSpace: "nowrap",
      }}
    >
      {s.label}
    </span>
  );
}

function formatDate(d: Date) {
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

function formatValeur(v: unknown) {
  const n = Number(v);
  if (n >= 1000) return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 });
  if (n >= 1) return n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 4 });
}

export default async function ProduitPage({
  params,
}: {
  params: Promise<{ code: string; produit: string }>;
}) {
  const { code, produit } = await params;

  const p = await prisma.produit.findUnique({
    where: { code: produit.toUpperCase() },
    include: {
      filiere: true,
      parent: { select: { code: true, nom: true } },
      derives: {
        orderBy: { code: "asc" },
        select: { id: true, code: true, nom: true, uniteRef: true, descriptionQualite: true },
      },
      prixReleves: {
        orderBy: { dateReleve: "desc" },
        take: 20,
        include: {
          marche: { select: { code: true, nom: true, type: true, devise: true } },
          source: { select: { code: true, nom: true } },
        },
      },
      structuresCout: {
        orderBy: [{ maillon: "asc" }, { poste: "asc" }],
        include: { source: { select: { code: true } } },
      },
    },
  });

  if (!p || p.filiere.code !== code.toUpperCase()) notFound();

  const saisonnalite = p.saisonnalite as Record<string, { debut: string; fin: string; note?: string }> | null;
  const chaine = p.chaineDValeur as { etapes?: string[]; note?: string } | null;

  // Last price
  const dernierPrix = p.prixReleves[0];

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* Breadcrumb */}
        <div style={{ marginBottom: "20px", display: "flex", alignItems: "center", gap: "6px", fontSize: 11, fontFamily: "monospace", color: "var(--text-muted)" }}>
          <Link href="/" style={{ color: "var(--text-muted)", textDecoration: "none" }}>AfricaGro</Link>
          <span>›</span>
          <Link href="/referentiel" style={{ color: "var(--text-muted)", textDecoration: "none" }}>Référentiel</Link>
          <span>›</span>
          <Link href={`/referentiel/${code.toLowerCase()}`} style={{ color: "var(--text-muted)", textDecoration: "none" }}>{p.filiere.nom}</Link>
          <span>›</span>
          <span style={{ color: "var(--ag-lime)" }}>{p.code}</span>
        </div>

        {/* Hero produit */}
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "12px",
            overflow: "hidden",
            marginBottom: "24px",
          }}
        >
          <div style={{ height: "3px", background: "linear-gradient(90deg, var(--ag-lime), var(--ag-olive), transparent)" }} />
          <div style={{ padding: "24px 28px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: "16px" }}>

              {/* Titre */}
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px", flexWrap: "wrap" }}>
                  <span
                    style={{
                      fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em",
                      color: "var(--ag-lime)", background: "rgba(146,186,89,0.1)",
                      border: "1px solid rgba(146,186,89,0.2)", padding: "2px 8px", borderRadius: "4px",
                    }}
                  >
                    {p.code}
                  </span>
                  {p.estDerive && p.parent && (
                    <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--text-muted)" }}>
                      Dérivé de{" "}
                      <Link href={`/referentiel/${code.toLowerCase()}/${p.parent.code.toLowerCase()}`}
                        style={{ color: "var(--ag-lime)", textDecoration: "none" }}>
                        {p.parent.code}
                      </Link>
                    </span>
                  )}
                  <span style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", background: "var(--bg-elevated)", padding: "2px 6px", borderRadius: "4px" }}>
                    {p.uniteRef}
                  </span>
                </div>
                <h1 className="font-display" style={{ fontSize: 22, color: "var(--text-primary)", margin: 0, lineHeight: 1.2 }}>
                  {p.nom}
                </h1>
                {p.descriptionQualite && (
                  <p style={{ marginTop: "8px", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
                    {p.descriptionQualite}
                  </p>
                )}
              </div>

              {/* Dernier prix */}
              {dernierPrix && (
                <div
                  style={{
                    padding: "16px 20px", borderRadius: "10px",
                    background: "var(--bg-elevated)", border: "1px solid var(--border-default)",
                    textAlign: "right", minWidth: "180px",
                  }}
                >
                  <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", marginBottom: "4px", letterSpacing: "0.06em" }}>
                    DERNIER RELEVÉ
                  </div>
                  <div style={{ fontSize: 28, fontWeight: 700, color: "var(--ag-lime)", fontFamily: "monospace", lineHeight: 1 }}>
                    {formatValeur(dernierPrix.valeur)}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)", fontFamily: "monospace", marginTop: "2px" }}>
                    {dernierPrix.devise} / {dernierPrix.unite}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: "6px" }}>
                    {formatDate(dernierPrix.dateReleve)} · <BadgeFiabilite niveau={dernierPrix.fiabilite} />
                  </div>
                </div>
              )}
            </div>

            {/* Quick stats bar */}
            <div
              style={{
                marginTop: "20px", paddingTop: "16px",
                borderTop: "1px solid var(--border-subtle)",
                display: "flex", gap: "24px", flexWrap: "wrap",
              }}
            >
              {[
                { v: p.prixReleves.length, l: "Relevés de prix" },
                { v: p.structuresCout.length, l: "Postes de coût" },
                { v: p.derives.length, l: "Dérivés" },
              ].map(({ v, l }) => (
                <div key={l} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: "var(--ag-lime)", fontFamily: "monospace" }}>{v}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{l}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sections */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>

          {/* Saisonnalité */}
          {saisonnalite && Object.keys(saisonnalite).length > 0 && (
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Saisonnalité</p>
              </div>
              <table className="ag-table">
                <thead>
                  <tr>
                    <th>Zone</th><th>Début</th><th>Fin</th><th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(saisonnalite).map(([zone, s]) => (
                    <tr key={zone}>
                      <td style={{ color: "var(--text-primary)", fontWeight: 600, fontFamily: "monospace" }}>{zone}</td>
                      <td style={{ color: "var(--ag-lime)", fontFamily: "monospace" }}>{s.debut}</td>
                      <td style={{ color: "var(--ag-lime)", fontFamily: "monospace" }}>{s.fin}</td>
                      <td style={{ color: "var(--text-muted)" }}>{s.note ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Chaîne de valeur */}
          {chaine?.etapes && chaine.etapes.length > 0 && (
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Chaîne de valeur</p>
              </div>
              <div style={{ padding: "20px" }}>
                {chaine.etapes.map((etape, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: "12px", marginBottom: i < chaine.etapes!.length - 1 ? "0" : "0" }}>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                      <div
                        style={{
                          width: 28, height: 28, borderRadius: "50%",
                          background: "var(--ag-forest)", border: "1px solid var(--border-accent)",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)",
                          fontWeight: 700, flexShrink: 0,
                        }}
                      >
                        {i + 1}
                      </div>
                      {i < chaine.etapes!.length - 1 && (
                        <div style={{ width: 1, height: 20, background: "var(--border-subtle)", margin: "3px 0" }} />
                      )}
                    </div>
                    <div style={{ padding: "5px 0 16px", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.5 }}>
                      {etape}
                    </div>
                  </div>
                ))}
                {chaine.note && (
                  <p style={{ marginTop: "8px", fontSize: 11, color: "var(--text-muted)", fontStyle: "italic" }}>{chaine.note}</p>
                )}
              </div>
            </div>
          )}

          {/* Cadre régl & acteurs */}
          {(p.cadreReglementaire || p.acteurs) && (
            <div
              style={{
                display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px",
              }}
            >
              {p.cadreReglementaire && (
                <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
                  <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                    <p className="ag-section-label">Cadre réglementaire</p>
                  </div>
                  <p style={{ padding: "16px 20px", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7, margin: 0 }}>{p.cadreReglementaire}</p>
                </div>
              )}
              {p.acteurs && (
                <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
                  <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                    <p className="ag-section-label">Acteurs clés</p>
                  </div>
                  <p style={{ padding: "16px 20px", fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7, margin: 0 }}>{p.acteurs}</p>
                </div>
              )}
            </div>
          )}

          {/* Prix relevés */}
          <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
            <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <p className="ag-section-label">Derniers relevés de prix</p>
              <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-lime)" }}>{p.prixReleves.length} relevés</span>
            </div>
            {p.prixReleves.length === 0 ? (
              <div style={{ padding: "24px 20px", textAlign: "center" }}>
                <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Aucun relevé de prix — déclenchez un connecteur</p>
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="ag-table">
                  <thead>
                    <tr>
                      <th>Date</th><th>Marché</th><th>Type</th>
                      <th style={{ textAlign: "right" }}>Valeur</th>
                      <th>Devise</th><th>Unité</th><th>Fiabilité</th><th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.prixReleves.map((pr) => (
                      <tr key={pr.id}>
                        <td style={{ fontFamily: "monospace", whiteSpace: "nowrap" }}>{formatDate(pr.dateReleve)}</td>
                        <td title={pr.marche.nom} style={{ fontFamily: "monospace", color: "var(--text-primary)" }}>{pr.marche.code}</td>
                        <td style={{ fontFamily: "monospace" }}>{pr.typePrix}{pr.echeance ? ` ${pr.echeance}` : ""}</td>
                        <td style={{ textAlign: "right", fontFamily: "monospace", color: "var(--ag-lime)", fontWeight: 700 }}>{formatValeur(pr.valeur)}</td>
                        <td style={{ fontFamily: "monospace" }}>{pr.devise}</td>
                        <td style={{ fontFamily: "monospace" }}>{pr.unite}</td>
                        <td><BadgeFiabilite niveau={pr.fiabilite} /></td>
                        <td title={pr.source.nom} style={{ fontFamily: "monospace", color: "var(--text-muted)" }}>{pr.source.code}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Structures de coûts */}
          {p.structuresCout.length > 0 && (
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <p className="ag-section-label">Structure de coûts</p>
                <span style={{ fontSize: 11, fontFamily: "monospace", color: "var(--ag-olive)" }}>{p.structuresCout.length} postes</span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="ag-table">
                  <thead>
                    <tr>
                      <th>Maillon</th><th>Poste</th>
                      <th style={{ textAlign: "right" }}>Montant</th>
                      <th>Devise</th><th>Unité</th><th>Période</th><th>Fiabilité</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.structuresCout.map((c) => (
                      <tr key={c.id}>
                        <td style={{ fontFamily: "monospace", fontWeight: 700, color: "var(--text-primary)" }}>{c.maillon}</td>
                        <td style={{ fontFamily: "monospace" }}>{c.poste.replace(/_/g, " ")}</td>
                        <td style={{ textAlign: "right", fontFamily: "monospace", color: "var(--ag-lime)", fontWeight: 700 }}>{formatValeur(c.montant)}</td>
                        <td style={{ fontFamily: "monospace" }}>{c.devise}</td>
                        <td style={{ fontFamily: "monospace" }}>{c.unite.replace(/_/g, " ")}</td>
                        <td style={{ fontFamily: "monospace", color: "var(--text-muted)" }}>{c.periode ?? "—"}</td>
                        <td><BadgeFiabilite niveau={c.fiabilite} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Dérivés */}
          {p.derives.length > 0 && (
            <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden" }}>
              <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
                <p className="ag-section-label">Produits dérivés ({p.derives.length})</p>
              </div>
              <div style={{ padding: "12px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "8px" }}>
                {p.derives.map((d) => (
                  <Link
                    key={d.code}
                    href={`/referentiel/${code.toLowerCase()}/${d.code.toLowerCase()}`}
                    style={{ textDecoration: "none" }}
                  >
                    <div
                      className="ag-kpi"
                      style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "8px", cursor: "pointer" }}
                    >
                      <div>
                        <div style={{ fontSize: 9, fontFamily: "monospace", color: "var(--ag-lime)", background: "rgba(146,186,89,0.08)", padding: "1px 5px", borderRadius: "3px", marginBottom: "4px", display: "inline-block" }}>
                          {d.code}
                        </div>
                        <div style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>{d.nom}</div>
                        {d.descriptionQualite && (
                          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: "3px", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical" }}>
                            {d.descriptionQualite}
                          </div>
                        )}
                      </div>
                      <span style={{ color: "var(--ag-lime)", fontSize: 14, flexShrink: 0 }}>›</span>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
