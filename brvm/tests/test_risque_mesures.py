"""Mesures de risque : volatilité, drawdown, et corrélation sur séances communes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from brvm.config.modeles import Configuration
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import SerieTechnique
from brvm.market.analyse import analyser
from brvm.risk.mesures import (
    calculer_correlation,
    calculer_drawdown,
    calculer_volatilite,
    rendements_sur_seances_cotees,
)
from brvm.utils.erreurs import ErreurDonneesInsuffisantes


class TestRendements:
    def test_les_seances_sans_echange_sont_sautees(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Un rendement nul faute d'échange n'est pas un rendement nul : c'est une
        absence d'observation."""
        serie = fabrique_serie([1000, None, None, 1100])
        rendements = rendements_sur_seances_cotees(serie)
        assert len(rendements) == 1
        assert rendements[0][1] == Decimal("0.1")

    def test_serie_sans_echange(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        assert rendements_sur_seances_cotees(fabrique_serie([1000])) == []


class TestVolatilite:
    def test_serie_immobile_a_une_volatilite_nulle(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        resultat = calculer_volatilite(fabrique_serie([1000] * 10), seances_par_an=250)
        assert resultat.valeur == Decimal(0)

    def test_serie_agitee_a_une_volatilite_positive(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        cours = [1000, 1100, 950, 1200, 900, 1150, 980, 1250]
        resultat = calculer_volatilite(fabrique_serie(cours), seances_par_an=250)
        assert resultat.valeur is not None and resultat.valeur > 0
        assert resultat.annualisee is not None
        assert resultat.annualisee > resultat.valeur

    def test_nombre_de_rendements_rapporte(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Il permet de juger si l'annualisation a un sens."""
        serie = fabrique_serie([1000, None, 1100, None, 1200])
        resultat = calculer_volatilite(serie, seances_par_an=250)
        assert resultat.nb_rendements == 2

    def test_pas_assez_d_echanges(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        resultat = calculer_volatilite(fabrique_serie([1000, None]), seances_par_an=250)
        assert resultat.valeur is None
        assert "n'a pas assez échangé" in (resultat.motif_indisponible or "")


class TestDrawdown:
    def test_progression_continue_sans_recul(self) -> None:
        valeurs = [(date(2026, 3, jour), 1000 + jour) for jour in range(2, 7)]
        resultat = calculer_drawdown(valeurs)
        assert resultat.drawdown_maximum == Decimal(0)
        assert resultat.drawdown_courant == Decimal(0)

    def test_recul_mesure_depuis_le_sommet(self) -> None:
        valeurs = [
            (date(2026, 3, 2), 100_000),
            (date(2026, 3, 3), 120_000),
            (date(2026, 3, 4), 90_000),
            (date(2026, 3, 5), 108_000),
        ]
        resultat = calculer_drawdown(valeurs)
        assert resultat.drawdown_maximum == Decimal("0.250000")
        assert resultat.date_du_maximum == date(2026, 3, 4)
        assert resultat.drawdown_courant == Decimal("0.100000")

    def test_sommet_atteint_annule_le_recul_courant(self) -> None:
        valeurs = [
            (date(2026, 3, 2), 100_000),
            (date(2026, 3, 3), 80_000),
            (date(2026, 3, 4), 130_000),
        ]
        resultat = calculer_drawdown(valeurs)
        assert resultat.drawdown_courant == Decimal(0)
        assert resultat.drawdown_maximum == Decimal("0.200000")

    def test_seances_depuis_le_sommet(self) -> None:
        valeurs = [
            (date(2026, 3, 2), 120_000),
            (date(2026, 3, 3), 110_000),
            (date(2026, 3, 4), 100_000),
        ]
        assert calculer_drawdown(valeurs).seances_sous_le_sommet == 2

    def test_serie_vide_refusee(self) -> None:
        with pytest.raises(ErreurDonneesInsuffisantes):
            calculer_drawdown([])


class TestCorrelation:
    def test_valeurs_parfaitement_liees(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        cours = [1000 + (index * 37) % 200 for index in range(30)]
        a = fabrique_serie(cours, ticker="TEST1")
        b = fabrique_serie([valeur * 2 for valeur in cours], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=10)
        assert resultat.valeur is not None
        assert abs(resultat.valeur - Decimal(1)) < Decimal("0.0001")

    def test_valeurs_opposees(self, fabrique_serie: Callable[..., SerieTechnique]) -> None:
        cours = [1000 + (index * 37) % 200 for index in range(30)]
        a = fabrique_serie(cours, ticker="TEST1")
        b = fabrique_serie([3000 - valeur for valeur in cours], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=10)
        assert resultat.valeur is not None and resultat.valeur < Decimal("-0.9")

    def test_seules_les_seances_communes_comptent(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Deux valeurs qui ne cotent pas les mêmes jours n'ont pas de rendement
        comparable ces jours-là."""
        a = fabrique_serie([1000, None, 1100, None, 1200, None], ticker="TEST1")
        b = fabrique_serie([None, 2000, None, 2200, None, 2400], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=2)
        assert resultat.seances_communes == 0
        assert resultat.valeur is None
        assert "réellement échangé" in (resultat.motif_indisponible or "")

    def test_pas_assez_de_seances_communes(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        a = fabrique_serie([1000, 1100, 1200], ticker="TEST1")
        b = fabrique_serie([2000, 2100, 2200], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=20)
        assert resultat.valeur is None
        assert "que le calendrier de cotation" in (resultat.motif_indisponible or "")

    def test_valeur_immobile_rend_la_correlation_indefinie(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        a = fabrique_serie([1000] * 30, ticker="TEST1")
        b = fabrique_serie([1000 + index for index in range(30)], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=10)
        assert resultat.valeur is None
        assert "n'a pas varié" in (resultat.motif_indisponible or "")

    def test_les_tickers_sont_rapportes(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        a = fabrique_serie([1000, 1100], ticker="TEST1")
        b = fabrique_serie([2000, 2100], ticker="TEST2")
        resultat = calculer_correlation(a, b, seances_minimum=1)
        assert (resultat.ticker_a, resultat.ticker_b) == ("TEST1", "TEST2")


class TestFenetreEffective:
    """La fenêtre déclarée doit changer le résultat, sinon elle ne sert à rien.

    Elle était déclarée dans les trois configurations livrées et lue par aucun
    calcul : toutes les volatilités portaient sur l'historique entier.
    """

    def test_la_fenetre_borne_reellement_le_calcul(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        # Cours calmes puis agités : une fenêtre courte ne doit voir que la fin.
        cours = [1000 + (i % 2) for i in range(40)] + [1000 + (i % 2) * 300 for i in range(40)]
        serie = fabrique_serie(cours)
        courte = calculer_volatilite(serie, seances_par_an=250, fenetre=20)
        longue = calculer_volatilite(serie, seances_par_an=250, fenetre=79)
        assert courte.valeur is not None and longue.valeur is not None
        assert courte.nb_rendements == 20
        assert longue.nb_rendements == 79
        assert courte.valeur > longue.valeur

    def test_le_critere_de_marche_emploie_la_fenetre_configuree(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le critère de volatilité du criblage doit passer la fenêtre déclarée."""
        cours = [1000 + (i % 2) for i in range(200)] + [1000 + (i % 2) * 300 for i in range(60)]
        serie = fabrique_serie(cours)
        analyse = analyser(
            ticker="TEST1",
            serie=serie,
            indicateurs=Indicateurs(serie, configuration),
            configuration=configuration,
        )
        critere = analyse.criteres["volatilite"]
        attendue = calculer_volatilite(
            serie,
            configuration.risque.seances_par_an,
            fenetre=configuration.risque.fenetre_volatilite,
        )
        assert critere.valeur == attendue.annualisee
        # Et surtout : ce n'est PAS la volatilité de tout l'historique.
        assert (
            critere.valeur
            != calculer_volatilite(serie, configuration.risque.seances_par_an).annualisee
        )
