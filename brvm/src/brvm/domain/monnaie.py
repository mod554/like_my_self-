"""Arithmétique monétaire XOF.

Règles du système :

* le franc CFA (XOF) n'a pas de subdivision en circulation : **tout montant est un
  entier**. Les montants transitent donc en ``int`` ;
* les grandeurs intermédiaires (taux, prix de revient unitaire, facteurs
  d'ajustement) sont des :class:`~decimal.Decimal`. Jamais de ``float`` sur de
  l'argent : ``0.1 + 0.2 != 0.3`` en binaire, et une erreur d'un franc répétée
  sur mille lignes fausse un prix de revient ;
* l'arrondi n'est jamais implicite : il se fait à un endroit nommé, avec un mode
  choisi dans la configuration ;
* aucune conversion de devise n'est effectuée nulle part dans le système.
"""

from __future__ import annotations

import decimal
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Final

from brvm.domain.enums import Devise

#: Nombre de décimales d'un montant XOF. Le franc CFA ne circule pas en centimes.
DECIMALES_XOF: Final[int] = 0

#: Quantum d'arrondi correspondant.
QUANTUM_XOF: Final[Decimal] = Decimal(1)

#: Séparateur de milliers à l'affichage. Espace ordinaire et non espace fine
#: insécable (U+202F), typographiquement plus juste en français mais mal
#: restituée par certains terminaux et par l'export tableur.
SEPARATEUR_MILLIERS: Final[str] = "\u0020"

#: Précision de travail des calculs intermédiaires (largement au-delà du besoin,
#: pour que l'arrondi final soit le seul endroit où l'on perd de l'information).
PRECISION_INTERNE: Final[int] = 28

NombreCompatible = Decimal | int | str | float


class ModeArrondi(StrEnum):
    """Modes d'arrondi autorisés, exposés dans le fichier de configuration."""

    HALF_UP = "HALF_UP"
    HALF_EVEN = "HALF_EVEN"
    CEILING = "CEILING"
    FLOOR = "FLOOR"

    @property
    def mode_decimal(self) -> str:
        return {
            ModeArrondi.HALF_UP: decimal.ROUND_HALF_UP,
            ModeArrondi.HALF_EVEN: decimal.ROUND_HALF_EVEN,
            ModeArrondi.CEILING: decimal.ROUND_CEILING,
            ModeArrondi.FLOOR: decimal.ROUND_FLOOR,
        }[self]


def vers_decimal(valeur: NombreCompatible) -> Decimal:
    """Convertit une valeur numérique en ``Decimal`` de façon déterministe.

    Un ``float`` est converti via sa représentation décimale courte
    (``Decimal(str(x))``) et non via son expansion binaire exacte : c'est ce que
    l'utilisateur a écrit qui fait foi, pas l'approximation IEEE-754.
    """
    if isinstance(valeur, Decimal):
        return valeur
    if isinstance(valeur, bool):  # bool est un int en Python : refus explicite.
        raise TypeError("Un booléen n'est pas un montant.")
    if isinstance(valeur, int):
        return Decimal(valeur)
    try:
        return Decimal(str(valeur))
    except (InvalidOperation, ValueError) as exc:
        raise TypeError(f"Valeur numérique invalide : {valeur!r}") from exc


def arrondi_xof(valeur: NombreCompatible, mode: ModeArrondi = ModeArrondi.HALF_UP) -> int:
    """Arrondit une valeur à l'unité XOF.

    C'est le **seul** point du système où un montant perd des décimales.
    """
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        return int(vers_decimal(valeur).quantize(QUANTUM_XOF, rounding=mode.mode_decimal))


def applique_taux(base: NombreCompatible, taux: NombreCompatible) -> Decimal:
    """Applique un taux à une base et renvoie un ``Decimal`` **non arrondi**.

    L'arrondi est laissé à l'appelant : sur une facture de SGI, chaque ligne est
    arrondie séparément puis les lignes sont sommées ; arrondir la somme donnerait
    un total différent.
    """
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        return vers_decimal(base) * vers_decimal(taux)


def borne(
    montant: NombreCompatible,
    minimum: int | None = None,
    maximum: int | None = None,
) -> Decimal:
    """Applique un minimum de perception et/ou un plafond à un montant."""
    valeur = vers_decimal(montant)
    if minimum is not None and valeur < minimum:
        valeur = Decimal(minimum)
    if maximum is not None and valeur > maximum:
        valeur = Decimal(maximum)
    return valeur


def somme_lignes(montants: list[int]) -> int:
    """Somme de lignes déjà arrondies.

    Fonction volontairement triviale : elle existe pour rendre explicite, à la
    lecture, que le total d'une facture est la somme des lignes arrondies et non
    l'arrondi de la somme.
    """
    return sum(montants)


def format_xof(montant: int) -> str:
    """Formate un montant pour l'affichage, séparateur de milliers compris."""
    return f"{montant:,}".replace(",", SEPARATEUR_MILLIERS) + f" {Devise.XOF.value}"
