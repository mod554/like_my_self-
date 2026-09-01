"""Détection de signaux, avec interdiction stricte du biais d'anticipation.

La règle qui gouverne tout ce module tient en une phrase : **un signal constaté
sur une barre ne peut pas être exécuté sur cette barre**.

La clôture d'une séance n'est connue qu'une fois la séance terminée. Un
croisement de moyennes calculé sur la clôture du jour J ne peut donc pas donner
lieu à un ordre exécuté au cours du jour J : au mieux à l'ouverture de J+1. Tout
backtest qui ignore ce décalage produit des performances flatteuses et
irréalisables — c'est la façon la plus courante de se mentir en analyse
technique.

Chaque :class:`Signal` porte donc deux dates : celle où il est constaté, et celle
où il devient exécutable. Le moteur de backtest n'a pas le droit de regarder la
première.

Ces signaux ne sont pas des recommandations. Ce sont des franchissements
mécaniques, dont la valeur prédictive n'est établie par rien, et dont le score de
confiance dit surtout à quel point la donnée sous-jacente est mince.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.confiance import ScoreConfiance
from brvm.indicators.resultats import ResultatIndicateur
from brvm.utils.erreurs import ErreurCalendrier


class SensSignal(StrEnum):
    ACHAT = "ACHAT"
    VENTE = "VENTE"


@dataclass(frozen=True, slots=True)
class Signal:
    """Franchissement constaté sur une séance, exécutable à la suivante."""

    ticker: str
    #: Séance sur laquelle le franchissement est constaté, après sa clôture.
    date_constat: date
    #: Première séance où un ordre peut être passé. Jamais égale au constat.
    date_execution: date
    sens: SensSignal
    regle: str
    explication: str
    confiance: ScoreConfiance
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.date_execution <= self.date_constat:
            raise ValueError(
                "Un signal ne peut pas être exécuté sur la séance qui l'a fait naître : "
                "sa clôture n'était pas connue pendant cette séance."
            )

    def resume(self) -> str:
        return (
            f"{self.sens.value} {self.ticker} — {self.regle}, constaté le "
            f"{self.date_constat.isoformat()}, exécutable le "
            f"{self.date_execution.isoformat()} (confiance {self.confiance.niveau})"
        )


def _croisements(
    rapide: Sequence[Decimal | None], lente: Sequence[Decimal | None]
) -> list[tuple[int, SensSignal]]:
    """Positions où ``rapide`` traverse ``lente``, avec le sens de la traversée.

    Les deux valeurs de la séance précédente et de la séance courante doivent
    être disponibles : un croisement supposé de part et d'autre d'un trou n'a pas
    été observé.
    """
    croisements: list[tuple[int, SensSignal]] = []
    for position in range(1, len(rapide)):
        avant_r, avant_l = rapide[position - 1], lente[position - 1]
        apres_r, apres_l = rapide[position], lente[position]
        if None in (avant_r, avant_l, apres_r, apres_l):
            continue
        assert avant_r is not None and avant_l is not None
        assert apres_r is not None and apres_l is not None
        if avant_r <= avant_l and apres_r > apres_l:
            croisements.append((position, SensSignal.ACHAT))
        elif avant_r >= avant_l and apres_r < apres_l:
            croisements.append((position, SensSignal.VENTE))
    return croisements


def _franchissements_seuil(
    valeurs: Sequence[Decimal | None], seuil: Decimal, montant: bool
) -> list[int]:
    """Positions où la série franchit ``seuil``, vers le haut si ``montant``."""
    positions: list[int] = []
    for position in range(1, len(valeurs)):
        avant, apres = valeurs[position - 1], valeurs[position]
        if avant is None or apres is None:
            continue
        if (montant and avant <= seuil < apres) or (not montant and avant >= seuil > apres):
            positions.append(position)
    return positions


class DetecteurSignaux:
    """Applique un jeu de règles mécaniques à une valeur."""

    def __init__(
        self,
        indicateurs: Indicateurs,
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        self.indicateurs = indicateurs
        self.configuration = configuration
        self.calendrier = calendrier
        self.reglages = configuration.indicateurs

    # ------------------------------------------------------------------ outils

    def _executable(self, constat: date) -> date | None:
        """Première séance suivant le constat, ``None`` si le calendrier l'ignore."""
        try:
            return self.calendrier.prochaine_seance(constat)
        except ErreurCalendrier:
            return None

    def _fabriquer(
        self,
        position: int,
        reference: ResultatIndicateur,
        sens: SensSignal,
        regle: str,
        explication: str,
    ) -> Signal | None:
        constat = reference.points[position].date_seance
        execution = self._executable(constat)
        if execution is None:
            return None
        avertissements = list(reference.avertissements)
        point = reference.points[position]
        if point.anciennete > 0:
            avertissements.append(
                f"Signal assis sur une donnée vieille de {point.anciennete} séance(s) : "
                "la dernière transaction remonte à avant le franchissement."
            )
        if point.taux_remplissage > self.reglages.taux_remplissage_alerte:
            avertissements.append(
                f"{point.taux_remplissage:.0%} de la fenêtre est constituée de cours "
                "reportés : le franchissement peut n'être qu'un artefact du report."
            )
        return Signal(
            ticker=self.indicateurs.serie.ticker,
            date_constat=constat,
            date_execution=execution,
            sens=sens,
            regle=regle,
            explication=explication,
            confiance=self.indicateurs.confiance,
            avertissements=tuple(avertissements),
        )

    # ------------------------------------------------------------------ règles

    def croisement_moyennes(self) -> list[Signal]:
        """Croisement de la moyenne courte et de la moyenne longue."""
        courte = self.indicateurs.moyenne_simple(self.reglages.fenetre_mm_courte)
        longue = self.indicateurs.moyenne_simple(self.reglages.fenetre_mm_longue)
        regle = (
            f"croisement MM{self.reglages.fenetre_mm_courte}/MM{self.reglages.fenetre_mm_longue}"
        )
        signaux: list[Signal] = []
        for position, sens in _croisements(courte.valeurs(), longue.valeurs()):
            direction = "au-dessus de" if sens is SensSignal.ACHAT else "sous"
            signal = self._fabriquer(
                position,
                courte,
                sens,
                regle,
                f"La moyenne {self.reglages.fenetre_mm_courte} séances est passée "
                f"{direction} la moyenne {self.reglages.fenetre_mm_longue} séances.",
            )
            if signal is not None:
                signaux.append(signal)
        return signaux

    def seuils_rsi(self) -> list[Signal]:
        """Sortie de zone de survente ou de surachat.

        Le signal est pris à la **sortie** de la zone, pas à l'entrée : un RSI qui
        plonge sous 30 peut y rester des semaines.
        """
        resultat = self.indicateurs.rsi()
        valeurs = resultat.valeurs()
        signaux: list[Signal] = []

        for position in _franchissements_seuil(valeurs, self.reglages.rsi_survente, True):
            signal = self._fabriquer(
                position,
                resultat,
                SensSignal.ACHAT,
                f"sortie de survente RSI {self.reglages.rsi_survente}",
                f"Le RSI est repassé au-dessus de {self.reglages.rsi_survente} après "
                "être descendu en dessous.",
            )
            if signal is not None:
                signaux.append(signal)

        for position in _franchissements_seuil(valeurs, self.reglages.rsi_surachat, False):
            signal = self._fabriquer(
                position,
                resultat,
                SensSignal.VENTE,
                f"sortie de surachat RSI {self.reglages.rsi_surachat}",
                f"Le RSI est repassé sous {self.reglages.rsi_surachat} après l'avoir dépassé.",
            )
            if signal is not None:
                signaux.append(signal)
        return signaux

    def croisement_macd(self) -> list[Signal]:
        """Croisement de la ligne MACD et de sa ligne de signal."""
        macd = self.indicateurs.macd()
        signaux: list[Signal] = []
        for position, sens in _croisements(macd.ligne.valeurs(), macd.signal.valeurs()):
            direction = "au-dessus de" if sens is SensSignal.ACHAT else "sous"
            signal = self._fabriquer(
                position,
                macd.ligne,
                sens,
                "croisement MACD/signal",
                f"La ligne MACD est passée {direction} sa ligne de signal.",
            )
            if signal is not None:
                signaux.append(signal)
        return signaux

    def tous(self) -> list[Signal]:
        """Tous les signaux détectés, du plus ancien au plus récent."""
        signaux = self.croisement_moyennes() + self.seuils_rsi() + self.croisement_macd()
        return sorted(signaux, key=lambda signal: (signal.date_constat, signal.regle))

    def derniers(self, depuis: date | None = None) -> list[Signal]:
        """Signaux constatés à partir d'une date, pour une revue quotidienne."""
        signaux = self.tous()
        if depuis is None:
            return signaux
        return [signal for signal in signaux if signal.date_constat >= depuis]
