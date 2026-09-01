"""Mesures de performance : TWR, TRI et contribution par ligne.

Deux chiffres coexistent parce qu'ils répondent à deux questions différentes, et
les confondre conduit à se féliciter ou se blâmer à tort.

**Le TWR** (rendement pondéré par le temps) neutralise les apports et retraits.
Il mesure la performance des choix de valeurs, indépendamment du moment où
l'argent est entré. C'est ce qui se compare à un indice.

**Le TRI** (taux de rendement interne, pondéré par les montants) tient compte du
calendrier des versements. Il mesure ce que *votre* argent a rapporté, y compris
l'effet d'avoir investi au bon ou au mauvais moment. Sur une stratégie
d'investissement progressif, les deux divergent nettement.

Aucun des deux n'est annualisé automatiquement : sur des séries courtes,
annualiser un rendement de trois mois produit un chiffre spectaculaire et
dépourvu de sens. L'annualisation est demandée explicitement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from itertools import pairwise
from typing import Final

from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.utils.erreurs import ErreurValidation

#: Base de calcul des durées. Convention exacte/365, la plus répandue.
JOURS_PAR_AN: Final[Decimal] = Decimal(365)

#: Bornes de recherche du TRI. Au-delà de +1000 %/an, le chiffre ne veut plus rien
#: dire ; en deçà de -99,99 %, le capital est perdu.
TRI_MINIMUM: Final[Decimal] = Decimal("-0.9999")
TRI_MAXIMUM: Final[Decimal] = Decimal(10)
TRI_ITERATIONS_MAX: Final[int] = 200
TRI_TOLERANCE: Final[Decimal] = Decimal("0.0000001")

_DECIMALES: Final[Decimal] = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class PointValorisation:
    """Valeur du portefeuille à une date, et flux externe survenu ce jour-là."""

    date_evaluation: date
    #: Valeur des titres détenus, après le flux du jour.
    valeur: int
    #: Apport (positif) ou retrait (négatif) de la journée. 0 s'il n'y en a pas.
    flux_externe: int = 0


@dataclass(frozen=True, slots=True)
class SousPeriode:
    """Un intervalle entre deux valorisations, avec son rendement propre."""

    debut: date
    fin: date
    valeur_initiale: int
    flux_externe: int
    valeur_finale: int
    rendement: Decimal


@dataclass(frozen=True, slots=True)
class ResultatTwr:
    """Rendement pondéré par le temps, et son détail par sous-période."""

    valeur: Decimal | None
    sous_periodes: tuple[SousPeriode, ...] = ()
    motif_indisponible: str | None = None

    def annualise(self, debut: date, fin: date) -> Decimal | None:
        """Ramène le rendement à une base annuelle.

        Renvoie ``None`` sur une période de moins d'un an : annualiser un
        rendement de trois mois produit un chiffre spectaculaire et faux.
        """
        if self.valeur is None:
            return None
        jours = Decimal((fin - debut).days)
        if jours < JOURS_PAR_AN:
            return None
        with localcontext() as contexte:
            contexte.prec = PRECISION_INTERNE
            return ((Decimal(1) + self.valeur) ** (JOURS_PAR_AN / jours) - Decimal(1)).quantize(
                _DECIMALES
            )


@dataclass(frozen=True, slots=True)
class FluxTresorerie:
    """Un mouvement de trésorerie du point de vue de l'investisseur.

    Négatif quand l'argent sort de la poche (achat, frais), positif quand il y
    rentre (vente, dividende, valeur finale du portefeuille).
    """

    date_flux: date
    montant: int
    libelle: str = ""


@dataclass(frozen=True, slots=True)
class ResultatTri:
    """Taux de rendement interne, ou la raison pour laquelle il n'existe pas."""

    valeur: Decimal | None
    iterations: int = 0
    motif_indisponible: str | None = None


@dataclass(frozen=True, slots=True)
class ContributionLigne:
    """Part d'une ligne dans le résultat d'ensemble."""

    ticker: str
    cout_engage: int
    valeur_actuelle: int
    dividendes_nets: int
    plus_values_realisees: int
    #: Gain total de la ligne, latent et réalisé, dividendes compris.
    gain: int
    #: Gain de la ligne rapporté au coût engagé sur l'ensemble du portefeuille.
    contribution: Decimal
    #: Gain de la ligne rapporté à son propre coût.
    rendement_propre: Decimal


# ------------------------------------------------------------------------- TWR


def calculer_twr(valorisations: Sequence[PointValorisation]) -> ResultatTwr:
    """Enchaîne les rendements des sous-périodes séparées par les flux externes.

    Convention : le flux d'une date est réputé intervenir **au début** de la
    sous-période qu'elle ouvre. Le rendement d'une sous-période est donc
    ``valeur_finale / (valeur_initiale + flux) - 1``.
    """
    if len(valorisations) < 2:
        return ResultatTwr(
            valeur=None,
            motif_indisponible=(
                "au moins deux valorisations sont nécessaires pour mesurer un rendement"
            ),
        )

    ordonnees = sorted(valorisations, key=lambda point: point.date_evaluation)
    sous_periodes: list[SousPeriode] = []

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        cumul = Decimal(1)

        for precedent, courant in pairwise(ordonnees):
            base = Decimal(precedent.valeur + courant.flux_externe)
            if base <= 0:
                return ResultatTwr(
                    valeur=None,
                    sous_periodes=tuple(sous_periodes),
                    motif_indisponible=(
                        f"portefeuille de valeur nulle ou négative au "
                        f"{precedent.date_evaluation.isoformat()} : le rendement de la "
                        "sous-période suivante n'est pas défini"
                    ),
                )
            rendement = Decimal(courant.valeur) / base - Decimal(1)
            cumul *= Decimal(1) + rendement
            sous_periodes.append(
                SousPeriode(
                    debut=precedent.date_evaluation,
                    fin=courant.date_evaluation,
                    valeur_initiale=precedent.valeur,
                    flux_externe=courant.flux_externe,
                    valeur_finale=courant.valeur,
                    rendement=rendement.quantize(_DECIMALES),
                )
            )
        total = (cumul - Decimal(1)).quantize(_DECIMALES)

    return ResultatTwr(valeur=total, sous_periodes=tuple(sous_periodes))


# ------------------------------------------------------------------------- TRI


def _valeur_actuelle_nette(flux: Sequence[FluxTresorerie], taux: Decimal, origine: date) -> Decimal:
    total = Decimal(0)
    for mouvement in flux:
        jours = Decimal((mouvement.date_flux - origine).days)
        exposant = jours / JOURS_PAR_AN
        total += Decimal(mouvement.montant) / ((Decimal(1) + taux) ** exposant)
    return total


def calculer_tri(flux: Sequence[FluxTresorerie]) -> ResultatTri:
    """Taux annuel qui annule la valeur actuelle nette des flux.

    Résolu par dichotomie plutôt que par Newton : la dichotomie ne diverge pas et
    donne un résultat reproductible, ce qui vaut mieux qu'une convergence rapide
    pour un chiffre qu'on relira dans six mois.

    Renvoie ``None`` avec un motif lorsque le taux n'existe pas : flux tous de
    même signe, série trop courte, ou absence de changement de signe dans
    l'intervalle de recherche.
    """
    if len(flux) < 2:
        return ResultatTri(valeur=None, motif_indisponible="au moins deux flux sont nécessaires")
    signes = {mouvement.montant > 0 for mouvement in flux if mouvement.montant != 0}
    if len(signes) < 2:
        return ResultatTri(
            valeur=None,
            motif_indisponible=(
                "tous les flux vont dans le même sens : sans encaissement face aux "
                "décaissements, aucun taux de rendement n'est défini"
            ),
        )

    origine = min(mouvement.date_flux for mouvement in flux)

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        try:
            bas, haut = TRI_MINIMUM, TRI_MAXIMUM
            valeur_bas = _valeur_actuelle_nette(flux, bas, origine)
            valeur_haut = _valeur_actuelle_nette(flux, haut, origine)
            if valeur_bas * valeur_haut > 0:
                return ResultatTri(
                    valeur=None,
                    motif_indisponible=(
                        f"aucun taux entre {TRI_MINIMUM:.2%} et {TRI_MAXIMUM:.0%} "
                        "n'annule la valeur actuelle nette des flux"
                    ),
                )

            for iteration in range(1, TRI_ITERATIONS_MAX + 1):
                milieu = (bas + haut) / Decimal(2)
                valeur_milieu = _valeur_actuelle_nette(flux, milieu, origine)
                if abs(valeur_milieu) < TRI_TOLERANCE or (haut - bas) < TRI_TOLERANCE:
                    return ResultatTri(valeur=milieu.quantize(_DECIMALES), iterations=iteration)
                if valeur_bas * valeur_milieu < 0:
                    haut = milieu
                else:
                    bas, valeur_bas = milieu, valeur_milieu
        except (InvalidOperation, DivisionByZero, OverflowError) as exc:
            return ResultatTri(
                valeur=None, motif_indisponible=f"calcul numériquement instable : {exc}"
            )

    return ResultatTri(
        valeur=None,
        iterations=TRI_ITERATIONS_MAX,
        motif_indisponible="la dichotomie n'a pas convergé dans le nombre d'itérations prévu",
    )


# ---------------------------------------------------------------- contributions


@dataclass(frozen=True, slots=True)
class DonneesLigne:
    """Ce qu'il faut savoir d'une ligne pour mesurer sa contribution."""

    ticker: str
    cout_engage: int
    valeur_actuelle: int
    dividendes_nets: int = 0
    plus_values_realisees: int = 0


def calculer_contributions(
    lignes: Sequence[DonneesLigne],
) -> tuple[ContributionLigne, ...]:
    """Répartit le résultat d'ensemble entre les lignes.

    La contribution rapporte le gain d'une ligne au coût engagé sur **tout** le
    portefeuille : les contributions s'additionnent donc pour donner le rendement
    global. Le rendement propre, lui, rapporte le gain de la ligne à son propre
    coût — c'est ce qui permet de comparer deux lignes de tailles différentes.
    """
    if not lignes:
        return ()
    cout_total = sum(ligne.cout_engage for ligne in lignes)
    if cout_total <= 0:
        raise ErreurValidation(
            "Coût engagé total nul ou négatif : la contribution de chaque ligne serait indéfinie.",
            cout_total=cout_total,
        )

    resultats: list[ContributionLigne] = []
    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        for ligne in lignes:
            gain = (
                ligne.valeur_actuelle
                - ligne.cout_engage
                + ligne.dividendes_nets
                + ligne.plus_values_realisees
            )
            propre = (
                (Decimal(gain) / Decimal(ligne.cout_engage)).quantize(_DECIMALES)
                if ligne.cout_engage > 0
                else Decimal(0)
            )
            resultats.append(
                ContributionLigne(
                    ticker=ligne.ticker,
                    cout_engage=ligne.cout_engage,
                    valeur_actuelle=ligne.valeur_actuelle,
                    dividendes_nets=ligne.dividendes_nets,
                    plus_values_realisees=ligne.plus_values_realisees,
                    gain=gain,
                    contribution=(Decimal(gain) / Decimal(cout_total)).quantize(_DECIMALES),
                    rendement_propre=propre,
                )
            )
    return tuple(resultats)
