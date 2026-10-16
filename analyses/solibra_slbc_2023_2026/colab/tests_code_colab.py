#!/usr/bin/env python3
"""Tests du code (pas des données). Les séries utilisées ici sont SYNTHÉTIQUES,
générées en mémoire dans un dossier temporaire, et ne sont jamais écrites dans
les livrables. Elles servent uniquement à vérifier le comportement du code.

    python3 tests_code_colab.py [chemin_du_ZIP_livré]
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import analyse_solibra_colab as A  # noqa: E402

RES = []


def test(nom, f):
    try:
        f()
        RES.append((nom, "OK", ""))
    except Exception as e:
        RES.append((nom, "ÉCHEC", f"{type(e).__name__}: {e}"))


def doit_echouer(f, motif):
    try:
        f()
    except A.ErreurDonnees as e:
        assert motif in str(e), f"message inattendu : {e}"
        return
    raise AssertionError("aucune ErreurDonnees levée")


def fixture(tmp):
    """Série SYNTHÉTIQUE : calendrier fictif, suspension fictive, fractionnement fictif."""
    jours = pd.bdate_range("2023-01-02", "2025-12-31")
    rng = np.random.default_rng(1)
    cal = pd.DataFrame({"Date": jours.strftime("%Y-%m-%d"), "statut_seance_officiel": "SEANCE", "SLBC_statut": "RETENU"})
    cal.loc[cal.Date == "2023-05-01", "statut_seance_officiel"] = "FERMETURE"
    susp = (cal.Date >= "2024-04-02") & (cal.Date <= "2024-09-11")
    cal.loc[susp, "SLBC_statut"] = "TITRE SUSPENDU"
    seances = cal[(cal.statut_seance_officiel == "SEANCE") & ~susp].Date.tolist()
    garde = [d for d in seances if rng.random() > 0.3]  # séances sans observation
    prix = 30000 * np.exp(np.cumsum(rng.normal(0, 0.02, len(garde))))
    prix = np.where(np.array(garde) < "2024-09-30", prix, prix / 10)
    vol = rng.integers(0, 500, len(garde))
    serie = pd.DataFrame({"Date": garde, "Close": np.round(prix, 2), "Volume": vol})
    serie = serie[serie.Volume > 0]
    meta = {"close_ajuste_fractionnement": "NON", "date_effet_fractionnement": "2024-09-30",
            "suspensions_confirmees": [["2024-04-02", "2024-09-11"]]}
    p_csv = os.path.join(tmp, A.NOM_ANALYSE)
    serie.to_csv(p_csv, index=False)
    cal.to_csv(os.path.join(tmp, A.NOM_CAL), index=False)
    json.dump(meta, open(os.path.join(tmp, A.NOM_META), "w"))
    p_zip = os.path.join(tmp, "synthetique.zip")
    with zipfile.ZipFile(p_zip, "w") as z:
        for n in (A.NOM_ANALYSE, A.NOM_CAL, A.NOM_META):
            z.write(os.path.join(tmp, n), "dossier/" + n)
    return serie, cal, p_csv, p_zip


def main():
    tmp = tempfile.mkdtemp()
    serie, cal, p_csv, p_zip = fixture(tmp)

    def zip_synthetique():
        r = A.executer(p_zip, os.path.join(tmp, "out1"))
        cls = r["classes_rendements"]
        assert cls.get("traverse une suspension") == 1, cls
        assert cls.get("traverse le fractionnement (cours non ajustés)") == 1, cls
        assert any(k.startswith("multi-séances") for k in cls), cls
        assert r["modules"]["VaR et ES historiques"]["statut"] == "EXÉCUTÉ"
        assert r["modules"]["bêta contre indice"]["statut"] == "NON EXÉCUTÉ"
        assert r["modules"]["Sharpe"]["statut"] == "NON EXÉCUTÉ"
        assert r["modules"]["rendement total"]["statut"] == "NON EXÉCUTÉ"
        assert "sqrt" in r["modules"]["volatilité et drawdown"]["detail"]
        rc = pd.read_csv(os.path.join(tmp, "out1", "tables", "rendements_classes.csv"))
        q = rc[rc.classe == "quotidien (séances successives)"]
        assert q.rendement_simple.abs().max() < 0.5, "un saut de fractionnement est compté comme quotidien"
        for f in ("cours_volumes.png", "volatilite_drawdown.png", "distribution_rendements.png"):
            assert os.path.getsize(os.path.join(tmp, "out1", "figures", f)) > 1000
        assert zipfile.ZipFile(os.path.join(tmp, "out1_export.zip")).testzip() is None
    test("ZIP synthétique : classement suspension / fractionnement / multi-séances, modules, exports", zip_synthetique)

    def csv_extension_zip():
        p = os.path.join(tmp, "en_fait_un_csv.zip")
        shutil.copy(p_csv, p)
        f, t = A.lire_entree(p)
        assert t == "texte"
    test("CSV nommé .zip : type réel détecté, pas de BadZipFile", csv_extension_zip)

    def html_nomme_zip():
        p = os.path.join(tmp, "page.zip")
        open(p, "w").write("<html>erreur 403</html>")
        doit_echouer(lambda: A.lire_entree(p), "html")
    test("HTML nommé .zip : erreur explicite", html_nomme_zip)

    def zip_tronque():
        p = os.path.join(tmp, "tronque.zip")
        open(p, "wb").write(open(p_zip, "rb").read()[:300])
        doit_echouer(lambda: A.lire_entree(p), "ZIP")
    test("ZIP tronqué : erreur explicite, pas d'exception brute", zip_tronque)

    def mauvaises_colonnes():
        doit_echouer(lambda: A.charger_serie(b"date,close,volume\n2025-01-02,1,1\n"), "colonnes")
    test("Colonnes non conformes refusées", mauvaises_colonnes)

    def anomalies_non_silencieuses():
        txt = b"Date,Close,Volume\n2025-01-02,100,5\n2025-01-03,-1,5\n2025-01-06,101,\n2025-01-06,102,3\n02/01/2025,99,1\n2025-01-08,1,5\n2025-01-09,100,2.5\n"
        df, an = A.charger_serie(txt)
        assert len(df) == 7 and len(an) == 5, (len(df), len(an), an.motif_anomalie.tolist())
    test("Anomalies signalées, aucune ligne supprimée du fichier", anomalies_non_silencieuses)

    def sans_calendrier():
        p = os.path.join(tmp, "seul.csv")
        shutil.copy(p_csv, p)
        r = A.executer(p, os.path.join(tmp, "out2"))
        assert r["modules"]["statistiques descriptives"]["statut"] == "NON EXÉCUTÉ"
        r2 = A.executer(p, os.path.join(tmp, "out3"), accepter_non_verifie=True)
        assert "NON VÉRIFIÉS" in r2["modules"]["rendements simples et logarithmiques"]["detail"]
    test("Sans calendrier : aucun rendement déclaré quotidien sauf option étiquetée", sans_calendrier)

    def annualisation_sourcee():
        doit_echouer(lambda: A.executer(p_zip, os.path.join(tmp, "out4"), seances_par_an=250), "source")
    test("Annualisation imposée sans source refusée", annualisation_sourcee)

    def beta_indice():
        idx = pd.DataFrame({"Date": cal.Date[cal.statut_seance_officiel == "SEANCE"]})
        idx["Close"] = 200 * np.exp(np.cumsum(np.random.default_rng(2).normal(0, .01, len(idx))))
        pi = os.path.join(tmp, "indice.csv")
        idx.to_csv(pi, index=False)
        r = A.executer(p_zip, os.path.join(tmp, "out5"), indice=pi)
        assert r["modules"]["bêta contre indice"]["statut"] == "EXÉCUTÉ"
    test("Bêta exécuté seulement avec indice fourni (indice synthétique)", beta_indice)

    def serie_vide_reelle():
        p = sys.argv[1] if len(sys.argv) > 1 else None
        if not p:
            raise AssertionError("ZIP livré non indiqué")
        r = A.executer(p, os.path.join(tmp, "out6"))
        assert r["lignes_fichier"] == 0 and "série vide" in r["avertissements"]
    test("ZIP livré (série réelle actuelle) : lecture et arrêt propre si vide", serie_vide_reelle)

    def cli():
        out = subprocess.run([sys.executable, os.path.join(ICI, "analyse_solibra_colab.py"),
                              os.path.join(tmp, "page.zip")], capture_output=True, text=True)
        assert out.returncode == 2 and "ERREUR DONNÉES" in out.stdout, out.stdout + out.stderr
    test("Ligne de commande : code retour 2 et message sur entrée invalide", cli)

    print("\n=== RÉSULTATS DES TESTS DU CODE (données synthétiques, hors livrables) ===")
    for n, s, d in RES:
        print(f"[{s}] {n} {d}")
    shutil.rmtree(tmp)
    return 0 if all(s == "OK" for _, s, _ in RES) else 1


if __name__ == "__main__":
    sys.exit(main())
