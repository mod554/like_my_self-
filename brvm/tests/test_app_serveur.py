"""Serveur de l'interface : routes, garde-fous, refus.

Un vrai serveur est démarré sur un port éphémère et interrogé par HTTP. Vérifier
le routage en appelant les fonctions directement laisserait passer précisément
ce qui compte ici : la traversée de dossier et les en-têtes.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from brvm.app.serveur import RACINE_WEB, TYPES, construire_serveur
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances


@pytest.fixture
def serveur(
    configuration: Configuration, calendrier: CalendrierSeances, tmp_path: Path
) -> Iterator[str]:
    """Un serveur réel, sur un port libre choisi par le système."""
    reglages = configuration.model_copy(
        update={
            "general": configuration.general.model_copy(
                update={"base_donnees": tmp_path / "interface.sqlite3"}
            )
        }
    )
    instance: ThreadingHTTPServer = construire_serveur(
        reglages, hote="127.0.0.1", port=0, calendrier=calendrier
    )
    fil = threading.Thread(target=instance.serve_forever, daemon=True)
    fil.start()
    try:
        yield f"http://127.0.0.1:{instance.server_address[1]}"
    finally:
        instance.shutdown()
        instance.server_close()


def demander(url: str) -> tuple[int, bytes, dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=10) as reponse:
            return reponse.status, reponse.read(), dict(reponse.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


class TestRoutes:
    def test_la_racine_sert_la_page(self, serveur: str) -> None:
        code, contenu, entetes = demander(serveur + "/")
        assert code == 200
        assert entetes["Content-Type"].startswith("text/html")
        assert b"Suivi de portefeuille" in contenu

    def test_l_etat_est_servi_en_json(self, serveur: str) -> None:
        code, contenu, entetes = demander(serveur + "/api/etat")
        assert code == 200
        assert entetes["Content-Type"].startswith("application/json")
        charge = json.loads(contenu)
        assert "fraicheur" in charge
        assert "portefeuille" in charge

    def test_la_feuille_de_style_et_le_script_sont_servis(self, serveur: str) -> None:
        for fichier, type_attendu in (("style.css", "text/css"), ("app.js", "text/javascript")):
            code, contenu, entetes = demander(f"{serveur}/{fichier}")
            assert code == 200, fichier
            assert entetes["Content-Type"].startswith(type_attendu)
            assert contenu

    def test_les_polices_sont_servies_et_mises_en_cache(self, serveur: str) -> None:
        """Elles ne changent jamais ; les rappeler à chaque visite serait absurde."""
        police = next(iter((RACINE_WEB / "polices").glob("*.woff2")))
        code, contenu, entetes = demander(f"{serveur}/polices/{police.name}")
        assert code == 200
        assert entetes["Content-Type"] == "font/woff2"
        assert "max-age" in entetes["Cache-Control"]
        assert contenu[:4] == b"wOF2"

    def test_l_etat_n_est_jamais_mis_en_cache(self, serveur: str) -> None:
        """Un état en cache, c'est un portefeuille affiché tel qu'il était."""
        _, _, entetes = demander(serveur + "/api/etat")
        assert entetes["Cache-Control"] == "no-store"


class TestRefus:
    def test_la_traversee_de_dossier_n_atteint_rien(self, serveur: str) -> None:
        """Le chemin est résolu puis vérifié comme descendant du dossier web."""
        for tentative in (
            "/../serveur.py",
            "/../../config/config.exemple.yaml",
            "/polices/../../etat.py",
        ):
            code, _, _ = demander(serveur + tentative)
            assert code == 404, tentative

    def test_une_extension_non_declaree_n_est_pas_servie(self, serveur: str) -> None:
        """Mieux vaut un 404 qu'un fichier remis avec le mauvais type."""
        piege = RACINE_WEB / "piege.txt"
        piege.write_text("secret", encoding="utf-8")
        try:
            code, _, _ = demander(serveur + "/piege.txt")
            assert code == 404
        finally:
            piege.unlink()

    def test_une_ressource_inconnue_donne_404(self, serveur: str) -> None:
        code, contenu, _ = demander(serveur + "/inexistant.js")
        assert code == 404
        assert "erreur" in json.loads(contenu)

    def test_toutes_les_extensions_servies_sont_declarees(self) -> None:
        """Aucun fichier livré ne doit dépendre d'un type deviné."""
        presentes = {f.suffix.lower() for f in RACINE_WEB.rglob("*") if f.is_file()}
        assert presentes <= set(TYPES), presentes - set(TYPES)


class TestEnTetes:
    def test_la_politique_de_contenu_interdit_tout_appel_distant(self, serveur: str) -> None:
        """Si quelqu'un ajoute un script de CDN, la page cassera visiblement
        plutôt que d'exfiltrer discrètement la composition d'un portefeuille."""
        _, _, entetes = demander(serveur + "/")
        politique = entetes["Content-Security-Policy"]
        assert "default-src 'self'" in politique
        assert "connect-src 'self'" in politique
        assert "frame-ancestors 'none'" in politique
        # Aucune échappatoire : ni script ni style en ligne.
        assert "unsafe-inline" not in politique
        assert "unsafe-eval" not in politique

    def test_le_type_annonce_fait_foi(self, serveur: str) -> None:
        _, _, entetes = demander(serveur + "/")
        assert entetes["X-Content-Type-Options"] == "nosniff"
        assert entetes["Referrer-Policy"] == "no-referrer"


class TestInterfaceLivree:
    """L'interface doit fonctionner hors ligne : rien ne sort vers l'extérieur."""

    def test_aucune_ressource_distante_dans_les_fichiers(self) -> None:
        for fichier in ("index.html", "style.css", "app.js"):
            texte = (RACINE_WEB / fichier).read_text(encoding="utf-8")
            for interdit in ("https://fonts.", "cdn.", "unpkg", "cdnjs", "googleapis"):
                assert interdit not in texte, f"{fichier} appelle {interdit}"

    def test_aucun_style_en_ligne_dans_le_document(self) -> None:
        """La politique de contenu les refuserait, et ils dispersent le système."""
        html = (RACINE_WEB / "index.html").read_text(encoding="utf-8")
        assert 'style="' not in html
        assert "<style" not in html

    def test_les_polices_declarees_existent(self) -> None:
        css = (RACINE_WEB / "style.css").read_text(encoding="utf-8")
        import re

        for chemin in re.findall(r'url\("([^"]+)"\)', css):
            assert (RACINE_WEB / chemin).is_file(), chemin


class TestRouteMarche:
    """Le criblage de la cote, servi en JSON.

    Le point le plus important n'est pas le contenu — les tests de
    ``brvm.market`` s'en chargent — mais que le capital demandé soit lu
    strictement : une saisie fautive réinterprétée en zéro produirait une page
    annonçant qu'aucune valeur n'est finançable, ce qui serait faux.
    """

    def test_repond_meme_sur_une_base_vide(self, serveur: str) -> None:
        code, contenu, _ = demander(serveur + "/api/marche")
        assert code == 200
        charge = json.loads(contenu)
        assert charge["univers"] == 0
        assert charge["propositions"] == {}
        assert "mention" in charge

    def test_sans_capital_aucune_repartition_n_est_supposee(self, serveur: str) -> None:
        charge = json.loads(demander(serveur + "/api/marche")[1])
        assert charge["propositions"] == {}

    @pytest.mark.parametrize(
        ("requete", "extrait"),
        [
            ("capital=abc", "Capital illisible"),
            ("capital=1,5", "Capital illisible"),
            ("capital=-1", "négatif"),
            ("capital=999999999999999", "au-delà du maximum"),
        ],
    )
    def test_capital_fautif_est_refuse_et_non_reinterprete(
        self, serveur: str, requete: str, extrait: str
    ) -> None:
        code, contenu, _ = demander(f"{serveur}/api/marche?{requete}")
        assert code == 400
        assert extrait in json.loads(contenu)["erreur"]

    def test_capital_vide_vaut_absence_pas_erreur(self, serveur: str) -> None:
        code, contenu, _ = demander(serveur + "/api/marche?capital=")
        assert code == 200
        assert json.loads(contenu)["propositions"] == {}

    def test_les_entetes_de_prudence_couvrent_aussi_cette_route(self, serveur: str) -> None:
        _, _, entetes = demander(serveur + "/api/marche")
        assert "default-src 'self'" in entetes["Content-Security-Policy"]
        assert entetes["Cache-Control"] == "no-store"
