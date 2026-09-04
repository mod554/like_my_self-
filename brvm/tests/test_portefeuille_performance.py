"""TWR, TRI et contributions : ce qu'ils mesurent, et quand ils n'existent pas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from brvm.portfolio.performance import (
    DonneesLigne,
    FluxTresorerie,
    PointValorisation,
    calculer_contributions,
    calculer_tri,
    calculer_twr,
)
from brvm.utils.erreurs import ErreurValidation


class TestTwr:
    def test_enchainement_de_deux_hausses(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2026, 4, 1), 110_000),
            PointValorisation(date(2026, 7, 1), 121_000),
        ]
        assert calculer_twr(points).valeur == Decimal("0.210000")

    def test_un_apport_ne_compte_pas_comme_une_performance(self) -> None:
        """C'est la raison d'être du TWR : neutraliser les versements."""
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2026, 4, 1), 200_000, flux_externe=100_000),
        ]
        assert calculer_twr(points).valeur == Decimal(0)

    def test_apport_puis_hausse(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2026, 4, 1), 110_000),
            PointValorisation(date(2026, 7, 1), 231_000, flux_externe=100_000),
        ]
        resultat = calculer_twr(points)
        assert resultat.valeur == Decimal("0.210000")
        assert [p.rendement for p in resultat.sous_periodes] == [
            Decimal("0.100000"),
            Decimal("0.100000"),
        ]

    def test_retrait_neutralise_aussi(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 200_000),
            PointValorisation(date(2026, 4, 1), 110_000, flux_externe=-100_000),
        ]
        assert calculer_twr(points).valeur == Decimal("0.100000")

    def test_baisse(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2026, 4, 1), 90_000),
        ]
        assert calculer_twr(points).valeur == Decimal("-0.100000")

    def test_une_seule_valorisation_ne_mesure_rien(self) -> None:
        resultat = calculer_twr([PointValorisation(date(2026, 1, 1), 100_000)])
        assert resultat.valeur is None
        assert resultat.motif_indisponible is not None

    def test_portefeuille_vide_interrompt_le_calcul(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 0),
            PointValorisation(date(2026, 4, 1), 10_000),
        ]
        resultat = calculer_twr(points)
        assert resultat.valeur is None
        assert "valeur nulle" in (resultat.motif_indisponible or "")

    def test_annualisation_refusee_sous_un_an(self) -> None:
        """Annualiser trois mois produit un chiffre spectaculaire et faux."""
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2026, 4, 1), 110_000),
        ]
        resultat = calculer_twr(points)
        assert resultat.annualise(date(2026, 1, 1), date(2026, 4, 1)) is None

    def test_annualisation_sur_deux_ans(self) -> None:
        points = [
            PointValorisation(date(2026, 1, 1), 100_000),
            PointValorisation(date(2028, 1, 1), 121_000),
        ]
        annuel = calculer_twr(points).annualise(date(2026, 1, 1), date(2028, 1, 1))
        assert annuel is not None
        assert Decimal("0.09") < annuel < Decimal("0.11")


class TestTri:
    def test_placement_simple(self) -> None:
        flux = [
            FluxTresorerie(date(2026, 1, 1), -100_000),
            FluxTresorerie(date(2027, 1, 1), 110_000),
        ]
        resultat = calculer_tri(flux)
        assert resultat.valeur is not None
        assert abs(resultat.valeur - Decimal("0.10")) < Decimal("0.001")

    def test_perte(self) -> None:
        flux = [
            FluxTresorerie(date(2026, 1, 1), -100_000),
            FluxTresorerie(date(2027, 1, 1), 90_000),
        ]
        resultat = calculer_tri(flux)
        assert resultat.valeur is not None and resultat.valeur < 0

    def test_versements_progressifs(self) -> None:
        """Le TRI tient compte du calendrier : c'est ce qui le distingue du TWR."""
        flux = [
            FluxTresorerie(date(2026, 1, 1), -300_000, "tranche 1"),
            FluxTresorerie(date(2026, 6, 1), -200_000, "tranche 2"),
            FluxTresorerie(date(2027, 1, 1), 560_000, "valeur finale"),
        ]
        resultat = calculer_tri(flux)
        assert resultat.valeur is not None and resultat.valeur > 0

    def test_flux_tous_du_meme_sens(self) -> None:
        flux = [
            FluxTresorerie(date(2026, 1, 1), -100_000),
            FluxTresorerie(date(2026, 6, 1), -50_000),
        ]
        resultat = calculer_tri(flux)
        assert resultat.valeur is None
        assert "même sens" in (resultat.motif_indisponible or "")

    def test_un_seul_flux(self) -> None:
        assert calculer_tri([FluxTresorerie(date(2026, 1, 1), -1)]).valeur is None

    def test_convergence_bornee(self) -> None:
        flux = [
            FluxTresorerie(date(2026, 1, 1), -100_000),
            FluxTresorerie(date(2027, 1, 1), 110_000),
        ]
        assert 0 < calculer_tri(flux).iterations <= 200


class TestContributions:
    def test_les_contributions_somment_au_rendement_global(self) -> None:
        lignes = [
            DonneesLigne("AAA", 200_000, 220_000, dividendes_nets=10_000),
            DonneesLigne("BBB", 175_000, 165_000),
            DonneesLigne("CCC", 125_000, 140_000),
        ]
        contributions = calculer_contributions(lignes)
        total_gain = sum(c.gain for c in contributions)
        assert total_gain == 35_000
        assert sum(c.contribution for c in contributions) == Decimal("0.070000")

    def test_rendement_propre_independant_de_la_taille(self) -> None:
        """Deux lignes qui gagnent 10 % ont le même rendement propre, mais des
        contributions différentes selon leur poids."""
        lignes = [
            DonneesLigne("PETITE", 100_000, 110_000),
            DonneesLigne("GROSSE", 400_000, 440_000),
        ]
        petite, grosse = calculer_contributions(lignes)
        assert petite.rendement_propre == grosse.rendement_propre
        assert grosse.contribution > petite.contribution

    def test_les_dividendes_comptent_dans_le_gain(self) -> None:
        sans = calculer_contributions([DonneesLigne("AAA", 100_000, 100_000)])[0]
        avec = calculer_contributions(
            [DonneesLigne("AAA", 100_000, 100_000, dividendes_nets=5_000)]
        )[0]
        assert sans.gain == 0 and avec.gain == 5_000

    def test_les_plus_values_realisees_comptent(self) -> None:
        ligne = calculer_contributions(
            [DonneesLigne("AAA", 100_000, 100_000, plus_values_realisees=8_000)]
        )[0]
        assert ligne.gain == 8_000

    def test_liste_vide(self) -> None:
        assert calculer_contributions([]) == ()

    def test_cout_total_nul_refuse(self) -> None:
        with pytest.raises(ErreurValidation, match="Coût engagé total"):
            calculer_contributions([DonneesLigne("AAA", 0, 1_000)])
