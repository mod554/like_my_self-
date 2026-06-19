// Moteur de calcul financier — VAN, TRI, Payback, Point mort, Sensibilité

export interface HypothesesInvestissement {
  capex: number; // investissement initial (année 0), en devise de référence
  opexFixes: number; // charges fixes annuelles
  opexVariables: number; // charges variables par unité produite
  prixUnitaire: number; // prix de vente par unité
  volumeAnnuel: number; // volume produit/vendu par an
  dureeAns: number; // durée de l'analyse en années
  tauxActualisation: number; // taux d'actualisation (ex : 0.12 = 12%)
  valeurResiduelle?: number; // valeur résiduelle à la fin (défaut : 0)
}

export interface ResultatsFinanciers {
  fluxNets: number[]; // flux net par année (0 = année investissement)
  fluxActualises: number[]; // flux nets actualisés
  fluxCumules: number[]; // flux cumulés (non actualisés)
  van: number; // Valeur Actuelle Nette
  tri: number | null; // Taux de Rendement Interne (null si non calculable)
  paybackAns: number | null; // délai de récupération en années (null si > durée)
  pointMortUnites: number; // volume minimal pour équilibre opérationnel
  margeContribution: number; // prix - coût variable unitaire
  margeBrute: number; // CA - coûts variables totaux (annuel)
  margeNettePct: number; // marge nette / CA (%)
  viable: boolean; // VAN >= 0 et TRI > taux actualisation
}

export function calculerFluxNets(h: HypothesesInvestissement): number[] {
  const flux: number[] = [];

  // Année 0 : investissement initial
  flux.push(-h.capex);

  // Années 1 à N
  for (let t = 1; t <= h.dureeAns; t++) {
    const ca = h.prixUnitaire * h.volumeAnnuel;
    const coutVariableTotal = h.opexVariables * h.volumeAnnuel;
    const fluxBrut = ca - coutVariableTotal - h.opexFixes;

    // Dernière année : ajouter la valeur résiduelle
    if (t === h.dureeAns) {
      flux.push(fluxBrut + (h.valeurResiduelle ?? 0));
    } else {
      flux.push(fluxBrut);
    }
  }

  return flux;
}

export function calculerVAN(
  fluxNets: number[],
  tauxActualisation: number
): number {
  return fluxNets.reduce((acc, flux, t) => {
    return acc + flux / Math.pow(1 + tauxActualisation, t);
  }, 0);
}

export function calculerTRI(
  fluxNets: number[],
  precision = 1e-6,
  maxIterations = 1000
): number | null {
  // Vérifier qu'il y a au moins un flux positif et un négatif
  const aPositif = fluxNets.some((f) => f > 0);
  const aNegatif = fluxNets.some((f) => f < 0);
  if (!aPositif || !aNegatif) return null;

  // Dichotomie dans [-99%, +1000%]
  let lo = -0.999;
  let hi = 10.0;

  const van = (r: number) =>
    fluxNets.reduce((acc, f, t) => acc + f / Math.pow(1 + r, t), 0);

  if (van(lo) * van(hi) > 0) return null;

  for (let i = 0; i < maxIterations; i++) {
    const mid = (lo + hi) / 2;
    if (Math.abs(van(mid)) < precision || (hi - lo) / 2 < precision) {
      return mid;
    }
    if (van(lo) * van(mid) < 0) {
      hi = mid;
    } else {
      lo = mid;
    }
  }

  return (lo + hi) / 2;
}

export function calculerPayback(fluxNets: number[]): number | null {
  let cumul = 0;
  for (let t = 0; t < fluxNets.length; t++) {
    const precedent = cumul;
    cumul += fluxNets[t];
    if (cumul >= 0 && t > 0) {
      // Interpolation linéaire
      return t - 1 + (-precedent / fluxNets[t]);
    }
  }
  return null; // Non récupéré dans la durée d'analyse
}

export function calculerPointMort(
  opexFixes: number,
  prixUnitaire: number,
  coutVariableUnitaire: number
): number {
  const margeContrib = prixUnitaire - coutVariableUnitaire;
  if (margeContrib <= 0) {
    throw new Error(
      "Point mort non calculable : marge sur coût variable nulle ou négative. Le prix de vente doit être supérieur au coût variable unitaire."
    );
  }
  return opexFixes / margeContrib;
}

export function analyserInvestissement(
  h: HypothesesInvestissement
): ResultatsFinanciers {
  const fluxNets = calculerFluxNets(h);
  const fluxActualises = fluxNets.map(
    (f, t) => f / Math.pow(1 + h.tauxActualisation, t)
  );

  // Flux cumulés (pour graphique de payback)
  const fluxCumules: number[] = [];
  let cumul = 0;
  for (const f of fluxNets) {
    cumul += f;
    fluxCumules.push(cumul);
  }

  const van = calculerVAN(fluxNets, h.tauxActualisation);
  const tri = calculerTRI(fluxNets);
  const paybackAns = calculerPayback(fluxNets);
  const margeContribution = h.prixUnitaire - h.opexVariables;
  const pointMortUnites = calculerPointMort(
    h.opexFixes,
    h.prixUnitaire,
    h.opexVariables
  );
  const ca = h.prixUnitaire * h.volumeAnnuel;
  const margeBrute = ca - h.opexVariables * h.volumeAnnuel;
  const beneficeNet = margeBrute - h.opexFixes;
  const margeNettePct = ca > 0 ? (beneficeNet / ca) * 100 : 0;

  return {
    fluxNets,
    fluxActualises,
    fluxCumules,
    van,
    tri,
    paybackAns,
    pointMortUnites,
    margeContribution,
    margeBrute,
    margeNettePct,
    viable: van >= 0 && tri !== null && tri > h.tauxActualisation,
  };
}

export interface ScenarioParams {
  variationPrixPct: number; // -20 = prix -20%
  variationCoutVariablePct: number; // +10 = coûts variables +10%
  variationVolumePct?: number; // +0 par défaut
}

export function analyseScenarios(
  hBase: HypothesesInvestissement,
  scenarios: { nom: string; params: ScenarioParams }[]
) {
  return scenarios.map(({ nom, params }) => {
    const hScenario: HypothesesInvestissement = {
      ...hBase,
      prixUnitaire: hBase.prixUnitaire * (1 + params.variationPrixPct / 100),
      opexVariables:
        hBase.opexVariables * (1 + params.variationCoutVariablePct / 100),
      volumeAnnuel:
        hBase.volumeAnnuel * (1 + (params.variationVolumePct ?? 0) / 100),
    };
    const resultats = analyserInvestissement(hScenario);
    return { nom, hypotheses: hScenario, resultats };
  });
}

export function analyseSensibilite(
  hBase: HypothesesInvestissement,
  plageVariationPrix: number[] = [-30, -20, -10, 0, 10, 20, 30],
  plageVariationCouts: number[] = [-20, -10, 0, 10, 20]
): { variationPrix: number; variationCout: number; van: number; tri: number | null }[][] {
  return plageVariationPrix.map((vPrix) =>
    plageVariationCouts.map((vCout) => {
      const h: HypothesesInvestissement = {
        ...hBase,
        prixUnitaire: hBase.prixUnitaire * (1 + vPrix / 100),
        opexVariables: hBase.opexVariables * (1 + vCout / 100),
      };
      const { van, tri } = analyserInvestissement(h);
      return { variationPrix: vPrix, variationCout: vCout, van, tri };
    })
  );
}
