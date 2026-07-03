export const dynamic = "force-dynamic";
import { prisma } from "@/lib/db";
import { calcIndicateurs, type PointPrix } from "@/lib/analytics";
import Link from "next/link";

// XOF is legally pegged to EUR at 655.957 — used as fallback if DB has no rate
const XOF_USD_FALLBACK = 655.957;
const EUR_USD_FALLBACK = 1.09;

// ─── Unit normalization ────────────────────────────────────────────────────────

// Convert a price (valeur / devise / unite) to USD per tonne
// Returns null if the unit is unrecognisable (skipped from average)
function normPrixUsdTonne(
  valeur: number,
  devise: string,
  unite: string,
  xofPerUsd: number,
  eurPerUsd: number,
): number | null {
  if (!isFinite(valeur) || valeur <= 0) return null;

  // 1. To USD
  let usd: number;
  const d = devise.toUpperCase();
  if (d === "XOF" || d === "CFA" || d === "FCFA") usd = valeur / xofPerUsd;
  else if (d === "EUR") usd = valeur * eurPerUsd;
  else usd = valeur; // assume USD

  // 2. To per tonne (price per unit → price per tonne)
  const u = unite.toLowerCase().replace(/[_\s]/g, "");
  if (u === "tonne" || u === "mt" || u === "t" || u === "metricton") return usd;
  if (u === "kg") return usd * 1000;            // price/kg × 1000 = price/tonne
  if (u === "quintal" || u === "q") return usd * 10;
  if (u === "bushel" || u === "bu")             // corn: 1 bu = 25.4 kg
    return usd * (1000 / 25.4);
  if (u === "sac50kg" || u === "sac50") return usd * 20;
  if (u === "sac100kg") return usd * 10;
  if (u === "livre" || u === "lb") return usd * (1000 / 0.4536);
  return null; // unknown unit — skip
}

// Same for cost structures
function normCoutUsdTonne(
  montant: number,
  devise: string,
  unite: string,
  xofPerUsd: number,
  eurPerUsd: number,
): number | null {
  if (!isFinite(montant) || montant < 0) return null;

  let usd: number;
  const d = devise.toUpperCase();
  if (d === "XOF" || d === "CFA" || d === "FCFA") usd = montant / xofPerUsd;
  else if (d === "EUR") usd = montant * eurPerUsd;
  else usd = montant;

  const u = unite.toLowerCase().replace(/[_\s]/g, "");
  if (u.startsWith("partonne") || u === "pertonne" || u === "tonne" || u === "mt") return usd;
  if (u === "parkg" || u === "perkg" || u === "kg") return usd * 1000;
  if (u === "parquintal") return usd * 10;
  if (u.includes("sac50")) return usd * 20;
  if (u.includes("sac100")) return usd * 10;
  // Unknown but has a value — assume /tonne (common in seed data like "par_tonne_rcn")
  return usd;
}

// ─── Data fetching ─────────────────────────────────────────────────────────────

async function getAnalyseData() {
  // Fetch exchange rates from DB (most recent per pair)
  const [xofRate, eurRate] = await Promise.all([
    prisma.tauxChange.findFirst({
      where: { deviseSrc: "USD", deviseDest: "XOF" },
      orderBy: { dateReleve: "desc" },
    }).catch(() => null),
    prisma.tauxChange.findFirst({
      where: { deviseSrc: "EUR", deviseDest: "USD" },
      orderBy: { dateReleve: "desc" },
    }).catch(() => null),
  ]);

  const xofPerUsd = xofRate ? Number(xofRate.taux) : XOF_USD_FALLBACK;
  const eurPerUsd = eurRate ? Number(eurRate.taux) : EUR_USD_FALLBACK;

  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      produits: {
        where: { estDerive: false },
        orderBy: { code: "asc" },
        include: {
          prixReleves: {
            where: { fiabilite: { not: "EXEMPLE" } },
            orderBy: { dateReleve: "desc" },
            take: 120,
            select: {
              valeur: true,
              devise: true,
              unite: true,
              dateReleve: true,
              fiabilite: true,
              notes: true,
              source: { select: { nom: true } },
            },
          },
          structuresCout: {
            orderBy: [{ maillon: "asc" }, { poste: "asc" }],
            select: { montant: true, devise: true, unite: true, maillon: true, poste: true, fiabilite: true },
          },
        },
      },
    },
  });

  return { filieres, xofPerUsd, eurPerUsd };
}

// ─── Margin calculation ────────────────────────────────────────────────────────

type PrixRow = { valeur: unknown; devise: string; unite: string; fiabilite: string; dateReleve: Date | string };
type CoutRow = { montant: unknown; devise: string; unite: string; maillon: string; poste: string; fiabilite: string };

const FIABILITE_ORDER = ["OFFICIEL", "INDICATIF", "ESTIME", "EXEMPLE"];

function calcAnalyse(
  prix: PrixRow[],
  couts: CoutRow[],
  xofPerUsd: number,
  eurPerUsd: number,
) {
  if (!prix.length) return null;

  // Select best available data quality (OFFICIEL > INDICATIF > ESTIME > EXEMPLE)
  let bestPrix: PrixRow[] = [];
  for (const niveau of FIABILITE_ORDER) {
    const filtered = prix.filter((p) => p.fiabilite === niveau);
    if (filtered.length >= 1) {
      bestPrix = filtered;
      break;
    }
  }
  if (!bestPrix.length) bestPrix = prix;
  const qualitePrix = bestPrix[0].fiabilite;

  // Normalize prices to USD/tonne and average the 3 most recent
  const normalises: number[] = [];
  for (const p of bestPrix.slice(0, 6)) {
    const v = normPrixUsdTonne(Number(p.valeur), p.devise, p.unite, xofPerUsd, eurPerUsd);
    if (v !== null) normalises.push(v);
    if (normalises.length >= 3) break;
  }
  if (!normalises.length) return null;

  const prixMoyenUsd = normalises.reduce((a, b) => a + b, 0) / normalises.length;
  const dernierReleve = bestPrix[0].dateReleve;

  // Cost structures
  if (!couts.length) {
    return { prixMoyenUsd, dernierReleve, qualitePrix, coutTotal: null, marge: null, tauxMarge: null, postes: [] };
  }

  // Prefer OFFICIEL/INDICATIF costs, but use all if needed
  const coutsValides = couts.filter((c) => Number(c.montant) > 0);
  const coutNormalises = coutsValides.map((c) => ({
    ...c,
    valeurUsd: normCoutUsdTonne(Number(c.montant), c.devise, c.unite, xofPerUsd, eurPerUsd) ?? 0,
  }));

  const coutTotal = coutNormalises.reduce((acc, c) => acc + c.valeurUsd, 0);
  const marge = prixMoyenUsd - coutTotal;
  const tauxMarge = prixMoyenUsd > 0 ? (marge / prixMoyenUsd) * 100 : null;

  const postes = coutNormalises.map((c) => ({
    label: c.poste,
    maillon: c.maillon,
    valeurUsd: c.valeurUsd,
    pct: coutTotal > 0 ? (c.valeurUsd / coutTotal) * 100 : 0,
    fiabilite: c.fiabilite,
  }));

  return { prixMoyenUsd, dernierReleve, qualitePrix, coutTotal, marge, tauxMarge, postes };
}

// ─── Formatting ────────────────────────────────────────────────────────────────

function fmtUsd(v: number, digits = 0) {
  return v.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + " USD/T";
}

function fmtDate(d: Date | string) {
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

const FIABILITE_STYLE: Record<string, { color: string; bg: string; label: string }> = {
  OFFICIEL:  { color: "#4A9B6F", bg: "rgba(74,155,111,0.12)",  label: "OFFICIEL" },
  INDICATIF: { color: "#92BA59", bg: "rgba(146,186,89,0.10)",  label: "INDICATIF" },
  ESTIME:    { color: "#B89B3A", bg: "rgba(184,155,58,0.10)",  label: "ESTIMÉ" },
  EXEMPLE:   { color: "#888",    bg: "rgba(120,120,120,0.10)", label: "EXEMPLE ⚠" },
};

// ─── Page ──────────────────────────────────────────────────────────────────────

export default async function AnalysePage() {
  let filieres: Awaited<ReturnType<typeof getAnalyseData>>["filieres"] = [];
  let xofPerUsd = 655.957;
  let eurPerUsd = 1.08;
  try {
    ({ filieres, xofPerUsd, eurPerUsd } = await getAnalyseData());
  } catch (e) {
    console.error("AnalysePage DB error:", e);
  }

  const FILIERE_COLOR: Record<string, string> = { MAIS: "#92BA59", CAJOU: "#B89B3A", COLA: "#8A9E1A" };
  const FILIERE_ICON: Record<string, string>  = { MAIS: "🌽", CAJOU: "🥜", COLA: "🌰" };

  const analyses = filieres.flatMap((f) =>
    f.produits.map((p) => {
      const serie: PointPrix[] = p.prixReleves
        .map((r) => ({
          date: new Date(r.dateReleve),
          valeurUsd: normPrixUsdTonne(Number(r.valeur), r.devise, r.unite, xofPerUsd, eurPerUsd) ?? NaN,
        }))
        .filter((pt) => isFinite(pt.valeurUsd));
      return {
        ...p,
        filiere: f,
        accent: FILIERE_COLOR[f.code] ?? "var(--ag-lime)",
        analyse: calcAnalyse(p.prixReleves, p.structuresCout, xofPerUsd, eurPerUsd),
        indicateurs: calcIndicateurs(serie),
      };
    })
  );

  const nbOfficiel = filieres.flatMap((f) => f.produits).flatMap((p) =>
    p.prixReleves.filter((r) => r.fiabilite === "OFFICIEL")
  ).length;

  const nbExemple = filieres.flatMap((f) => f.produits).flatMap((p) =>
    p.prixReleves.filter((r) => r.fiabilite === "EXEMPLE")
  ).length;

  return (
    <div style={{ flex: 1, padding: "32px 0 64px" }}>
      <div className="ag-container">

        {/* ── Header ── */}
        <div style={{ marginBottom: "28px" }}>
          <p className="ag-section-label" style={{ marginBottom: "6px" }}>Analyse &amp; Investissement · Africa Agro Partners</p>
          <h1 className="font-display" style={{ fontSize: 24, color: "var(--text-primary)", margin: 0 }}>
            Opportunités d&apos;investissement
          </h1>
          <p style={{ marginTop: "8px", fontSize: 13, color: "var(--text-secondary)" }}>
            Rentabilité par filière — prix normalisés en USD/tonne · Taux de change : 1 USD = {xofPerUsd.toFixed(3)} XOF
          </p>
        </div>

        {/* ── Data quality banner ── */}
        {nbOfficiel === 0 && (
          <div style={{
            padding: "14px 20px", borderRadius: "8px", marginBottom: "20px",
            background: "rgba(184,155,58,0.08)", border: "1px solid rgba(184,155,58,0.3)",
            borderLeft: "3px solid #B89B3A",
          }}>
            <p style={{ fontSize: 12, color: "#B89B3A", fontFamily: "monospace", margin: 0 }}>
              ⚠ DONNÉES EXEMPLE UNIQUEMENT — Aucun prix officiel collecté.
              Rendez-vous sur{" "}
              <Link href="/collecte" style={{ color: "#B89B3A", textDecoration: "underline" }}>
                /collecte
              </Link>{" "}
              et déclenchez la collecte pour importer des prix réels.
            </p>
          </div>
        )}

        {nbOfficiel > 0 && nbExemple > 0 && (
          <div style={{
            padding: "12px 18px", borderRadius: "8px", marginBottom: "20px",
            background: "rgba(74,155,111,0.06)", border: "1px solid rgba(74,155,111,0.2)",
            borderLeft: "3px solid #4A9B6F",
          }}>
            <p style={{ fontSize: 12, color: "#4A9B6F", fontFamily: "monospace", margin: 0 }}>
              ✓ {nbOfficiel} prix officiels collectés · {nbExemple} données exemple présentes.
              Les analyses utilisent en priorité les données officielles.
            </p>
          </div>
        )}

        {nbOfficiel > 0 && nbExemple === 0 && (
          <div style={{
            padding: "12px 18px", borderRadius: "8px", marginBottom: "20px",
            background: "rgba(74,155,111,0.06)", border: "1px solid rgba(74,155,111,0.2)",
            borderLeft: "3px solid #4A9B6F",
          }}>
            <p style={{ fontSize: 12, color: "#4A9B6F", fontFamily: "monospace", margin: 0 }}>
              ✓ {nbOfficiel} prix officiels collectés — données de marché réelles.
            </p>
          </div>
        )}

        {/* ── Cards produit ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "16px", marginBottom: "40px" }}>
          {analyses.map((a) => {
            const an = a.analyse;
            const hasPrix = an !== null;
            const hasMarge = hasPrix && an.marge !== null;
            const margePos = hasMarge && an.marge! > 0;
            const qs = an ? (FIABILITE_STYLE[an.qualitePrix] ?? FIABILITE_STYLE.EXEMPLE) : null;

            return (
              <div
                key={a.id}
                style={{
                  background: "var(--bg-surface)", border: "1px solid var(--border-subtle)",
                  borderRadius: "10px", overflow: "hidden",
                }}
              >
                {/* Accent bar */}
                <div style={{ height: "3px", background: `linear-gradient(90deg, ${a.accent}, transparent)` }} />

                <div style={{ padding: "20px" }}>
                  {/* Header produit */}
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "10px", marginBottom: "16px" }}>
                    <span style={{ fontSize: 22, marginTop: "2px" }}>{FILIERE_ICON[a.filiere.code]}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>{a.nom}</div>
                      <div style={{ fontSize: 10, fontFamily: "monospace", color: "var(--text-muted)", marginTop: "2px" }}>
                        {a.filiere.nom} · {a.uniteRef}
                      </div>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                      {qs && (
                        <span style={{
                          fontSize: 8, fontFamily: "monospace", letterSpacing: "0.06em",
                          padding: "2px 6px", borderRadius: "4px",
                          color: qs.color, background: qs.bg,
                          border: `1px solid ${qs.color}33`,
                        }}>
                          {qs.label}
                        </span>
                      )}
                      <Link
                        href={`/referentiel/${a.filiere.code.toLowerCase()}/${a.code.toLowerCase()}`}
                        style={{ fontSize: 10, color: a.accent, textDecoration: "none", fontFamily: "monospace" }}
                      >
                        Fiche →
                      </Link>
                    </div>
                  </div>

                  {/* KPIs prix / coûts */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "14px" }}>
                    <div style={{ background: "var(--bg-elevated)", borderRadius: "6px", padding: "10px" }}>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace", letterSpacing: "0.06em", marginBottom: "4px" }}>
                        PRIX MARCHÉ
                      </div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: a.accent, fontFamily: "monospace" }}>
                        {an?.prixMoyenUsd != null ? fmtUsd(an.prixMoyenUsd) : "—"}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: "2px" }}>
                        {an?.dernierReleve ? fmtDate(an.dernierReleve) : `${a.prixReleves.length} relevé(s)`}
                      </div>
                    </div>
                    <div style={{ background: "var(--bg-elevated)", borderRadius: "6px", padding: "10px" }}>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace", letterSpacing: "0.06em", marginBottom: "4px" }}>
                        COÛTS PROD.
                      </div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-secondary)", fontFamily: "monospace" }}>
                        {an?.coutTotal != null ? fmtUsd(an.coutTotal) : "—"}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: "2px" }}>
                        {a.structuresCout.length > 0
                          ? `${a.structuresCout.length} poste(s) de coût`
                          : "Pas de structure de coûts"}
                      </div>
                    </div>
                  </div>

                  {/* Marge */}
                  {hasMarge ? (
                    <div
                      style={{
                        padding: "12px 14px", borderRadius: "8px",
                        background: margePos ? "rgba(74,155,111,0.1)" : "rgba(224,82,82,0.1)",
                        border: `1px solid ${margePos ? "rgba(74,155,111,0.25)" : "rgba(224,82,82,0.25)"}`,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <div>
                          <div style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)", marginBottom: "4px" }}>
                            MARGE BRUTE EST.
                          </div>
                          <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "monospace", color: margePos ? "#4A9B6F" : "#E05252" }}>
                            {margePos ? "+" : ""}{fmtUsd(an!.marge!)}
                          </div>
                        </div>
                        <div style={{ textAlign: "right" }}>
                          <div style={{ fontSize: 26, fontWeight: 700, fontFamily: "monospace", color: margePos ? "#4A9B6F" : "#E05252" }}>
                            {an!.tauxMarge!.toFixed(1)}%
                          </div>
                          <div style={{ fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace" }}>
                            TAUX MARGE
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : hasPrix ? (
                    <div
                      style={{
                        padding: "12px 14px", borderRadius: "8px",
                        background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)",
                      }}
                    >
                      <p style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace", margin: 0 }}>
                        {a.structuresCout.length === 0
                          ? "Coûts manquants — saisir une structure de coûts pour calculer la marge"
                          : "Prix non normalisable — unité non reconnue"}
                      </p>
                    </div>
                  ) : (
                    <div
                      style={{
                        padding: "12px 14px", borderRadius: "8px",
                        background: "rgba(184,155,58,0.06)", border: "1px solid rgba(184,155,58,0.2)",
                      }}
                    >
                      <p style={{ fontSize: 12, color: "#B89B3A", fontFamily: "monospace", margin: 0 }}>
                        Aucun prix disponible —{" "}
                        <Link href="/collecte" style={{ color: "#B89B3A" }}>
                          déclencher la collecte
                        </Link>
                      </p>
                    </div>
                  )}

                  {/* Top cost breakdown */}
                  {an?.postes && an.postes.length > 0 && (
                    <div style={{ marginTop: "14px" }}>
                      <p className="ag-section-label" style={{ marginBottom: "8px", fontSize: 9 }}>
                        RÉPARTITION DES COÛTS
                      </p>
                      <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                        {an.postes.slice(0, 5).map((c, i) => (
                          <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <div style={{
                              fontSize: 9, color: "var(--text-muted)", fontFamily: "monospace",
                              width: 90, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            }}>
                              {c.label.replace(/_/g, " ")}
                            </div>
                            <div style={{ flex: 1, height: 4, background: "var(--bg-elevated)", borderRadius: "2px", overflow: "hidden" }}>
                              <div style={{ width: `${Math.min(100, c.pct)}%`, height: "100%", background: a.accent, borderRadius: "2px" }} />
                            </div>
                            <div style={{ fontSize: 9, color: "var(--text-secondary)", fontFamily: "monospace", width: 32, textAlign: "right" }}>
                              {c.pct.toFixed(0)}%
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Aide à la décision d'investissement — indicateurs quantitatifs ── */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden", marginBottom: "32px" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
            <p className="ag-section-label">Aide à la décision d&apos;investissement — indicateurs quantitatifs</p>
            <p style={{ fontSize: 11, color: "var(--text-muted)", margin: 0, fontFamily: "monospace" }}>
              Calculés sur l&apos;historique réel (USD/tonne) : tendance 90j, volatilité, position 52 semaines, drawdown, score composite
            </p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "0" }}>
            {analyses.filter((a) => a.indicateurs).map((a) => {
              const ind = a.indicateurs!;
              const sigStyle = ind.signal === "HAUSSIER"
                ? { color: "#4A9B6F", bg: "rgba(74,155,111,0.12)" }
                : ind.signal === "BAISSIER"
                ? { color: "#E05252", bg: "rgba(224,82,82,0.10)" }
                : { color: "#B89B3A", bg: "rgba(184,155,58,0.10)" };
              const scoreColor = ind.scoreOpportunite >= 65 ? "#4A9B6F" : ind.scoreOpportunite >= 45 ? "#B89B3A" : "#E05252";
              return (
                <div key={a.id} style={{ padding: "20px", borderRight: "1px solid var(--border-subtle)", borderBottom: "1px solid var(--border-subtle)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "14px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ fontSize: 18 }}>{FILIERE_ICON[a.filiere.code]}</span>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{a.nom}</div>
                        <div style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)" }}>{ind.nbPoints} relevés analysés</div>
                      </div>
                    </div>
                    <span style={{
                      fontSize: 9, fontFamily: "monospace", fontWeight: 700, letterSpacing: "0.06em",
                      padding: "3px 9px", borderRadius: "20px",
                      color: sigStyle.color, background: sigStyle.bg, border: `1px solid ${sigStyle.color}33`,
                    }}>
                      {ind.signal}
                    </span>
                  </div>

                  {/* Score gauge */}
                  <div style={{ marginBottom: "14px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
                      <span style={{ fontSize: 9, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.08em" }}>SCORE OPPORTUNITÉ ACHAT</span>
                      <span style={{ fontSize: 13, fontFamily: "monospace", fontWeight: 700, color: scoreColor }}>{ind.scoreOpportunite}/100</span>
                    </div>
                    <div style={{ height: 6, background: "var(--bg-elevated)", borderRadius: "3px", overflow: "hidden" }}>
                      <div style={{ width: `${ind.scoreOpportunite}%`, height: "100%", background: scoreColor, borderRadius: "3px" }} />
                    </div>
                  </div>

                  {/* Metrics grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "12px" }}>
                    {[
                      { l: "Dernier prix", v: `${ind.dernierPrix.toFixed(0)} $/T` },
                      { l: "Tendance 90j", v: ind.tendancePctMois !== null ? `${ind.tendancePctMois >= 0 ? "+" : ""}${ind.tendancePctMois.toFixed(1)}%/mois` : "—" },
                      { l: "Volatilité", v: ind.volatilitePct !== null ? `${ind.volatilitePct.toFixed(1)}%` : "—" },
                      { l: "MM30", v: ind.mm30 !== null ? `${ind.mm30.toFixed(0)} $/T` : ind.mm7 !== null ? `MM7 ${ind.mm7.toFixed(0)} $/T` : "—" },
                      { l: "Fourchette 52 sem.", v: `${ind.min52.toFixed(0)}–${ind.max52.toFixed(0)} $` },
                      { l: "Position / fourchette", v: `${ind.positionPct.toFixed(0)}%` },
                      { l: "Drawdown max", v: ind.drawdownMaxPct !== null ? `−${ind.drawdownMaxPct.toFixed(1)}%` : "—" },
                    ].map(({ l, v }) => (
                      <div key={l} style={{ background: "var(--bg-elevated)", borderRadius: "6px", padding: "7px 10px" }}>
                        <div style={{ fontSize: 8, fontFamily: "monospace", color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>{l}</div>
                        <div style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 700, color: "var(--text-primary)", marginTop: "2px" }}>{v}</div>
                      </div>
                    ))}
                  </div>

                  <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.55, margin: 0 }}>
                    {ind.recommandation}
                  </p>
                </div>
              );
            })}
            {analyses.every((a) => !a.indicateurs) && (
              <div style={{ padding: "24px", fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
                Pas encore assez d&apos;historique de prix — lancez la collecte sur /collecte.
              </div>
            )}
          </div>
          <div style={{ padding: "10px 20px", borderTop: "1px solid var(--border-subtle)" }}>
            <p style={{ fontSize: 10, color: "var(--text-muted)", fontFamily: "monospace", margin: 0 }}>
              ⚠ Indicateurs statistiques fournis à titre d&apos;aide à la décision — ne constituent pas un conseil en investissement. Croiser avec les coûts logistiques et le risque de change XOF/USD.
            </p>
          </div>
        </div>

        {/* ── Comparateur filières ── */}
        <div style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "10px", overflow: "hidden", marginBottom: "32px" }}>
          <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
            <p className="ag-section-label">Comparateur de rentabilité — toutes filières</p>
            <p style={{ fontSize: 11, color: "var(--text-muted)", margin: 0, fontFamily: "monospace" }}>
              Prix normalisés USD/tonne · Données en priorité OFFICIEL &gt; INDICATIF &gt; ESTIMÉ &gt; EXEMPLE
            </p>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="ag-table">
              <thead>
                <tr>
                  <th>Filière · Produit</th>
                  <th style={{ textAlign: "right" }}>Prix marché</th>
                  <th style={{ textAlign: "right" }}>Coûts prod.</th>
                  <th style={{ textAlign: "right" }}>Marge brute</th>
                  <th style={{ textAlign: "right" }}>Taux marge</th>
                  <th>Qualité données</th>
                  <th>Dernier relevé</th>
                </tr>
              </thead>
              <tbody>
                {analyses.map((a) => {
                  const an = a.analyse;
                  const hasMarge = an?.marge !== null && an?.marge !== undefined;
                  const pos = hasMarge && an!.marge! > 0;
                  const qs = an ? (FIABILITE_STYLE[an.qualitePrix] ?? FIABILITE_STYLE.EXEMPLE) : null;
                  return (
                    <tr key={a.id}>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                          <span>{FILIERE_ICON[a.filiere.code]}</span>
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{a.nom}</div>
                            <div style={{ fontSize: 10, fontFamily: "monospace", color: a.accent }}>{a.code}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", color: a.accent, fontWeight: 700 }}>
                        {an?.prixMoyenUsd != null ? fmtUsd(an.prixMoyenUsd) : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", color: "var(--text-secondary)" }}>
                        {an?.coutTotal != null ? fmtUsd(an.coutTotal) : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: hasMarge ? (pos ? "#4A9B6F" : "#E05252") : "var(--text-muted)" }}>
                        {hasMarge ? `${pos ? "+" : ""}${fmtUsd(an!.marge!)}` : "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, fontSize: 14, color: hasMarge ? (pos ? "#4A9B6F" : "#E05252") : "var(--text-muted)" }}>
                        {hasMarge ? `${an!.tauxMarge!.toFixed(1)}%` : "—"}
                      </td>
                      <td>
                        {qs ? (
                          <span style={{
                            fontSize: 9, fontFamily: "monospace", letterSpacing: "0.04em",
                            padding: "2px 6px", borderRadius: "4px",
                            color: qs.color, background: qs.bg,
                          }}>
                            {qs.label}
                          </span>
                        ) : (
                          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>—</span>
                        )}
                      </td>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>
                        {an?.dernierReleve ? fmtDate(an.dernierReleve) : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Méthodologie ── */}
        <div style={{
          padding: "16px 20px", borderRadius: "8px",
          background: "var(--bg-surface)", border: "1px solid var(--border-subtle)",
        }}>
          <p className="ag-section-label" style={{ marginBottom: "8px" }}>Méthodologie de calcul</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "12px" }}>
            {[
              { titre: "Normalisation des prix", desc: "Tous les prix sont convertis en USD/tonne avant calcul — XOF/kg, USD/bushel, etc. sont automatiquement normalisés." },
              { titre: "Sélection des données", desc: "L'algorithme utilise en priorité les données OFFICIEL (World Bank, FAO, IMF), puis INDICATIF, ESTIMÉ, EXEMPLE." },
              { titre: "Taux de change", desc: `1 USD = ${xofPerUsd.toFixed(3)} XOF (${xofPerUsd === XOF_USD_FALLBACK ? "taux légal fixe FCFA/EUR" : "taux collecté en BD"}). 1 EUR ≈ ${eurPerUsd.toFixed(2)} USD.` },
              { titre: "Marge brute estimée", desc: "Marge = Prix moyen marché − Somme des coûts de production. Ne comprend pas la fiscalité ni les coûts de financement." },
            ].map((m) => (
              <div key={m.titre}>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-primary)", marginBottom: "4px" }}>{m.titre}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>{m.desc}</div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
