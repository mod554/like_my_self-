// Facteurs de conversion d'unités — traçables

export const FACTEURS_UNITE: Record<string, Record<string, number>> = {
  // Masse — base : tonne métrique
  tonne: {
    tonne: 1,
    kg: 1000,
    lb: 2204.623,
    bushel_mais: 39.3683, // 1 tonne maïs = 39.37 bushels (USDA)
    sac50kg: 20,
    sac80kg: 12.5,
    sac100kg: 10,
  },
  kg: {
    kg: 1,
    tonne: 0.001,
    lb: 2.204623,
    sac50kg: 0.02,
    sac80kg: 0.0125,
    sac100kg: 0.01,
    bushel_mais: 0.039368,
  },
  lb: {
    lb: 1,
    kg: 0.453592,
    tonne: 0.000453592,
  },
  bushel: {
    bushel: 1,
    tonne: 0.025401, // maïs par défaut (25.4 kg/bushel)
    kg: 25.4012,
  },
  bushel_mais: {
    bushel_mais: 1,
    tonne: 0.025401,
    kg: 25.4012,
    lb: 56,
  },
  // Volume — base : litre
  litre: {
    litre: 1,
    ml: 1000,
    m3: 0.001,
    gallon_us: 0.264172,
  },
};

// Taux de change fixes et paramétrables
export const TAUX_FIXES: Record<string, Record<string, number>> = {
  EUR: {
    XOF: 655.957,
    XAF: 655.957, // même zone franc
  },
  XOF: {
    EUR: 1 / 655.957,
    XAF: 1,
  },
};

export interface ConversionUnite {
  valeur: number;
  uniteSource: string;
  uniteCible: string;
  facteur: number;
  resultat: number;
  tracabilite: string;
}

export function convertirUnite(
  valeur: number,
  uniteSource: string,
  uniteCible: string
): ConversionUnite {
  if (uniteSource === uniteCible) {
    return {
      valeur,
      uniteSource,
      uniteCible,
      facteur: 1,
      resultat: valeur,
      tracabilite: `${valeur} ${uniteSource} → (facteur 1) → ${valeur} ${uniteCible}`,
    };
  }

  const facteurs = FACTEURS_UNITE[uniteSource];
  if (!facteurs || facteurs[uniteCible] === undefined) {
    throw new Error(
      `Conversion d'unité impossible : ${uniteSource} → ${uniteCible}. Vérifiez les facteurs dans conversions.ts.`
    );
  }

  const facteur = facteurs[uniteCible];
  const resultat = valeur * facteur;

  return {
    valeur,
    uniteSource,
    uniteCible,
    facteur,
    resultat,
    tracabilite: `${valeur} ${uniteSource} × ${facteur} = ${resultat.toFixed(4)} ${uniteCible}`,
  };
}

export interface ConversionDevise {
  valeur: number;
  deviseSource: string;
  deviseCible: string;
  taux: number;
  sourcesTaux: string;
  resultat: number;
  tracabilite: string;
}

export function convertirDevise(
  valeur: number,
  deviseSource: string,
  deviseCible: string,
  tauxDuJour?: Record<string, number>
): ConversionDevise {
  if (deviseSource === deviseCible) {
    return {
      valeur,
      deviseSource,
      deviseCible,
      taux: 1,
      sourcesTaux: "identité",
      resultat: valeur,
      tracabilite: `${valeur} ${deviseSource} (même devise)`,
    };
  }

  // 1. Taux fixe légal (EUR/XOF)
  if (TAUX_FIXES[deviseSource]?.[deviseCible] !== undefined) {
    const taux = TAUX_FIXES[deviseSource][deviseCible];
    return {
      valeur,
      deviseSource,
      deviseCible,
      taux,
      sourcesTaux: "Taux fixe légal (UEMOA/BEAC)",
      resultat: valeur * taux,
      tracabilite: `${valeur} ${deviseSource} × ${taux} (fixe légal) = ${(valeur * taux).toFixed(2)} ${deviseCible}`,
    };
  }

  // 2. Taux du jour passé en paramètre
  const cleDirecte = `${deviseSource}_${deviseCible}`;
  const cleInverse = `${deviseCible}_${deviseSource}`;

  if (tauxDuJour?.[cleDirecte]) {
    const taux = tauxDuJour[cleDirecte];
    return {
      valeur,
      deviseSource,
      deviseCible,
      taux,
      sourcesTaux: "Taux du jour (BCE/source externe)",
      resultat: valeur * taux,
      tracabilite: `${valeur} ${deviseSource} × ${taux} (taux du jour) = ${(valeur * taux).toFixed(2)} ${deviseCible}`,
    };
  }

  if (tauxDuJour?.[cleInverse]) {
    const taux = 1 / tauxDuJour[cleInverse];
    return {
      valeur,
      deviseSource,
      deviseCible,
      taux,
      sourcesTaux: "Taux du jour inversé (BCE/source externe)",
      resultat: valeur * taux,
      tracabilite: `${valeur} ${deviseSource} ÷ ${tauxDuJour[cleInverse]} (taux du jour inversé) = ${(valeur * taux).toFixed(2)} ${deviseCible}`,
    };
  }

  throw new Error(
    `Taux de change introuvable : ${deviseSource} → ${deviseCible}. Passez un taux du jour via le paramètre tauxDuJour.`
  );
}
