#!/usr/bin/env python3
"""Lecture et contrôle reproductibles des livrables SOLIBRA / BRVM Composite.

Colab :
    !python audit_et_chargement_colab.py /content/BASE_ANALYSE_SOLIBRA_BRVM_2025_2026.zip
ou, dans un dossier décompressé :
    python audit_et_chargement_colab.py .

Le script n'altère aucun fichier. Il affiche les contrôles de la section 7
et se termine avec un code non nul si un contrôle de format échoue.
Il ne complète, n'interpole ni ne supprime aucune date.
"""
import os
import sys
import tempfile
import zipfile

import pandas as pd

FICHIERS = {
    "brut": "SOLIBRA_SLBC_2025_2026_BRUT.csv",
    "slbc": "SOLIBRA_SLBC_2025_2026_QUOTIDIEN.csv",
    "idx": "BRVM_COMPOSITE_2025_2026.csv",
    "div": "SOLIBRA_DIVIDENDES_2025_2026.csv",
    "prov_s": "PROVENANCE_SOLIBRA.csv",
    "prov_i": "PROVENANCE_BRVM_COMPOSITE.csv",
    "audit": "JOURNAL_AUDIT.csv",
    "cal": "CALENDRIER_ET_COUVERTURE.csv",
}
DEBUT, FIN = "2025-01-01", "2026-10-09"
echecs = []


def titre(t):
    print(f"\n=== {t} ===")


def verifier_zip(chemin):
    titre(f"ZIP {chemin}")
    with zipfile.ZipFile(chemin) as z:
        mauvais = z.testzip()
        print("membres :", len(z.namelist()))
        print("testzip :", "OK" if mauvais is None else f"ÉCHEC sur {mauvais}")
        if mauvais is not None:
            echecs.append("zip corrompu")
        d = tempfile.mkdtemp()
        z.extractall(d)
    racines = {os.path.dirname(n) for n in z.namelist() if n.endswith(FICHIERS["slbc"])}
    return os.path.join(d, sorted(racines)[0]) if racines else d


def charger(rep):
    out = {}
    for k, f in FICHIERS.items():
        p = os.path.join(rep, f)
        if not os.path.exists(p):
            echecs.append(f"fichier manquant : {f}")
            continue
        out[k] = pd.read_csv(p, dtype=str, keep_default_na=False)
    return out


def format_strict(df, colonnes, nom):
    if list(df.columns) != colonnes:
        echecs.append(f"{nom} : colonnes {list(df.columns)} != {colonnes}")
        print(f"{nom} : colonnes NON conformes : {list(df.columns)}")
        return None
    d = pd.to_datetime(df.Date, format="%Y-%m-%d", errors="coerce")
    if d.isna().any():
        echecs.append(f"{nom} : dates non AAAA-MM-JJ")
    c = pd.to_numeric(df.Close, errors="coerce")
    if c.isna().any() or (c <= 0).any() or df.Close.str.contains(",").any():
        echecs.append(f"{nom} : Close non numérique, <= 0 ou à virgule décimale")
    out = pd.DataFrame({"Date": d, "Close": c})
    if "Volume" in colonnes:
        v = pd.to_numeric(df.Volume, errors="coerce")
        if v.isna().any() or (v < 0).any() or (v % 1 != 0).any():
            echecs.append(f"{nom} : Volume non entier ou négatif")
        out["Volume"] = v
    return out


def decrire(s, nom, cal):
    titre(nom)
    print("effectif :", len(s))
    if len(s) == 0:
        print("AUCUNE OBSERVATION VALIDÉE")
        return
    print("dates extrêmes :", s.Date.min().date(), "->", s.Date.max().date())
    print("doublons de date :", int(s.Date.duplicated().sum()))
    print("valeurs manquantes :", s.isna().sum().to_dict())
    print("par année :", s.groupby(s.Date.dt.year).size().to_dict())
    print("par trimestre :", s.groupby(s.Date.dt.to_period("Q")).size().astype(int).to_dict())
    hors = s[(s.Date < DEBUT) | (s.Date > FIN)]
    print("hors période :", len(hors))
    if cal is not None:
        etab = set(cal.loc[cal.statut_seance_officiel.isin(["SEANCE", "SEANCE_EXCEPTIONNELLE"]), "Date"])
        hs = s[~s.Date.dt.strftime("%Y-%m-%d").isin(etab)]
        print("dates hors séances établies :", len(hs), list(hs.Date.dt.date[:10]))
    if "Volume" in s:
        print("volumes nuls :", int((s.Volume == 0).sum()))
    r = s.Close.pct_change()
    print("plus fortes variations absolues entre observations consécutives (non corrigées) :")
    print(s.assign(variation=r).reindex(r.abs().sort_values(ascending=False).index).head(5).to_string(index=False))


def main(arg):
    rep = verifier_zip(arg) if arg.endswith(".zip") else arg
    t = charger(rep)
    cal = t.get("cal")
    slbc = format_strict(t["slbc"], ["Date", "Close", "Volume"], "QUOTIDIEN") if "slbc" in t else None
    idx = format_strict(t["idx"], ["Date", "Close"], "COMPOSITE") if "idx" in t else None
    if slbc is not None:
        decrire(slbc, "SOLIBRA validé", cal)
    if idx is not None:
        decrire(idx, "BRVM Composite validé", cal)

    if "brut" in t:
        titre("Données brutes SOLIBRA")
        b = t["brut"]
        print("effectif :", len(b))
        if len(b):
            print("par fournisseur :", b.fournisseur.value_counts().to_dict())
            print("statut de contrôle :", b.statut_controle.value_counts().to_dict())
            print("doublons (Date, fournisseur) :", int(b.duplicated(["Date", "fournisseur"]).sum()))

    if "audit" in t:
        titre("Journal d'audit")
        a = t["audit"]
        print("par type :", a.type_operation.value_counts().to_dict())
        print("ajouts :", int((a.type_operation == "ajout").sum()),
              "| corrections :", int((a.type_operation == "correction").sum()),
              "| exclusions :", int((a.type_operation == "exclusion").sum()))
        nr = a[a.statut_resolution == "NON RÉSOLU"]
        print("non résolus :", len(nr))
        print("contradictions non résolues :",
              int(nr.justification.str.contains("divergentes").sum()))

    if cal is not None:
        titre("Calendrier et couverture")
        print("jours calendaires :", len(cal))
        print("statut officiel des jours :", cal.statut_seance_officiel.value_counts().to_dict())
        print("SLBC :", cal.SLBC_statut.value_counts().to_dict())
        print("Composite :", cal.COMPOSITE_statut.value_counts().to_dict())
        etab = cal.statut_seance_officiel.isin(["SEANCE", "SEANCE_EXCEPTIONNELLE"])
        n = int(etab.sum())
        if n:
            for col in ("SLBC_statut", "COMPOSITE_statut"):
                k = int((cal.loc[etab, col] == "DISPONIBLE").sum())
                print(f"couverture {col} : {k}/{n} = {k / n:.1%} des séances établies")
        else:
            print("couverture : non calculable (aucune séance établie par bulletin officiel)")

    if slbc is not None and idx is not None:
        titre("Rapprochement SOLIBRA / indice (jointure externe, rien n'est supprimé)")
        m = slbc.merge(idx, on="Date", how="outer", suffixes=("_SLBC", "_IDX"), indicator=True)
        print(m["_merge"].map({"both": "communes", "left_only": "SLBC seul",
                                "right_only": "indice seul"}).value_counts().to_dict())
        print(m[m["_merge"] != "both"].Date.dt.date.tolist()[:50])

    if "div" in t:
        titre("Dividendes")
        print(t["div"][["exercice", "montant_brut_par_action_FCFA", "date_detachement",
                        "date_paiement", "statut_verification"]].to_string(index=False))

    titre("Bilan des contrôles de format")
    print("OK" if not echecs else "\n".join(echecs))
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
