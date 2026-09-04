"""Analyse de pages : extraction de tableaux et correspondance de colonnes déclarée."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

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


# Reproduction de la STRUCTURE observée sur une capture de page de cote : un
# tableau d'indices, puis un tableau d'actions dont le code valeur n'existe que
# dans l'adresse du lien. Les chiffres et les noms ci-dessous sont fictifs.
PAGE_COTE = """
<html><body>
<h2>Les indices</h2>
<table>
  <tr><th>Nom</th><th>Dernier</th></tr>
  <tr><td><a href="/marches/cotation_TESTIDX">INDICE DE TEST</a></td><td>100.00</td></tr>
</table>
<h2>Les actions cotées</h2>
<table>
  <tr><th>Nom</th><th>Ouverture</th><th>+Haut</th><th>+Bas</th>
      <th>Volume (titres)</th><th>Volume (XOF)</th><th>Dernier</th><th>Variation</th></tr>
  <tr><td><a href="/marches/cotation_TEST1.ci">SOCIETE DE TEST UN</a></td>
      <td>1 990</td><td>1 990</td><td>1 945</td><td>2 649</td><td>5 152 305</td>
      <td><b>1 945</b></td><td>-2.51%</td></tr>
  <tr><td><a href="/marches/cotation_TEST2.sn">SOCIETE DE TEST DEUX</a></td>
      <td>28 400</td><td>28 425</td><td>28 400</td><td>4 872</td><td>138 486 600</td>
      <td><b>28 425</b></td><td>0.09%</td></tr>
  <tr><td><a href="/marches/cotation_TEST3.ci">SOCIETE SANS ECHANGE</a></td>
      <td>2 395</td><td>2 395</td><td>2 395</td><td>0</td><td>0</td>
      <td><b>2 395</b></td><td>0.00%</td></tr>
</table>
</body></html>
"""

REGLAGE_COTE = {
    "type": "tableau_html",
    "index_tableau": 1,
    "colonnes": {
        "Ouverture": "ouverture",
        "+Haut": "plus_haut",
        "+Bas": "plus_bas",
        "Volume (titres)": "volume_titres",
        "Volume (XOF)": "volume_xof",
        "Dernier": "cloture",
    },
    "colonnes_lien": {"Nom": {"champ": "ticker", "motif": "cotation_([A-Za-z0-9]+)"}},
    "date_seance_depuis": "jour_de_collecte",
}


class TestColonneLien:
    def analyseur(self, configuration: Configuration, **extras: object) -> AnalyseurTableauHtml:
        reglage = {**REGLAGE_COTE, **extras}
        return AnalyseurTableauHtml("cote", ConfigAnalyseur(**reglage), configuration)  # type: ignore[arg-type]

    def test_ticker_extrait_du_lien(self, configuration: Configuration) -> None:
        """Le code valeur n'est pas affiché : il n'existe que dans l'adresse du lien."""
        lignes = self.analyseur(configuration).analyser(PAGE_COTE, CONTEXTE)
        assert [ligne["ticker"] for ligne in lignes] == ["TEST1", "TEST2", "TEST3"]

    def test_colonnes_texte_et_lien_combinees(self, configuration: Configuration) -> None:
        premiere = self.analyseur(configuration).analyser(PAGE_COTE, CONTEXTE)[0]
        assert premiere["ouverture"] == "1 990"
        assert premiere["plus_bas"] == "1 945"
        assert premiere["volume_titres"] == "2 649"
        assert premiere["volume_xof"] == "5 152 305"
        assert premiere["cloture"] == "1 945"

    def test_conversion_complete_en_cotation(self, configuration: Configuration) -> None:
        """De la page brute à la cotation validée, sans intervention manuelle."""
        from brvm.ingestion.conversion import ConvertisseurCotation

        lignes = self.analyseur(configuration).analyser(PAGE_COTE, CONTEXTE)
        convertisseur = ConvertisseurCotation("cote", configuration)
        cotation, _ = convertisseur.convertir(lignes[1], collecte=CONTEXTE.horodatage_collecte)
        assert cotation.cotation is not None
        assert cotation.cotation.ticker == "TEST2"
        assert cotation.cotation.cloture == 28_425
        assert cotation.cotation.volume_xof == 138_486_600

    def test_volume_nul_donne_statut_inconnu_et_non_sans_transaction(
        self, configuration: Configuration
    ) -> None:
        """La page ne dit pas s'il n'y a pas eu d'échange ou si le volume n'est pas
        publié. Le système refuse de trancher."""
        from brvm.domain.enums import StatutSeance
        from brvm.ingestion.conversion import ConvertisseurCotation

        lignes = self.analyseur(configuration).analyser(PAGE_COTE, CONTEXTE)
        ligne, avertissement = ConvertisseurCotation("cote", configuration).convertir(
            lignes[2], collecte=CONTEXTE.horodatage_collecte
        )
        assert ligne.cotation is not None
        assert ligne.cotation.statut_seance is StatutSeance.INCONNU
        assert ligne.cotation.cours_effectivement_traite is None
        assert avertissement is not None

    def test_mauvais_index_prend_le_tableau_des_indices(self, configuration: Configuration) -> None:
        """Se tromper de tableau doit échouer bruyamment, pas rendre des indices
        déguisés en actions."""
        with pytest.raises(ErreurSource) as capture:
            self.analyseur(configuration, index_tableau=0).analyser(PAGE_COTE, CONTEXTE)
        assert "Ouverture" in str(capture.value) or "introuvables" in str(capture.value)

    def test_motif_qui_ne_correspond_a_rien_est_signale(self, configuration: Configuration) -> None:
        """Une liste vide passerait pour « le marché n'a rien coté » : on refuse."""
        reglage = {
            **REGLAGE_COTE,
            "colonnes_lien": {"Nom": {"champ": "ticker", "motif": "valeur_([A-Z]+)"}},
        }
        analyseur = AnalyseurTableauHtml("cote", ConfigAnalyseur(**reglage), configuration)  # type: ignore[arg-type]
        with pytest.raises(ErreurSource) as capture:
            analyseur.analyser(PAGE_COTE, CONTEXTE)
        message = str(capture.value)
        assert "motifs d'extraction" in message
        assert "cotation_TEST1.ci" in message


class TestValidationDesColonnesLien:
    def test_motif_sans_groupe_de_capture_refuse(self) -> None:
        with pytest.raises(ValidationError, match="groupe de capture"):
            ConfigAnalyseur(
                type="tableau_html",
                colonnes_lien={"Nom": {"champ": "ticker", "motif": "cotation_[A-Z]+"}},  # type: ignore[dict-item]
            )

    def test_expression_reguliere_invalide_refusee(self) -> None:
        with pytest.raises(ValidationError, match="régulière invalide"):
            ConfigAnalyseur(
                type="tableau_html",
                colonnes_lien={"Nom": {"champ": "ticker", "motif": "cotation_(["}},  # type: ignore[dict-item]
            )

    def test_colonne_declaree_deux_fois_refusee(self) -> None:
        with pytest.raises(ValidationError, match="à la fois en texte et en lien"):
            ConfigAnalyseur(
                type="tableau_html",
                colonnes={"Nom": "ticker"},
                colonnes_lien={"Nom": {"champ": "ticker", "motif": "cotation_([A-Z]+)"}},  # type: ignore[dict-item]
            )

    def test_ticker_peut_venir_du_seul_lien(self) -> None:
        reglage = ConfigAnalyseur(
            type="tableau_html",
            colonnes={"Dernier": "cloture"},
            colonnes_lien={"Nom": {"champ": "ticker", "motif": "cotation_([A-Z0-9]+)"}},  # type: ignore[dict-item]
            date_seance_depuis="jour_de_collecte",
        )
        assert reglage.colonnes_lien["Nom"].champ == "ticker"
