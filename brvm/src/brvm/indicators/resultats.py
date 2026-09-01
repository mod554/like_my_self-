"""Sorties d'indicateur : la valeur, et de quoi juger si on peut s'y fier.

Un indicateur qui renvoie un nombre nu est inutilisable sur ce marché : 42 calculé
sur vingt séances dont dix-huit sans échange ne vaut pas 42 calculé sur vingt
séances pleines. Chaque point porte donc, avec sa valeur, la qualité de la fenêtre
qui l'a produit — et le motif du refus quand il n'y a pas de valeur.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from brvm.indicators.confiance import ScoreConfiance


@dataclass(frozen=True, slots=True)
class PointIndicateur:
    """Valeur d'un indicateur pour une séance, avec la qualité de sa fenêtre."""

    date_seance: date
    valeur: Decimal | None
    #: Séances réellement cotées dans la fenêtre ayant servi au calcul.
    seances_cotees: int
    #: Taille de la fenêtre, en séances de calendrier.
    seances_fenetre: int
    #: Part de la fenêtre portant un cours reporté et non observé.
    taux_remplissage: Decimal
    #: Séances écoulées depuis la dernière séance réellement cotée.
    anciennete: int = 0
    #: Renseigné lorsque le système a refusé de calculer.
    motif_refus: str | None = None

    @property
    def disponible(self) -> bool:
        return self.valeur is not None


@dataclass(frozen=True, slots=True)
class ResultatIndicateur:
    """Série complète d'un indicateur, avec ses paramètres et sa confiance."""

    nom: str
    ticker: str
    parametres: Mapping[str, int | Decimal | str]
    points: tuple[PointIndicateur, ...]
    confiance: ScoreConfiance
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.points)

    @property
    def dernier(self) -> PointIndicateur | None:
        return self.points[-1] if self.points else None

    @property
    def derniere_valeur(self) -> Decimal | None:
        dernier = self.dernier
        return dernier.valeur if dernier is not None else None

    def valeurs(self) -> list[Decimal | None]:
        return [point.valeur for point in self.points]

    def dates(self) -> list[date]:
        return [point.date_seance for point in self.points]

    def par_date(self) -> dict[date, PointIndicateur]:
        return {point.date_seance: point for point in self.points}

    def points_disponibles(self) -> tuple[PointIndicateur, ...]:
        return tuple(point for point in self.points if point.disponible)

    def nb_refus(self) -> int:
        return sum(1 for point in self.points if point.motif_refus is not None)

    def resume(self) -> str:
        """Une ligne lisible, valeur et fiabilité ensemble."""
        dernier = self.dernier
        if dernier is None:
            return f"{self.nom} ({self.ticker}) : série vide"
        if dernier.valeur is None:
            return f"{self.nom} ({self.ticker}) : non calculé — {dernier.motif_refus}"
        fraicheur = (
            "" if dernier.anciennete == 0 else f", donnée vieille de {dernier.anciennete} séance(s)"
        )
        return (
            f"{self.nom} ({self.ticker}) au {dernier.date_seance.isoformat()} : "
            f"{dernier.valeur} — {dernier.seances_cotees}/{dernier.seances_fenetre} séances "
            f"cotées, confiance {self.confiance.niveau}{fraicheur}"
        )


@dataclass(frozen=True, slots=True)
class ResultatMacd:
    """Les trois composantes du MACD, chacune avec sa propre qualité de fenêtre."""

    ligne: ResultatIndicateur
    signal: ResultatIndicateur
    histogramme: ResultatIndicateur


@dataclass(frozen=True, slots=True)
class ResultatBollinger:
    """Les trois bandes, chacune avec sa propre qualité de fenêtre."""

    basse: ResultatIndicateur
    moyenne: ResultatIndicateur
    haute: ResultatIndicateur


@dataclass(frozen=True, slots=True)
class ResultatExtremes:
    """Plus bas et plus haut glissants."""

    plus_bas: ResultatIndicateur
    plus_haut: ResultatIndicateur


def series_alignees(resultats: Sequence[ResultatIndicateur]) -> bool:
    """Vrai si tous les résultats portent exactement les mêmes séances."""
    if not resultats:
        return True
    reference = resultats[0].dates()
    return all(resultat.dates() == reference for resultat in resultats[1:])
