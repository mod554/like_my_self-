"""Série ajustée : dividendes, divisions, et absence de biais d'anticipation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from brvm.domain.ajustement import ajuster_serie
from brvm.domain.enums import StatutSeance, TypeOst
from brvm.domain.modeles import Cotation, OperationSurTitre
from brvm.utils.erreurs import ErreurValidation

J1, J2, J3, J4 = (date(2026, 3, jour) for jour in (2, 3, 4, 5))


def dividende(montant: int, date_ex: date, ticker: str = "TEST1") -> OperationSurTitre:
    return OperationSurTitre(
        identifiant=f"DIV-{date_ex.isoformat()}",
        ticker=ticker,
        type_ost=TypeOst.DIVIDENDE,
        date_ex=date_ex,
        montant_brut_par_action=montant,
        source="fixture",
    )


def division(numerateur: int, denominateur: int, date_ex: date) -> OperationSurTitre:
    return OperationSurTitre(
        identifiant=f"DIV-TITRES-{date_ex.isoformat()}",
        ticker="TEST1",
        type_ost=TypeOst.DIVISION,
        date_ex=date_ex,
        ratio_numerateur=numerateur,
        ratio_denominateur=denominateur,
        source="fixture",
    )


class TestSansOperation:
    def test_serie_ajustee_identique_a_la_serie_brute(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3)]
        resultat = ajuster_serie(serie)
        assert [point.cloture_ajustee for point in resultat.points] == [Decimal(1000)] * 3
        assert all(point.facteur_cours == Decimal(1) for point in resultat.points)

    def test_serie_triee_meme_si_l_entree_ne_l_est_pas(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [fabrique_cotation(jour=jour) for jour in (J3, J1, J2)]
        resultat = ajuster_serie(serie)
        assert [point.date_seance for point in resultat.points] == [J1, J2, J3]


class TestDividende:
    def test_facteur_applique_aux_seances_anterieures(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Dividende de 50 sur un cours de 1 000 : facteur 0,95 avant détachement."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3)]
        resultat = ajuster_serie(serie, [dividende(50, J3)])
        ajustees = [point.cloture_ajustee for point in resultat.points]
        assert ajustees == [Decimal("950.000000"), Decimal("950.000000"), Decimal("1000.000000")]

    def test_bord_droit_egal_a_la_serie_brute(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Convention d'ajustement rétroactif : la dernière barre n'est jamais modifiée."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3)]
        resultat = ajuster_serie(serie, [dividende(50, J3)])
        dernier = resultat.points[-1]
        assert dernier.cloture_ajustee == Decimal(dernier.cloture_brute or 0)

    def test_reference_prise_sur_la_derniere_seance_reellement_cotee(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """La veille du détachement n'a pas échangé : on remonte au dernier cours traité.

        Un cours de référence reconduit ne dit rien du prix auquel le marché traitait ;
        l'utiliser fabriquerait un facteur arbitraire.
        """
        serie = [
            fabrique_cotation(jour=J1, cloture=800),
            fabrique_cotation(
                jour=J2, cloture=1000, statut=StatutSeance.SANS_TRANSACTION, volume=0
            ),
            fabrique_cotation(jour=J3, cloture=760),
        ]
        resultat = ajuster_serie(serie, [dividende(80, J3)])
        # Facteur = (800 - 80) / 800 = 0,9 — assis sur J1, pas sur le cours reconduit de J2.
        assert resultat.facteurs_par_ost[J3] == Decimal("0.900000")

    def test_dividende_sans_seance_cotee_anterieure_est_ecarte(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [
            fabrique_cotation(jour=J1, statut=StatutSeance.SANS_TRANSACTION, volume=0),
            fabrique_cotation(jour=J2, cloture=1000),
        ]
        resultat = ajuster_serie(serie, [dividende(50, J2)])
        assert resultat.facteurs_par_ost == {}
        assert any("aucune séance réellement cotée" in a for a in resultat.avertissements)

    def test_dividende_superieur_au_cours_est_ecarte(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Donnée manifestement fausse : signalée, jamais « corrigée »."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2)]
        resultat = ajuster_serie(serie, [dividende(1500, J2)])
        assert resultat.facteurs_par_ost == {}
        assert any("à vérifier à la source" in a for a in resultat.avertissements)

    def test_dividendes_successifs_se_composent(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3, J4)]
        resultat = ajuster_serie(serie, [dividende(100, J3), dividende(100, J4)])
        facteurs = {point.date_seance: point.facteur_cours for point in resultat.points}
        assert facteurs[J4] == Decimal("1.000000")
        assert facteurs[J3] == Decimal("0.900000")
        # J1 et J2 subissent les deux détachements : 0,9 × 0,9.
        assert facteurs[J2] == Decimal("0.810000")
        assert facteurs[J1] == Decimal("0.810000")


class TestDivision:
    def test_cours_divise_et_volume_multiplie(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [
            fabrique_cotation(jour=J1, cloture=1000, volume=100),
            fabrique_cotation(jour=J2, cloture=1000, volume=100),
            fabrique_cotation(jour=J3, cloture=500, volume=200),
        ]
        resultat = ajuster_serie(serie, [division(2, 1, J3)])
        assert [point.cloture_ajustee for point in resultat.points] == [Decimal("500.000000")] * 3
        assert [point.volume_ajuste for point in resultat.points] == [200, 200, 200]

    def test_regroupement(self, fabrique_cotation: Callable[..., Cotation]) -> None:
        serie = [
            fabrique_cotation(jour=J1, cloture=100, volume=1000),
            fabrique_cotation(jour=J2, cloture=1000, volume=100),
        ]
        resultat = ajuster_serie(
            serie,
            [
                OperationSurTitre(
                    identifiant="REGR",
                    ticker="TEST1",
                    type_ost=TypeOst.REGROUPEMENT,
                    date_ex=J2,
                    ratio_numerateur=1,
                    ratio_denominateur=10,
                    source="fixture",
                )
            ],
        )
        assert resultat.points[0].cloture_ajustee == Decimal("1000.000000")
        assert resultat.points[0].volume_ajuste == 100


class TestAbsenceDeBiaisDAnticipation:
    def test_operation_future_exclue_de_la_serie_connue_a_une_date(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """La série vue depuis J2 ne peut pas connaître le détachement de J3."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3)]
        operations = [dividende(50, J3)]

        vue_depuis_j2 = ajuster_serie(serie, operations, jusqu_a=J2)
        assert all(point.facteur_cours == Decimal(1) for point in vue_depuis_j2.points)
        assert vue_depuis_j2.jusqu_a == J2

        vue_complete = ajuster_serie(serie, operations)
        assert vue_complete.points[0].facteur_cours == Decimal("0.950000")

    def test_operation_du_jour_meme_est_connue(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Le détachement est public dès l'ouverture de sa séance : il est connu à J3."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2, J3)]
        resultat = ajuster_serie(serie, [dividende(50, J3)], jusqu_a=J3)
        assert resultat.points[0].facteur_cours == Decimal("0.950000")


class TestTracabilite:
    def test_operation_non_modelisee_signalee_et_ignoree(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Une augmentation de capital n'est pas modélisée : on le dit plutôt que
        de laisser croire qu'elle est prise en compte."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J1, J2)]
        resultat = ajuster_serie(
            serie,
            [
                OperationSurTitre(
                    identifiant="AK1",
                    ticker="TEST1",
                    type_ost=TypeOst.AUGMENTATION_CAPITAL,
                    date_ex=J2,
                    source="fixture",
                )
            ],
        )
        assert resultat.facteurs_par_ost == {}
        assert any("non modélisée" in a for a in resultat.avertissements)

    def test_operation_anterieure_a_la_serie_signalee(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Une division détachée avant la première barre n'ajuste rien : toutes les
        barres connues sont déjà post-division. On le signale au lieu de laisser
        croire qu'elle a été appliquée."""
        serie = [fabrique_cotation(jour=jour, cloture=1000) for jour in (J3, J4)]
        resultat = ajuster_serie(serie, [division(2, 1, J1)])
        assert all(point.facteur_cours == Decimal(1) for point in resultat.points)
        assert any("sans effet sur l'ajustement" in a for a in resultat.avertissements)

    def test_seances_cotees_filtre_les_seances_sans_echange(
        self, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        serie = [
            fabrique_cotation(jour=J1, cloture=1000),
            fabrique_cotation(
                jour=J2, cloture=1000, statut=StatutSeance.SANS_TRANSACTION, volume=0
            ),
            fabrique_cotation(jour=J3, cloture=1000),
        ]
        resultat = ajuster_serie(serie)
        assert len(resultat.points) == 3
        assert [point.date_seance for point in resultat.seances_cotees()] == [J1, J3]


class TestEntreesInvalides:
    def test_serie_vide(self) -> None:
        with pytest.raises(ErreurValidation, match="Série vide"):
            ajuster_serie([])

    def test_plusieurs_tickers(self, fabrique_cotation: Callable[..., Cotation]) -> None:
        serie = [
            fabrique_cotation(jour=J1, ticker="TEST1"),
            fabrique_cotation(jour=J2, ticker="TEST2"),
        ]
        with pytest.raises(ErreurValidation, match="une seule valeur"):
            ajuster_serie(serie)

    def test_doublon_de_seance(self, fabrique_cotation: Callable[..., Cotation]) -> None:
        serie = [
            fabrique_cotation(jour=J1, source="source_a"),
            fabrique_cotation(jour=J1, source="source_b"),
        ]
        with pytest.raises(ErreurValidation, match="dédoublonnez"):
            ajuster_serie(serie)

    def test_operation_d_un_autre_ticker(self, fabrique_cotation: Callable[..., Cotation]) -> None:
        serie = [fabrique_cotation(jour=J1)]
        with pytest.raises(ErreurValidation, match="autre valeur"):
            ajuster_serie(serie, [dividende(50, J1, ticker="TEST2")])
