export const dynamic = "force-dynamic";
export const maxDuration = 60;

// GET /api/export — export Excel structuré de toutes les données collectées :
// feuille Prix (avec source, fiabilité, notes), feuille Taux de change,
// feuille Sources. Pour analyses personnelles hors plateforme.

import ExcelJS from "exceljs";
import { prisma } from "@/lib/db";

const ENTETE_STYLE: Partial<ExcelJS.Style> = {
  font: { bold: true, color: { argb: "FFFFFFFF" }, size: 11 },
  fill: { type: "pattern", pattern: "solid", fgColor: { argb: "FF003D2E" } },
  alignment: { vertical: "middle" },
};

export async function GET() {
  try {
    const [releves, taux, sources] = await Promise.all([
      prisma.prixReleve.findMany({
        // Export orienté analyse : séries quotidiennes & de référence — on exclut
        // l'intraday (1h/1min) qui, à des centaines de barres/jour, noierait le reste.
        where: { fiabilite: { not: "EXEMPLE" }, typePrix: { notIn: ["SPOT_1H", "SPOT_1MIN"] } },
        orderBy: { dateReleve: "desc" },
        take: 5000,
        include: {
          produit: { select: { code: true, nom: true, filiere: { select: { code: true } } } },
          marche: { select: { code: true, nom: true, devise: true } },
          source: { select: { code: true, nom: true } },
        },
      }),
      prisma.tauxChange.findMany({
        orderBy: { dateReleve: "desc" },
        take: 2000,
      }),
      prisma.source.findMany({ orderBy: { code: "asc" } }),
    ]);

    const wb = new ExcelJS.Workbook();
    wb.creator = "Africa Agro Partners";
    wb.created = new Date();

    // ── Feuille 1 : Prix ────────────────────────────────────────────────────
    const wsPrix = wb.addWorksheet("Prix", { views: [{ state: "frozen", ySplit: 1 }] });
    wsPrix.columns = [
      { header: "Date relevé",   key: "dateReleve",   width: 13 },
      { header: "Filière",       key: "filiere",      width: 9 },
      { header: "Produit",       key: "produit",      width: 26 },
      { header: "Code produit",  key: "produitCode",  width: 14 },
      { header: "Marché",        key: "marche",       width: 30 },
      { header: "Type de prix",  key: "typePrix",     width: 12 },
      { header: "Valeur",        key: "valeur",       width: 14 },
      { header: "Devise",        key: "devise",       width: 8 },
      { header: "Unité",         key: "unite",        width: 9 },
      { header: "Fiabilité",     key: "fiabilite",    width: 11 },
      { header: "Source",        key: "source",       width: 38 },
      { header: "Code source",   key: "sourceCode",   width: 18 },
      { header: "Notes / provenance", key: "notes",   width: 60 },
      { header: "Date collecte", key: "dateCollecte", width: 13 },
    ];
    wsPrix.getRow(1).eachCell((c) => Object.assign(c, { style: ENTETE_STYLE }));
    for (const r of releves) {
      wsPrix.addRow({
        dateReleve: new Date(r.dateReleve),
        filiere: r.produit.filiere.code,
        produit: r.produit.nom,
        produitCode: r.produit.code,
        marche: r.marche.nom,
        typePrix: r.typePrix,
        valeur: Number(r.valeur),
        devise: r.devise,
        unite: r.unite,
        fiabilite: r.fiabilite,
        source: r.source.nom,
        sourceCode: r.source.code,
        notes: r.notes ?? "",
        dateCollecte: new Date(r.dateCollecte),
      });
    }
    wsPrix.getColumn("valeur").numFmt = "#,##0.00";
    wsPrix.getColumn("dateReleve").numFmt = "yyyy-mm-dd";
    wsPrix.getColumn("dateCollecte").numFmt = "yyyy-mm-dd";
    wsPrix.autoFilter = { from: "A1", to: "N1" };

    // ── Feuille 2 : Taux de change ──────────────────────────────────────────
    const wsTaux = wb.addWorksheet("Taux de change", { views: [{ state: "frozen", ySplit: 1 }] });
    wsTaux.columns = [
      { header: "Date relevé", key: "dateReleve", width: 18 },
      { header: "De",          key: "src",        width: 8 },
      { header: "Vers",        key: "dest",       width: 8 },
      { header: "Taux",        key: "taux",       width: 16 },
      { header: "Source",      key: "sourceCode", width: 16 },
    ];
    wsTaux.getRow(1).eachCell((c) => Object.assign(c, { style: ENTETE_STYLE }));
    for (const t of taux) {
      wsTaux.addRow({
        dateReleve: new Date(t.dateReleve),
        src: t.deviseSrc,
        dest: t.deviseDest,
        taux: Number(t.taux),
        sourceCode: t.sourceCode,
      });
    }
    wsTaux.getColumn("taux").numFmt = "#,##0.000000";
    wsTaux.getColumn("dateReleve").numFmt = "yyyy-mm-dd hh:mm";
    wsTaux.autoFilter = { from: "A1", to: "E1" };

    // ── Feuille 3 : Sources ─────────────────────────────────────────────────
    const wsSources = wb.addWorksheet("Sources");
    wsSources.columns = [
      { header: "Code",              key: "code",        width: 20 },
      { header: "Nom",               key: "nom",         width: 45 },
      { header: "Type",              key: "type",        width: 8 },
      { header: "Fiabilité défaut",  key: "fiab",        width: 16 },
      { header: "Fréquence",         key: "freq",        width: 12 },
      { header: "Dernière exécution",key: "derniere",    width: 20 },
      { header: "Statut",            key: "statut",      width: 10 },
      { header: "Description",       key: "description", width: 70 },
    ];
    wsSources.getRow(1).eachCell((c) => Object.assign(c, { style: ENTETE_STYLE }));
    for (const s of sources) {
      wsSources.addRow({
        code: s.code,
        nom: s.nom,
        type: s.type,
        fiab: s.fiabiliteDefaut,
        freq: s.frequence ?? "",
        derniere: s.derniereExecution ? new Date(s.derniereExecution) : "",
        statut: s.statutDernier ?? "",
        description: s.description ?? "",
      });
    }

    const buffer = await wb.xlsx.writeBuffer();
    const dateStr = new Date().toISOString().slice(0, 10);
    return new Response(buffer as ArrayBuffer, {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": `attachment; filename="africa-agro-prix-${dateStr}.xlsx"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (e) {
    return Response.json({ error: e instanceof Error ? e.message : String(e) }, { status: 503 });
  }
}
