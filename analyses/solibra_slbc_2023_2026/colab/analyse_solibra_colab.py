# -*- coding: utf-8 -*-
"""Analyse SOLIBRA (SLBC.CI) — script exécutable dans Google Colab ou en local.

Entrée attendue : SOLIBRA_SLBC_2023_2026_ANALYSE.csv (Date,Close,Volume) ou une
archive ZIP qui le contient, et facultativement CALENDRIER_COUVERTURE_2023_2026.csv
et METADONNEES_SERIE.json produits par construire_livrables.py.

Utilisation :
    python analyse_solibra_colab.py DONNEES.zip|DONNEES.csv [--sortie resultats]
        [--calendrier CAL.csv] [--close-ajuste NON|OUI|INCONNU]
        [--seances-par-an N --source-annualisation "texte"]
        [--taux-sans-risque 0.035 --source-taux "texte"]
        [--indice INDICE.csv] [--dividendes DIVIDENDES.csv]

Principes :
- le script ne modifie ni ne supprime aucune ligne en silence : toute ligne
  écartée d'un calcul figure dans resultats/tables/lignes_ecartees.csv avec son motif ;
- un rendement n'est « quotidien » que si les deux observations sont des
  séances successives établies par le calendrier ; sinon il est classé à part ;
- un rendement qui traverse une suspension ou le fractionnement (si les cours
  ne sont pas ajustés) est exclu des statistiques quotidiennes ;
- aucun réajustement n'est appliqué par ce script ;
- annualisation : seulement si un nombre de séances par an est fourni avec sa
  source, ou mesuré sur le calendrier officiel ; jamais 252 par défaut ;
- bêta, Sharpe et rendement total ne sont calculés que si l'indice, le taux sans
  risque (avec sa source) ou des dividendes vérifiés sont fournis.
La réussite de l'import ne prouve pas l'exactitude financière des données.
"""
import argparse
import io
import json
import os
import sys
import zipfile

import numpy as np
import pandas as pd

import matplotlib
if "google.colab" not in sys.modules and not os.environ.get("DISPLAY"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLONNES = ["Date", "Close", "Volume"]
NOM_ANALYSE = "SOLIBRA_SLBC_2023_2026_ANALYSE.csv"
NOM_CAL = "CALENDRIER_COUVERTURE_2023_2026.csv"
NOM_META = "METADONNEES_SERIE.json"
SEANCES_OK = {"SEANCE", "SEANCE_EXCEPTIONNELLE"}


class ErreurDonnees(Exception):
    pass


# ---------------------------------------------------------------- chargement
def type_reel(octets):
    """Type réel d'après le contenu (et non l'extension)."""
    if octets[:4] == b"PK\x03\x04":
        return "zip"
    if octets[:4] in (b"PK\x05\x06", b"PK\x07\x08"):
        return "zip_vide_ou_fragment"
    if octets[:5] == b"%PDF-":
        return "pdf"
    if octets[:2] == b"\x1f\x8b":
        return "gzip"
    if octets.lstrip()[:1] in (b"<",):
        return "html_ou_xml"
    try:
        octets[:4096].decode("utf-8-sig")
        return "texte"
    except UnicodeDecodeError:
        return "binaire_inconnu"


def lire_entree(chemin):
    """Retourne {nom: octets} pour un CSV ou un ZIP, en vérifiant le type réel."""
    octets = open(chemin, "rb").read()
    t = type_reel(octets)
    if t == "texte":
        return {os.path.basename(chemin): octets}, t
    if t == "zip":
        try:
            z = zipfile.ZipFile(io.BytesIO(octets))
        except zipfile.BadZipFile as e:
            raise ErreurDonnees(f"{chemin} : signature ZIP mais archive illisible ({e})")
        mauvais = z.testzip()
        if mauvais:
            raise ErreurDonnees(f"{chemin} : membre corrompu dans le ZIP : {mauvais}")
        return {os.path.basename(n): z.read(n) for n in z.namelist() if not n.endswith("/")}, t
    raise ErreurDonnees(f"{chemin} : type réel « {t} », ni CSV texte ni ZIP "
                        f"(extension {os.path.splitext(chemin)[1]!r} ignorée)")


def choisir(fichiers, nom, obligatoire=True):
    if nom in fichiers:
        return fichiers[nom]
    csvs = [k for k in fichiers if k.lower().endswith(".csv")]
    if len(fichiers) == 1 and obligatoire:
        return next(iter(fichiers.values()))
    if obligatoire:
        raise ErreurDonnees(f"{nom} introuvable ; fichiers présents : {sorted(fichiers)} "
                            f"(CSV : {csvs}). Indiquez le bon fichier.")
    return None


def charger_serie(octets):
    """Vérifie Date,Close,Volume ; ne supprime rien ; renvoie (df, anomalies)."""
    brut = pd.read_csv(io.BytesIO(octets), dtype=str, keep_default_na=False)
    if list(brut.columns) != COLONNES:
        raise ErreurDonnees(f"colonnes {list(brut.columns)} ; attendu exactement {COLONNES}")
    df = brut.copy()
    df["ligne_fichier"] = np.arange(2, len(df) + 2)
    df["Date_txt"], df["Close_txt"], df["Volume_txt"] = brut.Date, brut.Close, brut.Volume
    df["Date"] = pd.to_datetime(brut.Date, format="%Y-%m-%d", errors="coerce")
    df["Close"] = pd.to_numeric(brut.Close, errors="coerce")
    df["Volume"] = pd.to_numeric(brut.Volume, errors="coerce")
    motifs = []
    for _, r in df.iterrows():
        m = []
        if pd.isna(r.Date):
            m.append("date non AAAA-MM-JJ")
        if "," in r.Close_txt:
            m.append("virgule décimale dans Close")
        if pd.isna(r.Close) or (r.Close <= 0):
            m.append("Close manquant, non numérique ou <= 0")
        if r.Volume_txt.strip() == "":
            m.append("Volume manquant")
        elif pd.isna(r.Volume) or r.Volume < 0 or r.Volume != np.floor(r.Volume):
            m.append("Volume non entier ou négatif")
        motifs.append("; ".join(m))
    df["motif_anomalie"] = pd.Series(motifs, index=df.index, dtype=object)
    dup = df.Date.notna() & df.Date.duplicated(keep=False)
    df.loc[dup, "motif_anomalie"] = (df.loc[dup, "motif_anomalie"] + "; date en double").str.strip("; ")
    if not df.Date.dropna().is_monotonic_increasing:
        print("AVERTISSEMENT : dates non triées dans le fichier ; tri appliqué pour les calculs (fichier inchangé).")
    return df, df[df.motif_anomalie != ""]


def charger_calendrier(octets):
    """Calendrier officiel attendu : colonnes Date et statut_seance_officiel.
    Un calendrier sans ces colonnes (ex. calendrier de couverture non officiel) est ignoré
    avec un avertissement : aucune séance n'est alors tenue pour établie."""
    if octets is None:
        return None
    cal = pd.read_csv(io.BytesIO(octets), dtype=str, keep_default_na=False)
    req = {"Date", "statut_seance_officiel"}
    if not req <= set(cal.columns):
        print("AVERTISSEMENT : calendrier sans colonne statut_seance_officiel : ignoré ; "
              "aucune séance n'est établie par un calendrier officiel.")
        return None
    cal["Date"] = pd.to_datetime(cal.Date, format="%Y-%m-%d")
    return cal


# ------------------------------------------------------------ rendements
def classer_intervalles(obs, cal, meta, close_ajuste):
    """Rendements entre observations consécutives, chacun classé."""
    o = obs.sort_values("Date").reset_index(drop=True)
    r = pd.DataFrame({"Date_debut": o.Date.shift(1), "Date": o.Date,
                      "Close_prec": o.Close.shift(1), "Close": o.Close}).iloc[1:].copy()
    r["rendement_simple"] = r.Close / r.Close_prec - 1
    r["rendement_log"] = np.log(r.Close / r.Close_prec)
    seances = None
    susp = []
    if cal is not None:
        seances = pd.DatetimeIndex(sorted(cal.Date[cal.statut_seance_officiel.isin(SEANCES_OK)]))
        if "SLBC_statut" in cal:
            susp = list(cal.Date[cal.SLBC_statut == "TITRE SUSPENDU"])
    for a, b in (meta or {}).get("suspensions_confirmees", []) or []:
        susp += list(pd.date_range(a, b))
    susp = pd.DatetimeIndex(sorted(set(susp)))
    d_split = (meta or {}).get("date_effet_fractionnement")
    d_split = pd.Timestamp(d_split) if d_split else None
    classes, ecarts = [], []
    for _, x in r.iterrows():
        a, b = x.Date_debut, x.Date
        if len(susp) and ((susp > a) & (susp < b)).any():
            classes.append("traverse une suspension")
            ecarts.append(np.nan)
            continue
        if d_split is not None and a < d_split <= b and close_ajuste != "OUI":
            classes.append("traverse le fractionnement (cours non ajustés)")
            ecarts.append(np.nan)
            continue
        if seances is None or len(seances) == 0:
            classes.append("écart de séances non vérifiable (pas de calendrier officiel)")
            ecarts.append(np.nan)
            continue
        if a not in seances or b not in seances:
            classes.append("date hors calendrier officiel")
            ecarts.append(np.nan)
            continue
        n = int(((seances > a) & (seances < b)).sum())
        ecarts.append(n)
        classes.append("quotidien (séances successives)" if n == 0 else f"multi-séances ({n} séance(s) sans observation)")
    r["seances_intercalaires"] = ecarts
    r["classe"] = classes
    return r


def quotidiens(rend, accepter_non_verifie):
    q = rend.classe == "quotidien (séances successives)"
    if accepter_non_verifie:
        q |= rend.classe.str.startswith("écart de séances non vérifiable")
    return rend[q]


# ------------------------------------------------------------ statistiques
def stats_desc(x):
    x = pd.Series(x).dropna()
    if len(x) < 2:
        return {"n": len(x)}
    d = {"n": len(x), "moyenne": x.mean(), "ecart_type": x.std(ddof=1), "min": x.min(),
         "q01": x.quantile(.01), "q05": x.quantile(.05), "mediane": x.median(),
         "q95": x.quantile(.95), "q99": x.quantile(.99), "max": x.max(),
         "asymetrie": x.skew(), "kurtosis_exces": x.kurt(), "part_nulle": float((x == 0).mean())}
    try:
        from scipy import stats
        jb = stats.jarque_bera(x)
        d["jarque_bera"], d["jarque_bera_p"] = float(jb.statistic), float(jb.pvalue)
    except Exception:
        d["jarque_bera"] = "scipy indisponible"
    return d


def var_es(x, niveaux=(0.95, 0.99), b=2000, graine=0):
    """VaR/ES historiques (pertes positives) avec intervalle bootstrap et effectif de queue."""
    x = pd.Series(x).dropna().to_numpy()
    rng = np.random.default_rng(graine)
    out = []
    for c in niveaux:
        if len(x) == 0:
            out.append({"niveau": c, "n": 0})
            continue
        q = np.quantile(x, 1 - c)
        queue = x[x <= q]
        boot = np.array([np.quantile(s, 1 - c) for s in rng.choice(x, (b, len(x)))])
        es_b = np.array([s[s <= np.quantile(s, 1 - c)].mean() for s in rng.choice(x, (min(b, 500), len(x)))])
        out.append({"niveau": c, "n": len(x), "obs_dans_queue": int(len(queue)),
                    "VaR": -q, "VaR_IC95_bas": -np.quantile(boot, .975), "VaR_IC95_haut": -np.quantile(boot, .025),
                    "ES": -queue.mean(), "ES_IC95_bas": -np.quantile(es_b, .975), "ES_IC95_haut": -np.quantile(es_b, .025),
                    "avertissement": "queue < 10 observations : estimation très instable" if len(queue) < 10 else ""})
    return pd.DataFrame(out)


def drawdown(close):
    pic = close.cummax()
    return close / pic - 1


# ------------------------------------------------------------ programme
def executer(entree, sortie="resultats", calendrier=None, close_ajuste=None, seances_par_an=None,
             source_annualisation=None, taux_sans_risque=None, source_taux=None, indice=None,
             dividendes=None, accepter_non_verifie=False, afficher=False):
    rapport = {"modules": {}, "avertissements": []}
    tab = os.path.join(sortie, "tables")
    fig = os.path.join(sortie, "figures")
    os.makedirs(tab, exist_ok=True)
    os.makedirs(fig, exist_ok=True)

    def module(nom, statut, detail=""):
        rapport["modules"][nom] = {"statut": statut, "detail": detail}
        print(f"[{statut}] {nom} {('— ' + detail) if detail else ''}")

    def figure(f, nom):
        f.tight_layout()
        f.savefig(os.path.join(fig, nom), dpi=130)
        plt.show() if afficher else plt.close(f)

    # 1. contrôle et aperçu
    fichiers, t = lire_entree(entree)
    df, anomalies = charger_serie(choisir(fichiers, NOM_ANALYSE))
    meta = json.loads(fichiers[NOM_META]) if NOM_META in fichiers else None
    cal_oct = open(calendrier, "rb").read() if calendrier else fichiers.get(NOM_CAL)
    cal = charger_calendrier(cal_oct)
    if close_ajuste is None:
        close_ajuste = (meta or {}).get("close_ajuste_fractionnement", "INCONNU")
    rapport.update(entree=entree, type_reel=t, close_ajuste_fractionnement=close_ajuste,
                   lignes_fichier=len(df), lignes_anomalie=len(anomalies))
    anomalies.drop(columns=["Date", "Close", "Volume"]).to_csv(os.path.join(tab, "lignes_ecartees.csv"), index=False)
    obs = df[df.motif_anomalie == ""][["Date", "Close", "Volume"]].sort_values("Date").reset_index(drop=True)
    print(f"Fichier : {len(df)} lignes ; {len(anomalies)} ligne(s) en anomalie écartée(s) des calculs "
          f"(voir tables/lignes_ecartees.csv) ; {len(obs)} observation(s) utilisable(s).")
    print(f"Close ajusté du fractionnement : {close_ajuste}")
    if len(obs) == 0:
        module("contrôle et aperçu", "EXÉCUTÉ", "aucune observation utilisable : analyses suivantes non exécutées")
        rapport["avertissements"].append("série vide")
        json.dump(rapport, open(os.path.join(sortie, "rapport.json"), "w"), ensure_ascii=False, indent=2, default=str)
        return rapport
    apercu = {"premiere_date": obs.Date.min().date(), "derniere_date": obs.Date.max().date(),
              "observations": len(obs), "par_annee": obs.groupby(obs.Date.dt.year).size().to_dict(),
              "volumes_nuls": int((obs.Volume == 0).sum())}
    if cal is not None:
        etab = cal[cal.statut_seance_officiel.isin(SEANCES_OK)]
        rapport["couverture_seances_etablies"] = {
            int(a): f"{int(g.Date.isin(obs.Date).sum())}/{len(g)}" for a, g in etab.groupby(etab.Date.dt.year)}
        if len(etab) == 0:
            rapport["avertissements"].append("calendrier fourni sans aucune séance établie : couverture non démontrable")
    else:
        rapport["avertissements"].append("aucun calendrier : couverture et continuité des séances non vérifiables")
    rapport["apercu"] = apercu
    print(json.dumps(apercu, default=str, ensure_ascii=False))
    module("contrôle et aperçu", "EXÉCUTÉ")
    rapport["avertissement_completude"] = ("Série d'observations disponibles, pas un historique quotidien complet "
                                           "tant que la couverture des séances établies n'est pas de 100 %.")

    # 2. graphiques cours et volumes
    f, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    a1.plot(obs.Date, obs.Close, marker=".", lw=0.8, color="#1f4e79")
    a1.set_ylabel(f"Clôture (FCFA) — ajusté : {close_ajuste}")
    a1.set_title("SLBC.CI — observations disponibles (les trous ne sont pas comblés)")
    a2.bar(obs.Date, obs.Volume, width=1.0, color="#7f7f7f")
    a2.set_ylabel("Volume (actions)")
    figure(f, "cours_volumes.png")
    module("graphiques cours et volumes", "EXÉCUTÉ")

    # 3. rendements
    rend = classer_intervalles(obs, cal, meta, close_ajuste)
    rend.to_csv(os.path.join(tab, "rendements_classes.csv"), index=False)
    cls = rend.classe.value_counts().to_dict()
    rapport["classes_rendements"] = cls
    q = quotidiens(rend, accepter_non_verifie)
    if q.empty and not accepter_non_verifie and rend.classe.str.startswith("écart de séances non vérifiable").any():
        rapport["avertissements"].append("aucun rendement quotidien démontrable (pas de calendrier officiel) ; "
                                         "relancer avec --accepter-non-verifie pour une analyse étiquetée NON VÉRIFIÉE")
    etiquette = "" if not accepter_non_verifie else " [inclut des intervalles NON VÉRIFIÉS]"
    print("Classes de rendements :", cls)
    module("rendements simples et logarithmiques", "EXÉCUTÉ", f"{len(q)} rendement(s) quotidien(s) retenu(s){etiquette}")

    # 4. performance des cours (hors dividendes)
    perf = []
    for nom, g in [("période", obs)] + [(str(a), g) for a, g in obs.groupby(obs.Date.dt.year)]:
        if len(g) >= 2:
            p = {"periode": nom, "debut": g.Date.iloc[0].date(), "fin": g.Date.iloc[-1].date(),
                 "close_debut": g.Close.iloc[0], "close_fin": g.Close.iloc[-1],
                 "performance_cours": g.Close.iloc[-1] / g.Close.iloc[0] - 1}
            d_split = (meta or {}).get("date_effet_fractionnement")
            if d_split and close_ajuste != "OUI" and g.Date.iloc[0] < pd.Timestamp(d_split) <= g.Date.iloc[-1]:
                p["performance_cours"] = np.nan
                p["note"] = "non calculée : la période traverse le fractionnement et les cours ne sont pas ajustés"
            perf.append(p)
    pd.DataFrame(perf).to_csv(os.path.join(tab, "performance_cours.csv"), index=False)
    module("performance des cours (hors dividendes)", "EXÉCUTÉ",
           "performance de prix uniquement ; n'est pas un rendement total")

    # 5. statistiques descriptives
    sd = pd.DataFrame({"simple": stats_desc(q.rendement_simple), "log": stats_desc(q.rendement_log)})
    sd.to_csv(os.path.join(tab, "stats_descriptives_rendements.csv"))
    pd.DataFrame({"Close": stats_desc(obs.Close), "Volume": stats_desc(obs.Volume)}).to_csv(
        os.path.join(tab, "stats_descriptives_niveaux.csv"))
    module("statistiques descriptives", "EXÉCUTÉ" if len(q) >= 2 else "NON EXÉCUTÉ",
           "" if len(q) >= 2 else "moins de 2 rendements quotidiens")

    # 6. volatilité et drawdown
    if len(q) >= 2:
        vol = {"ecart_type_quotidien_log": q.rendement_log.std(ddof=1), "n": len(q)}
        if seances_par_an:
            if not source_annualisation:
                raise ErreurDonnees("--seances-par-an exige --source-annualisation")
            vol.update(annualisation=f"x sqrt({seances_par_an}) ; source : {source_annualisation}",
                       volatilite_annualisee=vol["ecart_type_quotidien_log"] * np.sqrt(seances_par_an))
        elif cal is not None and cal.statut_seance_officiel.isin(SEANCES_OK).any():
            etab = cal[cal.statut_seance_officiel.isin(SEANCES_OK)]
            par_an = etab.groupby(etab.Date.dt.year).size()
            completes = par_an[[a for a in par_an.index if (etab.Date.dt.year == a).any() and
                                pd.Timestamp(f"{a}-12-31") <= cal.Date.max() and pd.Timestamp(f"{a}-01-01") >= cal.Date.min()]]
            if len(completes):
                n = float(completes.mean())
                vol.update(annualisation=f"x sqrt({n:.1f}) = moyenne des séances établies des années complètes "
                                         f"{list(completes.index)} ({completes.to_dict()})",
                           volatilite_annualisee=vol["ecart_type_quotidien_log"] * np.sqrt(n))
            else:
                vol["annualisation"] = "non effectuée : aucune année complète de calendrier officiel"
        else:
            vol["annualisation"] = "non effectuée : ni calendrier officiel ni hypothèse sourcée"
        fen = 20
        roul = q.set_index("Date").rendement_log.rolling(fen, min_periods=fen).std()
        dd = drawdown(obs.set_index("Date").Close)
        if (meta or {}).get("date_effet_fractionnement") and close_ajuste != "OUI":
            dd_note = "drawdown non significatif à travers le fractionnement (cours non ajustés) : calculé par segment"
            ds = pd.Timestamp(meta["date_effet_fractionnement"])
            dd = pd.concat([drawdown(obs.set_index("Date").Close[:ds - pd.Timedelta(days=1)]),
                            drawdown(obs.set_index("Date").Close[ds:])])
            vol["drawdown_note"] = dd_note
        vol["drawdown_max"] = float(dd.min())
        vol["date_drawdown_max"] = dd.idxmin().date()
        pd.Series(vol).to_csv(os.path.join(tab, "volatilite_drawdown.csv"))
        f, (a1, a2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        a1.plot(roul.index, roul, color="#c55a11")
        a1.set_title(f"Écart type glissant ({fen} rendements quotidiens retenus, non annualisé)")
        a2.fill_between(dd.index, dd, 0, color="#a50f15", alpha=.5)
        a2.set_title("Drawdown du cours")
        figure(f, "volatilite_drawdown.png")
        module("volatilité et drawdown", "EXÉCUTÉ", vol["annualisation"])
    else:
        module("volatilité et drawdown", "NON EXÉCUTÉ", "moins de 2 rendements quotidiens")

    # 7. distributions
    if len(q) >= 10:
        f, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
        a1.hist(q.rendement_log, bins=min(50, max(10, len(q) // 5)), color="#1f4e79")
        a1.set_title(f"Rendements log quotidiens (n={len(q)})")
        try:
            from scipy import stats
            stats.probplot(q.rendement_log, dist="norm", plot=a2)
            a2.set_title("Q-Q plot contre loi normale")
        except Exception:
            a2.text(.1, .5, "scipy indisponible")
        figure(f, "distribution_rendements.png")
        module("distributions des rendements", "EXÉCUTÉ")
    else:
        module("distributions des rendements", "NON EXÉCUTÉ", "moins de 10 rendements quotidiens")

    # 8. VaR / ES historiques
    if len(q) >= 20:
        ve = var_es(q.rendement_simple)
        ve.to_csv(os.path.join(tab, "var_es_historiques.csv"), index=False)
        module("VaR et ES historiques", "EXÉCUTÉ",
               f"n={len(q)} ; horizon une séance ; pertes en rendement simple ; IC bootstrap i.i.d. "
               "(ignore l'autocorrélation et le regroupement de volatilité)")
    else:
        module("VaR et ES historiques", "NON EXÉCUTÉ", "moins de 20 rendements quotidiens")

    # 9. sous-périodes et sensibilité
    if len(q) >= 2:
        bornes = [("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"),
                  ("2025", "2025-01-01", "2025-12-31"), ("2026", "2026-01-01", "2026-12-31")]
        d_split = (meta or {}).get("date_effet_fractionnement")
        if d_split:
            bornes += [("avant fractionnement", "2023-01-01", str(pd.Timestamp(d_split) - pd.Timedelta(days=1))[:10]),
                       ("depuis fractionnement", d_split, "2026-12-31")]
        sp = []
        for nom, a, b in bornes:
            x = q[(q.Date >= a) & (q.Date <= b)].rendement_log
            sp.append({"sous_periode": nom, **stats_desc(x)})
        pd.DataFrame(sp).to_csv(os.path.join(tab, "sous_periodes.csv"), index=False)
        sens = []
        variantes = {
            "référence : quotidiens retenus": q.rendement_log,
            "avec multi-séances (non quotidiens)": rend[rend.classe.str.startswith(("quotidien", "multi"))].rendement_log,
            "sans rendements nuls": q.rendement_log[q.rendement_log != 0],
            "sans 1 % extrêmes (chaque côté)": q.rendement_log[q.rendement_log.between(
                q.rendement_log.quantile(.01), q.rendement_log.quantile(.99))],
        }
        for nom, x in variantes.items():
            d = stats_desc(x)
            d["VaR95_hist"] = float(-np.quantile(x, .05)) if len(x) >= 20 else np.nan
            sens.append({"variante": nom, **d})
        pd.DataFrame(sens).to_csv(os.path.join(tab, "sensibilite.csv"), index=False)
        module("sous-périodes et sensibilité", "EXÉCUTÉ")
    else:
        module("sous-périodes et sensibilité", "NON EXÉCUTÉ", "moins de 2 rendements quotidiens")

    # 10. modules conditionnels
    if indice:
        idx = pd.read_csv(indice, dtype={"Date": str})
        if list(idx.columns) != ["Date", "Close"]:
            raise ErreurDonnees("indice : colonnes Date,Close attendues")
        idx["Date"] = pd.to_datetime(idx.Date, format="%Y-%m-%d")
        ri = classer_intervalles(idx.assign(Volume=0), cal, None, "OUI")
        m = q.merge(ri[ri.classe.str.startswith("quotidien")][["Date_debut", "Date", "rendement_log"]],
                    on=["Date_debut", "Date"], suffixes=("", "_indice"))
        if len(m) >= 20:
            c = np.cov(m.rendement_log, m.rendement_log_indice, ddof=1)
            module("bêta contre indice", "EXÉCUTÉ", f"bêta={c[0, 1] / c[1, 1]:.4f} sur {len(m)} intervalles communs "
                   f"(SLBC {len(q)}, non appariés {len(q) - len(m)})")
        else:
            module("bêta contre indice", "NON EXÉCUTÉ", f"{len(m)} intervalles communs < 20")
    else:
        module("bêta contre indice", "NON EXÉCUTÉ", "aucun indice fourni")
    if taux_sans_risque is not None and source_taux and seances_par_an and len(q) >= 20:
        rf_q = (1 + taux_sans_risque) ** (1 / seances_par_an) - 1
        ex = q.rendement_simple - rf_q
        module("Sharpe", "EXÉCUTÉ", f"{ex.mean() / ex.std(ddof=1) * np.sqrt(seances_par_an):.3f} "
               f"(rf={taux_sans_risque} source : {source_taux} ; {seances_par_an} séances/an : {source_annualisation})")
    else:
        module("Sharpe", "NON EXÉCUTÉ", "exige --taux-sans-risque, --source-taux et --seances-par-an sourcé")
    if dividendes:
        dv = pd.read_csv(dividendes, dtype=str).fillna("")
        ok = dv[dv.get("statut_verification", "").astype(str).str.startswith("VÉRIFIÉ")]
        module("rendement total", "NON EXÉCUTÉ",
               f"{len(ok)} dividende(s) vérifié(s) ; calcul volontairement non automatisé tant que la base "
               "d'ajustement des cours et les dates de détachement ne sont pas toutes établies")
    else:
        module("rendement total", "NON EXÉCUTÉ", "aucun dividende documenté fourni")

    json.dump(rapport, open(os.path.join(sortie, "rapport.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    with zipfile.ZipFile(os.path.join(sortie + "_export.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for racine, _, fs in os.walk(sortie):
            for x in fs:
                z.write(os.path.join(racine, x), os.path.relpath(os.path.join(racine, x), os.path.dirname(sortie) or "."))
    print("Avertissements :", rapport["avertissements"] or "aucun")
    print("La réussite de l'exécution ne prouve pas l'exactitude financière des données.")
    return rapport


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("entree")
    p.add_argument("--sortie", default="resultats")
    p.add_argument("--calendrier")
    p.add_argument("--close-ajuste", choices=["NON", "OUI", "INCONNU"])
    p.add_argument("--seances-par-an", type=float)
    p.add_argument("--source-annualisation")
    p.add_argument("--taux-sans-risque", type=float)
    p.add_argument("--source-taux")
    p.add_argument("--indice")
    p.add_argument("--dividendes")
    p.add_argument("--accepter-non-verifie", action="store_true",
                   help="traiter les intervalles sans calendrier comme quotidiens, avec étiquette NON VÉRIFIÉ")
    a = p.parse_args(argv)
    try:
        executer(a.entree, a.sortie, a.calendrier, a.close_ajuste, a.seances_par_an, a.source_annualisation,
                 a.taux_sans_risque, a.source_taux, a.indice, a.dividendes, a.accepter_non_verifie)
    except ErreurDonnees as e:
        print("ERREUR DONNÉES :", e)
        return 2
    return 0


if __name__ == "__main__" and "ipykernel" not in sys.modules:
    sys.exit(main())
