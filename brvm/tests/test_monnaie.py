"""Arithmétique XOF : arrondis, taux, minimum de perception."""

from __future__ import annotations

from decimal import Decimal

import pytest

from brvm.domain.monnaie import (
    ModeArrondi,
    applique_taux,
    arrondi_xof,
    borne,
    format_xof,
    somme_lignes,
    vers_decimal,
)


class TestConversion:
    def test_entier_et_decimal_inchanges(self) -> None:
        assert vers_decimal(1200) == Decimal(1200)
        assert vers_decimal(Decimal("0.006")) == Decimal("0.006")

    def test_float_passe_par_sa_representation_decimale(self) -> None:
        # Decimal(0.1) donnerait 0.1000000000000000055511151231257827.
        assert vers_decimal(0.1) == Decimal("0.1")

    def test_booleen_refuse(self) -> None:
        # bool est un int en Python : accepter True comme montant serait un piège.
        with pytest.raises(TypeError):
            vers_decimal(True)

    def test_valeur_non_numerique_refusee(self) -> None:
        with pytest.raises(TypeError):
            vers_decimal("mille francs")


class TestArrondi:
    @pytest.mark.parametrize(
        ("valeur", "attendu"),
        [("0.5", 1), ("1.5", 2), ("2.5", 3), ("0.4", 0), ("-0.5", -1), ("-1.5", -2)],
    )
    def test_half_up_ecarte_de_zero(self, valeur: str, attendu: int) -> None:
        assert arrondi_xof(Decimal(valeur), ModeArrondi.HALF_UP) == attendu

    @pytest.mark.parametrize(
        ("valeur", "attendu"), [("0.5", 0), ("1.5", 2), ("2.5", 2), ("3.5", 4)]
    )
    def test_half_even_va_vers_le_pair(self, valeur: str, attendu: int) -> None:
        assert arrondi_xof(Decimal(valeur), ModeArrondi.HALF_EVEN) == attendu

    def test_ceiling_et_floor(self) -> None:
        assert arrondi_xof(Decimal("1.01"), ModeArrondi.CEILING) == 2
        assert arrondi_xof(Decimal("1.99"), ModeArrondi.FLOOR) == 1
        assert arrondi_xof(Decimal("-1.01"), ModeArrondi.FLOOR) == -2

    def test_resultat_est_un_entier_python(self) -> None:
        resultat = arrondi_xof(Decimal("1234.6"))
        assert isinstance(resultat, int)
        assert resultat == 1235


class TestTaux:
    def test_application_sans_arrondi_implicite(self) -> None:
        # 0,6 % de 1 000 000 = 6 000 exactement, mais la fonction ne doit pas
        # arrondir : c'est l'appelant qui décide.
        assert applique_taux(1_000_000, Decimal("0.006")) == Decimal("6000.000")

    def test_precision_conservee(self) -> None:
        resultat = applique_taux(3333, Decimal("0.00123"))
        assert resultat == Decimal("4.09959")

    def test_borne_applique_minimum_de_perception(self) -> None:
        assert borne(Decimal("250"), minimum=1000) == Decimal(1000)

    def test_borne_applique_plafond(self) -> None:
        assert borne(Decimal("50000"), maximum=25000) == Decimal(25000)

    def test_borne_laisse_passer_entre_les_bornes(self) -> None:
        assert borne(Decimal("1500.4"), minimum=1000, maximum=25000) == Decimal("1500.4")


class TestTotalDeFacture:
    def test_somme_des_lignes_arrondies_differe_de_l_arrondi_de_la_somme(self) -> None:
        """Le choix du système : arrondir chaque ligne, puis sommer.

        C'est ainsi qu'un avis d'opéré est établi. Ce test fige la différence pour
        qu'une modification du moteur de frais ne la fasse pas basculer en silence.
        """
        brut = [Decimal("0.5"), Decimal("0.5"), Decimal("0.5")]
        par_ligne = somme_lignes([arrondi_xof(valeur) for valeur in brut])
        globalement = arrondi_xof(sum(brut))
        assert par_ligne == 3
        assert globalement == 2
        assert par_ligne != globalement


def test_format_affichage() -> None:
    assert format_xof(1234567) == "1 234 567 XOF"
    assert format_xof(0) == "0 XOF"
