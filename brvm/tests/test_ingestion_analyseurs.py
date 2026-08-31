"""Analyse de pages : extraction de tableaux et correspondance de colonnes déclarée."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from brvm.config.modeles import CHAMPS_ANALYSABLES, ConfigAnalyseur, Configuration
from brvm.ingestion.analyseurs import AnalyseurTableauHtml, extraire_tableaux, resumer_tableaux
from brvm.ingestion.conversion import CHAMPS
from brvm.ingestion.web import ContexteAnalyse
from brvm.utils.erreurs import ErreurSource

# Page fictive : la mise en page ci-dessous n'imite aucun site réel, elle sert
# uniquement à vérifier le comportement de l'extracteur.
PAGE = """
<html><head><style>td { color: red; }</style></head><body>
<table><tr><th>Info</th></tr><tr><td>tableau sans rapport</td></tr></table>
<table>
  <tr><th>Symbole</th><th>Cours</th><th> Volume </th><th>Veille</th></tr>
  <tr><td>TEST1</td><td>1 000</td><td>500</td><td>995</td></tr>
  <tr><td>TEST2</td><td>2 500</td><td>10</td><td>2 500</td></tr>
  <tr><td></td><td></td><td></td><td></td></tr>
</table>
</body></html>
"""

CONTEXTE = ContexteAnalyse(
    url="https://exemple-test.invalid/cote",
    jour=None,
    horodatage_collecte=datetime(2026, 3, 2, 15, 45, tzinfo=UTC),
)

COLONNES = {
    "Symbole": "ticker",
    "Cours": "cloture",
    "Volume": "volume_titres",
    "Veille": "cours_precedent",
}


def reglage(**extras: object) -> ConfigAnalyseur:
    parametres: dict[str, object] = {
        "type": "tableau_html",
        "index_tableau": 1,
        "colonnes": COLONNES,
        "date_seance_depuis": "jour_de_collecte",
    }
    parametres.update(extras)
    return ConfigAnalyseur(**parametres)  # type: ignore[arg-type]


class TestExtraction:
    def test_tous_les_tableaux_sont_vus(self) -> None:
        assert len(extraire_tableaux(PAGE)) == 2

    def test_cellules_normalisees(self) -> None:
        tableau = extraire_tableaux(PAGE)[1]
        assert tableau[0] == ["Symbole", "Cours", "Volume", "Veille"]
        assert tableau[1] == ["TEST1", "1 000", "500", "995"]

    def test_contenu_de_script_et_style_ignore(self) -> None:
        page = "<table><tr><td>TEST1<script>alert(1)</script></td></tr></table>"
        assert extraire_tableaux(page)[0][0] == ["TEST1"]

    def test_saut_de_ligne_devient_espace(self) -> None:
        page = "<table><tr><td>TEST1<br>suite</td></tr></table>"
        assert extraire_tableaux(page)[0][0] == ["TEST1 suite"]

    def test_tableau_imbrique(self) -> None:
        page = "<table><tr><td><table><tr><td>interne</td></tr></table></td></tr></table>"
        tableaux = extraire_tableaux(page)
        assert len(tableaux) == 2
        assert ["interne"] in tableaux[0]

    def test_page_sans_tableau(self) -> None:
        assert extraire_tableaux("<html><p>rien</p></html>") == []

    def test_balises_non_fermees_ne_perdent_pas_les_donnees(self) -> None:
        """Une page mal formée est fréquente ; on récupère ce qui est lisible."""
        page = "<table><tr><td>TEST1<td>1000"
        tableaux = extraire_tableaux(page)
        assert tableaux and tableaux[0][0] == ["TEST1", "1000"]

    def test_resume_liste_les_index_et_entetes(self) -> None:
        resume = resumer_tableaux(PAGE)
        assert "index_tableau: 1" in resume
        assert "Symbole" in resume

    def test_resume_sans_tableau(self) -> None:
        assert "Aucun tableau" in resumer_tableaux("<p>rien</p>")


class TestCorrespondanceDeColonnes:
    def test_lignes_extraites(self, configuration: Configuration) -> None:
        analyseur = AnalyseurTableauHtml("test", reglage(), configuration)
        lignes = analyseur.analyser(PAGE, CONTEXTE)
        assert len(lignes) == 2
        assert lignes[0]["ticker"] == "TEST1"
        assert lignes[0]["cloture"] == "1 000"
        assert lignes[0]["cours_precedent"] == "995"

    def test_entetes_insensibles_a_la_casse_et_aux_espaces(
        self, configuration: Configuration
    ) -> None:
        colonnes = {"  symbole ": "ticker", "COURS": "cloture"}
        analyseur = AnalyseurTableauHtml("test", reglage(colonnes=colonnes), configuration)
        assert analyseur.analyser(PAGE, CONTEXTE)[0]["ticker"] == "TEST1"

    def test_ligne_sans_ticker_ignoree(self, configuration: Configuration) -> None:
        analyseur = AnalyseurTableauHtml("test", reglage(), configuration)
        assert all(ligne["ticker"] for ligne in analyseur.analyser(PAGE, CONTEXTE))

    def test_index_de_tableau_hors_page(self, configuration: Configuration) -> None:
        analyseur = AnalyseurTableauHtml("test", reglage(index_tableau=9), configuration)
        with pytest.raises(ErreurSource, match="ne contient que 2 tableau"):
            analyseur.analyser(PAGE, CONTEXTE)

    def test_entete_declare_introuvable(self, configuration: Configuration) -> None:
        """Si le site change ses en-têtes, la collecte s'arrête et le dit — elle ne
        renvoie pas un tableau vide."""
        colonnes = {**COLONNES, "Capitalisation": "volume_xof"}
        analyseur = AnalyseurTableauHtml("test", reglage(colonnes=colonnes), configuration)
        with pytest.raises(ErreurSource) as capture:
            analyseur.analyser(PAGE, CONTEXTE)
        message = str(capture.value)
        assert "volume_xof" in message
        assert "Symbole" in message

    def test_tableau_sans_ligne_de_donnees(self, configuration: Configuration) -> None:
        page = "<table><tr><th>Symbole</th><th>Cours</th></tr></table>"
        analyseur = AnalyseurTableauHtml(
            "test", reglage(index_tableau=0, colonnes={"Symbole": "ticker"}), configuration
        )
        with pytest.raises(ErreurSource, match="ligne de données"):
            analyseur.analyser(page, CONTEXTE)


class TestDateDeSeance:
    def test_jour_demande_prioritaire(self, configuration: Configuration) -> None:
        analyseur = AnalyseurTableauHtml("test", reglage(), configuration)
        contexte = ContexteAnalyse(
            url=CONTEXTE.url,
            jour=date(2026, 3, 3),
            horodatage_collecte=CONTEXTE.horodatage_collecte,
        )
        assert analyseur.analyser(PAGE, contexte)[0]["date_seance"] == "2026-03-03"

    def test_date_ramenee_au_fuseau_du_marche(self, configuration: Configuration) -> None:
        """Une collecte tardive ne doit pas dater la séance du lendemain."""
        analyseur = AnalyseurTableauHtml("test", reglage(), configuration)
        contexte = ContexteAnalyse(
            url=CONTEXTE.url,
            jour=None,
            horodatage_collecte=datetime(2026, 3, 2, 23, 30, tzinfo=UTC),
        )
        # Africa/Abidjan est à UTC+00 : 23 h 30 UTC reste le 2 mars localement.
        assert analyseur.analyser(PAGE, contexte)[0]["date_seance"] == "2026-03-02"

    def test_colonne_de_date_utilisee_si_declaree(self, configuration: Configuration) -> None:
        page = (
            "<table><tr><th>Symbole</th><th>Séance</th><th>Cours</th></tr>"
            "<tr><td>TEST1</td><td>2026-03-02</td><td>1000</td></tr></table>"
        )
        analyseur = AnalyseurTableauHtml(
            "test",
            reglage(
                index_tableau=0,
                colonnes={"Symbole": "ticker", "Séance": "date_seance", "Cours": "cloture"},
                date_seance_depuis="colonne",
            ),
            configuration,
        )
        assert analyseur.analyser(page, CONTEXTE)[0]["date_seance"] == "2026-03-02"


def test_vocabulaire_de_champs_aligne_entre_config_et_ingestion() -> None:
    """La configuration valide les noms de champs sans importer l'ingestion.

    Les deux listes doivent donc rester identiques, sous peine d'accepter en
    configuration un champ que l'analyseur ignorerait ensuite en silence.
    """
    assert frozenset(CHAMPS) == CHAMPS_ANALYSABLES
