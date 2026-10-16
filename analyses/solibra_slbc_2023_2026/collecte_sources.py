#!/usr/bin/env python3
"""Collecte brute SOLIBRA (SLBC.CI), 2023-01-01 -> 2026-10-15 (16 intervalles trimestriels).

Principe : on enregistre ce qui est réellement reçu (octets bruts + SHA-256),
jamais une valeur supposée. Toute tentative, réussie ou non, est journalisée
dans preuves/COLLECTE_TENTATIVES.csv avec l'erreur observée.

Usage (Colab ou poste avec accès réseau) :
    python3 collecte_sources.py            # toutes les sources
    python3 collecte_sources.py sika       # une seule famille de sources

Aucune dépendance hors bibliothèque standard.

Points NON vérifiés depuis l'environnement de rédaction (réseau bloqué) :
- l'API Sika Finance (POST /api/general/GetHistos) et ses noms de champs ;
- les paramètres éventuels attendus par l'URL de téléchargement Ilboursa ;
- la structure HTML des pages BRVM listant les bulletins officiels.
Le script conserve donc la réponse brute sans l'interpréter ; la
normalisation (normaliser_sika.py) échoue explicitement si les champs
attendus sont absents.
"""
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ICI = os.path.dirname(os.path.abspath(__file__))
PREUVES = os.path.join(ICI, "preuves")
BRUT = os.path.join(PREUVES, "brut")
JOURNAL = os.path.join(PREUVES, "COLLECTE_TENTATIVES.csv")

DEBUT = dt.date(2023, 1, 1)
FIN = dt.date(2026, 10, 15)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (audit-recherche)"
CHAMPS_JOURNAL = [
    "horodatage_utc", "source", "serie", "periode_debut", "periode_fin",
    "methode", "url", "corps_requete", "statut_http", "octets",
    "content_type", "fichier", "sha256", "resultat", "erreur_observee",
]


def fenetres_trimestrielles(debut=DEBUT, fin=FIN):
    """Fenêtres calendaires de trois mois maximum couvrant [debut, fin]."""
    out, d = [], debut
    while d <= fin:
        m = d.month + 3
        y = d.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        f = min(dt.date(y, m, 1) - dt.timedelta(days=1), fin)
        out.append((d, f))
        d = f + dt.timedelta(days=1)
    return out


def journaliser(ligne):
    neuf = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CHAMPS_JOURNAL)
        if neuf:
            w.writeheader()
        w.writerow({k: ligne.get(k, "") for k in CHAMPS_JOURNAL})


def recuperer(source, serie, url, nom_fichier, periode=(None, None),
              data=None, headers=None):
    """Télécharge, enregistre les octets bruts et journalise. Retourne le chemin ou None."""
    os.makedirs(BRUT, exist_ok=True)
    h = {"User-Agent": UA}
    h.update(headers or {})
    corps = data.decode("utf-8") if isinstance(data, bytes) else (data or "")
    ligne = {
        "horodatage_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source, "serie": serie,
        "periode_debut": periode[0].isoformat() if periode[0] else "",
        "periode_fin": periode[1].isoformat() if periode[1] else "",
        "methode": "POST" if data else "GET", "url": url, "corps_requete": corps,
    }
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            octets = r.read()
            ligne["statut_http"] = r.status
            ligne["content_type"] = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        ligne.update(statut_http=e.code, resultat="NON RÉCUPÉRÉ",
                     erreur_observee=f"HTTPError {e.code} {e.reason}")
        journaliser(ligne)
        return None
    except Exception as e:  # réseau, DNS, proxy, TLS...
        ligne.update(resultat="NON RÉCUPÉRÉ",
                     erreur_observee=f"{type(e).__name__}: {e}"[:300])
        journaliser(ligne)
        return None
    chemin = os.path.join(BRUT, nom_fichier)
    with open(chemin, "wb") as fh:
        fh.write(octets)
    ligne.update(octets=len(octets), fichier=os.path.relpath(chemin, ICI),
                 sha256=hashlib.sha256(octets).hexdigest(),
                 resultat="RÉCUPÉRÉ" if octets else "RÉPONSE VIDE")
    journaliser(ligne)
    return chemin


def collecter_sika():
    url = "https://www.sikafinance.com/api/general/GetHistos"
    for serie, ticker in (("SLBC.CI", "SLBC.CI"),):
        for d, f in fenetres_trimestrielles():
            corps = json.dumps({"ticker": ticker, "datedeb": d.isoformat(),
                                "datefin": f.isoformat(), "xperiod": "0"}).encode()
            recuperer("sikafinance", serie, url,
                      f"sika_{ticker}_{d:%Y%m%d}_{f:%Y%m%d}.json", (d, f), data=corps,
                      headers={"Content-Type": "application/json",
                               "Referer": f"https://www.sikafinance.com/marches/historiques/{ticker}"})
            time.sleep(1.5)
    # page HTML publique, archivée telle quelle comme preuve d'affichage
    recuperer("sikafinance", "SLBC.CI", "https://www.sikafinance.com/marches/historiques/SLBC.CI",
              "sika_page_historiques_SLBC.CI.html")


def collecter_ilboursa():
    # URL fournie par le commanditaire ; les paramètres de période éventuels ne
    # sont pas documentés publiquement : on tente l'URL brute puis une variante
    # par fenêtre trimestrielle, et l'on conserve chaque réponse.
    base = "https://www.ilboursa.com/marches/download/SLBC.CI"
    recuperer("ilboursa", "SLBC.CI", base, "ilboursa_SLBC.CI_brut.bin")
    for d, f in fenetres_trimestrielles():
        q = urllib.parse.urlencode({"datedeb": d.strftime("%d/%m/%Y"), "datefin": f.strftime("%d/%m/%Y")})
        recuperer("ilboursa", "SLBC.CI", f"{base}?{q}",
                  f"ilboursa_SLBC.CI_{d:%Y%m%d}_{f:%Y%m%d}.bin", (d, f))
        time.sleep(1.5)


def collecter_brvm(max_pages=40):
    """Pages de liste des bulletins officiels, puis PDF datés de la période."""
    pdfs = set()
    for p in range(max_pages):
        url = f"https://www.brvm.org/fr/bulletins-officiels-de-la-cote?page={p}"
        chemin = recuperer("brvm.org", "BULLETINS", url, f"brvm_liste_bulletins_p{p:03d}.html")
        if not chemin:
            break
        html = open(chemin, encoding="utf-8", errors="replace").read()
        trouves = set(re.findall(r'href="([^"]+\.pdf)"', html, flags=re.I))
        if not trouves:
            break
        pdfs |= {urllib.parse.urljoin(url, t) for t in trouves}
        time.sleep(1.5)
    for u in sorted(pdfs):
        nom = os.path.basename(urllib.parse.urlparse(u).path)
        if re.search(r"202[3-6]", nom):
            recuperer("brvm.org", "BULLETIN_PDF", u, f"brvm_{nom}")
            time.sleep(1.5)
    for p in range(10):
        recuperer("brvm.org", "AVIS", f"https://www.brvm.org/fr/avis?page={p}",
                  f"brvm_liste_avis_p{p:03d}.html")
    recuperer("brvm.org", "INDICES", "https://www.brvm.org/fr/indices", "brvm_indices.html")


SOURCES = {"sika": collecter_sika, "ilboursa": collecter_ilboursa, "brvm": collecter_brvm}

if __name__ == "__main__":
    os.makedirs(PREUVES, exist_ok=True)
    for nom in (sys.argv[1:] or list(SOURCES)):
        SOURCES[nom]()
    print("Journal :", JOURNAL)
