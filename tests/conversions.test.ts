import { describe, it, expect } from "vitest";
import { convertirUnite, convertirDevise } from "@/lib/conversions";

describe("convertirUnite", () => {
  it("même unité → facteur 1", () => {
    const r = convertirUnite(100, "tonne", "tonne");
    expect(r.facteur).toBe(1);
    expect(r.resultat).toBe(100);
  });

  it("1 tonne = 1000 kg", () => {
    const r = convertirUnite(1, "tonne", "kg");
    expect(r.resultat).toBeCloseTo(1000, 0);
  });

  it("1 tonne maïs ≈ 39.37 bushels", () => {
    const r = convertirUnite(1, "tonne", "bushel_mais");
    expect(r.resultat).toBeCloseTo(39.368, 1);
  });

  it("25.4 kg = 1 bushel maïs", () => {
    const r = convertirUnite(1, "bushel_mais", "kg");
    expect(r.resultat).toBeCloseTo(25.4012, 2);
  });

  it("lève une erreur pour conversion inconnue", () => {
    expect(() => convertirUnite(1, "bushel", "litre")).toThrow();
  });

  it("la tracabilité contient les unités", () => {
    const r = convertirUnite(5, "tonne", "kg");
    expect(r.tracabilite).toContain("tonne");
    expect(r.tracabilite).toContain("kg");
  });
});

describe("convertirDevise", () => {
  it("même devise → résultat identique", () => {
    const r = convertirDevise(100, "USD", "USD");
    expect(r.resultat).toBe(100);
    expect(r.taux).toBe(1);
  });

  it("1 EUR = 655.957 XOF (taux légal fixe)", () => {
    const r = convertirDevise(1, "EUR", "XOF");
    expect(r.resultat).toBeCloseTo(655.957, 2);
    expect(r.sourcesTaux).toContain("fixe légal");
  });

  it("655.957 XOF = 1 EUR", () => {
    const r = convertirDevise(655.957, "XOF", "EUR");
    expect(r.resultat).toBeCloseTo(1, 4);
  });

  it("conversion USD/EUR avec taux du jour", () => {
    const tauxDuJour = { USD_EUR: 0.92 };
    const r = convertirDevise(100, "USD", "EUR", tauxDuJour);
    expect(r.resultat).toBeCloseTo(92, 2);
  });

  it("lève une erreur sans taux du jour pour USD/NGN", () => {
    expect(() => convertirDevise(100, "USD", "NGN")).toThrow();
  });

  it("la tracabilité contient les devises et le taux", () => {
    const r = convertirDevise(100, "EUR", "XOF");
    expect(r.tracabilite).toContain("EUR");
    expect(r.tracabilite).toContain("XOF");
    expect(r.tracabilite).toContain("655");
  });
});
