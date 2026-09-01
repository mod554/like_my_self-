"""Calculs d'indicateurs : valeurs de référence, propagation des trous, causalité."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import ClassVar

import pytest

from brvm.indicators import calculs
from brvm.utils.erreurs import ErreurValidation

Serie = list[Decimal | None]


def d(*valeurs: float | int | None) -> Serie:
    return [None if valeur is None else Decimal(str(valeur)) for valeur in valeurs]


def texte(serie: Sequence[Decimal | None]) -> list[str | None]:
    return [None if valeur is None else str(valeur) for valeur in serie]


class TestMoyenneSimple:
    def test_valeurs_de_reference(self) -> None:
        resultat = calculs.moyenne_mobile_simple(d(1, 2, 3, 4, 5), 3)
        assert texte(resultat) == [None, None, "2.000000", "3.000000", "4.000000"]

    def test_fenetre_incomplete_reste_indeterminee(self) -> None:
        assert calculs.moyenne_mobile_simple(d(1, 2), 3) == [None, None]

    def test_un_trou_rend_la_fenetre_indeterminee(self) -> None:
        """Aucune interpolation : une donnée manquante n'est pas une donnée."""
        resultat = calculs.moyenne_mobile_simple(d(1, 2, None, 4, 5, 6), 3)
        assert resultat[2] is None and resultat[3] is None and resultat[4] is None
        assert resultat[5] is not None

    def test_fenetre_invalide(self) -> None:
        with pytest.raises(ErreurValidation):
            calculs.moyenne_mobile_simple(d(1, 2, 3), 0)


class TestMoyenneExponentielle:
    def test_amorcage_par_la_moyenne_simple(self) -> None:
        """Coefficient 2/(3+1) = 0,5 : chaque valeur pèse la moitié."""
        resultat = calculs.moyenne_mobile_exponentielle(d(1, 2, 3, 4, 5), 3)
        assert texte(resultat) == [None, None, "2.000000", "3.000000", "4.000000"]

    def test_un_trou_remet_le_calcul_a_zero(self) -> None:
        """Reprendre la récurrence de part et d'autre d'un trou fabriquerait une
        continuité qui n'a pas été observée."""
        resultat = calculs.moyenne_mobile_exponentielle(d(1, 2, 3, None, 5, 6, 7, 8), 3)
        assert resultat[2] is not None
        assert resultat[3] is None and resultat[4] is None and resultat[5] is None
        assert resultat[6] is not None  # trois valeurs consécutives à nouveau

    def test_fenetre_minimale(self) -> None:
        with pytest.raises(ErreurValidation):
            calculs.moyenne_mobile_exponentielle(d(1, 2, 3), 1)


class TestRsi:
    def test_hausse_ininterrompue_donne_cent(self) -> None:
        resultat = calculs.rsi(d(*range(1, 25)), 14)
        assert resultat[-1] == Decimal(100)

    def test_baisse_ininterrompue_donne_zero(self) -> None:
        resultat = calculs.rsi(d(*range(24, 0, -1)), 14)
        assert resultat[-1] == Decimal(0)

    def test_indetermine_avant_la_premiere_fenetre(self) -> None:
        resultat = calculs.rsi(d(*range(1, 20)), 14)
        assert all(valeur is None for valeur in resultat[:14])
        assert resultat[14] is not None

    def test_borne_entre_zero_et_cent(self) -> None:
        cours = d(*[100 + (index * 37) % 23 for index in range(60)])
        for valeur in calculs.rsi(cours, 14):
            if valeur is not None:
                assert Decimal(0) <= valeur <= Decimal(100)

    def test_trou_remet_l_amorcage_a_zero(self) -> None:
        cours = [*d(*range(1, 20)), None, *d(*range(1, 20))]
        resultat = calculs.rsi(cours, 14)
        assert resultat[18] is not None
        assert all(valeur is None for valeur in resultat[19:33])


class TestMacd:
    def test_trois_series_de_meme_longueur(self) -> None:
        cours = d(*[100 + index for index in range(60)])
        ligne, signal, histogramme = calculs.macd(cours, 12, 26, 9)
        assert len(ligne) == len(signal) == len(histogramme) == 60

    def test_histogramme_est_la_difference(self) -> None:
        cours = d(*[100 + (index * 3) % 17 for index in range(80)])
        ligne, signal, histogramme = calculs.macd(cours, 12, 26, 9)
        for valeur_ligne, valeur_signal, valeur_histo in zip(
            ligne, signal, histogramme, strict=True
        ):
            if valeur_histo is not None:
                assert valeur_ligne is not None and valeur_signal is not None
                assert valeur_histo == valeur_ligne - valeur_signal

    def test_hausse_reguliere_donne_un_macd_positif(self) -> None:
        ligne, _, _ = calculs.macd(d(*[100 + index * 2 for index in range(80)]), 12, 26, 9)
        assert ligne[-1] is not None and ligne[-1] > 0

    def test_fenetres_incoherentes_refusees(self) -> None:
        with pytest.raises(ErreurValidation, match="strictement inférieure"):
            calculs.macd(d(1, 2, 3), 26, 12, 9)


class TestBollinger:
    def test_ecart_type_de_population(self) -> None:
        """Convention Bollinger : diviseur n, pas n-1. Pour 1,2,3 → √(2/3)."""
        resultat = calculs.ecart_type_mobile(d(1, 2, 3), 3)
        assert texte(resultat)[-1] == "0.816497"

    def test_bandes_symetriques_autour_de_la_moyenne(self) -> None:
        basse, moyenne, haute = calculs.bandes_bollinger(d(1, 2, 3), 3, Decimal(2))
        assert moyenne[-1] == Decimal("2.000000")
        assert basse[-1] is not None and haute[-1] is not None
        assert haute[-1] - moyenne[-1] == moyenne[-1] - basse[-1]

    def test_serie_plate_donne_des_bandes_confondues(self) -> None:
        basse, moyenne, haute = calculs.bandes_bollinger(d(5, 5, 5, 5), 3, Decimal(2))
        assert basse[-1] == moyenne[-1] == haute[-1]


class TestAtr:
    def test_valeur_de_reference(self) -> None:
        """Amplitudes vraies : 3, 3, puis 3 → moyenne constante à 3."""
        hauts = d(None, 12, 14, 13)
        bas = d(None, 9, 11, 10)
        clotures = d(10, 11, 13, 12)
        assert texte(calculs.atr(hauts, bas, clotures, 2)) == [
            None,
            None,
            "3.000000",
            "3.000000",
        ]

    def test_prend_en_compte_les_ecarts_a_la_cloture_veille(self) -> None:
        """Une ouverture en décalage compte dans l'amplitude vraie : c'est le cas
        fréquent d'une valeur qui n'a pas coté la veille."""
        hauts = d(None, 30, 30)
        bas = d(None, 28, 28)
        clotures = d(10, 29, 29)
        resultat = calculs.atr(hauts, bas, clotures, 2)
        # TR = max(2, |30-10|, |28-10|) = 20 sur la deuxième barre.
        assert resultat[-1] is not None and resultat[-1] > Decimal(2)

    def test_longueurs_incoherentes_refusees(self) -> None:
        with pytest.raises(ErreurValidation, match="même longueur"):
            calculs.atr(d(1, 2), d(1), d(1, 2), 2)


class TestObv:
    def test_valeur_de_reference(self) -> None:
        resultat = calculs.obv(d(10, 11, 10, 10, 12), [0, 100, 200, 300, 400])
        assert texte(resultat) == ["0", "100", "-100", "-100", "300"]

    def test_seance_inconnue_ne_modifie_pas_le_cumul(self) -> None:
        """On ignore si elle aurait été haussière, pas qu'elle a été neutre."""
        resultat = calculs.obv(d(10, 11, None, 12), [0, 100, 200, 300])
        assert resultat[2] == resultat[1]

    def test_longueurs_incoherentes_refusees(self) -> None:
        with pytest.raises(ErreurValidation, match="même longueur"):
            calculs.obv(d(1, 2), [1])


class TestMomentumEtExtremes:
    def test_momentum_en_fraction(self) -> None:
        assert texte(calculs.momentum(d(100, 110), 1)) == [None, "0.100000"]

    def test_momentum_negatif(self) -> None:
        assert texte(calculs.momentum(d(100, 90), 1)) == [None, "-0.100000"]

    def test_momentum_sur_reference_nulle_reste_indetermine(self) -> None:
        assert calculs.momentum(d(0, 10), 1) == [None, None]

    def test_extremes_glissants(self) -> None:
        plus_bas, plus_haut = calculs.extremes_glissants(d(5, 3, 9, 1, 7), 3)
        assert texte(plus_bas) == [None, None, "3", "1", "1"]
        assert texte(plus_haut) == [None, None, "9", "9", "9"]


class TestCausalite:
    """Aucun indicateur ne doit voir l'avenir.

    Le test est direct : tronquer la série juste après l'indice *i* ne doit
    changer aucune valeur jusqu'à *i*. C'est cette propriété qui rend un backtest
    honnête ; sans elle, toute performance simulée est fictive.
    """

    SERIE: ClassVar[list[Decimal]] = [Decimal(100 + (index * 7) % 13) for index in range(60)]

    @pytest.mark.parametrize(
        ("nom", "fonction"),
        [
            ("MM simple", lambda v: calculs.moyenne_mobile_simple(v, 5)),
            ("MM exponentielle", lambda v: calculs.moyenne_mobile_exponentielle(v, 5)),
            ("RSI", lambda v: calculs.rsi(v, 14)),
            ("MACD", lambda v: calculs.macd(v, 12, 26, 9)[0]),
            ("MACD signal", lambda v: calculs.macd(v, 12, 26, 9)[1]),
            ("Bollinger haute", lambda v: calculs.bandes_bollinger(v, 20, Decimal(2))[2]),
            ("Momentum", lambda v: calculs.momentum(v, 10)),
            ("Plus haut", lambda v: calculs.extremes_glissants(v, 20)[1]),
        ],
    )
    def test_troncature_sans_effet_sur_le_passe(
        self, nom: str, fonction: Callable[[Serie], Serie]
    ) -> None:
        complet = fonction(list(self.SERIE))
        for position in range(len(self.SERIE)):
            tronque = fonction(list(self.SERIE[: position + 1]))
            assert tronque[position] == complet[position], (
                f"{nom} : la valeur à l'indice {position} change selon que l'on "
                "connaît ou non la suite de la série."
            )

    def test_atr_est_causal(self) -> None:
        hauts = [valeur + Decimal(5) for valeur in self.SERIE]
        bas = [valeur - Decimal(5) for valeur in self.SERIE]
        complet = calculs.atr(hauts, bas, list(self.SERIE), 14)
        for position in range(len(self.SERIE)):
            tronque = calculs.atr(
                hauts[: position + 1], bas[: position + 1], list(self.SERIE[: position + 1]), 14
            )
            assert tronque[position] == complet[position]

    def test_obv_est_causal(self) -> None:
        volumes = [100 + index for index in range(len(self.SERIE))]
        complet = calculs.obv(list(self.SERIE), volumes)
        for position in range(len(self.SERIE)):
            tronque = calculs.obv(list(self.SERIE[: position + 1]), volumes[: position + 1])
            assert tronque[position] == complet[position]
