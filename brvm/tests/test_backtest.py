"""Backtest : ordre des opérations, exécution conservatrice, métriques, walk-forward."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest

from brvm.backtest.metriques import calculer_metriques, transactions_depuis
from brvm.backtest.moteur import MoteurBacktest
from brvm.backtest.strategie import (
    ContexteBarre,
    Intention,
    StrategieAchatConservation,
)
from brvm.backtest.walkforward import decouper, valider
from brvm.config.modeles import Configuration
from brvm.domain.enums import SensOperation
from brvm.indicators.serie import SerieTechnique
from brvm.utils.erreurs import ErreurDonneesInsuffisantes, ErreurValidation


@dataclass
class EspionStrategie:
    """Enregistre tout ce qu'elle voit, pour vérifier ce qu'on lui donne."""

    intentions_par_barre: Mapping[int, Sequence[Intention]] = field(default_factory=dict)
    nom: str = "espion"
    vues: list[tuple[date, date]] = field(default_factory=list)
    decisions: list[date] = field(default_factory=list)

    def decider(self, contexte: ContexteBarre) -> Sequence[Intention]:
        for serie in contexte.series.values():
            if serie.barres:
                self.vues.append((contexte.date_seance, serie.barres[-1].date_seance))
        self.decisions.append(contexte.date_seance)
        return self.intentions_par_barre.get(contexte.index, ())


class TestAntiAnticipation:
    def test_la_strategie_ne_voit_jamais_une_barre_future(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Garantie structurelle : les séries reçues sont tronquées à la barre courante."""
        serie = fabrique_serie([1000 + index for index in range(20)])
        espion = EspionStrategie()
        MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        assert espion.vues
        for date_contexte, derniere_barre in espion.vues:
            assert derniere_barre <= date_contexte

    def test_une_intention_n_est_jamais_executee_sur_sa_propre_barre(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index for index in range(20)], volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 10)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        execution = resultat.executions[0]
        assert execution.date_seance > espion.decisions[0]
        assert execution.date_seance == serie.barres[1].date_seance

    def test_aucune_decision_sur_la_derniere_barre(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Elle ne pourrait jamais être exécutée : la demander serait trompeur."""
        serie = fabrique_serie([1000 + index for index in range(10)])
        espion = EspionStrategie()
        MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        assert espion.decisions[-1] == serie.barres[-2].date_seance


class TestExecution:
    def test_execution_a_l_ouverture_de_la_barre_suivante(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1100, 1200], volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 10)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        # L'ouverture de la deuxième barre vaut sa clôture dans la fixture : 1 100.
        assert resultat.executions[0].cours_reference == 1_100

    def test_glissement_en_defaveur_de_l_operateur(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, 1000, 1000], volume=10_000)
        achat = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 10)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(achat)
        execution = resultat.executions[0]
        assert execution.cours_execute is not None
        assert execution.cours_execute > 1_000  # slippage 0,5 % du barème de test

    def test_glissement_inverse_a_la_vente(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 5, volume=10_000)
        strategie = EspionStrategie(
            intentions_par_barre={
                0: [Intention("TEST1", SensOperation.ACHAT, 10)],
                2: [Intention("TEST1", SensOperation.VENTE, 10)],
            }
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(strategie)
        vente = next(e for e in resultat.executions if e.sens is SensOperation.VENTE)
        assert vente.cours_execute is not None and vente.cours_execute < 1_000

    def test_plafond_de_volume_execute_partiellement(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le barème de test plafonne à 10 % du volume de la séance."""
        serie = fabrique_serie([1000] * 5, volume=100)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 500)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        execution = resultat.executions[0]
        assert execution.partielle
        assert execution.quantite_executee == 10
        assert "exécution partielle" in execution.motif

    def test_aucune_execution_sur_une_seance_sans_transaction(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000, None, 1000], volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 10)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        execution = resultat.executions[0]
        assert not execution.executee
        assert "aurait pas trouvé de contrepartie" in (execution.refus or "")

    def test_especes_insuffisantes(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1_000_000] * 5, volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 100)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        assert "insuffisantes" in (resultat.executions[0].refus or "")

    def test_les_frais_reels_sont_appliques(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 5, volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 100)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        assert resultat.executions[0].frais > 0
        assert resultat.total_frais == resultat.executions[0].frais

    def test_vente_limitee_a_la_position(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 6, volume=10_000)
        strategie = EspionStrategie(
            intentions_par_barre={
                0: [Intention("TEST1", SensOperation.ACHAT, 10)],
                2: [Intention("TEST1", SensOperation.VENTE, 100)],
            }
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(strategie)
        vente = next(e for e in resultat.executions if e.sens is SensOperation.VENTE)
        assert vente.quantite_executee == 10

    def test_periode_trop_courte(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000])
        with pytest.raises(ErreurValidation, match="deux séances"):
            MoteurBacktest({"TEST1": serie}, configuration).executer(EspionStrategie())

    def test_series_vides_refusees(self, configuration: Configuration) -> None:
        with pytest.raises(ErreurValidation, match="Aucune série"):
            MoteurBacktest({}, configuration)


class TestCourbeEtPositions:
    def test_courbe_valorisee_a_chaque_barre(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 5, volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(EspionStrategie())
        assert len(resultat.courbe) == 5
        assert all(
            point.valeur_totale == configuration.backtest.capital_initial
            for point in resultat.courbe
        )

    def test_position_et_especes_apres_achat(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 5, volume=10_000)
        espion = EspionStrategie(
            intentions_par_barre={0: [Intention("TEST1", SensOperation.ACHAT, 100)]}
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(espion)
        assert resultat.positions_finales == {"TEST1": 100}
        assert resultat.especes_finales < configuration.backtest.capital_initial

    def test_achat_conservation(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index * 10 for index in range(20)], volume=10_000)
        strategie = StrategieAchatConservation({"TEST1": 50})
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(strategie)
        assert len(resultat.executions_reussies) == 1
        assert resultat.positions_finales == {"TEST1": 50}
        assert resultat.valeur_finale > configuration.backtest.capital_initial


class TestMetriques:
    def test_rendement_et_frais(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index * 20 for index in range(30)], volume=10_000)
        strategie = StrategieAchatConservation({"TEST1": 100})
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(strategie)
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.rendement_total > 0
        assert metriques.total_frais > 0
        assert metriques.performance_brute > metriques.performance_nette

    def test_part_des_couts_dans_la_performance_brute(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Le chiffre qui dit ce que l'intermédiaire a pris sur le travail accompli."""
        serie = fabrique_serie([1000 + index * 20 for index in range(30)], volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(
            StrategieAchatConservation({"TEST1": 100})
        )
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.part_des_couts is not None
        assert Decimal(0) < metriques.part_des_couts < Decimal(1)

    def test_part_des_couts_indefinie_si_performance_negative(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([2000 - index * 30 for index in range(30)], volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(
            StrategieAchatConservation({"TEST1": 100})
        )
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.part_des_couts is None
        assert any("partie en frais" in a for a in metriques.avertissements)

    def test_drawdown_mesure(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        cours = [1000 + index * 20 for index in range(15)] + [
            1300 - index * 30 for index in range(15)
        ]
        resultat = MoteurBacktest(
            {"TEST1": fabrique_serie(cours, volume=10_000)}, configuration
        ).executer(StrategieAchatConservation({"TEST1": 100}))
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.drawdown_maximum > 0

    def test_taux_de_reussite_sans_cession(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Une position encore ouverte n'est ni gagnante ni perdante."""
        serie = fabrique_serie([1000 + index for index in range(20)], volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(
            StrategieAchatConservation({"TEST1": 10})
        )
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.taux_reussite is None
        assert any("Aucune cession" in a for a in metriques.avertissements)

    def test_taux_de_reussite_avec_cession(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index * 50 for index in range(10)], volume=10_000)
        strategie = EspionStrategie(
            intentions_par_barre={
                0: [Intention("TEST1", SensOperation.ACHAT, 100)],
                5: [Intention("TEST1", SensOperation.VENTE, 100)],
            }
        )
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(strategie)
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.nb_cessions == 1
        assert metriques.taux_reussite == Decimal(1)

    def test_volatilite_nulle_signalee(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 10, volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(EspionStrategie())
        metriques = calculer_metriques(resultat, configuration)
        assert metriques.sharpe is None
        assert any("Volatilité nulle" in a for a in metriques.avertissements)

    def test_resume_lisible(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000 + index * 20 for index in range(30)], volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(
            StrategieAchatConservation({"TEST1": 100})
        )
        resume = calculer_metriques(resultat, configuration).resume()
        assert "Rendement total" in resume and "Part des coûts" in resume

    def test_conversion_en_transactions(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 5, volume=10_000)
        resultat = MoteurBacktest({"TEST1": serie}, configuration).executer(
            StrategieAchatConservation({"TEST1": 10})
        )
        transactions = transactions_depuis(resultat.executions)
        assert len(transactions) == 1
        assert transactions[0].total_frais == resultat.executions_reussies[0].frais


class TestWalkForward:
    def test_decoupage_en_fenetres_glissantes(self) -> None:
        seances = [date(2026, 1, 1) + timedelta(days=jour) for jour in range(20)]
        fenetres = decouper(seances, apprentissage=10, validation=5)
        assert len(fenetres) == 2
        assert fenetres[0].debut_validation > fenetres[0].fin_apprentissage
        # Les validations se suivent sans se chevaucher.
        assert fenetres[1].debut_validation > fenetres[0].fin_validation

    def test_fenetres_trop_courtes_refusees(self) -> None:
        with pytest.raises(ErreurDonneesInsuffisantes):
            decouper([date(2026, 1, 1)], apprentissage=1, validation=0)

    def test_historique_insuffisant_explique(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 10, volume=10_000)
        with pytest.raises(ErreurDonneesInsuffisantes, match="insuffisant"):
            valider(
                {"TEST1": serie},
                lambda parametres: StrategieAchatConservation({"TEST1": 10}),
                [{"quantite": 10}],
                configuration,
            )

    def test_grille_vide_refusee(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        serie = fabrique_serie([1000] * 10, volume=10_000)
        with pytest.raises(ErreurDonneesInsuffisantes, match="Grille"):
            valider(
                {"TEST1": serie},
                lambda parametres: StrategieAchatConservation({"TEST1": 10}),
                [],
                configuration,
            )

    def test_validation_complete(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        """Les paramètres sont choisis sur l'apprentissage, mesurés sur la validation."""
        cours = [1000 + (index * 17) % 300 for index in range(120)]
        serie = fabrique_serie(cours, volume=10_000)
        courtes = configuration.backtest.model_copy(
            update={"walk_forward_apprentissage": 40, "walk_forward_validation": 20}
        )
        reglages = configuration.model_copy(update={"backtest": courtes})

        resultat = valider(
            {"TEST1": serie},
            lambda parametres: StrategieAchatConservation({"TEST1": parametres["quantite"]}),
            [{"quantite": 10}, {"quantite": 50}],
            reglages,
        )
        assert len(resultat.fenetres) >= 2
        assert resultat.rendement_valide is not None
        assert all(
            fenetre.parametres_retenus in ({"quantite": 10}, {"quantite": 50})
            for fenetre in resultat.fenetres
        )
        assert "validation" in resultat.resume()

    def test_l_ecart_entre_apprentissage_et_validation_est_signale(
        self, fabrique_serie: Callable[..., SerieTechnique], configuration: Configuration
    ) -> None:
        cours = [1000 + (index * 23) % 400 for index in range(120)]
        serie = fabrique_serie(cours, volume=10_000)
        courtes = configuration.backtest.model_copy(
            update={"walk_forward_apprentissage": 40, "walk_forward_validation": 20}
        )
        reglages = configuration.model_copy(update={"backtest": courtes})
        resultat = valider(
            {"TEST1": serie},
            lambda parametres: StrategieAchatConservation({"TEST1": parametres["quantite"]}),
            [{"quantite": 10}, {"quantite": 30}, {"quantite": 60}],
            reglages,
        )
        # L'écart peut être positif ou négatif, mais il doit être calculable.
        assert all(isinstance(fenetre.ecart_de_rendement, Decimal) for fenetre in resultat.fenetres)
