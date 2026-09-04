"""Tableau de bord : chaque onglet porte son bandeau de fraîcheur.

Streamlit n'est pas installé pour les tests, et n'a pas besoin de l'être : les
fonctions d'affichage reçoivent l'objet `st` en paramètre, ce qui permet de
vérifier ce qui est affiché sans lancer de serveur. C'est aussi la preuve que ce
module ne calcule rien : il ne fait que rendre l'état qu'on lui donne.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from brvm.app.etat import EtatSysteme, assembler
from brvm.app.tableau_de_bord import (
    _config_depuis_arguments,
    _onglet_donnees,
    _onglet_portefeuille,
    _onglet_risque,
    _onglet_signaux,
    charger_etat,
)
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import SensOperation, StatutSeance
from brvm.domain.modeles import Cotation, Transaction
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotTransactions

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)
ONGLETS: list[Callable[[Any, EtatSysteme], None]] = [
    _onglet_portefeuille,
    _onglet_signaux,
    _onglet_risque,
    _onglet_donnees,
]


class StreamlitSimule:
    """Doublure minimale : retient tout ce qui a été affiché, par catégorie.

    Volontairement bête. Une doublure qui se réécrit elle-même ne prouve rien
    sur le code qu'elle est censée observer.
    """

    def __init__(self) -> None:
        self.affiche: dict[str, list[str]] = {
            nom: [] for nom in ("info", "error", "warning", "caption", "write", "text", "subheader")
        }
        self.metriques: list[tuple[str, str]] = []
        self.tables: list[list[dict[str, Any]]] = []

    def _noter(self, categorie: str) -> Callable[..., None]:
        def enregistrer(texte: Any = "", *_: Any, **__: Any) -> None:
            self.affiche[categorie].append(str(texte))

        return enregistrer

    def __getattr__(self, nom: str) -> Any:
        if nom in {"info", "error", "warning", "caption", "write", "text", "subheader"}:
            return self._noter(nom)
        raise AttributeError(f"Le tableau de bord utilise st.{nom}, non simulé ici.")

    def metric(self, libelle: str, valeur: str) -> None:
        self.metriques.append((libelle, valeur))

    def columns(self, nombre: int) -> list[StreamlitSimule]:
        return [self for _ in range(nombre)]

    def dataframe(self, donnees: list[dict[str, Any]], width: str = "") -> None:
        self.tables.append(donnees)

    @property
    def tout(self) -> str:
        return "\n".join(texte for lot in self.affiche.values() for texte in lot)


def simulateur() -> StreamlitSimule:
    return StreamlitSimule()


@pytest.fixture
def etat(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
) -> EtatSysteme:
    DepotTransactions(base).enregistrer(
        Transaction(
            identifiant="T1",
            ticker="TEST1",
            date_operation=date(2026, 3, 2),
            sens=SensOperation.ACHAT,
            quantite=10,
            cours_unitaire=1000,
        )
    )
    jour = date(2026, 3, 2)
    cotations = []
    while jour <= date(2026, 3, 20):
        if calendrier.est_jour_de_seance(jour):
            horodatage = datetime(jour.year, jour.month, jour.day, 15, 0, tzinfo=UTC)
            cotations.append(
                fabrique_cotation(
                    jour=jour,
                    cloture=1000 + (jour.day % 5) * 10,
                    ticker="TEST1",
                    source="fichier_manuel",
                    statut=StatutSeance.COTEE,
                    volume=500,
                    horodatage_donnee=horodatage,
                    horodatage_collecte=horodatage,
                )
            )
        jour += timedelta(days=1)
    DepotCotations(base).enregistrer_lot(cotations)
    return assembler(base, configuration, calendrier, instant=INSTANT)


class TestBandeauDeFraicheur:
    def test_chaque_onglet_affiche_lhorodatage_le_plus_ancien(self, etat: EtatSysteme) -> None:
        """C'est la seule information qui conditionne toutes les autres."""
        for onglet in ONGLETS:
            st = simulateur()
            onglet(st, etat)
            assert etat.entete_fraicheur() in st.tout, onglet.__name__

    def test_une_donnee_perimee_passe_en_erreur_pas_en_information(
        self,
        base: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        etat: EtatSysteme,
    ) -> None:
        tardif = assembler(base, configuration, calendrier, instant=INSTANT.replace(year=2027))
        st = simulateur()
        _onglet_portefeuille(st, tardif)
        assert st.affiche["error"]
        assert not st.affiche["info"]
        assert "pas aujourd'hui" in st.affiche["error"][0]


class TestContenu:
    def test_le_portefeuille_montre_ses_totaux_et_le_motif_de_performance(
        self, etat: EtatSysteme
    ) -> None:
        st = simulateur()
        _onglet_portefeuille(st, etat)
        libelles = [libelle for libelle, _ in st.metriques]
        assert "Coût engagé" in libelles
        assert "Valeur" in libelles
        assert any("valorisation" in texte.lower() for texte in st.affiche["caption"]), (
            "le motif d'absence de performance doit être affiché"
        )

    def test_les_lignes_portent_lage_de_leur_cours(self, etat: EtatSysteme) -> None:
        st = simulateur()
        _onglet_portefeuille(st, etat)
        assert "Âge (min)" in st.tables[0][0]
        assert st.tables[0][0]["Valeur"] == "TEST1"

    def test_longlet_signaux_rappelle_quil_ne_conseille_rien(self, etat: EtatSysteme) -> None:
        st = simulateur()
        _onglet_signaux(st, etat)
        assert any("pas des recommandations" in texte for texte in st.affiche["caption"])
        assert any("exécutable le" in texte for texte in st.affiche["caption"])

    def test_longlet_risque_rappelle_le_delai_de_debouclage(self, etat: EtatSysteme) -> None:
        st = simulateur()
        _onglet_risque(st, etat)
        assert "Concentration" in st.affiche["subheader"]
        assert "Liquidité" in st.affiche["subheader"]
        assert any("semaines" in texte for texte in st.affiche["caption"])

    def test_longlet_donnees_montre_le_journal_des_collectes(self, etat: EtatSysteme) -> None:
        st = simulateur()
        _onglet_donnees(st, etat)
        assert "Journal des collectes" in st.affiche["subheader"]
        assert "Anomalies ouvertes" in st.affiche["subheader"]


class TestChargement:
    def test_charge_letat_sans_ecrire_ni_collecter(
        self, dossier_config: Path, tmp_path: Path
    ) -> None:
        chemin = dossier_config / "config_valide.yaml"
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        brut["general"]["base_donnees"] = str(tmp_path / "tb.sqlite3")
        brut["general"]["repertoire_donnees"] = str(tmp_path)
        cible = dossier_config / "tb.yaml"
        cible.write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")

        etat = charger_etat(cible)
        assert etat.portefeuille.lignes == ()
        assert etat.entete_fraicheur()

    def test_le_chemin_de_configuration_est_obligatoire(self) -> None:
        with pytest.raises(SystemExit):
            _config_depuis_arguments([])

    def test_les_arguments_de_streamlit_sont_ignores(self) -> None:
        """Streamlit passe ses propres options : elles ne doivent pas gêner."""
        chemin = _config_depuis_arguments(["--server.port", "8080", "--config", "config/x.yaml"])
        assert chemin == Path("config/x.yaml")
