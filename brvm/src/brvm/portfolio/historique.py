"""Historisation des valorisations, et ce qu'elle rend enfin mesurable.

Le système photographiait le portefeuille à chaque lecture, sans jamais garder
la photographie. Deux conséquences, l'une et l'autre documentées comme des
manques : aucune performance chiffrée n'était publiée, et le seuil de repli
déclaré dans `risque.drawdown_alerte` ne pouvait se comparer à rien.

Une règle gouverne ce module, et elle est stricte :

**Un repli se mesure sur l'ACTIF TOTAL, titres et espèces.** Le mesurer sur les
seuls titres reproduit exactement la faute qui avait fait retirer le TWR : un
portefeuille entièrement soldé afficherait un recul de 100 %, alors que son
argent est simplement passé en espèces.

Quand le solde d'espèces n'est pas connaissable — aucun apport déclaré — la
série d'actif total n'existe pas, et le repli n'est pas calculé. Il n'est pas
approché sur les titres : on rend le motif.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from brvm.domain.enums import TypeFluxEspece
from brvm.domain.modeles import FluxEspece, Valorisation
from brvm.portfolio.performance import PointValorisation
from brvm.portfolio.valorisation import Portefeuille

#: Motif rendu quand la série d'actif total est incomplète.
MOTIF_ACTIF_INCOMPLET: str = (
    "Le solde d'espèces n'est pas connu sur toute la période : le repli ne peut "
    "pas être mesuré. Le calculer sur les seuls titres ferait apparaître un recul "
    "de 100 % dès qu'une ligne est soldée, alors que l'argent est passé en "
    "espèces. Déclarez vos apports pour rendre l'actif total mesurable."
)

#: Motif rendu quand l'historique est trop court.
MOTIF_SERIE_TROP_COURTE: str = (
    "Une seule séance valorisée : un repli se mesure contre un plus-haut "
    "antérieur, il faut au moins deux points."
)


def photographier(
    portefeuille: Portefeuille, jour: date, instant: datetime | None = None
) -> Valorisation:
    """Fige l'état du portefeuille pour une séance.

    Le nombre de lignes non valorisées est conservé : une valorisation établie
    alors que trois lignes n'ont pas de cours n'a pas la même portée qu'une
    valorisation complète, et le lecteur doit pouvoir en juger.
    """
    solde = portefeuille.tresorerie.solde
    return Valorisation(
        date_seance=jour,
        valeur_titres=portefeuille.valeur_totale,
        cout_total=portefeuille.cout_total,
        plus_value_brute=portefeuille.plus_value_latente_brute,
        nb_lignes=len(portefeuille.lignes),
        nb_non_valorisees=len(portefeuille.lignes_non_valorisees),
        horodatage_calcul=instant or datetime.now(UTC),
        especes=solde,
        actif_total=portefeuille.actif_total,
        motif_especes=portefeuille.tresorerie.motif_indisponible,
    )


def serie_actif_total(
    valorisations: Sequence[Valorisation],
) -> tuple[list[tuple[date, int]], str | None]:
    """Série d'actif total exploitable, ou le motif qui l'en empêche.

    Returns:
        La série et ``None``, ou une liste vide et le motif. Une série partielle
        n'est jamais rendue : un repli calculé sur des points manquants sauterait
        au-dessus des creux et sous-estimerait le recul.
    """
    if not valorisations:
        return [], "Aucune valorisation enregistrée."
    if any(valorisation.actif_total is None for valorisation in valorisations):
        return [], MOTIF_ACTIF_INCOMPLET
    serie = [
        (valorisation.date_seance, valorisation.actif_total)
        for valorisation in valorisations
        if valorisation.actif_total is not None
    ]
    if len(serie) < 2:
        return [], MOTIF_SERIE_TROP_COURTE
    return serie, None


def points_de_performance(
    valorisations: Sequence[Valorisation], flux: Sequence[FluxEspece]
) -> tuple[list[PointValorisation], str | None]:
    """Assemble la série que le TWR attend, ou dit ce qui l'en empêche.

    Un rendement pondéré par le temps neutralise les apports et retraits : ils
    ne sont pas de la performance, ils sont de l'argent qui entre ou sort. Il
    faut donc les DATER, et les rattacher à la sous-période qu'ils ouvrent.

    Les dividendes et les frais de garde ne sont **pas** des flux externes : ils
    sont produits par le portefeuille lui-même, et c'est précisément ce que la
    performance doit mesurer. Les compter ici les effacerait du rendement.
    """
    serie, motif = serie_actif_total(valorisations)
    if motif is not None:
        return [], motif

    externes: dict[date, int] = {}
    for mouvement in flux:
        if mouvement.type_flux is TypeFluxEspece.APPORT:
            externes[mouvement.date_flux] = (
                externes.get(mouvement.date_flux, 0) + mouvement.montant_net
            )
        elif mouvement.type_flux is TypeFluxEspece.RETRAIT:
            externes[mouvement.date_flux] = (
                externes.get(mouvement.date_flux, 0) - mouvement.montant_net
            )

    # Un apport antérieur à la première valorisation est déjà DANS cette
    # valorisation : le compter en flux le retrancherait deux fois.
    premiere = serie[0][0]
    points = [
        PointValorisation(
            date_evaluation=jour,
            valeur=valeur,
            flux_externe=0 if jour <= premiere else externes.get(jour, 0),
        )
        for jour, valeur in serie
    ]
    return points, None
