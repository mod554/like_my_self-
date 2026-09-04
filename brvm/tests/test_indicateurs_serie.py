"""Série technique : report borné, distinction des origines, ajustement."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import StatutFiabilite, StatutSeance, TypeOst
from brvm.domain.modeles import Cotation, OperationSurTitre
from brvm.indicators.serie import OrigineValeur, SerieTechnique, construire_serie
from brvm.utils.erreurs import ErreurValidation

LUNDI = date(2026, 3, 2)


class TestConstruction:
    def test_une_barre_par_seance_du_calendrier(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, 1010, 1020, 1030, 1040])
        assert len(serie) == 5
        assert serie.dates() == [date(2026, 3, jour) for jour in range(2, 7)]

    def test_le_week_end_n_est_pas_un_trou(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Samedi et dimanche ne sont pas des séances manquantes : ils n'existent pas."""
        serie = fabrique_serie([1000] * 7)
        assert serie.dates()[4] == date(2026, 3, 6)  # vendredi
        assert serie.dates()[5] == date(2026, 3, 9)  # lundi suivant
        assert serie.nb_absentes() == 0

    def test_serie_vide_refusee(
        self, calendrier: CalendrierSeances, configuration: Configuration
    ) -> None:
        with pytest.raises(ErreurValidation, match="Aucune cotation exploitable"):
            construire_serie([], calendrier, configuration)

    def test_quarantaine_ecartee_et_signalee(
        self,
        calendrier: CalendrierSeances,
        configuration: Configuration,
        fabrique_cotation: Callable[..., Cotation],
    ) -> None:
        cotations = [
            fabrique_cotation(jour=date(2026, 3, 2), cloture=1000),
            fabrique_cotation(
                jour=date(2026, 3, 3),
                cloture=9999,
                statut_fiabilite=StatutFiabilite.QUARANTAINE,
            ),
            fabrique_cotation(jour=date(2026, 3, 4), cloture=1010),
        ]
        serie = construire_serie(cotations, calendrier, configuration)
        assert serie.barres[1].origine is OrigineValeur.REPORTEE
        assert serie.barres[1].cloture == Decimal("1000.000000")
        assert any("quarantaine" in message for message in serie.avertissements)


class TestReportBorne:
    def test_seance_sans_transaction_est_reportee(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, None, 1020])
        assert serie.barres[1].origine is OrigineValeur.REPORTEE
        assert serie.barres[1].cloture == Decimal("1000.000000")
        assert serie.barres[1].anciennete == 1

    def test_au_dela_de_la_limite_le_trou_reste_un_trou(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """La configuration de test autorise trois séances de report."""
        serie = fabrique_serie([1000, None, None, None, None, 1050])
        origines = [barre.origine for barre in serie.barres]
        assert origines[1:4] == [OrigineValeur.REPORTEE] * 3
        assert origines[4] is OrigineValeur.ABSENTE
        assert serie.barres[4].cloture is None

    def test_le_compteur_repart_apres_une_cotation(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, None, 1020, None, None])
        assert [barre.anciennete for barre in serie.barres] == [0, 1, 0, 1, 2]

    def test_une_seance_reportee_n_a_ni_amplitude_ni_volume(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Inventer un haut égal à la clôture affirmerait une volatilité nulle."""
        barre = fabrique_serie([1000, None, 1020]).barres[1]
        assert barre.haut is None and barre.bas is None and barre.ouverture is None
        assert barre.volume == 0

    def test_taux_de_remplissage(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        serie = fabrique_serie([1000, None, None, 1030])
        assert serie.taux_remplissage() == Decimal("0.5")
        assert serie.nb_cotees() == 2
        assert serie.nb_reportees() == 2

    def test_serie_tres_creuse_declenche_un_avertissement(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, None, None, 1030, None, None, 1060])
        assert any("cours reporté" in message for message in serie.avertissements)


class TestSousSeries:
    def test_barres_cotees(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        serie = fabrique_serie([1000, None, 1020, None, 1040])
        assert [barre.cloture for barre in serie.barres_cotees()] == [
            Decimal("1000.000000"),
            Decimal("1020.000000"),
            Decimal("1040.000000"),
        ]
        assert serie.index_cotees() == [0, 2, 4]

    def test_volume_moyen_ignore_les_seances_sans_echange(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Diviser par des jours où rien ne pouvait s'échanger fausserait la mesure."""
        serie = fabrique_serie([1000, None, 1020], volume=100)
        assert serie.volume_moyen() == Decimal(100)

    def test_montant_moyen(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        serie = fabrique_serie([1000, 2000], volume=10)
        assert serie.montant_moyen_xof() == Decimal(15000)

    def test_fourchette_absente_si_non_publiee(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        assert fabrique_serie([1000, 1010]).fourchette_moyenne() is None

    def test_fourchette_moyenne_si_publiee(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie(
            [1000, 1000], meilleure_limite_achat=990, meilleure_limite_vente=1010
        )
        assert serie.fourchette_moyenne() == Decimal("0.02")


class TestAjustement:
    def test_les_indicateurs_tournent_sur_la_serie_ajustee(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Sans ajustement, un détachement se lit comme une chute de marché."""
        dividende = OperationSurTitre(
            identifiant="DIV1",
            ticker="TEST1",
            type_ost=TypeOst.DIVIDENDE,
            date_ex=date(2026, 3, 4),
            montant_brut_par_action=100,
            source="fixture",
        )
        serie = fabrique_serie([1000, 1000, 900], operations=[dividende])
        # Facteur (1000-100)/1000 = 0,9 appliqué aux séances antérieures au détachement.
        assert serie.barres[0].cloture == Decimal("900.000000")
        assert serie.barres[1].cloture == Decimal("900.000000")
        assert serie.barres[2].cloture == Decimal("900.000000")

    def test_ohlc_ajuste_du_meme_facteur(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Un haut brut avec une clôture ajustée donnerait des amplitudes fantaisistes."""
        dividende = OperationSurTitre(
            identifiant="DIV1",
            ticker="TEST1",
            type_ost=TypeOst.DIVIDENDE,
            date_ex=date(2026, 3, 4),
            montant_brut_par_action=100,
            source="fixture",
        )
        serie = fabrique_serie([1000, 1000, 900], amplitude=10, operations=[dividende])
        barre = serie.barres[0]
        assert barre.haut == Decimal("909.000000")  # 1010 × 0,9
        assert barre.bas == Decimal("891.000000")  # 990 × 0,9

    def test_borne_de_connaissance(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        """Vue depuis le 3 mars, la série ignore un détachement du 4."""
        dividende = OperationSurTitre(
            identifiant="DIV1",
            ticker="TEST1",
            type_ost=TypeOst.DIVIDENDE,
            date_ex=date(2026, 3, 4),
            montant_brut_par_action=100,
            source="fixture",
        )
        serie = fabrique_serie([1000, 1000, 900], operations=[dividende], jusqu_a=date(2026, 3, 3))
        assert len(serie) == 2
        assert serie.barres[0].cloture == Decimal("1000.000000")


def test_statut_inconnu_n_est_pas_une_cotation(
    calendrier: CalendrierSeances,
    configuration: Configuration,
    fabrique_cotation: Callable[..., Cotation],
) -> None:
    """INCONNU ne prouve pas qu'il y a eu échange : la barre n'est pas cotée."""
    cotations = [
        fabrique_cotation(jour=LUNDI, cloture=1000),
        fabrique_cotation(
            jour=date(2026, 3, 3), cloture=1010, statut=StatutSeance.INCONNU, volume=0
        ),
    ]
    serie = construire_serie(cotations, calendrier, configuration)
    assert serie.barres[1].origine is OrigineValeur.REPORTEE
    assert serie.barres[1].cloture == Decimal("1000.000000")
