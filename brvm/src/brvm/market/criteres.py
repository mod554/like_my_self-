"""Un critère mesuré, sa note, et la raison quand il n'y en a pas.

Tout le classement de cette couche repose sur cette structure. Un critère porte
trois choses, jamais moins :

* **la mesure brute**, dans son unité (un momentum en fraction, un PER en
  multiple) — pour que le chiffre reste vérifiable ;
* **la note**, entre 0 et 1, obtenue par une règle **déclarée** ;
* **le motif**, quand la note n'a pas pu être établie.

Un critère non mesurable n'est jamais noté zéro. Zéro voudrait dire « mauvais » ;
l'absence veut dire « on ne sait pas », et les deux ne se traitent pas pareil :
une note zéro pèse dans une moyenne, une absence en sort le critère et réduit la
couverture. La couverture est rapportée avec le score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from brvm.domain.monnaie import PRECISION_INTERNE

UN = Decimal(1)
ZERO = Decimal(0)


def borner(valeur: Decimal) -> Decimal:
    return max(ZERO, min(UN, valeur))


@dataclass(frozen=True, slots=True)
class Critere:
    """Une mesure, sa note et sa provenance."""

    nom: str
    #: Ce que dit le critère, en français, sur cette valeur précise.
    libelle: str
    valeur: Decimal | None = None
    unite: str = ""
    note: Decimal | None = None
    motif_absent: str | None = None

    @property
    def mesurable(self) -> bool:
        return self.note is not None

    @classmethod
    def absent(cls, nom: str, libelle: str, motif: str) -> Critere:
        return cls(nom=nom, libelle=libelle, motif_absent=motif)


def note_croissante(valeur: Decimal, plancher: Decimal, plafond: Decimal) -> Decimal:
    """Note linéaire : plus c'est haut, mieux c'est. Bornes déclarées.

    Au-delà du plafond la note sature à 1 plutôt que de croître sans fin : un
    momentum de +80 % sur une valeur qui cote deux fois par mois ne vaut pas
    quatre fois un momentum de +20 %, il signale surtout un cours peu formé.
    """
    if plafond <= plancher:
        return ZERO
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        return borner((valeur - plancher) / (plafond - plancher))


def note_decroissante(valeur: Decimal, plancher: Decimal, plafond: Decimal) -> Decimal:
    """Note linéaire inversée : plus c'est bas, mieux c'est."""
    return UN - note_croissante(valeur, plancher, plafond)


def note_centree(valeur: Decimal, cible: Decimal, tolerance: Decimal) -> Decimal:
    """Note maximale à la cible, décroissante de part et d'autre.

    Sert aux critères où un extrême dans les deux sens est également mauvais —
    un RSI à 15 comme à 85 dit la même chose : le cours s'est éloigné de son
    régime, et rien ne dit dans quel sens il y reviendra.
    """
    if tolerance <= ZERO:
        return ZERO
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        return borner(UN - abs(valeur - cible) / tolerance)


@dataclass(frozen=True, slots=True)
class Score:
    """Un score composite, avec tout ce qu'il faut pour le contester."""

    valeur: Decimal | None
    criteres: tuple[Critere, ...] = ()
    #: Part des critères pondérés qui ont pu être mesurés.
    couverture: Decimal = ZERO
    #: Multiplicateurs appliqués après la moyenne : liquidité, confiance.
    portes: tuple[Critere, ...] = ()
    motif_absent: str | None = None
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def classable(self) -> bool:
        return self.valeur is not None

    def mesurables(self) -> tuple[Critere, ...]:
        return tuple(critere for critere in self.criteres if critere.mesurable)

    def manquants(self) -> tuple[Critere, ...]:
        return tuple(critere for critere in self.criteres if not critere.mesurable)


def composer(
    criteres: Sequence[tuple[Critere, Decimal]],
    portes: Sequence[Critere] = (),
    couverture_minimale: Decimal = Decimal("0.5"),
) -> Score:
    """Assemble des critères pondérés en un score, ou refuse de le faire.

    Deux mécaniques distinctes, et la distinction est le cœur du calcul :

    * **les critères pondérés** entrent dans une moyenne. Un critère absent en
      sort — il ne compte pas zéro — et fait baisser la couverture ;
    * **les portes** (liquidité, confiance de la donnée) multiplient le résultat.
      Une porte à zéro annule le score, quelle que soit la moyenne. Sur cette
      place, une valeur au momentum superbe qui n'échange rien n'est pas une
      demi-occasion : elle n'est pas jouable du tout.

    Sous ``couverture_minimale``, le score n'est pas rendu : une moyenne sur deux
    critères parmi huit ne mesure pas la même chose qu'une moyenne sur huit, et
    les présenter côte à côte dans un classement serait trompeur.
    """
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        poids_total = sum((poids for _, poids in criteres), ZERO)
        if poids_total <= ZERO:
            return Score(
                valeur=None,
                criteres=tuple(critere for critere, _ in criteres),
                motif_absent="aucun critère pondéré n'est déclaré",
            )

        poids_mesure = sum((poids for critere, poids in criteres if critere.mesurable), ZERO)
        couverture = poids_mesure / poids_total
        tous = tuple(critere for critere, _ in criteres)

        if couverture < couverture_minimale:
            manquants = ", ".join(c.nom for c in tous if not c.mesurable)
            return Score(
                valeur=None,
                criteres=tous,
                couverture=couverture,
                portes=tuple(portes),
                motif_absent=(
                    f"couverture insuffisante ({couverture:.0%} des critères mesurés, "
                    f"minimum {couverture_minimale:.0%}). Manquent : {manquants}"
                ),
            )

        moyenne = (
            sum(
                (
                    (critere.note or ZERO) * poids
                    for critere, poids in criteres
                    if critere.mesurable
                ),
                ZERO,
            )
            / poids_mesure
        )

        avertissements: list[str] = []
        resultat = moyenne
        for porte in portes:
            if not porte.mesurable:
                return Score(
                    valeur=None,
                    criteres=tous,
                    couverture=couverture,
                    portes=tuple(portes),
                    motif_absent=(
                        f"{porte.libelle} non mesurable — {porte.motif_absent}. "
                        "Sans elle, un classement n'aurait pas de sens."
                    ),
                )
            resultat *= porte.note or ZERO
            if (porte.note or ZERO) < Decimal("0.3"):
                avertissements.append(
                    f"{porte.libelle} très basse ({porte.note:.0%}) : elle écrase le "
                    "score, et c'est voulu."
                )

        if couverture < UN:
            avertissements.append(
                f"Score établi sur {couverture:.0%} des critères. "
                "Les valeurs à couverture inégale ne se comparent pas strictement."
            )

        return Score(
            valeur=borner(resultat),
            criteres=tous,
            couverture=couverture,
            portes=tuple(portes),
            avertissements=tuple(avertissements),
        )
