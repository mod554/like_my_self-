"""Détection d'anomalies : ce qui est signalé, avec quelle gravité, et jamais corrigé."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import pytest

from brvm.config.modeles import ConfigSource, Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import GraviteAnomalie, StatutFiabilite, StatutSeance
from brvm.domain.modeles import Cotation
from brvm.ingestion.anomalies import (
    Constat,
    DetecteurAnomalies,
    TypeAnomalie,
    statut_depuis_constats,
)

MAINTENANT = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)
SEANCE = date(2026, 3, 2)  # lundi
SAMEDI = date(2026, 3, 7)


@pytest.fixture
def reglage_source(configuration: Configuration) -> ConfigSource:
    return configuration.sources[0]


@pytest.fixture
def detecteur(configuration: Configuration, calendrier: CalendrierSeances) -> DetecteurAnomalies:
    return DetecteurAnomalies(configuration, calendrier)


def types(constats: list[Constat]) -> set[TypeAnomalie]:
    return {constat.type_anomalie for constat in constats}


class TestVariation:
    def test_variation_au_dela_du_seuil_met_en_quarantaine(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        """Le seuil réglementaire vient de la configuration ; aucune valeur codée en dur."""
        cotation = fabrique_cotation(jour=SEANCE, cloture=1200, cours_precedent=1000)
        constats = detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        assert TypeAnomalie.VARIATION_HORS_SEUIL in types(constats)
        assert statut_depuis_constats(constats) is StatutFiabilite.QUARANTAINE

    def test_variation_dans_le_seuil_ne_signale_rien(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=1050, cours_precedent=1000)
        assert detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT) == []

    def test_variation_exactement_au_seuil_acceptee(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=1100, cours_precedent=1000)
        assert detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT) == []

    def test_baisse_hors_seuil_signalee_aussi(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=800, cours_precedent=1000)
        assert TypeAnomalie.VARIATION_HORS_SEUIL in types(
            detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        )

    def test_gravite_configurable(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        souple = configuration.model_copy(
            update={
                "ingestion": configuration.ingestion.model_copy(
                    update={"quarantaine_si_variation_hors_seuil": False}
                )
            }
        )
        detecteur = DetecteurAnomalies(souple, calendrier)
        cotation = fabrique_cotation(jour=SEANCE, cloture=1200, cours_precedent=1000)
        constats = detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        assert statut_depuis_constats(constats) is StatutFiabilite.SUSPECTE


class TestVolume:
    def test_montant_hors_encadrement_haut_bas(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(
            jour=SEANCE,
            cloture=1000,
            plus_haut=1010,
            plus_bas=990,
            volume=100,
            volume_xof=5_000_000,
        )
        assert TypeAnomalie.VOLUME_INCOHERENT in types(
            detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        )

    def test_montant_dans_l_encadrement_accepte(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        """Une séance traite à plusieurs cours : l'encadrement va du plus bas au plus haut."""
        cotation = fabrique_cotation(
            jour=SEANCE,
            cloture=1000,
            plus_haut=1010,
            plus_bas=990,
            volume=100,
            volume_xof=99_500,
        )
        assert detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT) == []

    def test_sans_haut_ni_bas_le_controle_se_fait_sur_la_cloture(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=1000, volume=100, volume_xof=250_000)
        assert TypeAnomalie.VOLUME_INCOHERENT in types(
            detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        )

    def test_montant_non_publie_n_est_pas_une_anomalie(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=1000, volume=100)
        assert detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT) == []


class TestCarnet:
    def test_fourchette_inversee(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(
            jour=SEANCE, cloture=1000, meilleure_limite_achat=1010, meilleure_limite_vente=990
        )
        constats = detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        assert TypeAnomalie.FOURCHETTE_INVERSEE in types(constats)
        assert statut_depuis_constats(constats) is StatutFiabilite.SUSPECTE

    def test_fourchette_normale_acceptee(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(
            jour=SEANCE, cloture=1000, meilleure_limite_achat=990, meilleure_limite_vente=1010
        )
        assert detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT) == []


class TestCalendrierEtFraicheur:
    def test_seance_un_samedi_est_bloquante(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        """Une cotation un jour non ouvré trahit presque toujours une analyse décalée."""
        cotation = fabrique_cotation(jour=SAMEDI, cloture=1000)
        constats = detecteur.examiner(
            cotation, reglage_source, maintenant=datetime(2026, 3, 9, 16, 0, tzinfo=UTC)
        )
        assert TypeAnomalie.SEANCE_HORS_CALENDRIER in types(constats)
        assert statut_depuis_constats(constats) is StatutFiabilite.QUARANTAINE

    def test_date_future_bloquante(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(
            jour=date(2026, 3, 10),
            cloture=1000,
            horodatage_donnee=datetime(2026, 3, 10, 15, 0, tzinfo=UTC),
            horodatage_collecte=datetime(2026, 3, 10, 15, 0, tzinfo=UTC),
        )
        constats = detecteur.examiner(cotation, reglage_source, maintenant=MAINTENANT)
        assert TypeAnomalie.DATE_FUTURE in types(constats)

    def test_date_hors_couverture_signalee_sans_bloquer(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        """Le calendrier ne couvre pas 2027 : le contrôle est inopérant, on le dit."""
        cotation = fabrique_cotation(
            jour=date(2027, 1, 4),
            cloture=1000,
            horodatage_donnee=datetime(2027, 1, 4, 15, 0, tzinfo=UTC),
            horodatage_collecte=datetime(2027, 1, 4, 15, 0, tzinfo=UTC),
        )
        constats = detecteur.examiner(
            cotation, reglage_source, maintenant=datetime(2027, 1, 4, 16, 0, tzinfo=UTC)
        )
        assert TypeAnomalie.SEANCE_HORS_CALENDRIER in types(constats)
        assert statut_depuis_constats(constats) is StatutFiabilite.SUSPECTE

    def test_donnee_perimee(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotation = fabrique_cotation(jour=SEANCE, cloture=1000)
        constats = detecteur.examiner(
            cotation, reglage_source, maintenant=datetime(2026, 3, 5, 16, 0, tzinfo=UTC)
        )
        assert TypeAnomalie.DONNEE_PERIMEE in types(constats)


class TestReferentiel:
    def test_ticker_inconnu_signale_sans_creer_l_instrument(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        detecteur = DetecteurAnomalies(configuration, calendrier, tickers_connus={"TEST2"})
        constats = detecteur.examiner(
            fabrique_cotation(jour=SEANCE, cloture=1000), reglage_source, maintenant=MAINTENANT
        )
        assert TypeAnomalie.TICKER_INCONNU in types(constats)
        assert statut_depuis_constats(constats) is StatutFiabilite.SUSPECTE

    def test_ticker_connu_accepte(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        detecteur = DetecteurAnomalies(configuration, calendrier, tickers_connus={"TEST1"})
        assert (
            detecteur.examiner(
                fabrique_cotation(jour=SEANCE, cloture=1000),
                reglage_source,
                maintenant=MAINTENANT,
            )
            == []
        )

    def test_referentiel_absent_desactive_le_controle(
        self,
        detecteur: DetecteurAnomalies,
        reglage_source: ConfigSource,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        assert (
            detecteur.examiner(
                fabrique_cotation(jour=SEANCE, cloture=1000),
                reglage_source,
                maintenant=MAINTENANT,
            )
            == []
        )


class TestControlesDeLot:
    def test_doublon_dans_une_collecte(
        self, detecteur: DetecteurAnomalies, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        cotations = [
            fabrique_cotation(jour=SEANCE, cloture=1000),
            fabrique_cotation(jour=SEANCE, cloture=1010),
        ]
        constats = detecteur.examiner_lot(cotations)
        assert 0 not in constats
        assert constats[1][0].type_anomalie is TypeAnomalie.DOUBLON
        assert constats[1][0].gravite is GraviteAnomalie.BLOQUANTE

    def test_lot_sans_doublon(
        self, detecteur: DetecteurAnomalies, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        cotations = [
            fabrique_cotation(jour=SEANCE),
            fabrique_cotation(jour=date(2026, 3, 3)),
        ]
        assert detecteur.examiner_lot(cotations) == {}

    def test_seances_manquantes_ne_sont_pas_des_seances_sans_transaction(
        self, detecteur: DetecteurAnomalies, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        recues = [fabrique_cotation(jour=date(2026, 3, 2))]
        constats = detecteur.seances_manquantes(recues, date(2026, 3, 2), date(2026, 3, 4), "TEST1")
        assert [constat.date_seance for constat in constats] == [
            date(2026, 3, 3),
            date(2026, 3, 4),
        ]
        assert StatutSeance.SANS_TRANSACTION.value in constats[0].message

    def test_seances_manquantes_hors_couverture(self, detecteur: DetecteurAnomalies) -> None:
        constats = detecteur.seances_manquantes([], date(2027, 1, 1), date(2027, 1, 5), "TEST1")
        assert len(constats) == 1
        assert "non vérifiables" in constats[0].message


class TestStatutDeFiabilite:
    def test_aucun_constat_donne_fiable(self) -> None:
        assert statut_depuis_constats([]) is StatutFiabilite.FIABLE

    def test_info_seule_reste_fiable(self) -> None:
        constat = Constat(TypeAnomalie.DOUBLON, GraviteAnomalie.INFO, "note")
        assert statut_depuis_constats([constat]) is StatutFiabilite.FIABLE

    def test_la_gravite_la_plus_forte_l_emporte(self) -> None:
        constats = [
            Constat(TypeAnomalie.TICKER_INCONNU, GraviteAnomalie.AVERTISSEMENT, "a"),
            Constat(TypeAnomalie.DOUBLON, GraviteAnomalie.BLOQUANTE, "b"),
        ]
        assert statut_depuis_constats(constats) is StatutFiabilite.QUARANTAINE
