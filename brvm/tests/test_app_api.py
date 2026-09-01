"""Sérialisation pour l'interface web.

Ce qui est vérifié ici : l'interface reçoit **exactement** ce que l'état contient,
sans arrondi de complaisance et sans zéro de remplacement. Une valeur absente
traverse la sérialisation en restant absente.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest

from brvm.app.api import TRAME_SEANCES, courbe, serialiser, trame
from brvm.app.etat import EtatSysteme, assembler
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import SensOperation, StatutSeance
from brvm.domain.modeles import Cotation, Transaction
from brvm.indicators.serie import OrigineValeur
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotCotations, DepotTransactions

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)


@pytest.fixture
def etat(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
) -> EtatSysteme:
    """Un portefeuille à deux lignes : une cotée par intermittence, une sans cours.

    L'intermittence n'est pas un cas limite sur cette place : c'est le cas normal,
    et une interface conçue sur une valeur qui cote tous les jours ne le montre
    jamais.
    """
    depot = DepotTransactions(base)
    depot.enregistrer(
        Transaction(
            identifiant="T1",
            ticker="TEST1",
            date_operation=date(2026, 3, 2),
            sens=SensOperation.ACHAT,
            quantite=10,
            cours_unitaire=1000,
        )
    )
    depot.enregistrer(
        Transaction(
            identifiant="T2",
            ticker="TEST2",
            date_operation=date(2026, 3, 2),
            sens=SensOperation.ACHAT,
            quantite=5,
            cours_unitaire=2000,
        )
    )

    cotations = []
    jour = date(2026, 3, 2)
    numero = 0
    while jour <= date(2026, 3, 20):
        if calendrier.est_jour_de_seance(jour):
            numero += 1
            horodatage = datetime(jour.year, jour.month, jour.day, 15, 0, tzinfo=UTC)
            cote = numero % 3 != 0  # deux séances cotées sur trois
            cotations.append(
                fabrique_cotation(
                    jour=jour,
                    cloture=1000 + numero * 10 if cote else None,
                    ticker="TEST1",
                    source="fichier_manuel",
                    statut=StatutSeance.COTEE if cote else StatutSeance.SANS_TRANSACTION,
                    volume=400 if cote else 0,
                    horodatage_donnee=horodatage,
                    horodatage_collecte=horodatage,
                )
            )
        jour += timedelta(days=1)
    DepotCotations(base).enregistrer_lot(cotations)
    return assembler(base, configuration, calendrier, instant=INSTANT)


class TestCharge:
    def test_la_charge_est_du_json_valide(self, etat: EtatSysteme) -> None:
        """Elle traverse un aller-retour JSON sans perdre ni Decimal ni date."""
        charge = json.loads(json.dumps(serialiser(etat), ensure_ascii=False))
        assert charge["portefeuille"]["cout_total"] == etat.portefeuille.cout_total
        assert charge["instant"] == etat.instant.isoformat()

    def test_la_fraicheur_voyage_avec_son_seuil(self, etat: EtatSysteme) -> None:
        """Un âge sans le seuil toléré ne se juge pas."""
        f = serialiser(etat)["fraicheur"]
        assert f["horodatage"] is not None
        assert f["age_minutes"] is not None
        assert f["seuil_minutes"] == etat.configuration.alertes.age_donnee_max_minutes
        assert f["texte"] == etat.entete_fraicheur()

    def test_aucune_performance_chiffree(self, etat: EtatSysteme) -> None:
        performance = serialiser(etat)["performance"]
        assert performance["disponible"] is False
        assert "compte espèces" in performance["motif"]

    def test_les_deux_methodes_sont_transmises(self, etat: EtatSysteme) -> None:
        """PMP et FIFO répondent à deux questions : l'interface reçoit les deux."""
        assert set(serialiser(etat)["plus_values_realisees"]) == {"PMP", "FIFO"}


class TestValeursAbsentes:
    def test_une_ligne_sans_cours_ne_vaut_pas_zero(self, etat: EtatSysteme) -> None:
        """Le pire résultat possible serait un zéro qui se lit comme une mesure."""
        lignes = {poste["ticker"]: poste for poste in serialiser(etat)["portefeuille"]["lignes"]}
        sans_cours = lignes["TEST2"]
        assert sans_cours["valorisee"] is False
        assert sans_cours["cours"] is None
        assert sans_cours["valeur"] is None
        assert sans_cours["motif_indisponible"]
        assert "TEST2" in serialiser(etat)["portefeuille"]["non_valorisees"]

    def test_un_decimal_absent_reste_absent(self, etat: EtatSysteme) -> None:
        lignes = {poste["ticker"]: poste for poste in serialiser(etat)["portefeuille"]["lignes"]}
        assert lignes["TEST2"]["poids"] is None


class TestTrame:
    """La signature de l'interface : la texture du silence derrière chaque cours."""

    def test_la_trame_compte_les_seances_reellement_cotees(self, etat: EtatSysteme) -> None:
        donnees = trame(etat.valeurs["TEST1"].serie)
        assert donnees["attendues"] == len(donnees["seances"])
        assert 0 < donnees["cotees"] < donnees["attendues"]
        cotees = sum(1 for s in donnees["seances"] if s["origine"] == OrigineValeur.COTEE.value)
        assert cotees == donnees["cotees"]

    def test_chaque_seance_porte_son_origine(self, etat: EtatSysteme) -> None:
        origines = {s["origine"] for s in trame(etat.valeurs["TEST1"].serie)["seances"]}
        assert origines <= {"COTEE", "REPORTEE", "ABSENTE"}
        assert "COTEE" in origines

    def test_la_derniere_seance_cotee_est_datee(self, etat: EtatSysteme) -> None:
        """Sans elle, « il y a 4 jours » ne dit pas de quelle séance il s'agit."""
        assert trame(etat.valeurs["TEST1"].serie)["derniere_cotee"] is not None

    def test_la_profondeur_est_bornee(self, etat: EtatSysteme) -> None:
        assert len(trame(etat.valeurs["TEST1"].serie)["seances"]) <= TRAME_SEANCES

    def test_chaque_ligne_valorisee_porte_sa_trame(self, etat: EtatSysteme) -> None:
        lignes = {poste["ticker"]: poste for poste in serialiser(etat)["portefeuille"]["lignes"]}
        assert lignes["TEST1"]["trame"] is not None
        # Une valeur sans aucune cotation n'a pas de trame : l'interface le dit,
        # elle n'affiche pas une trame vide qui se lirait comme « rien n'a coté ».
        assert lignes["TEST2"]["trame"] is None


class TestCourbe:
    def test_chaque_point_sait_sil_a_ete_observe(self, etat: EtatSysteme) -> None:
        """Un point reporté est transmis, mais marqué : la vue le trace en
        pointillé plutôt que de lisser une tendance qui n'a pas eu lieu."""
        points = courbe(etat.valeurs["TEST1"].serie)
        assert points
        assert all("cotee" in point for point in points)
        assert any(point["cotee"] for point in points)

    def test_aucun_point_sans_cours(self, etat: EtatSysteme) -> None:
        assert all(point["cloture"] is not None for point in courbe(etat.valeurs["TEST1"].serie))

    def test_les_points_sont_ordonnes(self, etat: EtatSysteme) -> None:
        dates = [point["date"] for point in courbe(etat.valeurs["TEST1"].serie)]
        assert dates == sorted(dates)


class TestRisque:
    def test_chaque_concentration_porte_sa_limite(self, etat: EtatSysteme) -> None:
        """Un poids sans sa limite ne se juge pas : la jauge a besoin des deux."""
        for constat in serialiser(etat)["risque"]["concentrations"]:
            assert constat["poids"] is not None
            assert constat["limite"] is not None
            assert isinstance(constat["respecte"], bool)

    def test_une_liquidite_non_mesurable_le_dit(self, etat: EtatSysteme) -> None:
        for constat in serialiser(etat)["risque"]["liquidites"]:
            if not constat["mesurable"]:
                assert constat["motif_indisponible"]
                assert constat["seances_pour_deboucler"] is None
