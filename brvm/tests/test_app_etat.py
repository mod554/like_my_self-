"""État du système : une seule lecture, servie à toutes les sorties.

Le point vérifié ici n'est pas qu'un chiffre soit juste — les couches
précédentes s'en chargent — mais que **toutes les restitutions montrent
exactement le même**, et que la fraîcheur voyage avec elles.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from brvm.app.etat import MOTIF_PERFORMANCE_ABSENTE, assembler
from brvm.app.export import exporter, horodater, restituer
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import MethodeValorisation, SensOperation, StatutSeance
from brvm.domain.modeles import Cotation, Transaction
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotInstruments, DepotTransactions

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)


@pytest.fixture
def base_peuplee(
    base: BaseDonnees,
    configuration: Configuration,
    fabrique_cotation: Callable[..., Cotation],
    calendrier: CalendrierSeances,
) -> BaseDonnees:
    """Une base minimale mais réaliste : un instrument, un achat, une série."""
    from brvm.ingestion.univers import charger_univers

    DepotInstruments(base).enregistrer_lot(charger_univers(configuration.marche.fichier_univers))
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
                    cloture=1000 + (jour.day % 7) * 10,
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
    return base


class TestAssemblage:
    def test_compose_le_portefeuille_et_ses_series(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert [ligne.ticker for ligne in etat.portefeuille.lignes] == ["TEST1"]
        assert "TEST1" in etat.valeurs
        assert etat.valeurs["TEST1"].serie.barres

    def test_les_deux_methodes_sont_conservees(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """PMP et FIFO répondent à deux questions : aucune n'est écartée."""
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert set(etat.suivis) == {MethodeValorisation.PMP, MethodeValorisation.FIFO}

    def test_la_borne_de_connaissance_est_respectee(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """Rejoué au 10 mars, l'état ne doit connaître aucune séance postérieure."""
        etat = assembler(
            base_peuplee, configuration, calendrier, instant=INSTANT, jusqu_a=date(2026, 3, 10)
        )
        derniere = etat.valeurs["TEST1"].serie.barres[-1]
        assert derniere.date_seance <= date(2026, 3, 10)
        ligne = etat.portefeuille.lignes[0]
        assert ligne.date_cours is not None and ligne.date_cours <= date(2026, 3, 10)

    def test_une_valeur_sans_cotation_est_signalee_pas_ignoree(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        DepotTransactions(base_peuplee).enregistrer(
            Transaction(
                identifiant="T2",
                ticker="TEST2",
                date_operation=date(2026, 3, 2),
                sens=SensOperation.ACHAT,
                quantite=5,
                cours_unitaire=2000,
            )
        )
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert "TEST2" not in etat.valeurs
        assert any("TEST2" in message for message in etat.avertissements)
        assert "TEST2" in [ligne.ticker for ligne in etat.portefeuille.lignes_non_valorisees]

    def test_aucune_performance_chiffree_nest_publiee(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """Un rendement calculé sans compte espèces serait faux dès la première
        ligne soldée : le système dit pourquoi il n'en publie pas."""
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert etat.motif_performance_absente == MOTIF_PERFORMANCE_ABSENTE
        assert "compte espèces" in etat.motif_performance_absente


class TestFraicheur:
    def test_le_bandeau_donne_lage_de_la_donnee_la_plus_ancienne(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert etat.horodatage_le_plus_ancien is not None
        assert "Donnée la plus ancienne" in etat.entete_fraicheur()

    def test_donnee_perimee_au_dela_du_seuil_declare(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        tardif = INSTANT.replace(year=2027)
        etat = assembler(base_peuplee, configuration, calendrier, instant=tardif)
        assert etat.donnee_perimee() is True


class TestRestitutions:
    def test_le_texte_porte_le_bandeau_et_la_mention(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        texte = restituer(etat)
        assert etat.entete_fraicheur() in texte
        assert "Aucun conseil d'investissement" in texte
        assert "TEST1" in texte

    def test_une_ligne_non_valorisee_est_dite_telle_quelle(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        DepotTransactions(base_peuplee).enregistrer(
            Transaction(
                identifiant="T2",
                ticker="TEST2",
                date_operation=date(2026, 3, 2),
                sens=SensOperation.ACHAT,
                quantite=5,
                cours_unitaire=2000,
            )
        )
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        assert "TEST2" in restituer(etat)
        assert "NON VALORISÉE" in restituer(etat)

    def test_le_classeur_a_cinq_feuilles_toutes_bandeautees(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        chemin = exporter(etat, tmp_path / "rapport.xlsx")

        classeur = openpyxl.load_workbook(chemin)
        assert classeur.sheetnames == [
            "Positions",
            "Signaux",
            "Risque",
            "Anomalies",
            "Collectes",
        ]
        for nom in classeur.sheetnames:
            feuille = classeur[nom]
            assert feuille["A1"].value == f"État au {etat.instant.isoformat()}"
            assert feuille["A2"].value == etat.entete_fraicheur()
            assert "Aucun conseil" in str(feuille["A3"].value)

    def test_le_classeur_montre_les_memes_totaux_que_le_texte(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        """Deux sorties, une source : elles ne peuvent pas diverger."""
        openpyxl = pytest.importorskip("openpyxl")
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        classeur = openpyxl.load_workbook(exporter(etat, tmp_path / "r.xlsx"))
        feuille = classeur["Positions"]
        totaux = {
            rangee[0].value: rangee[1].value
            for rangee in feuille.iter_rows(min_row=6)
            if isinstance(rangee[0].value, str) and rangee[0].value.startswith("TOTAL")
        }
        assert totaux["TOTAL valeur"] == etat.portefeuille.valeur_totale
        assert totaux["TOTAL coût engagé"] == etat.portefeuille.cout_total

    def test_la_feuille_signaux_porte_la_date_dexecution(
        self,
        base_peuplee: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        etat = assembler(base_peuplee, configuration, calendrier, instant=INSTANT)
        feuille = openpyxl.load_workbook(exporter(etat, tmp_path / "r.xlsx"))["Signaux"]
        entetes = [cellule.value for cellule in feuille[5]]
        assert "Exécutable à partir du" in entetes
        assert "Séance de constat" in entetes

    def test_le_nom_du_fichier_est_horodate(self) -> None:
        """Un export non daté est ininterprétable trois mois plus tard."""
        cible = horodater(Path("rapports/portefeuille.xlsx"), INSTANT)
        assert cible.name == "portefeuille_20260320-1600.xlsx"

    def test_extension_ajoutee_si_absente(self) -> None:
        assert horodater(Path("rapports/etat"), INSTANT).suffix == ".xlsx"
