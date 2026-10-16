#!/usr/bin/env python3
"""Construit les livrables A, B, C, E, F, G, H à partir des seules preuves
présentes dans preuves/brut/ et des saisies manuelles documentées.

Règles appliquées (aucune exception) :
- pas d'interpolation, pas de report du cours précédent, pas de volume
  inconnu remplacé par zéro, pas de montant = Close x Volume ;
- une observation n'entre dans la série validée (B) que si sa date est une
  séance établie par un bulletin officiel (calendrier_officiel_saisie.csv),
  si ses valeurs passent les contrôles et si aucune contradiction entre
  sources n'est non résolue ;
- les originaux de preuves/brut/ ne sont jamais modifiés.

Saisies manuelles attendues (en-têtes fournis, vides tant qu'aucun
document n'a été lu) :
- saisies/calendrier_officiel_saisie.csv :
    Date,statut_seance,reference,fichier_preuve,page
    statut_seance ∈ {SEANCE, FERMETURE, SEANCE_EXCEPTIONNELLE}
- saisies/bulletins_slbc_saisie.csv (lecture des bulletins PDF) :
    Date,statut_titre,Close,Volume,Montant_negocie,fichier_preuve,page,numero_bulletin
    statut_titre ∈ {TRANSACTION, SANS_TRANSACTION, SUSPENDU}
- saisies/bulletins_composite_saisie.csv :
    Date,Close,fichier_preuve,page,numero_bulletin
- saisies/decisions_contradictions.csv :
    Date,serie,valeur_retenue_close,valeur_retenue_volume,justification,reference
"""
import csv
import datetime as dt
import glob
import hashlib
import json
import os

import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
BRUT = os.path.join(ICI, "preuves", "brut")
SAIS = os.path.join(ICI, "saisies")
JOURNAL_COLLECTE = os.path.join(ICI, "preuves", "COLLECTE_TENTATIVES.csv")
DEBUT, FIN = "2025-01-01", "2026-10-09"

COLS_BRUT = ["Date", "Close", "Volume", "Montant_negocie", "statut_titre", "fournisseur",
             "url", "fichier_source", "ligne_ou_page", "sha256_fichier",
             "date_recuperation", "valeur_originale_texte"]
COLS_PROV = ["Date", "Close", "Volume", "fournisseur", "url", "fichier_source",
             "ligne_ou_page", "date_recuperation", "sha256_fichier", "statut_controle"]
COLS_PROV_IDX = ["Date", "Close", "fournisseur", "url", "fichier_source",
                 "ligne_ou_page", "date_recuperation", "sha256_fichier", "statut_controle"]
COLS_AUDIT = ["id", "Date", "serie", "champ", "valeur_initiale", "valeur_retenue",
              "type_operation", "justification", "reference", "statut_resolution"]

SAISIES = {
    "calendrier_officiel_saisie.csv": "Date,statut_seance,reference,fichier_preuve,page",
    "bulletins_slbc_saisie.csv": "Date,statut_titre,Close,Volume,Montant_negocie,fichier_preuve,page,numero_bulletin",
    "bulletins_composite_saisie.csv": "Date,Close,fichier_preuve,page,numero_bulletin",
    "decisions_contradictions.csv": "Date,serie,valeur_retenue_close,valeur_retenue_volume,justification,reference",
}


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def journal_collecte():
    if os.path.exists(JOURNAL_COLLECTE):
        return pd.read_csv(JOURNAL_COLLECTE, dtype=str).fillna("")
    return pd.DataFrame(columns=["fichier", "url", "horodatage_utc"])


def lire_saisie(nom):
    p = os.path.join(SAIS, nom)
    if not os.path.exists(p):
        os.makedirs(SAIS, exist_ok=True)
        open(p, "w", encoding="utf-8").write(SAISIES[nom] + "\n")
    return pd.read_csv(p, dtype=str).fillna("")


def parse_date_fr(s):
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s[:19] if "T" in s else s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def lire_sika(jc):
    """Lit les JSON Sika bruts. Échoue explicitement si la structure diffère."""
    lignes, anomalies = [], []
    for f in sorted(glob.glob(os.path.join(BRUT, "sika_*.json"))):
        rel = os.path.relpath(f, ICI)
        meta = jc[jc.fichier == rel]
        url = meta.url.iloc[-1] if len(meta) else ""
        quand = meta.horodatage_utc.iloc[-1] if len(meta) else ""
        serie = "BRVM_COMPOSITE" if "BRVMC" in os.path.basename(f) else "SLBC.CI"
        try:
            d = json.load(open(f, encoding="utf-8"))
            lst = d["lst"]
        except Exception as e:
            anomalies.append((rel, f"structure JSON non reconnue : {type(e).__name__} {e}"))
            continue
        for i, r in enumerate(lst):
            manquants = [k for k in ("Date", "Close") if k not in r]
            if manquants:
                anomalies.append((rel, f"élément {i} sans champs {manquants}"))
                continue
            lignes.append({
                "serie": serie, "Date": parse_date_fr(r["Date"]), "Date_texte": r["Date"],
                "Close": r.get("Close"), "Volume": r.get("Volume"),
                "Montant_negocie": "",  # non fourni : jamais déduit de Close x Volume
                "statut_titre": "", "fournisseur": "sikafinance", "url": url,
                "fichier_source": rel, "ligne_ou_page": f"lst[{i}]",
                "sha256_fichier": sha(f), "date_recuperation": quand,
                "valeur_originale_texte": json.dumps(r, ensure_ascii=False),
            })
    return lignes, anomalies


def lire_ilboursa(jc):
    """Lit un fichier Ilboursa seulement s'il s'agit d'un CSV aux colonnes reconnues."""
    lignes, anomalies = [], []
    for f in sorted(glob.glob(os.path.join(BRUT, "ilboursa_*.bin"))):
        rel = os.path.relpath(f, ICI)
        meta = jc[jc.fichier == rel]
        try:
            df = pd.read_csv(f, sep=None, engine="python", dtype=str)
        except Exception as e:
            anomalies.append((rel, f"format non lisible comme CSV : {e}"))
            continue
        cols = {c.lower().strip(): c for c in df.columns}
        cd = next((cols[c] for c in ("date", "séance", "seance") if c in cols), None)
        cc = next((cols[c] for c in ("close", "clôture", "cloture", "dernier") if c in cols), None)
        cv = next((cols[c] for c in ("volume", "vol", "quantité", "quantite") if c in cols), None)
        if not (cd and cc):
            anomalies.append((rel, f"colonnes non reconnues : {list(df.columns)}"))
            continue
        for i, r in df.iterrows():
            lignes.append({
                "serie": "SLBC.CI", "Date": parse_date_fr(r[cd]), "Date_texte": r[cd],
                "Close": r[cc], "Volume": r[cv] if cv else "", "Montant_negocie": "",
                "statut_titre": "", "fournisseur": "ilboursa",
                "url": meta.url.iloc[-1] if len(meta) else "", "fichier_source": rel,
                "ligne_ou_page": f"ligne {i + 2}", "sha256_fichier": sha(f),
                "date_recuperation": meta.horodatage_utc.iloc[-1] if len(meta) else "",
                "valeur_originale_texte": json.dumps(r.to_dict(), ensure_ascii=False),
            })
    return lignes, anomalies


def lire_bulletins():
    out = []
    for _, r in lire_saisie("bulletins_slbc_saisie.csv").iterrows():
        out.append({"serie": "SLBC.CI", "Date": parse_date_fr(r.Date), "Date_texte": r.Date,
                    "Close": r.Close, "Volume": r.Volume, "Montant_negocie": r.Montant_negocie,
                    "statut_titre": r.statut_titre, "fournisseur": "brvm.org (bulletin officiel)",
                    "url": "", "fichier_source": r.fichier_preuve,
                    "ligne_ou_page": f"page {r.page} / BOC n°{r.numero_bulletin}",
                    "sha256_fichier": sha(os.path.join(ICI, r.fichier_preuve)) if r.fichier_preuve and os.path.exists(os.path.join(ICI, r.fichier_preuve)) else "",
                    "date_recuperation": "", "valeur_originale_texte": ""})
    for _, r in lire_saisie("bulletins_composite_saisie.csv").iterrows():
        out.append({"serie": "BRVM_COMPOSITE", "Date": parse_date_fr(r.Date), "Date_texte": r.Date,
                    "Close": r.Close, "Volume": "", "Montant_negocie": "", "statut_titre": "",
                    "fournisseur": "brvm.org (bulletin officiel)", "url": "",
                    "fichier_source": r.fichier_preuve,
                    "ligne_ou_page": f"page {r.page} / BOC n°{r.numero_bulletin}",
                    "sha256_fichier": "", "date_recuperation": "", "valeur_originale_texte": ""})
    return out


def num_pos(x):
    try:
        v = float(str(x).replace(" ", "").replace(" ", "").replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def entier_nn(x):
    s = str(x).replace(" ", "").replace(" ", "")
    if s == "":
        return None
    try:
        v = float(s.replace(",", "."))
    except ValueError:
        return None
    return int(v) if v >= 0 and v == int(v) else None


def main():
    jc = journal_collecte()
    audit = []

    def log(**k):
        k.setdefault("id", f"A{len(audit) + 1:04d}")
        audit.append(k)

    obs, anom = [], []
    for fn in (lire_sika, lire_ilboursa):
        l, a = fn(jc)
        obs += l
        anom += a
    obs += lire_bulletins()
    for rel, msg in anom:
        log(Date="", serie="", champ="fichier", valeur_initiale=rel, valeur_retenue="",
            type_operation="exclusion", justification=msg, reference=rel,
            statut_resolution="NON RÉSOLU")

    df = pd.DataFrame(obs, columns=["serie", "Date_texte"] + COLS_BRUT)
    cal = lire_saisie("calendrier_officiel_saisie.csv")
    cal["Date"] = cal.Date.map(parse_date_fr)
    seances = set(cal.loc[cal.statut_seance.isin(["SEANCE", "SEANCE_EXCEPTIONNELLE"]), "Date"])
    fermes = set(cal.loc[cal.statut_seance == "FERMETURE", "Date"])
    decisions = lire_saisie("decisions_contradictions.csv")

    # Contrôles par observation
    statuts = []
    for _, r in df.iterrows():
        pb = []
        if not r.Date:
            pb.append("date illisible")
        elif not (DEBUT <= r.Date <= FIN):
            pb.append("hors période")
        elif r.Date in fermes:
            pb.append("date = fermeture officielle")
        elif r.Date not in seances:
            pb.append("séance non établie par bulletin")
        if r.statut_titre not in ("SANS_TRANSACTION", "SUSPENDU") and num_pos(r.Close) is None:
            pb.append("cours non numérique ou non strictement positif")
        if r.serie == "SLBC.CI" and r.statut_titre not in ("SANS_TRANSACTION", "SUSPENDU") \
                and entier_nn(r.Volume) is None:
            pb.append("volume absent, non entier ou négatif")
        statuts.append("OK" if not pb else "; ".join(pb))
    df["statut_controle"] = statuts

    # Contradictions entre sources pour une même date et série
    valid = {"SLBC.CI": {}, "BRVM_COMPOSITE": {}}
    for (serie, date), g in df[df.Date.notna()].groupby(["serie", "Date"]):
        g_ok = g[g.statut_controle == "OK"]
        vals = {(num_pos(r.Close), entier_nn(r.Volume) if serie == "SLBC.CI" else None)
                for _, r in g_ok.iterrows()}
        if len(vals) == 1:
            valid[serie][date] = next(iter(vals))
            continue
        if len(vals) > 1:
            dec = decisions[(decisions.Date == date) & (decisions.serie == serie)]
            detail = " | ".join(f"{r.fournisseur}: Close={r.Close} Volume={r.Volume} ({r.fichier_source} {r.ligne_ou_page})"
                                for _, r in g_ok.iterrows())
            if len(dec):
                d0 = dec.iloc[0]
                vr = (num_pos(d0.valeur_retenue_close),
                      entier_nn(d0.valeur_retenue_volume) if serie == "SLBC.CI" else None)
                valid[serie][date] = vr
                log(Date=date, serie=serie, champ="Close/Volume", valeur_initiale=detail,
                    valeur_retenue=f"{vr[0]}/{vr[1]}", type_operation="correction",
                    justification=d0.justification, reference=d0.reference,
                    statut_resolution="RÉSOLU")
            else:
                df.loc[g_ok.index, "statut_controle"] = "contradiction non résolue"
                log(Date=date, serie=serie, champ="Close/Volume", valeur_initiale=detail,
                    valeur_retenue="", type_operation="exclusion",
                    justification="valeurs divergentes entre sources, aucune preuve décisive",
                    reference="", statut_resolution="NON RÉSOLU")
    for _, r in df[(df.statut_controle != "OK") & (df.statut_controle != "contradiction non résolue")].iterrows():
        log(Date=r.Date or r.Date_texte, serie=r.serie, champ="observation",
            valeur_initiale=f"Close={r.Close} Volume={r.Volume}", valeur_retenue="",
            type_operation="exclusion", justification=r.statut_controle,
            reference=f"{r.fichier_source} {r.ligne_ou_page}", statut_resolution="NON RÉSOLU")

    # A. brut (SLBC uniquement, toutes observations, sans correction)
    a = df[df.serie == "SLBC.CI"][COLS_BRUT + ["statut_controle"]]
    a.to_csv(os.path.join(ICI, "SOLIBRA_SLBC_2025_2026_BRUT.csv"), index=False)

    # B. série validée : séances avec transaction uniquement
    b = sorted((d, c, v) for d, (c, v) in valid["SLBC.CI"].items() if c is not None and v is not None)
    with open(os.path.join(ICI, "SOLIBRA_SLBC_2025_2026_QUOTIDIEN.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Close", "Volume"])
        w.writerows([(d, repr(c) if c != int(c) else int(c), v) for d, c, v in b])

    # C. indice validé
    c = sorted((d, cl) for d, (cl, _) in valid["BRVM_COMPOSITE"].items() if cl is not None)
    with open(os.path.join(ICI, "BRVM_COMPOSITE_2025_2026.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Close"])
        w.writerows(c)

    # E/F. provenance
    df[df.serie == "SLBC.CI"][COLS_PROV].to_csv(os.path.join(ICI, "PROVENANCE_SOLIBRA.csv"), index=False)
    df[df.serie == "BRVM_COMPOSITE"][COLS_PROV_IDX].to_csv(
        os.path.join(ICI, "PROVENANCE_BRVM_COMPOSITE.csv"), index=False)

    # H. calendrier et couverture
    jours = pd.date_range(DEBUT, FIN, freq="D")
    rows = []
    calm = cal.set_index("Date") if len(cal) else None
    slbc_stat = {r.Date: r.statut_titre for _, r in df[(df.serie == "SLBC.CI") & (df.fournisseur.str.startswith("brvm"))].iterrows()}
    for j in jours:
        d = j.date().isoformat()
        if calm is not None and d in calm.index:
            st, ref = calm.loc[d, "statut_seance"], calm.loc[d, "reference"]
        else:
            st, ref = "NON ÉTABLI", ""
        def dispo(serie):
            if st == "FERMETURE":
                return "JOUR SANS SÉANCE"
            if d in valid[serie]:
                return "DISPONIBLE"
            if serie == "SLBC.CI" and slbc_stat.get(d) == "SANS_TRANSACTION":
                return "SÉANCE SANS TRANSACTION"
            if serie == "SLBC.CI" and slbc_stat.get(d) == "SUSPENDU":
                return "TITRE SUSPENDU"
            sub = df[(df.serie == serie) & (df.Date == d)]
            if len(sub):
                return "EXCLU (" + "; ".join(sorted(set(sub.statut_controle))) + ")"
            return "NON RÉCUPÉRÉ"
        rows.append({"Date": d, "jour_semaine": j.day_name(),
                     "lundi_vendredi": j.weekday() < 5, "statut_seance_officiel": st,
                     "reference_officielle": ref, "SLBC_statut": dispo("SLBC.CI"),
                     "COMPOSITE_statut": dispo("BRVM_COMPOSITE"),
                     "motif_absence": "" if st not in ("NON ÉTABLI",) else
                     "aucun bulletin/avis BRVM récupéré (accès réseau refusé, voir COLLECTE_TENTATIVES.csv)"})
    pd.DataFrame(rows).to_csv(os.path.join(ICI, "CALENDRIER_ET_COUVERTURE.csv"), index=False)

    # G. journal d'audit : constats documentaires fixes + journal calculé
    fixes = pd.read_csv(os.path.join(SAIS, "constats_audit_documentaires.csv"), dtype=str).fillna("")
    calc = pd.DataFrame(audit, columns=COLS_AUDIT)
    calc["id"] = [f"C{i + 1:04d}" for i in range(len(calc))]
    pd.concat([fixes, calc], ignore_index=True)[COLS_AUDIT].to_csv(
        os.path.join(ICI, "JOURNAL_AUDIT.csv"), index=False)
    print(f"observations brutes={len(df)} validées SLBC={len(b)} indice={len(c)} "
          f"anomalies fichiers={len(anom)} entrées audit calculées={len(calc)}")


if __name__ == "__main__":
    main()
