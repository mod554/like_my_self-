// Indicateurs quantitatifs d'aide à la décision d'investissement
// Fonctions pures — série de prix normalisés USD/tonne, du plus ancien au plus récent

export interface PointPrix {
  date: Date;
  valeurUsd: number;
}

export interface IndicateursQuantitatifs {
  nbPoints: number;
  dernierPrix: number;
  mm7: number | null;          // moyenne mobile 7 relevés
  mm30: number | null;         // moyenne mobile 30 relevés
  volatilitePct: number | null;  // écart-type des rendements (%)
  tendancePctMois: number | null; // pente régression linéaire, en %/mois
  min52: number;
  max52: number;
  positionPct: number;         // 0 = au plus bas 52 sem., 100 = au plus haut
  drawdownMaxPct: number | null;
  rsi14: number | null;          // Relative Strength Index 14 périodes
  croisementMM: "GOLDEN" | "DEATH" | null; // croisement MM7/MM30 récent
  momentum30Pct: number | null;  // variation prix vs il y a ~30 relevés (%)
  fiabiliteStat: "OK" | "FAIBLE"; // FAIBLE si < 10 points — stats indicatives
  support: number;               // plus bas 52 sem. (niveau de support)
  resistance: number;            // plus haut 52 sem. (niveau de résistance)
  zoneAchatMax: number;          // borne haute de la zone d'accumulation (min52 + 25% de fourchette)
  signal: "HAUSSIER" | "BAISSIER" | "NEUTRE";
  scoreOpportunite: number;    // 0-100 — opportunité d'achat/positionnement
  recommandation: string;
}

function moyenne(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function ecartType(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = moyenne(xs);
  return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
}

// Régression linéaire simple sur (jours depuis début, prix) → pente USD/jour
function penteLineaire(points: PointPrix[]): number | null {
  if (points.length < 3) return null;
  const t0 = points[0].date.getTime();
  const xs = points.map((p) => (p.date.getTime() - t0) / 86_400_000);
  const ys = points.map((p) => p.valeurUsd);
  const mx = moyenne(xs);
  const my = moyenne(ys);
  let num = 0, den = 0;
  for (let i = 0; i < xs.length; i++) {
    num += (xs[i] - mx) * (ys[i] - my);
    den += (xs[i] - mx) ** 2;
  }
  return den === 0 ? null : num / den;
}

export function calcIndicateurs(serie: PointPrix[]): IndicateursQuantitatifs | null {
  const points = serie
    .filter((p) => isFinite(p.valeurUsd) && p.valeurUsd > 0)
    .sort((a, b) => a.date.getTime() - b.date.getTime());
  if (points.length < 2) return null;

  const valeurs = points.map((p) => p.valeurUsd);
  const dernierPrix = valeurs[valeurs.length - 1];

  const mm = (n: number) =>
    valeurs.length >= n ? moyenne(valeurs.slice(-n)) : null;
  const mm7 = mm(7);
  const mm30 = mm(30);

  // Rendements période à période
  const rendements: number[] = [];
  for (let i = 1; i < valeurs.length; i++) {
    if (valeurs[i - 1] > 0) rendements.push((valeurs[i] - valeurs[i - 1]) / valeurs[i - 1]);
  }
  const volatilitePct = rendements.length >= 3 ? ecartType(rendements) * 100 : null;

  // Tendance : régression sur les 90 derniers jours de données
  const coupure = points[points.length - 1].date.getTime() - 90 * 86_400_000;
  const recents = points.filter((p) => p.date.getTime() >= coupure);
  const pente = penteLineaire(recents.length >= 3 ? recents : points);
  const tendancePctMois =
    pente !== null && dernierPrix > 0 ? (pente * 30 / dernierPrix) * 100 : null;

  // Fenêtre 52 semaines
  const coupure52 = points[points.length - 1].date.getTime() - 365 * 86_400_000;
  const fenetre = points.filter((p) => p.date.getTime() >= coupure52);
  const v52 = (fenetre.length >= 2 ? fenetre : points).map((p) => p.valeurUsd);
  const min52 = Math.min(...v52);
  const max52 = Math.max(...v52);
  const positionPct = max52 > min52 ? ((dernierPrix - min52) / (max52 - min52)) * 100 : 50;

  // Drawdown maximal
  let pic = valeurs[0];
  let ddMax = 0;
  for (const v of valeurs) {
    if (v > pic) pic = v;
    const dd = pic > 0 ? (pic - v) / pic : 0;
    if (dd > ddMax) ddMax = dd;
  }
  const drawdownMaxPct = valeurs.length >= 3 ? ddMax * 100 : null;

  // RSI 14 (Wilder) — force relative des hausses vs baisses
  let rsi14: number | null = null;
  if (valeurs.length >= 15) {
    const deltas = valeurs.slice(-15).map((v, i, a) => (i === 0 ? 0 : v - a[i - 1])).slice(1);
    const gains = deltas.filter((d) => d > 0).reduce((a, b) => a + b, 0) / 14;
    const pertes = -deltas.filter((d) => d < 0).reduce((a, b) => a + b, 0) / 14;
    rsi14 = pertes === 0 ? 100 : Math.round(100 - 100 / (1 + gains / pertes));
  }

  // Croisement MM7/MM30 sur les 5 derniers relevés (golden/death cross)
  let croisementMM: "GOLDEN" | "DEATH" | null = null;
  if (valeurs.length >= 35) {
    const mmAt = (n: number, fin: number) => moyenne(valeurs.slice(fin - n, fin));
    const avant = mmAt(7, valeurs.length - 5) - mmAt(30, valeurs.length - 5);
    const apres = mmAt(7, valeurs.length) - mmAt(30, valeurs.length);
    if (avant <= 0 && apres > 0) croisementMM = "GOLDEN";
    else if (avant >= 0 && apres < 0) croisementMM = "DEATH";
  }

  // Momentum : variation vs ~30 relevés en arrière
  const momentum30Pct = valeurs.length >= 31 && valeurs[valeurs.length - 31] > 0
    ? ((dernierPrix - valeurs[valeurs.length - 31]) / valeurs[valeurs.length - 31]) * 100
    : null;

  const fiabiliteStat: "OK" | "FAIBLE" = points.length >= 10 ? "OK" : "FAIBLE";

  // Signal : prix vs MM et pente
  let signal: IndicateursQuantitatifs["signal"] = "NEUTRE";
  const ref = mm30 ?? mm7;
  if (ref !== null && tendancePctMois !== null) {
    if (dernierPrix > ref * 1.02 && tendancePctMois > 0.5) signal = "HAUSSIER";
    else if (dernierPrix < ref * 0.98 && tendancePctMois < -0.5) signal = "BAISSIER";
  } else if (tendancePctMois !== null) {
    signal = tendancePctMois > 1 ? "HAUSSIER" : tendancePctMois < -1 ? "BAISSIER" : "NEUTRE";
  }

  // Score opportunité (positionnement acheteur/investisseur) 0-100 :
  // prix bas dans sa fourchette 52 sem. (poids 45) + tendance repartie à la
  // hausse (poids 35) + volatilité maîtrisée (poids 20)
  let score = 0;
  score += (1 - positionPct / 100) * 45;
  if (tendancePctMois !== null) {
    score += Math.max(0, Math.min(1, (tendancePctMois + 2) / 6)) * 35;
  } else {
    score += 17.5;
  }
  if (volatilitePct !== null) {
    score += Math.max(0, 1 - Math.min(volatilitePct, 25) / 25) * 20;
  } else {
    score += 10;
  }
  const scoreOpportunite = Math.round(Math.max(0, Math.min(100, score)));

  // Niveaux de trading concrets
  const support = min52;
  const resistance = max52;
  const zoneAchatMax = min52 + (max52 - min52) * 0.25;

  const fmtN = (v: number) => v >= 100 ? v.toFixed(0) : v.toFixed(2);
  let recommandation: string;
  if (fiabiliteStat === "FAIBLE") {
    recommandation = `Historique trop court (${points.length} relevés) pour des statistiques robustes — indicateurs donnés à titre purement informatif. Support ${fmtN(support)} $ / résistance ${fmtN(resistance)} $.`;
  } else if (scoreOpportunite >= 65) {
    recommandation = `Fenêtre d'achat potentielle — prix dans la zone d'accumulation (≤ ${fmtN(zoneAchatMax)} $/T). Objectif de revente vers la résistance ${fmtN(resistance)} $/T${rsi14 !== null ? `, RSI ${rsi14}` : ""}. Croiser avec les coûts logistiques réels.`;
  } else if (scoreOpportunite >= 45) {
    recommandation = `Position neutre — attendre soit un repli vers la zone d'achat (≤ ${fmtN(zoneAchatMax)} $/T), soit une cassure confirmée de la MM30${croisementMM === "GOLDEN" ? " (golden cross récent : signal précoce haussier)" : ""}.`;
  } else if (signal === "HAUSSIER") {
    recommandation = `Prix élevés (${positionPct.toFixed(0)}% de la fourchette 52 sem.) en tendance haussière — favorable au VENDEUR/producteur ; acheteur : risque de retournement sous la résistance ${fmtN(resistance)} $/T${rsi14 !== null && rsi14 > 70 ? `, RSI ${rsi14} en surchauffe` : ""}.`;
  } else {
    recommandation = `Conditions défavorables à l'achat — ${croisementMM === "DEATH" ? "death cross MM7/MM30 récent, " : ""}attendre une stabilisation au-dessus du support ${fmtN(support)} $/T avant tout positionnement.`;
  }

  return {
    nbPoints: points.length,
    dernierPrix,
    mm7, mm30,
    volatilitePct,
    tendancePctMois,
    min52, max52, positionPct,
    drawdownMaxPct,
    rsi14,
    croisementMM,
    momentum30Pct,
    fiabiliteStat,
    support,
    resistance,
    zoneAchatMax,
    signal,
    scoreOpportunite,
    recommandation,
  };
}
