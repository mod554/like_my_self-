"""Calcul des indicateurs — fonctions pures, sans configuration ni contexte.

Ce module ne connaît ni le marché, ni le calendrier, ni la notion de fiabilité.
Il transforme des suites de nombres en d'autres suites de nombres. Tout ce qui
relève du jugement — refuser un calcul faute de séances cotées, pondérer un
signal par la liquidité — est décidé une couche plus haut.

**Les trous se propagent.** Une entrée manquante (``None``) rend indéterminées
toutes les sorties qui en dépendent. Aucune interpolation, aucun remplacement par
zéro : sur un marché où l'absence de cotation est fréquente, confondre « valeur
inconnue » et « valeur nulle » fabrique des tendances qui n'existent pas.

**Les indicateurs récursifs redémarrent après un trou.** Une moyenne mobile
exponentielle, un RSI ou un ATR de Wilder se calculent de proche en proche : une
valeur manquante casse la chaîne. Plutôt que de la reprendre comme si de rien
n'était, le calcul repart à zéro et attend d'avoir de nouveau une fenêtre
complète. C'est plus sévère, et c'est le seul choix qui ne fabrique pas
d'information.

**Causalité.** La sortie d'indice *i* ne dépend que des entrées d'indice ≤ *i*.
Tronquer la série après *i* ne change aucune valeur jusqu'à *i* — propriété
vérifiée par les tests, car c'est elle qui interdit le biais d'anticipation.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext
from typing import Final

from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.utils.erreurs import ErreurValidation

#: Décimales conservées sur les sorties, pour des comparaisons reproductibles.
DECIMALES: Final[int] = 6

_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-DECIMALES)

Valeurs = Sequence[Decimal | None]
Sortie = list[Decimal | None]


def _q(valeur: Decimal) -> Decimal:
    return valeur.quantize(_QUANTUM)


def _exiger_fenetre(fenetre: int, minimum: int = 1) -> None:
    if fenetre < minimum:
        raise ErreurValidation(
            f"Fenêtre invalide : {fenetre}. Un minimum de {minimum} est nécessaire.",
            fenetre=fenetre,
        )


def _vide(longueur: int) -> Sortie:
    return [None] * longueur


# ------------------------------------------------------------------- moyennes


def moyenne_mobile_simple(valeurs: Valeurs, fenetre: int) -> Sortie:
    """Moyenne arithmétique des ``fenetre`` dernières valeurs.

    Indéterminée tant que la fenêtre n'est pas entièrement renseignée.
    """
    _exiger_fenetre(fenetre)
    sortie = _vide(len(valeurs))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for position in range(fenetre - 1, len(valeurs)):
            tranche = valeurs[position - fenetre + 1 : position + 1]
            if any(valeur is None for valeur in tranche):
                continue
            total = sum((valeur for valeur in tranche if valeur is not None), Decimal(0))
            sortie[position] = _q(total / Decimal(fenetre))
    return sortie


def moyenne_mobile_exponentielle(valeurs: Valeurs, fenetre: int) -> Sortie:
    """Moyenne exponentielle de facteur ``2 / (fenetre + 1)``.

    Amorcée par la moyenne simple des ``fenetre`` premières valeurs consécutives
    disponibles. Un trou remet le calcul à zéro : il faudra de nouveau ``fenetre``
    valeurs consécutives pour réamorcer.
    """
    _exiger_fenetre(fenetre, 2)
    sortie = _vide(len(valeurs))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        alpha = Decimal(2) / Decimal(fenetre + 1)
        precedente: Decimal | None = None
        consecutives: list[Decimal] = []

        for position, valeur in enumerate(valeurs):
            if valeur is None:
                precedente = None
                consecutives = []
                continue
            if precedente is None:
                consecutives.append(valeur)
                if len(consecutives) < fenetre:
                    continue
                precedente = sum(consecutives, Decimal(0)) / Decimal(fenetre)
            else:
                precedente = alpha * valeur + (Decimal(1) - alpha) * precedente
            sortie[position] = _q(precedente)
    return sortie


def ecart_type_mobile(valeurs: Valeurs, fenetre: int) -> Sortie:
    """Écart-type de population sur la fenêtre (diviseur ``n``, pas ``n - 1``).

    C'est la convention des bandes de Bollinger.
    """
    _exiger_fenetre(fenetre, 2)
    sortie = _vide(len(valeurs))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for position in range(fenetre - 1, len(valeurs)):
            tranche = [valeur for valeur in valeurs[position - fenetre + 1 : position + 1]]
            if any(valeur is None for valeur in tranche):
                continue
            connues = [valeur for valeur in tranche if valeur is not None]
            moyenne = sum(connues, Decimal(0)) / Decimal(fenetre)
            variance = sum(((valeur - moyenne) ** 2 for valeur in connues), Decimal(0)) / Decimal(
                fenetre
            )
            sortie[position] = _q(variance.sqrt())
    return sortie


# -------------------------------------------------------------------- momentum


def rsi(valeurs: Valeurs, fenetre: int) -> Sortie:
    """Indice de force relative, lissage de Wilder.

    Renvoie 100 lorsque la fenêtre ne comporte aucune baisse : le rapport de force
    est alors infini, et 100 en est la limite. Un trou dans les cours remet
    l'amorçage à zéro.
    """
    _exiger_fenetre(fenetre, 2)
    sortie = _vide(len(valeurs))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        gains: list[Decimal] = []
        pertes: list[Decimal] = []
        gain_moyen: Decimal | None = None
        perte_moyenne: Decimal | None = None

        for position in range(1, len(valeurs)):
            precedent, courant = valeurs[position - 1], valeurs[position]
            if precedent is None or courant is None:
                gains, pertes = [], []
                gain_moyen = perte_moyenne = None
                continue

            variation = courant - precedent
            gain = variation if variation > 0 else Decimal(0)
            perte = -variation if variation < 0 else Decimal(0)

            if gain_moyen is None or perte_moyenne is None:
                gains.append(gain)
                pertes.append(perte)
                if len(gains) < fenetre:
                    continue
                gain_moyen = sum(gains, Decimal(0)) / Decimal(fenetre)
                perte_moyenne = sum(pertes, Decimal(0)) / Decimal(fenetre)
            else:
                gain_moyen = (gain_moyen * (fenetre - 1) + gain) / Decimal(fenetre)
                perte_moyenne = (perte_moyenne * (fenetre - 1) + perte) / Decimal(fenetre)

            if perte_moyenne == 0:
                sortie[position] = Decimal(100)
            else:
                force = gain_moyen / perte_moyenne
                sortie[position] = _q(Decimal(100) - Decimal(100) / (Decimal(1) + force))
    return sortie


def momentum(valeurs: Valeurs, decalage: int) -> Sortie:
    """Variation relative sur ``decalage`` séances, exprimée en fraction.

    0.05 signifie « +5 % par rapport au cours d'il y a ``decalage`` séances ».
    """
    _exiger_fenetre(decalage)
    sortie = _vide(len(valeurs))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for position in range(decalage, len(valeurs)):
            reference, courant = valeurs[position - decalage], valeurs[position]
            if reference is None or courant is None or reference == 0:
                continue
            sortie[position] = _q(courant / reference - Decimal(1))
    return sortie


# --------------------------------------------------------------------- MACD


def macd(valeurs: Valeurs, rapide: int, lente: int, signal: int) -> tuple[Sortie, Sortie, Sortie]:
    """Convergence-divergence de moyennes mobiles.

    Returns:
        La ligne MACD, sa ligne de signal, et l'histogramme (différence des deux).
    """
    if rapide >= lente:
        raise ErreurValidation(
            "La fenêtre rapide du MACD doit être strictement inférieure à la lente.",
            rapide=rapide,
            lente=lente,
        )
    ema_rapide = moyenne_mobile_exponentielle(valeurs, rapide)
    ema_lente = moyenne_mobile_exponentielle(valeurs, lente)
    ligne: Sortie = [
        None if (a is None or b is None) else _q(a - b)
        for a, b in zip(ema_rapide, ema_lente, strict=True)
    ]
    ligne_signal = moyenne_mobile_exponentielle(ligne, signal)
    histogramme: Sortie = [
        None if (m is None or s is None) else _q(m - s)
        for m, s in zip(ligne, ligne_signal, strict=True)
    ]
    return ligne, ligne_signal, histogramme


# --------------------------------------------------------------- Bollinger


def bandes_bollinger(
    valeurs: Valeurs, fenetre: int, ecarts: Decimal
) -> tuple[Sortie, Sortie, Sortie]:
    """Moyenne mobile encadrée de ``ecarts`` écarts-types.

    Returns:
        La bande basse, la moyenne, la bande haute.
    """
    moyenne = moyenne_mobile_simple(valeurs, fenetre)
    ecart = ecart_type_mobile(valeurs, fenetre)
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        basse: Sortie = [
            None if (m is None or e is None) else _q(m - ecarts * e)
            for m, e in zip(moyenne, ecart, strict=True)
        ]
        haute: Sortie = [
            None if (m is None or e is None) else _q(m + ecarts * e)
            for m, e in zip(moyenne, ecart, strict=True)
        ]
    return basse, moyenne, haute


# ------------------------------------------------------------------ amplitude


def atr(hauts: Valeurs, bas: Valeurs, clotures: Valeurs, fenetre: int) -> Sortie:
    """Amplitude moyenne vraie, lissage de Wilder.

    L'amplitude vraie d'une séance retient le plus grand des trois écarts :
    haut-bas, |haut − clôture veille| et |bas − clôture veille|. Les deux derniers
    capturent les ouvertures en décalage, fréquentes sur une valeur qui ne cote
    pas tous les jours.

    À n'alimenter qu'avec des séances réellement cotées : une séance sans
    transaction n'a pas d'amplitude nulle, elle n'en a pas.
    """
    _exiger_fenetre(fenetre, 2)
    if not (len(hauts) == len(bas) == len(clotures)):
        raise ErreurValidation("Les trois séries d'entrée doivent avoir la même longueur.")
    sortie = _vide(len(clotures))
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        amplitudes: list[Decimal] = []
        moyenne: Decimal | None = None

        for position in range(1, len(clotures)):
            haut, bas_, cloture_veille = hauts[position], bas[position], clotures[position - 1]
            if haut is None or bas_ is None or cloture_veille is None:
                amplitudes = []
                moyenne = None
                continue
            amplitude = max(haut - bas_, abs(haut - cloture_veille), abs(bas_ - cloture_veille))
            if moyenne is None:
                amplitudes.append(amplitude)
                if len(amplitudes) < fenetre:
                    continue
                moyenne = sum(amplitudes, Decimal(0)) / Decimal(fenetre)
            else:
                moyenne = (moyenne * (fenetre - 1) + amplitude) / Decimal(fenetre)
            sortie[position] = _q(moyenne)
    return sortie


def extremes_glissants(valeurs: Valeurs, fenetre: int) -> tuple[Sortie, Sortie]:
    """Plus haut et plus bas sur la fenêtre.

    Returns:
        Le plus bas et le plus haut, indéterminés si la fenêtre est incomplète.
    """
    _exiger_fenetre(fenetre)
    plus_bas = _vide(len(valeurs))
    plus_haut = _vide(len(valeurs))
    for position in range(fenetre - 1, len(valeurs)):
        tranche = valeurs[position - fenetre + 1 : position + 1]
        if any(valeur is None for valeur in tranche):
            continue
        connues = [valeur for valeur in tranche if valeur is not None]
        plus_bas[position] = min(connues)
        plus_haut[position] = max(connues)
    return plus_bas, plus_haut


# --------------------------------------------------------------------- volume


def obv(clotures: Valeurs, volumes: Sequence[int]) -> Sortie:
    """Volume cumulé signé par le sens de la séance.

    Le cumul démarre à zéro sur la première séance exploitable. Une séance dont le
    cours est inconnu ne modifie pas le cumul et ne l'interrompt pas : on ignore
    si elle aurait été haussière, pas qu'elle a été neutre.

    À n'alimenter qu'avec des séances réellement cotées.
    """
    if len(clotures) != len(volumes):
        raise ErreurValidation("Cours et volumes doivent avoir la même longueur.")
    sortie = _vide(len(clotures))
    cumul: Decimal | None = None
    precedent: Decimal | None = None

    for position, cloture in enumerate(clotures):
        if cloture is None:
            sortie[position] = cumul
            continue
        if cumul is None or precedent is None:
            cumul = Decimal(0)
        elif cloture > precedent:
            cumul += Decimal(volumes[position])
        elif cloture < precedent:
            cumul -= Decimal(volumes[position])
        precedent = cloture
        sortie[position] = cumul
    return sortie
