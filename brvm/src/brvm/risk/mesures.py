"""Mesures de risque : volatilité, drawdown, corrélation.

Une précision qui change tout sur ce marché : **la corrélation entre deux valeurs
n'est calculée que sur les séances où les deux ont réellement échangé**.

Calculée sur des séries à cours reportés, elle mesure surtout que deux valeurs
n'ont pas coté les mêmes jours — deux titres immobiles paraissent parfaitement
corrélés alors qu'aucune information ne les relie. Une diversification bâtie sur
une telle corrélation est une illusion, et c'est exactement le genre d'illusion
qui coûte cher le jour où le marché bouge.

Même logique pour la volatilité : une série de rendements nuls parce que rien ne
s'est échangé n'est pas une série de faible volatilité.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Final

from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.indicators.serie import SerieTechnique
from brvm.utils.erreurs import ErreurDonneesInsuffisantes

_DECIMALES: Final[Decimal] = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class PointDrawdown:
    """Recul par rapport au plus haut atteint jusque-là."""

    date_evaluation: date
    valeur: int
    plus_haut_atteint: int
    drawdown: Decimal


@dataclass(frozen=True, slots=True)
class ResultatDrawdown:
    """Perte maximale subie depuis un sommet, et l'état courant."""

    points: tuple[PointDrawdown, ...]
    drawdown_courant: Decimal
    drawdown_maximum: Decimal
    date_du_maximum: date | None
    #: Nombre de séances écoulées depuis le dernier sommet, si l'on est en recul.
    seances_sous_le_sommet: int


@dataclass(frozen=True, slots=True)
class ResultatVolatilite:
    """Volatilité mesurée, et sur quoi elle a été mesurée."""

    valeur: Decimal | None
    annualisee: Decimal | None
    nb_rendements: int
    motif_indisponible: str | None = None


@dataclass(frozen=True, slots=True)
class ResultatCorrelation:
    """Corrélation de deux valeurs, sur leurs séances cotées communes."""

    ticker_a: str
    ticker_b: str
    valeur: Decimal | None
    #: Séances où les DEUX valeurs ont réellement échangé.
    seances_communes: int
    motif_indisponible: str | None = None


def rendements_sur_seances_cotees(serie: SerieTechnique) -> list[tuple[date, Decimal]]:
    """Rendements d'une séance cotée à la suivante, les trous étant sautés.

    Un rendement nul parce que rien ne s'est échangé n'est pas un rendement nul :
    c'est une absence d'observation. Les séances non cotées sont donc ignorées
    plutôt que comptées comme immobiles.
    """
    cotees = [barre for barre in serie.barres_cotees() if barre.cloture is not None]
    resultats: list[tuple[date, Decimal]] = []
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for precedente, courante in pairwise(cotees):
            if precedente.cloture is None or courante.cloture is None:
                continue
            if precedente.cloture == 0:
                continue
            resultats.append(
                (courante.date_seance, courante.cloture / precedente.cloture - Decimal(1))
            )
    return resultats


def calculer_volatilite(
    serie: SerieTechnique, seances_par_an: int, fenetre: int | None = None
) -> ResultatVolatilite:
    """Écart-type des rendements des séances cotées, annualisé.

    L'annualisation multiplie par la racine du nombre de séances par an. Sur une
    valeur qui ne cote qu'une séance sur trois, ce facteur suppose une continuité
    qui n'existe pas : le résultat reste indicatif, et le nombre de rendements
    ayant servi au calcul est rapporté pour qu'on puisse en juger.
    """
    rendements = [valeur for _, valeur in rendements_sur_seances_cotees(serie)]
    if fenetre is not None:
        rendements = rendements[-fenetre:]
    if len(rendements) < 2:
        return ResultatVolatilite(
            valeur=None,
            annualisee=None,
            nb_rendements=len(rendements),
            motif_indisponible=(
                "au moins deux rendements sur séances réellement cotées sont "
                "nécessaires ; la valeur n'a pas assez échangé"
            ),
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        moyenne = sum(rendements, Decimal(0)) / Decimal(len(rendements))
        # Écart-type d'échantillon : on estime une volatilité à partir d'un
        # échantillon de séances, pas d'une population exhaustive.
        variance = sum(((valeur - moyenne) ** 2 for valeur in rendements), Decimal(0)) / Decimal(
            len(rendements) - 1
        )
        ecart = variance.sqrt()
        annualisee = ecart * Decimal(seances_par_an).sqrt()

    return ResultatVolatilite(
        valeur=ecart.quantize(_DECIMALES),
        annualisee=annualisee.quantize(_DECIMALES),
        nb_rendements=len(rendements),
    )


def calculer_drawdown(
    valorisations: Sequence[tuple[date, int]],
) -> ResultatDrawdown:
    """Suit le recul du portefeuille par rapport à son plus haut historique.

    Raises:
        ErreurDonneesInsuffisantes: série vide.
    """
    if not valorisations:
        raise ErreurDonneesInsuffisantes(
            "Aucune valorisation : le drawdown ne peut pas être calculé."
        )

    ordonnees = sorted(valorisations, key=lambda element: element[0])
    points: list[PointDrawdown] = []
    sommet = ordonnees[0][1]
    date_sommet = ordonnees[0][0]
    maximum = Decimal(0)
    date_maximum: date | None = None

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for jour, valeur in ordonnees:
            if valeur > sommet:
                sommet = valeur
                date_sommet = jour
            recul = (
                Decimal(0)
                if sommet <= 0
                else (Decimal(sommet - valeur) / Decimal(sommet)).quantize(_DECIMALES)
            )
            if recul > maximum:
                maximum = recul
                date_maximum = jour
            points.append(
                PointDrawdown(
                    date_evaluation=jour,
                    valeur=valeur,
                    plus_haut_atteint=sommet,
                    drawdown=recul,
                )
            )

    sous_le_sommet = sum(1 for jour, _ in ordonnees if jour > date_sommet)
    return ResultatDrawdown(
        points=tuple(points),
        drawdown_courant=points[-1].drawdown,
        drawdown_maximum=maximum,
        date_du_maximum=date_maximum,
        seances_sous_le_sommet=sous_le_sommet,
    )


def calculer_correlation(
    serie_a: SerieTechnique, serie_b: SerieTechnique, seances_minimum: int
) -> ResultatCorrelation:
    """Corrélation des rendements, sur les seules séances cotées **communes**.

    Deux valeurs qui ne cotent pas les mêmes jours n'ont pas de rendement
    comparable ces jours-là. Les apparier sur une série reportée produirait une
    corrélation élevée qui ne dit rien du marché.
    """
    rendements_a = dict(rendements_sur_seances_cotees(serie_a))
    rendements_b = dict(rendements_sur_seances_cotees(serie_b))
    communes = sorted(set(rendements_a) & set(rendements_b))

    if len(communes) < seances_minimum:
        return ResultatCorrelation(
            ticker_a=serie_a.ticker,
            ticker_b=serie_b.ticker,
            valeur=None,
            seances_communes=len(communes),
            motif_indisponible=(
                f"seulement {len(communes)} séance(s) où les deux valeurs ont "
                f"réellement échangé, contre {seances_minimum} exigées. Une "
                "corrélation calculée sur moins ne mesurerait que le calendrier "
                "de cotation."
            ),
        )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        valeurs_a = [rendements_a[jour] for jour in communes]
        valeurs_b = [rendements_b[jour] for jour in communes]
        n = Decimal(len(communes))
        moyenne_a = sum(valeurs_a, Decimal(0)) / n
        moyenne_b = sum(valeurs_b, Decimal(0)) / n
        covariance = sum(
            ((a - moyenne_a) * (b - moyenne_b) for a, b in zip(valeurs_a, valeurs_b, strict=True)),
            Decimal(0),
        )
        variance_a = sum(((a - moyenne_a) ** 2 for a in valeurs_a), Decimal(0))
        variance_b = sum(((b - moyenne_b) ** 2 for b in valeurs_b), Decimal(0))

        if variance_a == 0 or variance_b == 0:
            return ResultatCorrelation(
                ticker_a=serie_a.ticker,
                ticker_b=serie_b.ticker,
                valeur=None,
                seances_communes=len(communes),
                motif_indisponible=(
                    "l'une des deux valeurs n'a pas varié sur les séances communes : "
                    "la corrélation n'est pas définie"
                ),
            )
        correlation = covariance / (variance_a.sqrt() * variance_b.sqrt())

    return ResultatCorrelation(
        ticker_a=serie_a.ticker,
        ticker_b=serie_b.ticker,
        valeur=correlation.quantize(_DECIMALES),
        seances_communes=len(communes),
    )
