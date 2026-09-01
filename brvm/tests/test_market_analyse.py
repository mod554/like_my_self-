"""Mesure d'une valeur : ce qui n'a pas pu être mesuré est nommé, jamais noté."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

from brvm.config.modeles import CRITERES_FONDAMENTAUX, CRITERES_TECHNIQUES, Configuration
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import SerieTechnique
from brvm.market.analyse import analyser, dernier_cours_cote
from brvm.market.fondamentaux import Fondamentaux


def mesurer(
    serie: SerieTechnique,
    configuration: Configuration,
    ticker: str = "TEST1",
    **extras: object,
) -> object:
    return analyser(
        ticker=ticker,
        serie=serie,
        indicateurs=Indicateurs(serie, configuration),
        configuration=configuration,
        **extras,  # type: ignore[arg-type]
    )


class TestDernierCoursCote:
    def test_ignore_les_reports(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Un cours reporté n'a jamais été échangé : le mesurer serait mesurer
        une fiction."""
        serie = fabrique_serie([1000, 1100, None, None])
        assert serie.barres[-1].cloture == Decimal(1100)  # report
        assert dernier_cours_cote(serie) == 1100

    def test_absent_quand_aucune_seance_cotee(
        self, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        assert dernier_cours_cote(fabrique_serie([None, None, None])) is None


class TestCriteresTechniques:
    def test_serie_reguliere_mesure_tous_les_criteres_techniques(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + i * 5 for i in range(120)])
        analyse = mesurer(serie, configuration)
        non_mesures = [
            nom
            for nom in CRITERES_TECHNIQUES
            if not analyse.criteres[nom].mesurable  # type: ignore[attr-defined]
        ]
        assert non_mesures == []

    def test_serie_courte_nomme_ce_qui_manque_au_lieu_de_noter_zero(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1010, 1020])
        analyse = mesurer(serie, configuration)
        absents = [c for c in analyse.criteres.values() if not c.mesurable]  # type: ignore[attr-defined]
        assert absents, "une série de trois séances ne peut pas tout mesurer"
        for critere in absents:
            assert critere.note is None
            assert critere.motif_absent

    def test_momentum_haussier_note_mieux_qu_un_momentum_baissier(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        hausse = mesurer(fabrique_serie([1000 + i * 5 for i in range(120)]), configuration)
        baisse = mesurer(fabrique_serie([1600 - i * 5 for i in range(120)]), configuration)
        assert hausse.criteres["momentum"].note > baisse.criteres["momentum"].note  # type: ignore[attr-defined]

    def test_source_sans_montant_echange_ne_note_pas_le_volume(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Une source qui ne publie pas les montants ne fait pas tomber la note
        à zéro : elle rend le critère non mesurable, ce qui n'est pas la même
        chose et se lit dans la couverture."""
        serie = fabrique_serie([1000 + i for i in range(120)], volume_xof=None)
        analyse = mesurer(serie, configuration)
        assert not analyse.criteres["volume"].mesurable  # type: ignore[attr-defined]
        assert "aucun montant" in (analyse.criteres["volume"].motif_absent or "")  # type: ignore[attr-defined]

    def test_repli_est_nul_au_plus_haut(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = mesurer(fabrique_serie([1000 + i * 5 for i in range(120)]), configuration)
        assert analyse.criteres["repli"].valeur == Decimal(0)  # type: ignore[attr-defined]
        assert analyse.criteres["repli"].note == Decimal(0)  # type: ignore[attr-defined]


class TestCriteresFondamentaux:
    def test_absents_sont_tous_nommes_quand_rien_n_est_saisi(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = mesurer(fabrique_serie([1000 + i for i in range(120)]), configuration)
        for nom in CRITERES_FONDAMENTAUX:
            critere = analyse.criteres[nom]  # type: ignore[attr-defined]
            assert not critere.mesurable
            assert "fondamentale" in (critere.motif_absent or "")

    def test_avertit_que_le_long_terme_s_abstiendra(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = mesurer(fabrique_serie([1000 + i for i in range(120)]), configuration)
        assert any("long terme" in a for a in analyse.avertissements)  # type: ignore[attr-defined]

    def test_exercice_saisi_produit_les_ratios(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        exercices = [
            Fondamentaux(
                ticker="TEST1",
                exercice=2025,
                source="rapport annuel fictif",
                dividende_par_action=60,
                resultat_net_par_action=100,
                capitaux_propres_par_action=800,
            ),
            Fondamentaux(
                ticker="TEST1",
                exercice=2024,
                source="rapport annuel fictif",
                dividende_par_action=50,
            ),
        ]
        analyse = mesurer(
            fabrique_serie([1000 + i for i in range(120)]),
            configuration,
            exercices=exercices,
            annee_courante=2026,
        )
        assert analyse.ratios is not None  # type: ignore[attr-defined]
        assert analyse.criteres["rendement_dividende"].mesurable  # type: ignore[attr-defined]
        assert analyse.criteres["per"].mesurable  # type: ignore[attr-defined]
        assert analyse.criteres["price_book"].mesurable  # type: ignore[attr-defined]
        assert analyse.criteres["regularite_dividende"].mesurable  # type: ignore[attr-defined]

    def test_un_seul_exercice_ne_mesure_aucune_regularite(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Une régularité sur un point n'est pas une régularité."""
        exercices = [
            Fondamentaux(
                ticker="TEST1",
                exercice=2025,
                source="fictif",
                dividende_par_action=60,
            )
        ]
        analyse = mesurer(
            fabrique_serie([1000 + i for i in range(120)]),
            configuration,
            exercices=exercices,
            annee_courante=2026,
        )
        critere = analyse.criteres["regularite_dividende"]  # type: ignore[attr-defined]
        assert not critere.mesurable
        assert "deux au minimum" in (critere.motif_absent or "")

    def test_ratios_calcules_sur_le_dernier_cours_cote(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le rendement se rapporte à un cours réellement échangé, pas à un report."""
        serie = fabrique_serie([1000] * 118 + [500, None])
        analyse = mesurer(
            serie,
            configuration,
            exercices=[
                Fondamentaux(
                    ticker="TEST1", exercice=2025, source="fictif", dividende_par_action=50
                )
            ],
            annee_courante=2026,
        )
        assert analyse.cours == 500  # type: ignore[attr-defined]
        assert analyse.ratios.rendement_dividende == Decimal("0.1")  # type: ignore[attr-defined]


class TestConfianceEtTaille:
    def test_serie_trouee_abaisse_la_confiance(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        pleine = mesurer(fabrique_serie([1000 + i for i in range(120)]), configuration)
        trouee = mesurer(
            fabrique_serie([1000 + i if i % 4 == 0 else None for i in range(120)]),
            configuration,
        )
        assert trouee.confiance < pleine.confiance  # type: ignore[attr-defined]
        assert trouee.seances_cotees < trouee.seances_attendues  # type: ignore[attr-defined]

    def test_taille_tenable_absente_est_motivee(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Aucune séance cotée : aucune taille de position n'est défendable, et
        le système dit pourquoi plutôt que de rendre un zéro muet."""
        analyse = mesurer(fabrique_serie([None] * 40), configuration)
        assert analyse.taille_tenable == 0  # type: ignore[attr-defined]
        assert analyse.motif_taille  # type: ignore[attr-defined]

    def test_date_du_cours_est_celle_d_une_seance_cotee(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1010, None, None], debut=date(2026, 3, 2))
        analyse = mesurer(serie, configuration)
        assert analyse.date_cours == serie.barres[1].date_seance  # type: ignore[attr-defined]


class TestCritereInconnu:
    def test_critere_non_produit_est_absent_et_non_nul(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        analyse = mesurer(fabrique_serie([1000 + i for i in range(120)]), configuration)
        inconnu = analyse.critere("critere_qui_n_existe_pas")  # type: ignore[attr-defined]
        assert not inconnu.mesurable
        assert inconnu.note is None
