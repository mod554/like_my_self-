#!/usr/bin/env python3
"""Relit les livrables SOLIBRA 2023-2026 avec pandas et zipfile, et affiche les contrôles.
Ne modifie aucun fichier. Usage : python3 verifier_livrables.py [dossier_ou_zip]"""
import io
import os
import sys
import zipfile

import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
cible = sys.argv[1] if len(sys.argv) > 1 else ICI


def lire(nom):
    if cible.endswith(".zip"):
        z = zipfile.ZipFile(cible)
        assert z.testzip() is None, "ZIP corrompu"
        membre = [n for n in z.namelist() if n.endswith(nom)][0]
        return pd.read_csv(io.BytesIO(z.read(membre)), dtype=str, keep_default_na=False)
    return pd.read_csv(os.path.join(cible, nom), dtype=str, keep_default_na=False)


a = lire("SOLIBRA_SLBC_2023_2026_ANALYSE.csv")
assert list(a.columns) == ["Date", "Close", "Volume"], list(a.columns)
a["d"] = pd.to_datetime(a.Date, format="%Y-%m-%d", errors="raise")
a["C"] = pd.to_numeric(a.Close, errors="raise")
a["V"] = pd.to_numeric(a.Volume, errors="raise")
print("== ANALYSE : Date,Close,Volume")
print("effectif :", len(a), "| dates extrêmes :", a.d.min().date(), "->", a.d.max().date())
print("effectif annuel :", a.groupby(a.d.dt.year).size().to_dict())
print("effectif trimestriel :", a.groupby(a.d.dt.to_period("Q")).size().astype(int).to_dict())
print("doublons de date :", int(a.d.duplicated().sum()), "| valeurs manquantes :", int(a[["Date", "Close", "Volume"]].eq("").sum().sum()))
print("cours <= 0 :", int((a.C <= 0).sum()), "| volumes négatifs :", int((a.V < 0).sum()), "| volumes nuls :", int((a.V == 0).sum()))
print("week-ends :", int((a.d.dt.weekday >= 5).sum()), "| dans la suspension 02/04/2024-10/09/2024 :",
      int(((a.d >= "2024-04-02") & (a.d <= "2024-09-10")).sum()))
print("15/10/2026 présent :", "2026-10-15" in set(a.Date), "(exclu : clôture provisoire contredite)")
print("cours 26/09, 30/09, 08/10/2024 :", a.set_index("d").C.reindex(pd.to_datetime(["2024-09-26", "2024-09-30", "2024-10-08"])).tolist(),
      "(pas de division par 10 visible)")
print("variation journalière absolue max :", round(a.C.pct_change().abs().max() * 100, 2), "%")

print("\n== BRUT")
b = lire("SOLIBRA_SLBC_2023_2026_BRUT.csv")
print("lignes :", len(b), "| statuts :", b.statut_analyse.str.split(":").str[0].str.strip().value_counts().to_dict())

print("\n== CALENDRIER")
c = lire("CALENDRIER_COUVERTURE_2023_2026.csv")
print("jours calendaires :", len(c), "| jours ouvrés :", int((c.jour_ouvre == "True").sum()))
print("statuts :", c.statut.str.split(" ").str[0].value_counts().to_dict())

print("\n== JOURNAL")
j = lire("JOURNAL_CORRECTIONS_EXCLUSIONS.csv")
print("entrées :", len(j), "| opérations :", j.operation.value_counts().to_dict())
print("non résolues :", int(j.statut_resolution.str.startswith("NON").sum()))

print("\n== DIVIDENDES")
print(lire("SOLIBRA_DIVIDENDES_2023_2026.csv")[["exercice", "dividende_brut_FCFA_par_action",
      "dividende_net_FCFA_par_action", "date_detachement", "date_paiement", "anomalies_dates"]].to_string(index=False))

print("\n== CONCORDANCE AVEC LES COURS DE RÉFÉRENCE BRVM (dividendes.json)")
for d, ref in [("2024-06-03", 8325), ("2025-07-24", 19320), ("2026-07-28", 39500)]:
    v = a.set_index("d").C.get(pd.Timestamp(d))
    print(d, "CSV =", v, "| référence BRVM =", ref, "| concordant :", v == ref if v is not None else "ligne absente")
