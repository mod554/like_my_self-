#!/usr/bin/env python3
"""Importe l'historique SOLIBRA (SLBC) depuis le dépôt public harzat/brvm-data-public
et produit les livrables 2023-01-01 -> 2026-10-15.

Source : https://github.com/harzat/brvm-data-public, commit ed5e3e355d4fdd21b024de59140a19a67e4dccd3
Fichier : Historique_Complet_SOLIBRA_CI.csv (copie conservée dans preuves/brut/, SHA-256 contrôlé)

Règles (aucune valeur créée, aucune interpolation, aucun volume inventé) :
- le fichier source et sa copie ne sont jamais modifiés ;
- BRUT contient toutes les lignes de la fenêtre, avec leurs valeurs texte d'origine et des indicateurs de contrôle ;
- ANALYSE ne contient que les lignes dont le volume titres est établi (valeur présente, ou 0 si
  « Volume FCFA » vaut 0 dans la source) et qui ne sont pas exclues par une contradiction non résolue ;
- une ligne en contradiction avec une autre source ou avec un calendrier officiel est gardée en BRUT
  et sortie de ANALYSE, avec son motif dans JOURNAL_CORRECTIONS_EXCLUSIONS.csv ;
- les cours ne sont PAS ajustés du fractionnement : la série publiée n'affiche pas la cassure attendue
  au 30/09/2024, ce qui est consigné comme contradiction non résolue (voir README) ;
- les dividendes sont transcrits du dépôt et renvoient aux avis BRVM cités ; les PDF n'ont pas été ouverts.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import zipfile

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = "/home/user/harzat/brvm-data-public"
COMMIT = "ed5e3e355d4fdd21b024de59140a19a67e4dccd3"
URL_DEPOT = "https://github.com/harzat/brvm-data-public"
URL_FICHIER = f"{URL_DEPOT}/blob/{COMMIT}/Historique_Complet_SOLIBRA_CI.csv"
DATE_RECUP = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
DEBUT, FIN = pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-15")
SUSP_DEBUT, SUSP_FIN = pd.Timestamp("2024-04-02"), pd.Timestamp("2024-09-11")
FRAC_FENETRE = (pd.Timestamp("2024-09-27"), pd.Timestamp("2024-10-08"))
BRUT_DIR = os.path.join(ICI, "preuves", "brut")
os.makedirs(BRUT_DIR, exist_ok=True)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def num(s):
    s = str(s).replace(" ", "").replace("\xa0", "").replace(" ", "").strip()
    if s in ("", "-"):
        return np.nan
    return float(s.replace(",", "."))


# ------------------------------------------------------------------ 1. copies et preuves
src = os.path.join(DEPOT, "Historique_Complet_SOLIBRA_CI.csv")
cop = os.path.join(BRUT_DIR, "Historique_Complet_SOLIBRA_CI.csv")
shutil.copyfile(src, cop)
assert sha(src) == sha(cop)
sha_src = sha(cop)
for f in ["prix_ecartes.json", "prix_confirmes.json", "dividendes.json", "seance.json", "trading_status.json"]:
    shutil.copyfile(os.path.join(DEPOT, f), os.path.join(BRUT_DIR, f))
ev_all = json.load(open(os.path.join(DEPOT, "events.json"), encoding="utf-8"))["events"]
ev_sol = [e for e in ev_all if "SOLIBRA" in " ".join(str(e.get(k) or "") for k in ("issuer", "company", "ticker", "title"))]
json.dump(ev_sol, open(os.path.join(BRUT_DIR, "events_SOLIBRA_extrait.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ 2. lecture et parsing
raw = pd.read_csv(cop, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
assert list(raw.columns) == ["Date", "Clôture", "Plus bas", "Plus haut", "Ouverture",
                             "Volume Titres", "Volume FCFA", "Variation %"], list(raw.columns)
df = pd.DataFrame({
    "ligne_source": np.arange(2, len(raw) + 2),
    "Date_texte": raw["Date"],
    "Date": pd.to_datetime(raw["Date"], format="%d/%m/%Y", errors="coerce"),
    "Close": raw["Clôture"].map(num),
    "Plus_bas": raw["Plus bas"].map(num),
    "Plus_haut": raw["Plus haut"].map(num),
    "Ouverture": raw["Ouverture"].map(num),
    "Volume": raw["Volume Titres"].map(num),
    "Volume_FCFA": raw["Volume FCFA"].map(num),
    "Variation_texte": raw["Variation %"],
})
total_lignes = len(df)
df_all = df.copy()
w = df[(df.Date >= DEBUT) & (df.Date <= FIN)].copy().reset_index(drop=True)

# ------------------------------------------------------------------ 3. indicateurs par ligne
w["ret"] = w.Close.pct_change()
w["jour_ouvre"] = w.Date.dt.weekday < 5
prev = w.shift(1)
w["copie_precedente"] = (w.Close == prev.Close) & (w.Ouverture == prev.Ouverture) & \
                        (w.Plus_haut == prev.Plus_haut) & (w.Plus_bas == prev.Plus_bas)

# indicateurs (texte pour la lisibilité)
motifs_brut = []
statut_ana = []
for _, r in w.iterrows():
    m = []
    if not r.jour_ouvre:
        m.append("week-end")
    if SUSP_DEBUT <= r.Date <= SUSP_FIN:
        m.append("pendant suspension de cotation (avis 054 du 02/04/2024, levée avis 227 du 11/09/2024)")
    if FRAC_FENETRE[0] <= r.Date <= FRAC_FENETRE[1]:
        m.append("fenêtre du fractionnement (avis 242) : cassure de cours absente")
    if pd.isna(r.Volume) and r.Volume_FCFA == 0:
        m.append("volume titres vide, Volume FCFA = 0 : séance sans transaction")
    elif pd.isna(r.Volume):
        m.append("volume titres vide, Volume FCFA > 0 : volume non établi")
    if r.Date.date().isoformat() in ("2025-04-18", "2026-04-03"):
        m.append("vendredi saint : jour férié probable, séance publiée (contradiction à trancher)")
    if r.Date == pd.Timestamp("2026-10-15"):
        m.append("clôture provisoire : écart avec le snapshot BRVM du 15/10 (238 titres, 38 490 FCFA)")
    if pd.notna(r.ret) and abs(r.ret) > 0.10:
        m.append(f"variation {r.ret:+.1%} > 10 % (conservée, non corrigée)")
    if pd.notna(r.Close) and pd.notna(r.Plus_haut) and pd.notna(r.Plus_bas) and \
            (r.Close > r.Plus_haut or r.Close < r.Plus_bas):
        m.append("clôture hors de [plus bas, plus haut] (conservée, non corrigée)")
    if r.copie_precedente:
        m.append("OHLC identique à la séance précédente (conservée)")
    motifs_brut.append("; ".join(m))

    # décision pour ANALYSE
    if pd.isna(r.Close) or r.Close <= 0:
        statut_ana.append("EXCLUE : cours absent ou non strictement positif")
    elif not r.jour_ouvre:
        statut_ana.append("EXCLUE : week-end")
    elif SUSP_DEBUT <= r.Date <= SUSP_FIN:
        statut_ana.append("EXCLUE : cotation suspendue (avis BRVM)")
    elif pd.isna(r.Volume) and r.Volume_FCFA == 0:
        statut_ana.append("RETENUE : séance sans transaction, volume 0 établi par Volume FCFA = 0")
    elif pd.isna(r.Volume):
        statut_ana.append("EXCLUE : volume titres non établi (aucune estimation)")
    elif r.Date.date().isoformat() in ("2025-04-18", "2026-04-03"):
        statut_ana.append("EXCLUE : contradiction non résolue (vendredi saint)")
    elif r.Date == pd.Timestamp("2026-10-15"):
        statut_ana.append("EXCLUE : contradiction non résolue (clôture provisoire contredite par le snapshot BRVM)")
    else:
        statut_ana.append("RETENUE")
w["motif_controle"] = motifs_brut
w["statut_analyse"] = statut_ana

# ------------------------------------------------------------------ 4. journal
jrn = []


def jout(date, champ, avant, apres, operation, motif, reference, statut):
    jrn.append({"Date": date, "champ": champ, "valeur_initiale": avant, "valeur_retenue": apres,
                "operation": operation, "justification": motif, "reference": reference,
                "statut_resolution": statut})


# 4a. jours retirés par le dépôt (absents du CSV) : constat, pas d'observation
retires = json.load(open(os.path.join(DEPOT, "prix_ecartes.json"), encoding="utf-8"))["jours"]
for d, motifs in sorted(retires.items()):
    if not (DEBUT <= pd.Timestamp(d) <= FIN):
        continue
    for motif, titres in motifs.items():
        if "SOLIBRA_CI" in titres:
            jout(d, "observation", "non présente dans le CSV source", "", "exclusion (amont)",
                 f"le dépôt a retiré cette ligne : {motif}", "prix_ecartes.json", "RÉSOLU (retrait amont constaté)")

# 4b. lignes de la fenêtre
for _, r in w.iterrows():
    d = r.Date.date().isoformat()
    ref = f"Historique_Complet_SOLIBRA_CI.csv ligne {r.ligne_source}"
    if r.statut_analyse.startswith("EXCLUE"):
        jout(d, "observation", f"Close={r.Close:g} Volume={'' if pd.isna(r.Volume) else int(r.Volume)} VolFCFA={r.Volume_FCFA:g}",
             "", "exclusion", r.statut_analyse.replace("EXCLUE : ", ""), ref, "NON RÉSOLU" if "contradiction" in r.statut_analyse else "RÉSOLU (règle)")
    if "clôture provisoire" in r.motif_controle:
        jout(d, "Close/Volume", f"CSV: {r.Close:g}/{r.Volume:g}", "snapshot BRVM: 38490/238",
             "contradiction", "clôture provisoire du 15/10/2026 contredite par la page BRVM 'Cours des actions' (seance.json)",
             "seance.json : cours.SLBC", "NON RÉSOLU")
    if "fractionnement" in r.motif_controle and r.Date == FRAC_FENETRE[0]:
        pass

# 4c. contradiction structurelle : fractionnement
jout("2024-09-30", "Close (série entière)",
     "avis BRVM n°242 du 27/09/2024 : division par 10 (fractionnement) ; 16 460 840 actions ; presse : cours divisé par 10",
     "CSV : aucune cassure (9 500 le 26/09 -> 10 975 le 30/09 -> 15 505 le 08/10)",
     "non ajusté (conservé)",
     "le CSV ne montre pas la baisse de cours attendue d'un fractionnement 10 pour 1 ; les cours pré- et post-séance "
     "sont cohérents avec les cours de référence BRVM du dépôt (8 325 le 03/06/2024, 19 320 le 24/07/2025, 39 500 le 28/07/2026) ; "
     "le fractionnement est donc soit absent de la cotation, soit documenté ailleurs : l'avis n°242 doit être lu",
     "events.json (théorique n°242), dividendes.json (cours_reference)", "NON RÉSOLU")

# 4d. ligne pendant suspension
for _, r in w[(w.Date >= SUSP_DEBUT) & (w.Date <= SUSP_FIN)].iterrows():
    jout(r.Date.date().isoformat(), "observation", f"Close={r.Close:g} Volume={'' if pd.isna(r.Volume) else int(r.Volume)} VolFCFA={r.Volume_FCFA:g}",
         "", "exclusion",
         "cotation suspendue entre l'avis 054 (02/04/2024) et l'avis 227 (11/09/2024) ; ligne publiée sans volume titres",
         f"Historique_Complet_SOLIBRA_CI.csv ligne {r.ligne_source}", "NON RÉSOLU")

# 4e. cours hors fourchette, copies, variations
nb_ohlc = int(w.motif_controle.str.contains("hors de").sum())
nb_cop = int(w.copie_precedente.sum())
jout("", "OHLC", f"{nb_ohlc} lignes de la fenêtre", "conservées", "constat",
     "clôture hors de [plus bas, plus haut] : incohérence de la source, aucune correction appliquée",
     "BRUT colonne motif_controle", "NON RÉSOLU (non corrigé)")
jout("", "copies", f"{nb_cop} lignes identiques à la séance précédente", "conservées", "constat",
     "copies d'OHLC : le dépôt n'en retire que celles d'au moins 20 titres ; les autres sont conservées et peuvent être des cotations inchangées",
     "BRUT colonne motif_controle", "NON RÉSOLU (non tranché)")
for _, r in w[w.motif_controle.str.contains("variation")].iterrows():
    jout(r.Date.date().isoformat(), "Close", f"{r.Close:g}", f"{r.Close:g}", "constat",
         f"variation {r.ret:+.1%} conservée ; aucune source indépendante ne la confirme ou ne la contredit",
         f"ligne {r.ligne_source}", "NON RÉSOLU (non corrigé)")

# 4f. volume FCFA vs Close x Volume (constat, pas de correction)
ecart = ((w.Volume_FCFA - w.Close * w.Volume).abs() / w.Volume_FCFA)
nb_ecart = int(((ecart > 0.02) & w.Volume.notna() & (w.Volume_FCFA > 0)).sum())
jout("", "Volume FCFA", f"{nb_ecart} lignes où Volume FCFA diffère de Close x Volume de plus de 2 %", "non corrigé",
     "constat", "Volume FCFA est un montant publié (VWAP probable), il n'est pas recalculé comme Close x Volume",
     "BRUT colonnes Volume_FCFA", "RÉSOLU (règle)")

jrn_df = pd.DataFrame(jrn)
jrn_df.insert(0, "id", [f"J{i + 1:04d}" for i in range(len(jrn_df))])

# ------------------------------------------------------------------ 5. séries de sortie
brut = w[["Date_texte", "Date", "Close", "Plus_bas", "Plus_haut", "Ouverture", "Volume", "Volume_FCFA",
          "Variation_texte", "ligne_source", "motif_controle", "statut_analyse"]].copy()
brut["Date"] = brut.Date.dt.strftime("%Y-%m-%d")
brut["fichier_source"] = "Historique_Complet_SOLIBRA_CI.csv"
brut["url"] = URL_FICHIER
brut["commit"] = COMMIT
brut["sha256_fichier"] = sha_src
brut["date_recuperation_utc"] = DATE_RECUP
brut["fournisseur"] = "harzat/brvm-data-public (compilation publique ; origine déclarée : BRVM, SikaFinance, RicheBourse)"
brut.to_csv(os.path.join(ICI, "SOLIBRA_SLBC_2023_2026_BRUT.csv"), index=False, encoding="utf-8")

ana = w[w.statut_analyse.str.startswith("RETENUE")].copy()
ana["Volume"] = ana.Volume.fillna(0).astype("int64")
ana_out = pd.DataFrame({"Date": ana.Date.dt.strftime("%Y-%m-%d"),
                        "Close": ana.Close.map(lambda x: int(x) if float(x).is_integer() else x),
                        "Volume": ana.Volume})
ana_out.to_csv(os.path.join(ICI, "SOLIBRA_SLBC_2023_2026_ANALYSE.csv"), index=False, encoding="utf-8")

prov = pd.DataFrame({
    "Date": brut.Date, "Close": brut.Close, "Volume": brut.Volume, "Volume_FCFA": brut.Volume_FCFA,
    "fournisseur": "harzat/brvm-data-public", "url": URL_FICHIER, "commit": COMMIT,
    "fichier_source": "preuves/brut/Historique_Complet_SOLIBRA_CI.csv", "ligne_source": brut.ligne_source,
    "sha256_fichier": sha_src, "date_recuperation_utc": DATE_RECUP,
    "statut_controle": brut.statut_analyse,
})
prov.to_csv(os.path.join(ICI, "PROVENANCE_SOLIBRA_2023_2026.csv"), index=False, encoding="utf-8")

jrn_df.to_csv(os.path.join(ICI, "JOURNAL_CORRECTIONS_EXCLUSIONS.csv"), index=False, encoding="utf-8")

# ------------------------------------------------------------------ 6. calendrier et couverture
susp_tab = pd.date_range(SUSP_DEBUT, SUSP_FIN - pd.Timedelta(days=1))
retires_dates = {d for d, m in retires.items() if any("SOLIBRA_CI" in t for t in m.values())}
statut_par_jour = dict(zip(w.Date, w.statut_analyse))
lignes_cal = []
for j in pd.date_range(DEBUT, FIN, freq="D"):
    d = j.date().isoformat()
    if j.weekday() >= 5:
        s = "WEEK-END"
    elif j in susp_tab:
        s = "SUSPENDU (avis 054 -> 227)"
    elif j in statut_par_jour:
        s = statut_par_jour[j]
    elif d in retires_dates:
        s = "EXCLU EN AMONT PAR LE DÉPÔT (férié ou copie)"
    else:
        s = "JOUR OUVRÉ SANS LIGNE : séance non établie (pas de calendrier officiel)"
    lignes_cal.append({"Date": d, "jour": j.day_name(), "jour_ouvre": j.weekday() < 5, "statut": s})
cal = pd.DataFrame(lignes_cal)
cal.to_csv(os.path.join(ICI, "CALENDRIER_COUVERTURE_2023_2026.csv"), index=False, encoding="utf-8")

inter = []
for k, (a, b) in enumerate([(pd.Timestamp(f"{y}-{m:02d}-01"), None) for y in range(2023, 2027) for m in (1, 4, 7, 10)], 1):
    end = min((a + pd.offsets.QuarterEnd(0)), FIN)
    if a > FIN:
        break
    sub = cal[(cal.Date >= a.strftime("%Y-%m-%d")) & (cal.Date <= end.strftime("%Y-%m-%d"))]
    inter.append({"intervalle": k, "debut": a.date(), "fin": end.date(),
                  "jours_ouvres": int(sub.jour_ouvre.sum()),
                  "retenues": int(sub.statut.str.startswith("RETENUE").sum()),
                  "exclues_ou_sans_transaction": int(sub.statut.str.startswith(("EXCLUE", "RETENUE : séance sans")).sum()),
                  "suspendus": int(sub.statut.str.startswith("SUSPENDU").sum()),
                  "jours_ouvres_sans_ligne": int(sub.statut.str.startswith("JOUR OUVRÉ SANS LIGNE").sum()),
                  "source_utilisee": "1 fichier complet du dépôt, filtré sur l'intervalle",
                  "echecs_collecte": "aucun (fichier récupéré par git ; sites officiels inaccessibles, voir preuves/COLLECTE_TENTATIVES.csv)"})
pd.DataFrame(inter).to_csv(os.path.join(ICI, "COUVERTURE_PAR_INTERVALLE.csv"), index=False, encoding="utf-8")

# ------------------------------------------------------------------ 7. dividendes et événements
dv = json.load(open(os.path.join(DEPOT, "dividendes.json"), encoding="utf-8"))["all"]
div_rows = []
for r in dv:
    if r.get("ticker") == "SLBC" and r.get("exercice") in (2023, 2024, 2025):
        anomalies = ";".join(r.get("date_anomalies") or [])
        div_rows.append({
            "exercice": r["exercice"],
            "dividende_brut_FCFA_par_action": r.get("dividende_brut"),
            "dividende_net_FCFA_par_action": r.get("dividende_net"),
            "taux_retenue_pct": r.get("dividende_net_taux_pct"),
            "date_annonce": r.get("date_annonce"),
            "date_detachement": r.get("date_detachement"),
            "date_paiement": r.get("date_paiement"),
            "reference_documentaire": r.get("document_url"),
            "statut_verification": "transcrit du dépôt ; avis PDF cité non ouvert (inaccessible)",
            "anomalies_dates": anomalies,
            "remarque": r.get("dividende_remarque") or "",
        })
pd.DataFrame(div_rows).to_csv(os.path.join(ICI, "SOLIBRA_DIVIDENDES_2023_2026.csv"), index=False, encoding="utf-8")

ev_rows = []
for e in ev_sol:
    d = str(e.get("event_at") or "")
    if d[:10] and DEBUT <= pd.Timestamp(d[:10]) <= FIN:
        ev_rows.append({"date_evenement": d[:10], "categorie": e.get("category"), "titre": e.get("title"),
                        "role_date": e.get("date_role"), "source": e.get("source"),
                        "document": (e.get("document_url") or (e.get("documents") or [{}])[0].get("url") or "")})
pd.DataFrame(ev_rows).sort_values("date_evenement").to_csv(
    os.path.join(ICI, "EVENEMENTS_SOLIBRA_2023_2026.csv"), index=False, encoding="utf-8")

# ------------------------------------------------------------------ 8. métadonnées
meta = {
    "fichier": "SOLIBRA_SLBC_2023_2026_ANALYSE.csv",
    "colonnes": ["Date", "Close", "Volume"],
    "close": "cours de clôture publié par la source, FCFA par action, NON ajusté du fractionnement",
    "volume": "nombre de titres échangés (Volume Titres) ; 0 seulement si Volume FCFA = 0 dans la source",
    "statut_serie": "SÉRIE NON VALIDÉE : source secondaire unique, contradictions non résolues (voir journal)",
    "fractionnement_2024": "avis BRVM n°242 (27/09/2024) lu par son titre seulement ; effet absent du CSV ; non appliqué",
    "source": URL_DEPOT, "commit": COMMIT, "sha256_source": sha_src, "date_recuperation_utc": DATE_RECUP,
    "close_ajuste_fractionnement": "NON",
    "date_effet_fractionnement": "2024-09-30",
    "date_effet_source": "presse (CGF Bourse) ; avis BRVM n°242 non lu",
    "suspensions_confirmees": [["2024-04-02", "2024-09-10"]],
    "source_suspension": "titres des avis BRVM n°054 (02/04/2024) et n°227 (11/09/2024), non lus",
    "fenetre": [DEBUT.date().isoformat(), FIN.date().isoformat()],
    "lignes_source_total": total_lignes,
    "lignes_fenetre": len(w),
    "lignes_analyse": len(ana_out),
}
json.dump(meta, open(os.path.join(ICI, "METADONNEES_SERIE.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"source={total_lignes} fenêtre={len(w)} analyse={len(ana_out)} journal={len(jrn_df)} "
      f"dividendes={len(div_rows)} événements={len(ev_rows)}")
print(w.statut_analyse.value_counts().to_string())
