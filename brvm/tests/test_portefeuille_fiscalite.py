"""Fiscalité : retenue sur dividendes, régime des plus-values."""

from __future__ import annotations

from decimal import Decimal

import pytest

from brvm.config.modeles import Configuration
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.utils.erreurs import ErreurValidation


def moteur_avec(configuration: Configuration, **fiscalite: object) -> MoteurFiscal:
    return MoteurFiscal(
        configuration.model_copy(
            update={"fiscalite": configuration.fiscalite.model_copy(update=fiscalite)}
        )
    )


class TestDividendes:
    """Le barème de test retient 10 % à la source."""

    def test_retenue_appliquee(self, moteur_fiscal: MoteurFiscal) -> None:
        decompte = moteur_fiscal.dividende(quantite=7, dividende_par_action=1_740)
        assert decompte.montant_brut == 12_180
        assert decompte.retenue == 1_218
        assert decompte.montant_net == 10_962

    def test_rendement_net_inferieur_au_rendement_brut(self, moteur_fiscal: MoteurFiscal) -> None:
        """Un rendement affiché brut surestime toujours ce qui est encaissé."""
        net = moteur_fiscal.rendement_net(dividende_par_action=1_740, cours=28_400)
        brut = Decimal(1_740) / Decimal(28_400)
        assert net < brut
        assert net == Decimal(1_566) / Decimal(28_400)

    def test_provenance_des_taux_conservee(self, moteur_fiscal: MoteurFiscal) -> None:
        """Un taux sans référence n'est pas auditable."""
        decompte = moteur_fiscal.dividende(1, 100)
        assert decompte.source_reference

    def test_detail_lisible(self, moteur_fiscal: MoteurFiscal) -> None:
        detail = moteur_fiscal.dividende(7, 1_740).detail()
        assert "retenue à la source" in detail and "net encaissé" in detail

    def test_taux_nul_laisse_le_brut_intact(self, configuration: Configuration) -> None:
        moteur = moteur_avec(configuration, retenue_dividendes=Decimal(0))
        assert moteur.dividende(10, 100).montant_net == 1_000

    @pytest.mark.parametrize("quantite", [0, -1])
    def test_quantite_invalide(self, moteur_fiscal: MoteurFiscal, quantite: int) -> None:
        with pytest.raises(ErreurValidation):
            moteur_fiscal.dividende(quantite, 100)

    def test_dividende_negatif_refuse(self, moteur_fiscal: MoteurFiscal) -> None:
        with pytest.raises(ErreurValidation):
            moteur_fiscal.dividende(10, -1)

    def test_cours_nul_refuse(self, moteur_fiscal: MoteurFiscal) -> None:
        with pytest.raises(ErreurValidation):
            moteur_fiscal.rendement_net(100, 0)


class TestPlusValues:
    def test_regime_exonere_ne_prelève_rien(self, moteur_fiscal: MoteurFiscal) -> None:
        """Le barème de test déclare les plus-values non imposables."""
        decompte = moteur_fiscal.plus_value(50_000)
        assert decompte.imposable is False
        assert decompte.impot == 0
        assert decompte.plus_value_nette == 50_000
        assert "non imposable" in decompte.motif

    def test_regime_imposable(self, configuration: Configuration) -> None:
        moteur = moteur_avec(
            configuration,
            plus_values_imposables=True,
            plus_values_taux=Decimal("0.15"),
        )
        decompte = moteur.plus_value(50_000)
        assert decompte.imposable is True
        assert decompte.impot == 7_500
        assert decompte.plus_value_nette == 42_500

    def test_moins_value_ne_genere_aucun_impot(self, configuration: Configuration) -> None:
        moteur = moteur_avec(
            configuration, plus_values_imposables=True, plus_values_taux=Decimal("0.15")
        )
        decompte = moteur.plus_value(-20_000)
        assert decompte.impot == 0
        assert decompte.plus_value_nette == -20_000
        assert "moins-value" in decompte.motif

    def test_exoneration_pour_duree_de_detention(self, configuration: Configuration) -> None:
        moteur = moteur_avec(
            configuration,
            plus_values_imposables=True,
            plus_values_taux=Decimal("0.15"),
            plus_values_exoneration_mois=24,
        )
        assert moteur.plus_value(50_000, duree_detention_mois=30).impot == 0
        assert moteur.plus_value(50_000, duree_detention_mois=12).impot == 7_500

    def test_duree_inconnue_signale_l_exoneration_non_appliquee(
        self, configuration: Configuration
    ) -> None:
        """En PMP la durée n'existe pas : l'utilisateur doit savoir que
        l'exonération n'a pas pu être vérifiée."""
        moteur = moteur_avec(
            configuration,
            plus_values_imposables=True,
            plus_values_taux=Decimal("0.15"),
            plus_values_exoneration_mois=24,
        )
        decompte = moteur.plus_value(50_000, duree_detention_mois=None)
        assert decompte.impot == 7_500
        assert "durée de détention inconnue" in decompte.motif

    def test_detail_lisible(self, moteur_fiscal: MoteurFiscal) -> None:
        detail = moteur_fiscal.plus_value(10_000).detail()
        assert "plus-value brute" in detail and "plus-value nette" in detail
