#!/usr/bin/env python3
"""Construit les livrables SOLIBRA (SLBC.CI) 2023-01-01 -> 2026-10-15 à partir des
seules preuves présentes (preuves/brut/, fournis/) et des saisies documentées
(saisies/). Les originaux ne sont jamais modifiés.

Règles :
- aucune interpolation, aucun report, aucun volume inconnu remplacé par zéro ;
- aucune ligne ajoutée pour compléter le calendrier ;
- un fichier fourni (fournis/) n'est jamais une preuve de sa propre validité :
  il est lu, tracé et comparé, mais ne suffit pas à retenir une observation ;
- ANALYSE contient les cours tels que cotés (NON ajustés du fractionnement).
  Une observation d'une source dont la base d'ajustement est « OUI » ou
  « INCONNU » n'est retenue que pour les dates postérieures ou égales à la date
  d'effet du fractionnement confirmée par avis officiel ; sans cette
  confirmation, seules les sources déclarées « NON » sont retenues ;
- la série ajustée (fichier séparé) n'est produite que si le fractionnement
  est confirmé par un avis officiel saisi dans saisies/evenements_officiels.csv ;
- avec EXIGER_CALENDRIER_OFFICIEL=True (défaut), une date n'est retenue que si
  un bulletin officiel l'établit comme séance.
"""
import datetime as dt
import glob
import hashlib
import json
import os
import sys

import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
BRUT = os.path.join(ICI, "preuves", "brut")
FOURNIS = os.path.join(ICI, "fournis")
SAIS = os.path.join(ICI, "saisies")
JOURNAL_COLLECTE = os.path.join(ICI, "preuves", "COLLECTE_TENTATIVES.csv")
DEBUT, FIN = "2023-01-01", "2026-10-15"
EXIGER_CALENDRIER_OFFICIEL = True

SAISIES = {
    "calendrier_officiel_saisie.csv": "Date,statut_seance,reference,fichier_preuve,page",
    "bulletins_slbc_saisie.csv": "Date,statut_titre,Close,Volume,fichier_preuve,page,numero_bulletin",
    "decisions_contradictions.csv": "Date,valeur_retenue_close,valeur_retenue_volume,justification,reference",
    "evenements_officiels.csv": "type,date_debut,date_fin,ratio_nouvelles_pour_une,reference_avis,fichier_preuve,page,statut",
    "base_ajustement_sources.csv": "fournisseur,ajuste_fractionnement,preuve",
}
COLS_BRUT = ["Date", "Close", "Volume", "statut_titre", "fournisseur", "url", "fichier_source",
             "ligne_ou_page", "sha256_fichier", "date_recuperation", "base_ajustement",
             "valeur_originale_texte", "statut_controle"]
COLS_PROV = ["Date", "Close", "Volume", "fournisseur", "url", "fichier_source", "ligne_ou_page",
             "sha256_fichier", "date_recuperation", "base_ajustement", "statut_controle"]
COLS_JOURNAL = ["id", "Date", "champ", "valeur_initiale", "valeur_retenue", "operation",
                "justification", "reference", "statut_resolution"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def saisie(nom):
    p = os.path.join(SAIS, nom)
    if not os.path.exists(p):
        os.makedirs(SAIS, exist_ok=True)
        open(p, "w", encoding="utf-8").write(SAISIES[nom] + "\n")
    return pd.read_csv(p, dtype=str).fillna("")


def date_iso(s):
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def nombre(x):
    s = str(x).strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if s == "":
        return None
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def meta_collecte():
    if os.path.exists(JOURNAL_COLLECTE):
        return pd.read_csv(JOURNAL_COLLECTE, dtype=str).fillna("")
    return pd.DataFrame(columns=["fichier", "url", "horodatage_utc", "periode_debut", "periode_fin",
                                 "source", "resultat", "erreur_observee"])


def ligne(fournisseur, date_txt, close, volume, url, rel, pos, quand, orig, statut_titre=""):
    return {"Date": date_iso(date_txt), "Date_texte": date_txt, "Close": close, "Volume": volume,
            "statut_titre": statut_titre, "fournisseur": fournisseur, "url": url,
            "fichier_source": rel, "ligne_ou_page": pos,
            "sha256_fichier": sha(os.path.join(ICI, rel)) if rel and os.path.exists(os.path.join(ICI, rel)) else "",
            "date_recuperation": quand, "valeur_originale_texte": orig}


def lire_csv_generique(chemin, fournisseur, url, quand, anomalies):
    rel = os.path.relpath(chemin, ICI)
    try:
        df = pd.read_csv(chemin, sep=None, engine="python", dtype=str)
    except Exception as e:
        anomalies.append((rel, f"illisible comme CSV : {type(e).__name__}"))
        return []
    cols = {c.lower().strip(): c for c in df.columns}
    cd = next((cols[c] for c in ("date", "séance", "seance") if c in cols), None)
    cc = next((cols[c] for c in ("close", "clôture", "cloture", "dernier", "cours") if c in cols), None)
    cv = next((cols[c] for c in ("volume", "vol", "quantité", "quantite", "titres échangés") if c in cols), None)
    if not (cd and cc):
        anomalies.append((rel, f"colonnes non reconnues : {list(df.columns)}"))
        return []
    return [ligne(fournisseur, r[cd], r[cc], r[cv] if cv else "", url, rel, f"ligne {i + 2}", quand,
                  json.dumps(r.to_dict(), ensure_ascii=False)) for i, r in df.iterrows()]


def lire_tout(jc):
    obs, anomalies = [], []
    for f in sorted(glob.glob(os.path.join(BRUT, "sika_*.json"))):
        rel = os.path.relpath(f, ICI)
        m = jc[jc.fichier == rel]
        url, quand = (m.url.iloc[-1], m.horodatage_utc.iloc[-1]) if len(m) else ("", "")
        try:
            lst = json.load(open(f, encoding="utf-8"))["lst"]
        except Exception as e:
            anomalies.append((rel, f"structure JSON non reconnue : {type(e).__name__}"))
            continue
        for i, r in enumerate(lst):
            if "Date" not in r or "Close" not in r:
                anomalies.append((rel, f"élément {i} sans Date/Close"))
                continue
            obs.append(ligne("sikafinance", r["Date"], r["Close"], r.get("Volume", ""), url, rel,
                             f"lst[{i}]", quand, json.dumps(r, ensure_ascii=False)))
    for f in sorted(glob.glob(os.path.join(BRUT, "ilboursa_*.bin"))):
        rel = os.path.relpath(f, ICI)
        m = jc[jc.fichier == rel]
        obs += lire_csv_generique(f, "ilboursa", m.url.iloc[-1] if len(m) else "",
                                  m.horodatage_utc.iloc[-1] if len(m) else "", anomalies)
    for f in sorted(glob.glob(os.path.join(FOURNIS, "**", "*.csv"), recursive=True)):
        obs += lire_csv_generique(f, "fichier_fourni:" + os.path.basename(f), "", "", anomalies)
    for _, r in saisie("bulletins_slbc_saisie.csv").iterrows():
        obs.append(ligne("brvm.org (bulletin officiel)", r.Date, r.Close, r.Volume, "", r.fichier_preuve,
                         f"page {r.page} / BOC n°{r.numero_bulletin}", "", "", r.statut_titre))
    return obs, anomalies


def main():
    jc = meta_collecte()
    journal = []

    def log(**k):
        journal.append(k)

    obs, anomalies = lire_tout(jc)
    for rel, msg in anomalies:
        log(Date="", champ="fichier", valeur_initiale=rel, valeur_retenue="", operation="exclusion",
            justification=msg, reference=rel, statut_resolution="NON RÉSOLU")
    df = pd.DataFrame(obs, columns=["Date_texte"] + COLS_BRUT[:-1])

    cal = saisie("calendrier_officiel_saisie.csv")
    cal["Date"] = cal.Date.map(date_iso)
    seances = set(cal.Date[cal.statut_seance.isin(["SEANCE", "SEANCE_EXCEPTIONNELLE"])])
    fermes = set(cal.Date[cal.statut_seance == "FERMETURE"])

    ev = saisie("evenements_officiels.csv")
    ev_ok = ev[ev.statut == "CONFIRMÉ PAR AVIS OFFICIEL"]
    split = ev_ok[ev_ok.type == "FRACTIONNEMENT"]
    date_split = date_iso(split.date_debut.iloc[0]) if len(split) else None
    ratio = nombre(split.ratio_nouvelles_pour_une.iloc[0]) if len(split) else None
    suspensions = [(date_iso(r.date_debut), date_iso(r.date_fin) or FIN)
                   for _, r in ev_ok[ev_ok.type == "SUSPENSION"].iterrows()]

    def suspendu(d):
        return any(a <= d <= b for a, b in suspensions)

    base = saisie("base_ajustement_sources.csv").set_index("fournisseur").ajuste_fractionnement.to_dict()
    df["base_ajustement"] = [
        "NON (cours cotés)" if f.startswith("brvm.org") else base.get(f.split(":")[0], "INCONNU")
        for f in df.fournisseur]

    statuts = []
    for _, r in df.iterrows():
        pb = []
        if not r.Date:
            pb.append("date illisible")
        elif not (DEBUT <= r.Date <= FIN):
            pb.append("hors période")
        else:
            if r.Date in fermes:
                pb.append("date = fermeture officielle")
            if suspendu(r.Date) and r.statut_titre != "SUSPENDU":
                pb.append("date pendant une suspension officielle")
            if EXIGER_CALENDRIER_OFFICIEL and r.Date not in seances:
                pb.append("séance non établie par bulletin")
            if r.base_ajustement != "NON (cours cotés)" and r.base_ajustement != "NON" and \
                    (date_split is None or r.Date < date_split):
                pb.append(f"base d'ajustement {r.base_ajustement} avant fractionnement confirmé")
        if r.fournisseur.startswith("fichier_fourni"):
            pb.append("fichier fourni seul : non probant")
        if r.statut_titre in ("", "TRANSACTION"):
            c, v = nombre(r.Close), nombre(r.Volume)
            if c is None or c <= 0:
                pb.append("cours non numérique ou <= 0")
            if v is None:
                pb.append("volume absent ou non numérique")
            elif v < 0 or v != int(v):
                pb.append("volume négatif ou non entier")
            elif v == 0:
                pb.append("volume nul sans statut de séance sans transaction documenté")
        statuts.append("OK" if not pb else "; ".join(pb))
    df["statut_controle"] = statuts

    # contradictions entre sources (sur les observations OK et les fichiers fournis à valeurs valides)
    retenu = {}
    for d, g in df[df.Date.notna() & (df.statut_titre.isin(["", "TRANSACTION"]))].groupby("Date"):
        ok = g[g.statut_controle == "OK"]
        comparables = g[(g.statut_controle == "OK") | (g.statut_controle == "fichier fourni seul : non probant")]
        vals = {(nombre(r.Close), int(nombre(r.Volume))) for _, r in comparables.iterrows()
                if nombre(r.Close) and nombre(r.Volume) is not None}
        if len(vals) > 1:
            detail = " | ".join(f"{r.fournisseur}: {r.Close}/{r.Volume} ({r.fichier_source} {r.ligne_ou_page})"
                                for _, r in comparables.iterrows())
            dec = saisie("decisions_contradictions.csv")
            dec = dec[dec.Date.map(date_iso) == d]
            if len(dec) and len(ok):
                c, v = nombre(dec.valeur_retenue_close.iloc[0]), nombre(dec.valeur_retenue_volume.iloc[0])
                retenu[d] = (c, int(v))
                log(Date=d, champ="Close/Volume", valeur_initiale=detail, valeur_retenue=f"{c}/{int(v)}",
                    operation="correction", justification=dec.justification.iloc[0],
                    reference=dec.reference.iloc[0], statut_resolution="RÉSOLU")
            else:
                df.loc[g.index[g.statut_controle == "OK"], "statut_controle"] = "contradiction non résolue"
                log(Date=d, champ="Close/Volume", valeur_initiale=detail, valeur_retenue="",
                    operation="exclusion", justification="valeurs divergentes entre sources, sans preuve décisive",
                    reference="", statut_resolution="NON RÉSOLU")
        elif len(ok):
            c, v = vals.pop() if vals else (None, None)
            retenu[d] = (c, v)
    for _, r in df[~df.statut_controle.isin(["OK", "contradiction non résolue"])].iterrows():
        log(Date=r.Date or r.Date_texte, champ="observation", valeur_initiale=f"Close={r.Close} Volume={r.Volume}",
            valeur_retenue="", operation="exclusion", justification=r.statut_controle,
            reference=f"{r.fournisseur} {r.fichier_source} {r.ligne_ou_page}", statut_resolution="NON RÉSOLU")

    sortie = lambda n: os.path.join(ICI, n)
    df[COLS_BRUT].to_csv(sortie("SOLIBRA_SLBC_2023_2026_BRUT.csv"), index=False)
    df[COLS_PROV].to_csv(sortie("PROVENANCE_SOLIBRA_2023_2026.csv"), index=False)
    an = pd.DataFrame([(d, c, v) for d, (c, v) in sorted(retenu.items())], columns=["Date", "Close", "Volume"])
    an["Volume"] = an.Volume.astype("Int64")
    an.to_csv(sortie("SOLIBRA_SLBC_2023_2026_ANALYSE.csv"), index=False, float_format="%.10g")

    # série ajustée séparée, seulement si fractionnement confirmé officiellement
    meta = {"fichier": "SOLIBRA_SLBC_2023_2026_ANALYSE.csv", "colonnes": ["Date", "Close", "Volume"],
            "unite_close": "FCFA par action, cours de clôture tel que coté",
            "close_ajuste_fractionnement": "NON",
            "volume": "nombre d'actions échangées tel que publié (non ajusté)",
            "fractionnement_confirme_par_avis_officiel": bool(date_split),
            "date_effet_fractionnement": date_split, "ratio_nouvelles_pour_une": ratio,
            "suspensions_confirmees": suspensions, "exiger_calendrier_officiel": EXIGER_CALENDRIER_OFFICIEL,
            "genere_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if date_split and ratio:
        aj = an.copy()
        avant = aj.Date < date_split
        aj.loc[avant, "Close"] = aj.loc[avant, "Close"] / ratio
        aj.loc[avant, "Volume"] = (aj.loc[avant, "Volume"] * ratio).astype("Int64")
        aj.to_csv(sortie("SOLIBRA_SLBC_2023_2026_AJUSTE_FRACTIONNEMENT.csv"), index=False, float_format="%.10g")
        meta["serie_ajustee"] = {"fichier": "SOLIBRA_SLBC_2023_2026_AJUSTE_FRACTIONNEMENT.csv",
                                 "transformation": f"Date < {date_split} : Close / {ratio:g} ; Volume x {ratio:g}",
                                 "reference": split.reference_avis.iloc[0]}
    else:
        meta["serie_ajustee"] = None
        meta["raison_absence_serie_ajustee"] = "fractionnement non confirmé par un avis officiel récupéré"
    json.dump(meta, open(sortie("METADONNEES_SERIE.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # calendrier et couverture : un jour calendaire par ligne, aucune observation ajoutée
    calm = cal.dropna(subset=["Date"]).drop_duplicates("Date").set_index("Date")
    st_bul = df[df.fournisseur.str.startswith("brvm")].set_index("Date").statut_titre.to_dict()
    rows = []
    for j in pd.date_range(DEBUT, FIN, freq="D"):
        d = j.date().isoformat()
        st = calm.statut_seance.get(d, "NON ÉTABLI")
        if st == "FERMETURE":
            s = "JOUR SANS SÉANCE"
        elif suspendu(d) or st_bul.get(d) == "SUSPENDU":
            s = "TITRE SUSPENDU"
        elif d in retenu:
            s = "RETENU"
        elif st_bul.get(d) == "SANS_TRANSACTION":
            s = "SÉANCE SANS TRANSACTION"
        elif (df.Date == d).any():
            s = "EXCLU (" + "; ".join(sorted(set(df.loc[df.Date == d, "statut_controle"]))) + ")"
        else:
            s = "NON RÉCUPÉRÉ"
        rows.append({"Date": d, "jour_semaine": j.day_name(), "lundi_vendredi": j.weekday() < 5,
                     "statut_seance_officiel": st, "reference_officielle": calm.reference.get(d, ""),
                     "SLBC_statut": s})
    calendrier = pd.DataFrame(rows)
    calendrier.to_csv(sortie("CALENDRIER_COUVERTURE_2023_2026.csv"), index=False)

    # couverture par intervalle de trois mois
    sys.path.insert(0, ICI)
    from collecte_sources import fenetres_trimestrielles
    inter = []
    for k, (a, b) in enumerate(fenetres_trimestrielles(), 1):
        a, b = a.isoformat(), b.isoformat()
        t = jc[(jc.periode_debut == a) & (jc.periode_fin == b)]
        dd = df[(df.Date >= a) & (df.Date <= b)]
        inter.append({"intervalle": k, "debut": a, "fin": b, "tentatives": len(t),
                      "tentatives_reussies": int((t.resultat == "RÉCUPÉRÉ").sum()),
                      "sources_tentees": ";".join(sorted(set(t.source))),
                      "sources_reussies": ";".join(sorted(set(t.source[t.resultat == "RÉCUPÉRÉ"]))),
                      "echecs": ";".join(sorted(set(t.erreur_observee[t.resultat != "RÉCUPÉRÉ"]))),
                      "lignes_recuperees": len(dd), "dates_retenues": sum(a <= d <= b for d in retenu),
                      "lignes_exclues": int((dd.statut_controle != "OK").sum())})
    pd.DataFrame(inter).to_csv(sortie("COUVERTURE_PAR_INTERVALLE.csv"), index=False)

    fixes = pd.read_csv(os.path.join(SAIS, "constats_documentaires.csv"), dtype=str).fillna("")
    calc = pd.DataFrame(journal, columns=COLS_JOURNAL)
    calc["id"] = [f"C{i + 1:04d}" for i in range(len(calc))]
    pd.concat([fixes, calc], ignore_index=True)[COLS_JOURNAL].to_csv(
        sortie("JOURNAL_CORRECTIONS_EXCLUSIONS.csv"), index=False)
    print(f"brutes={len(df)} retenues={len(an)} exclusions/corrections journalisées={len(calc)} "
          f"anomalies fichiers={len(anomalies)} fractionnement confirmé={bool(date_split)}")


if __name__ == "__main__":
    main()
