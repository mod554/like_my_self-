"""Interface de stratégie et vue du marché offerte à une décision.

Le biais d'anticipation n'est pas évité ici par discipline, mais **par
construction** : une stratégie ne reçoit jamais autre chose qu'un
:class:`ContexteBarre`, et celui-ci ne contient que des séries tronquées à la
barre courante incluse. Il n'existe aucun chemin par lequel une stratégie
pourrait consulter une barre future, même par erreur.

Une intention décidée sur une barre est transmise au moteur, qui l'exécutera à
l'ouverture de la barre suivante — jamais sur celle qui l'a produite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from brvm.config.modeles import Configuration
from brvm.domain.enums import SensOperation
from brvm.indicators.serie import SerieTechnique


@dataclass(frozen=True, slots=True)
class Intention:
    """Ordre souhaité, à exécuter à l'ouverture de la barre suivante."""

    ticker: str
    sens: SensOperation
    quantite: int
    motif: str = ""

    def __post_init__(self) -> None:
        if self.quantite <= 0:
            raise ValueError("Une intention doit porter une quantité strictement positive.")


@dataclass(frozen=True, slots=True)
class ContexteBarre:
    """Tout ce qu'une stratégie a le droit de savoir à la clôture d'une barre."""

    date_seance: date
    #: Rang de la barre dans la période simulée.
    index: int
    #: Séries tronquées à cette barre incluse. Aucune barre postérieure n'y figure.
    series: Mapping[str, SerieTechnique]
    #: Quantités détenues à cet instant.
    positions: Mapping[str, int]
    especes: int
    configuration: Configuration
    #: Valeur du portefeuille à la clôture de cette barre.
    valeur_portefeuille: int = 0

    def cours(self, ticker: str) -> Decimal | None:
        """Dernière clôture connue d'une valeur, ``None`` si elle n'a jamais coté."""
        serie = self.series.get(ticker)
        if serie is None or not serie.barres:
            return None
        return serie.barres[-1].cloture

    def quantite(self, ticker: str) -> int:
        return self.positions.get(ticker, 0)


@runtime_checkable
class Strategie(Protocol):
    """Contrat d'une stratégie simulable.

    ``decider`` est appelée une fois par barre, après sa clôture. Elle ne doit
    avoir aucun effet de bord : le moteur peut la rejouer sur des fenêtres
    différentes lors d'une validation walk-forward.
    """

    nom: str

    def decider(self, contexte: ContexteBarre) -> Sequence[Intention]: ...


@dataclass
class StrategieAchatConservation:
    """Stratégie de référence : acheter une fois, puis ne plus rien faire.

    Elle sert de point de comparaison. Une stratégie active qui ne bat pas
    l'achat-conservation après frais n'a pas démontré grand-chose — et sur un
    marché où chaque aller-retour coûte deux commissions et deux TVA, c'est un
    comparatif exigeant.
    """

    repartition: Mapping[str, int]
    nom: str = "achat et conservation"
    _fait: bool = field(default=False, init=False)

    def decider(self, contexte: ContexteBarre) -> Sequence[Intention]:
        if self._fait:
            return ()
        intentions = [
            Intention(ticker, SensOperation.ACHAT, quantite, "constitution initiale")
            for ticker, quantite in self.repartition.items()
            if quantite > 0
        ]
        self._fait = True
        return intentions

    def reinitialiser(self) -> None:
        """Remet la stratégie dans son état initial, pour une nouvelle simulation."""
        self._fait = False
