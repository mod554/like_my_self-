"""Moteur de backtest événementiel, barre par barre.

L'ordre des opérations sur chaque barre est le cœur du dispositif, et il n'est
pas négociable :

1. **exécuter** les intentions décidées à la barre *précédente*, à l'ouverture de
   celle-ci ;
2. **valoriser** le portefeuille à la clôture ;
3. **décider** des intentions pour la barre suivante, à partir d'une vue tronquée
   à cette barre incluse.

Une intention ne peut donc jamais être exécutée sur la barre qui l'a produite.

Hypothèses d'exécution, toutes conservatrices :

* exécution **à l'ouverture de la barre suivante**, jamais à la clôture qui a
  produit le signal ;
* **glissement** appliqué en défaveur de l'opérateur : à la hausse sur un achat,
  à la baisse sur une vente ;
* **plafond de volume** : un ordre ne peut consommer qu'une part configurée du
  volume de la séance. Au-delà, il est exécuté partiellement et l'écart est
  consigné — supposer qu'un gros ordre passe entièrement sur une valeur peu
  liquide est la façon la plus rapide de fabriquer une performance imaginaire ;
* **aucune exécution sur une séance sans transaction** : s'il ne s'est rien
  échangé, l'ordre n'aurait pas trouvé de contrepartie ;
* **frais réels** du barème configuré sur chaque opération simulée.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext

from brvm.config.modeles import Configuration
from brvm.domain.enums import SensOperation
from brvm.domain.monnaie import PRECISION_INTERNE, arrondi_xof
from brvm.indicators.serie import BarreTechnique, SerieTechnique
from brvm.portfolio.frais import MoteurFrais
from brvm.utils.erreurs import ErreurValidation

from .strategie import ContexteBarre, Intention, Strategie


@dataclass(frozen=True, slots=True)
class Execution:
    """Une opération simulée, exécutée, partielle ou refusée."""

    date_seance: date
    ticker: str
    sens: SensOperation
    quantite_demandee: int
    quantite_executee: int
    cours_reference: int | None
    cours_execute: int | None
    frais: int
    montant_net: int
    motif: str = ""
    refus: str | None = None

    @property
    def executee(self) -> bool:
        return self.quantite_executee > 0

    @property
    def partielle(self) -> bool:
        return 0 < self.quantite_executee < self.quantite_demandee


@dataclass(frozen=True, slots=True)
class PointCourbe:
    """Valeur du portefeuille à la clôture d'une barre."""

    date_seance: date
    especes: int
    valeur_titres: int
    valeur_totale: int
    #: Lignes non valorisées faute de cours ce jour-là.
    tickers_non_valorises: tuple[str, ...] = ()


@dataclass(slots=True)
class ResultatBacktest:
    """Ce qu'a produit une simulation, sans interprétation."""

    strategie: str
    debut: date
    fin: date
    capital_initial: int
    especes_finales: int
    positions_finales: dict[str, int] = field(default_factory=dict)
    executions: list[Execution] = field(default_factory=list)
    courbe: list[PointCourbe] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def valeur_finale(self) -> int:
        return self.courbe[-1].valeur_totale if self.courbe else self.capital_initial

    @property
    def executions_reussies(self) -> tuple[Execution, ...]:
        return tuple(execution for execution in self.executions if execution.executee)

    @property
    def total_frais(self) -> int:
        return sum(execution.frais for execution in self.executions)

    @property
    def refus(self) -> tuple[Execution, ...]:
        return tuple(execution for execution in self.executions if execution.refus)


class MoteurBacktest:
    """Rejoue une stratégie sur une période, barre par barre."""

    def __init__(
        self,
        series: Mapping[str, SerieTechnique],
        configuration: Configuration,
        moteur_frais: MoteurFrais | None = None,
    ) -> None:
        if not series:
            raise ErreurValidation("Aucune série fournie : rien à simuler.")
        self.series = dict(series)
        self.configuration = configuration
        self.reglages = configuration.backtest
        self.moteur_frais = moteur_frais or MoteurFrais(configuration)
        self.calendrier_commun = self._calendrier_commun()

    def _calendrier_commun(self) -> list[date]:
        """Union des séances de toutes les séries, dans l'ordre.

        L'union plutôt que l'intersection : une valeur qui ne cote pas un jour
        donné ne doit pas faire disparaître ce jour pour les autres.
        """
        jours: set[date] = set()
        for serie in self.series.values():
            jours.update(barre.date_seance for barre in serie.barres)
        return sorted(jours)

    # ---------------------------------------------------------------- simulation

    def executer(
        self, strategie: Strategie, debut: date | None = None, fin: date | None = None
    ) -> ResultatBacktest:
        """Simule la stratégie sur la période demandée.

        Raises:
            ErreurValidation: période vide ou hors des séries fournies.
        """
        jours = [
            jour
            for jour in self.calendrier_commun
            if (debut is None or jour >= debut) and (fin is None or jour <= fin)
        ]
        if len(jours) < 2:
            raise ErreurValidation(
                "Au moins deux séances sont nécessaires pour simuler : une pour décider, "
                "une pour exécuter.",
                seances=len(jours),
            )

        resultat = ResultatBacktest(
            strategie=getattr(strategie, "nom", type(strategie).__name__),
            debut=jours[0],
            fin=jours[-1],
            capital_initial=self.reglages.capital_initial,
            especes_finales=self.reglages.capital_initial,
        )
        especes = self.reglages.capital_initial
        positions: dict[str, int] = {}
        en_attente: Sequence[Intention] = ()

        index_par_serie = {
            ticker: {barre.date_seance: rang for rang, barre in enumerate(serie.barres)}
            for ticker, serie in self.series.items()
        }

        for rang, jour in enumerate(jours):
            # 1. Exécuter ce qui a été décidé la veille, à l'ouverture du jour.
            for intention in en_attente:
                execution, especes = self._executer_intention(
                    intention, jour, index_par_serie, positions, especes
                )
                resultat.executions.append(execution)
                if execution.executee:
                    delta = (
                        execution.quantite_executee
                        if intention.sens is SensOperation.ACHAT
                        else -execution.quantite_executee
                    )
                    positions[intention.ticker] = positions.get(intention.ticker, 0) + delta
                    if positions[intention.ticker] == 0:
                        positions.pop(intention.ticker)
            en_attente = ()

            # 2. Valoriser à la clôture.
            point = self._valoriser(jour, index_par_serie, positions, especes)
            resultat.courbe.append(point)

            # 3. Décider pour la barre suivante, sur une vue tronquée.
            if rang < len(jours) - 1:
                contexte = ContexteBarre(
                    date_seance=jour,
                    index=rang,
                    series=self._series_tronquees(jour, index_par_serie),
                    positions=dict(positions),
                    especes=especes,
                    configuration=self.configuration,
                    valeur_portefeuille=point.valeur_totale,
                )
                en_attente = tuple(strategie.decider(contexte))

        resultat.especes_finales = especes
        resultat.positions_finales = dict(positions)
        return resultat

    # ------------------------------------------------------------------ interne

    def _barre(
        self,
        ticker: str,
        jour: date,
        index_par_serie: Mapping[str, Mapping[date, int]],
    ) -> tuple[BarreTechnique | None, BarreTechnique | None]:
        """Barre du jour et barre précédente, ``None`` si la valeur n'est pas suivie."""
        serie = self.series.get(ticker)
        rang = index_par_serie.get(ticker, {}).get(jour)
        if serie is None or rang is None:
            return None, None
        precedente = serie.barres[rang - 1] if rang > 0 else None
        return serie.barres[rang], precedente

    def _series_tronquees(
        self, jour: date, index_par_serie: Mapping[str, Mapping[date, int]]
    ) -> dict[str, SerieTechnique]:
        """Vue des séries arrêtée à ``jour`` inclus.

        C'est la garantie structurelle contre le biais d'anticipation : la
        stratégie ne peut pas voir ce qui n'existe pas encore dans son contexte.
        """
        tronquees: dict[str, SerieTechnique] = {}
        for ticker, serie in self.series.items():
            rang = index_par_serie.get(ticker, {}).get(jour)
            if rang is None:
                # La valeur n'a pas de barre ce jour-là : on remonte à la dernière
                # barre antérieure connue.
                anterieures = [
                    position
                    for position, barre in enumerate(serie.barres)
                    if barre.date_seance <= jour
                ]
                if not anterieures:
                    continue
                rang = anterieures[-1]
            tronquees[ticker] = SerieTechnique(
                ticker=serie.ticker,
                barres=serie.barres[: rang + 1],
                avertissements=serie.avertissements,
                jusqu_a=jour,
            )
        return tronquees

    def _cours_d_execution(
        self, barre: BarreTechnique, precedente: BarreTechnique | None
    ) -> tuple[int | None, str | None]:
        """Cours de référence retenu pour exécuter, et le motif d'un refus."""
        if not barre.cotee:
            return None, (
                "aucune transaction sur cette séance : l'ordre n'aurait pas trouvé de contrepartie"
            )
        if barre.ouverture is not None:
            return int(barre.ouverture.to_integral_value()), None
        if self.reglages.execution_sans_ouverture == "REFUSER":
            return None, (
                "cours d'ouverture non publié par la source, et la configuration "
                "refuse d'exécuter sans lui"
            )
        if precedente is None or precedente.cloture is None:
            return None, (
                "cours d'ouverture non publié et aucune clôture antérieure pour lui "
                "servir d'approximation"
            )
        return int(precedente.cloture.to_integral_value()), None

    def _executer_intention(
        self,
        intention: Intention,
        jour: date,
        index_par_serie: Mapping[str, Mapping[date, int]],
        positions: Mapping[str, int],
        especes: int,
    ) -> tuple[Execution, int]:
        barre, precedente = self._barre(intention.ticker, jour, index_par_serie)
        if barre is None:
            return self._refus(intention, jour, "valeur absente des séries simulées"), especes

        reference, motif_refus = self._cours_d_execution(barre, precedente)
        if reference is None:
            return self._refus(intention, jour, motif_refus or "cours indisponible"), especes

        with localcontext() as contexte:
            contexte.prec = PRECISION_INTERNE
            glissement = self.reglages.slippage
            facteur = (
                Decimal(1) + glissement
                if intention.sens is SensOperation.ACHAT
                else Decimal(1) - glissement
            )
            cours = max(1, arrondi_xof(Decimal(reference) * facteur))
            plafond = Decimal(barre.volume) * self.reglages.part_max_volume_seance
            quantite_max = int(plafond.to_integral_value(rounding="ROUND_FLOOR"))

        quantite = min(intention.quantite, quantite_max)
        if intention.sens is SensOperation.VENTE:
            quantite = min(quantite, positions.get(intention.ticker, 0))

        if quantite <= 0:
            return (
                self._refus(
                    intention,
                    jour,
                    f"volume de la séance insuffisant : {barre.volume} titres échangés, "
                    f"soit un maximum de {quantite_max} exécutable au plafond configuré",
                    cours_reference=reference,
                ),
                especes,
            )

        decompte = self.moteur_frais.calculer(intention.sens, quantite, cours)
        if intention.sens is SensOperation.ACHAT and decompte.montant_net > especes:
            return (
                self._refus(
                    intention,
                    jour,
                    f"espèces insuffisantes : {decompte.montant_net} nécessaires, "
                    f"{especes} disponibles",
                    cours_reference=reference,
                ),
                especes,
            )

        especes += (
            -decompte.montant_net if intention.sens is SensOperation.ACHAT else decompte.montant_net
        )
        motif = intention.motif
        if quantite < intention.quantite:
            motif = (
                f"{motif} — exécution partielle : {quantite} sur {intention.quantite} "
                f"demandés, plafonnée par le volume de la séance"
            ).strip(" —")

        return (
            Execution(
                date_seance=jour,
                ticker=intention.ticker,
                sens=intention.sens,
                quantite_demandee=intention.quantite,
                quantite_executee=quantite,
                cours_reference=reference,
                cours_execute=cours,
                frais=decompte.total,
                montant_net=decompte.montant_net,
                motif=motif,
            ),
            especes,
        )

    @staticmethod
    def _refus(
        intention: Intention, jour: date, motif: str, cours_reference: int | None = None
    ) -> Execution:
        return Execution(
            date_seance=jour,
            ticker=intention.ticker,
            sens=intention.sens,
            quantite_demandee=intention.quantite,
            quantite_executee=0,
            cours_reference=cours_reference,
            cours_execute=None,
            frais=0,
            montant_net=0,
            motif=intention.motif,
            refus=motif,
        )

    def _valoriser(
        self,
        jour: date,
        index_par_serie: Mapping[str, Mapping[date, int]],
        positions: Mapping[str, int],
        especes: int,
    ) -> PointCourbe:
        valeur_titres = 0
        non_valorises: list[str] = []
        for ticker, quantite in positions.items():
            barre, _ = self._barre(ticker, jour, index_par_serie)
            if barre is None or barre.cloture is None:
                non_valorises.append(ticker)
                continue
            valeur_titres += quantite * int(barre.cloture.to_integral_value())
        return PointCourbe(
            date_seance=jour,
            especes=especes,
            valeur_titres=valeur_titres,
            valeur_totale=especes + valeur_titres,
            tickers_non_valorises=tuple(sorted(non_valorises)),
        )
