import { describe, it, expect } from "vitest";
import {
  calculerVAN,
  calculerTRI,
  calculerPayback,
  calculerPointMort,
  analyserInvestissement,
  analyseScenarios,
  type HypothesesInvestissement,
} from "@/lib/finance";

const BASE: HypothesesInvestissement = {
  capex: 100_000,
  opexFixes: 20_000,
  opexVariables: 5,
  prixUnitaire: 10,
  volumeAnnuel: 10_000,
  dureeAns: 5,
  tauxActualisation: 0.12,
};

describe("calculerVAN", () => {
  it("renvoie la VAN exacte pour des flux simples", () => {
    // -100, +110 sur 1 an à 10% → VAN = -100 + 110/1.1 = 0
    const flux = [-100, 110];
    expect(calculerVAN(flux, 0.1)).toBeCloseTo(0, 4);
  });

  it("VAN négative quand flux insuffisants", () => {
    const flux = [-100_000, 10_000, 10_000, 10_000, 10_000, 10_000];
    const van = calculerVAN(flux, 0.12);
    expect(van).toBeLessThan(0);
  });

  it("VAN positive pour projet rentable", () => {
    const flux = [-100_000, 40_000, 40_000, 40_000, 40_000, 40_000];
    const van = calculerVAN(flux, 0.1);
    expect(van).toBeGreaterThan(0);
  });
});

describe("calculerTRI", () => {
  it("TRI ≈ 10% pour flux -100, +110 sur 1 an", () => {
    const tri = calculerTRI([-100, 110]);
    expect(tri).not.toBeNull();
    expect(tri!).toBeCloseTo(0.1, 3);
  });

  it("TRI null si tous les flux positifs", () => {
    expect(calculerTRI([10, 20, 30])).toBeNull();
  });

  it("TRI null si tous les flux négatifs", () => {
    expect(calculerTRI([-10, -20, -30])).toBeNull();
  });

  it("TRI cohérent avec le cas de base", () => {
    const r = analyserInvestissement(BASE);
    if (r.tri !== null) {
      // Vérifier que VAN au TRI ≈ 0
      const vanAuTRI = calculerVAN(r.fluxNets, r.tri);
      expect(Math.abs(vanAuTRI)).toBeLessThan(1); // < 1 USD d'erreur
    }
  });
});

describe("calculerPayback", () => {
  it("payback = 2 ans pour investissement récupéré en 2 ans", () => {
    const flux = [-100, 60, 60, 30, 30];
    // Après an 1 : cumul -40 ; après an 2 : +20 → payback entre 1 et 2
    const pb = calculerPayback(flux);
    expect(pb).not.toBeNull();
    expect(pb!).toBeGreaterThan(1);
    expect(pb!).toBeLessThan(2);
  });

  it("payback null si jamais récupéré", () => {
    const flux = [-1_000_000, 100, 100, 100];
    expect(calculerPayback(flux)).toBeNull();
  });
});

describe("calculerPointMort", () => {
  it("point mort = opexFixes / margeContrib", () => {
    const pm = calculerPointMort(20_000, 10, 5);
    expect(pm).toBe(4_000); // 20000 / (10-5)
  });

  it("lève une erreur si marge nulle", () => {
    expect(() => calculerPointMort(20_000, 5, 5)).toThrow();
  });

  it("lève une erreur si marge négative", () => {
    expect(() => calculerPointMort(20_000, 4, 5)).toThrow();
  });
});

describe("analyserInvestissement (cas de base)", () => {
  it("retourne les bons champs", () => {
    const r = analyserInvestissement(BASE);
    expect(r).toHaveProperty("van");
    expect(r).toHaveProperty("tri");
    expect(r).toHaveProperty("paybackAns");
    expect(r).toHaveProperty("pointMortUnites");
    expect(r).toHaveProperty("fluxNets");
    expect(r.fluxNets).toHaveLength(BASE.dureeAns + 1);
  });

  it("le premier flux = -CAPEX", () => {
    const r = analyserInvestissement(BASE);
    expect(r.fluxNets[0]).toBe(-BASE.capex);
  });

  it("point mort cohérent avec les hypothèses de base", () => {
    const r = analyserInvestissement(BASE);
    // opexFixes=20000, margeContrib=10-5=5 → PM=4000
    expect(r.pointMortUnites).toBeCloseTo(4_000, 0);
  });
});

describe("analyseScenarios", () => {
  it("retourne 3 scénarios nommés", () => {
    const scenarios = analyseScenarios(BASE, [
      { nom: "bas", params: { variationPrixPct: -20, variationCoutVariablePct: 10 } },
      { nom: "central", params: { variationPrixPct: 0, variationCoutVariablePct: 0 } },
      { nom: "haut", params: { variationPrixPct: 20, variationCoutVariablePct: -10 } },
    ]);
    expect(scenarios).toHaveLength(3);
    expect(scenarios[0].nom).toBe("bas");
    expect(scenarios[2].nom).toBe("haut");
    // Scénario haut doit avoir VAN > scénario bas
    expect(scenarios[2].resultats.van).toBeGreaterThan(scenarios[0].resultats.van);
  });
});
