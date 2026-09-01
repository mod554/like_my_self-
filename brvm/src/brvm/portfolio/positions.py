"""Suivi des lignes : prix de revient en PMP et en FIFO.

Les deux méthodes sont calculées en parallèle parce qu'elles ne répondent pas à
la même question.

**PMP** (prix moyen pondéré) répond à « combien m'a coûté un titre en moyenne ? ».
C'est la présentation habituelle d'un relevé de portefeuille. Elle a une
conséquence qu'il faut assumer : après un achat, les titres perdent leur
identité. Une vente ne consomme aucun lot en particulier, et **la durée de
détention des titres cédés n'existe plus**. Le système renvoie alors ``None``
plutôt qu'une durée inventée.

**FIFO** (premier entré, premier sorti) suit chaque lot séparément. Une vente
consomme les lots les plus anciens, et produit une cession **par lot consommé** —
exactement ce dont un calcul de plus-value a besoin quand le régime dépend de la
durée de détention.

Si votre fiscalité comporte une exonération pour durée de détention, seule la
méthode FIFO permet de la calculer.

Coût de revient
---------------
Le coût d'un lot inclut les frais d'acquisition. Le produit d'une vente est net
des frais de cession. Les frais réellement facturés, lorsqu'ils figurent sur la
transaction, l'emportent toujours sur ceux que le barème recalculerait : c'est
l'avis d'opéré qui fait foi, pas le modèle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from brvm.domain.enums import MethodeValorisation, SensOperation, TypeOst
from brvm.domain.modeles import OperationSurTitre, Transaction
from brvm.domain.monnaie import ModeArrondi, arrondi_xof
from brvm.portfolio.frais import MoteurFrais
from brvm.utils.erreurs import ErreurValidation

#: Opérations qui modifient le nombre de titres détenus.
OST_SUR_QUANTITE: frozenset[TypeOst] = frozenset(
    {TypeOst.DIVISION, TypeOst.REGROUPEMENT, TypeOst.ATTRIBUTION_GRATUITE}
)


def mois_ecoules(debut: date, fin: date) -> int:
    """Nombre de mois entiers entre deux dates."""
    mois = (fin.year - debut.year) * 12 + (fin.month - debut.month)
    if fin.day < debut.day:
        mois -= 1
    return max(0, mois)


@dataclass(frozen=True, slots=True)
class Lot:
    """Un paquet de titres acquis à une date, avec son coût unitaire frais inclus."""

    date_acquisition: date
    quantite: int
    cout_unitaire: Decimal
    reference: str

    @property
    def cout_total(self) -> Decimal:
        return self.cout_unitaire * Decimal(self.quantite)


@dataclass(frozen=True, slots=True)
class Cession:
    """Une vente réalisée, ramenée à ce qui sert au calcul de plus-value."""

    ticker: str
    date_operation: date
    quantite: int
    #: Produit encaissé, net des frais de cession.
    produit_net: int
    #: Coût des titres cédés, frais d'acquisition inclus.
    cout_de_revient: int
    methode: MethodeValorisation
    reference_transaction: str
    #: Renseignée en FIFO seulement : en PMP, les titres n'ont pas d'identité.
    duree_detention_mois: int | None = None
    date_acquisition: date | None = None

    @property
    def plus_value_brute(self) -> int:
        return self.produit_net - self.cout_de_revient


@dataclass(frozen=True, slots=True)
class Position:
    """État d'une ligne à un instant donné."""

    ticker: str
    quantite: int
    #: Coût total engagé sur les titres encore détenus, frais inclus.
    cout_total: int
    date_premiere_entree: date | None
    methode: MethodeValorisation
    lots: tuple[Lot, ...] = ()

    @property
    def prix_revient_unitaire(self) -> Decimal:
        if self.quantite == 0:
            return Decimal(0)
        return Decimal(self.cout_total) / Decimal(self.quantite)

    def duree_detention_mois(self, reference: date) -> int | None:
        if self.date_premiere_entree is None:
            return None
        return mois_ecoules(self.date_premiere_entree, reference)


@dataclass(slots=True)
class ResultatSuivi:
    """Positions et cessions produites par une méthode de valorisation."""

    methode: MethodeValorisation
    positions: dict[str, Position] = field(default_factory=dict)
    cessions: list[Cession] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    def position(self, ticker: str) -> Position | None:
        return self.positions.get(ticker)

    def lignes_ouvertes(self) -> dict[str, Position]:
        return {
            ticker: position for ticker, position in self.positions.items() if position.quantite > 0
        }

    def cout_total(self) -> int:
        return sum(position.cout_total for position in self.lignes_ouvertes().values())

    def plus_values_realisees(self) -> int:
        return sum(cession.plus_value_brute for cession in self.cessions)


def montant_net_effectif(transaction: Transaction, moteur: MoteurFrais | None) -> int:
    """Montant réellement décaissé ou encaissé.

    Les frais consignés sur la transaction — ceux de l'avis d'opéré — l'emportent
    sur ceux que le barème recalculerait. Le barème n'intervient que si aucun
    frais n'a été saisi.
    """
    if transaction.frais or moteur is None:
        return transaction.montant_net
    decompte = moteur.calculer(transaction.sens, transaction.quantite, transaction.cours_unitaire)
    return decompte.montant_net


class _EtatLigne:
    """État mutable d'une ligne pendant le parcours chronologique."""

    def __init__(self, ticker: str, methode: MethodeValorisation) -> None:
        self.ticker = ticker
        self.methode = methode
        self.quantite = 0
        self.cout_total = 0
        self.premiere_entree: date | None = None
        self.lots: list[Lot] = []

    def figer(self) -> Position:
        return Position(
            ticker=self.ticker,
            quantite=self.quantite,
            cout_total=self.cout_total,
            date_premiere_entree=self.premiere_entree,
            methode=self.methode,
            lots=tuple(self.lots),
        )


def suivre(
    transactions: Sequence[Transaction],
    operations: Sequence[OperationSurTitre] = (),
    methode: MethodeValorisation = MethodeValorisation.PMP,
    moteur: MoteurFrais | None = None,
    mode_arrondi: ModeArrondi = ModeArrondi.HALF_UP,
) -> ResultatSuivi:
    """Rejoue les transactions dans l'ordre et produit positions et cessions.

    Args:
        transactions: opérations du portefeuille, dans un ordre quelconque.
        operations: opérations sur titres. Seules celles qui modifient le nombre
            de titres sont prises en compte ; les dividendes relèvent des flux
            d'espèces.
        methode: PMP ou FIFO.
        moteur: barème de frais, utilisé seulement pour les transactions saisies
            sans frais.
        mode_arrondi: mode appliqué aux arrondis de coût.

    Raises:
        ErreurValidation: vente portant sur plus de titres que détenus.
    """
    resultat = ResultatSuivi(methode=methode)
    etats: dict[str, _EtatLigne] = {}

    # Les opérations sur titres se détachent à l'ouverture : à date égale, elles
    # précèdent les transactions de la séance.
    evenements: list[tuple[date, int, object]] = [
        (operation.date_ex, 0, operation)
        for operation in operations
        if operation.type_ost in OST_SUR_QUANTITE
    ]
    evenements += [(transaction.date_operation, 1, transaction) for transaction in transactions]
    evenements.sort(key=lambda element: (element[0], element[1]))

    for _, _, evenement in evenements:
        if isinstance(evenement, OperationSurTitre):
            _appliquer_ost(evenement, etats, resultat)
        elif isinstance(evenement, Transaction):
            _appliquer_transaction(evenement, etats, resultat, moteur, mode_arrondi)

    resultat.positions = {ticker: etat.figer() for ticker, etat in etats.items()}
    return resultat


def _appliquer_ost(
    operation: OperationSurTitre,
    etats: dict[str, _EtatLigne],
    resultat: ResultatSuivi,
) -> None:
    etat = etats.get(operation.ticker)
    if etat is None or etat.quantite == 0:
        return

    facteur = operation.facteur_titres
    avant = etat.quantite
    apres = int((Decimal(avant) * facteur).to_integral_value(rounding="ROUND_FLOOR"))
    if apres <= 0:
        resultat.avertissements.append(
            f"{operation.ticker} : l'opération {operation.identifiant} ramènerait la "
            "ligne à zéro titre. Elle est ignorée, à vérifier manuellement."
        )
        return

    reste = Decimal(avant) * facteur - Decimal(apres)
    if reste > 0:
        resultat.avertissements.append(
            f"{operation.ticker} : l'opération {operation.identifiant} donne "
            f"{Decimal(avant) * facteur} titres. La fraction de {reste} rompu n'est pas "
            "modélisée — elle est en général réglée en espèces par l'émetteur. "
            "Vérifiez le montant reçu."
        )

    etat.quantite = apres
    # Le coût total ne change pas : une division ne fait rien débourser.
    if etat.methode is MethodeValorisation.FIFO:
        nouveaux: list[Lot] = []
        for lot in etat.lots:
            quantite = int(
                (Decimal(lot.quantite) * facteur).to_integral_value(rounding="ROUND_FLOOR")
            )
            if quantite <= 0:
                continue
            nouveaux.append(
                Lot(
                    date_acquisition=lot.date_acquisition,
                    quantite=quantite,
                    cout_unitaire=lot.cout_total / Decimal(quantite),
                    reference=lot.reference,
                )
            )
        etat.lots = nouveaux


def _appliquer_transaction(
    transaction: Transaction,
    etats: dict[str, _EtatLigne],
    resultat: ResultatSuivi,
    moteur: MoteurFrais | None,
    mode_arrondi: ModeArrondi,
) -> None:
    etat = etats.setdefault(transaction.ticker, _EtatLigne(transaction.ticker, resultat.methode))
    montant_net = montant_net_effectif(transaction, moteur)

    if transaction.sens is SensOperation.ACHAT:
        etat.quantite += transaction.quantite
        etat.cout_total += montant_net
        if etat.premiere_entree is None:
            etat.premiere_entree = transaction.date_operation
        if etat.methode is MethodeValorisation.FIFO:
            etat.lots.append(
                Lot(
                    date_acquisition=transaction.date_operation,
                    quantite=transaction.quantite,
                    cout_unitaire=Decimal(montant_net) / Decimal(transaction.quantite),
                    reference=transaction.identifiant,
                )
            )
        return

    if transaction.quantite > etat.quantite:
        raise ErreurValidation(
            f"Vente de {transaction.quantite} titres {transaction.ticker} alors que "
            f"{etat.quantite} seulement sont détenus au {transaction.date_operation}. "
            "Une transaction manque, ou une opération sur titres n'a pas été saisie.",
            ticker=transaction.ticker,
            transaction=transaction.identifiant,
        )

    if etat.methode is MethodeValorisation.PMP:
        _ceder_pmp(transaction, etat, resultat, montant_net, mode_arrondi)
    else:
        _ceder_fifo(transaction, etat, resultat, montant_net, mode_arrondi)

    if etat.quantite == 0:
        etat.premiere_entree = None


def _ceder_pmp(
    transaction: Transaction,
    etat: _EtatLigne,
    resultat: ResultatSuivi,
    produit_net: int,
    mode_arrondi: ModeArrondi,
) -> None:
    if transaction.quantite == etat.quantite:
        # Dernière cession : elle emporte tout le coût restant, sans résidu.
        cout_cede = etat.cout_total
    else:
        prix_revient = Decimal(etat.cout_total) / Decimal(etat.quantite)
        cout_cede = arrondi_xof(prix_revient * Decimal(transaction.quantite), mode_arrondi)

    etat.quantite -= transaction.quantite
    etat.cout_total -= cout_cede
    resultat.cessions.append(
        Cession(
            ticker=transaction.ticker,
            date_operation=transaction.date_operation,
            quantite=transaction.quantite,
            produit_net=produit_net,
            cout_de_revient=cout_cede,
            methode=MethodeValorisation.PMP,
            reference_transaction=transaction.identifiant,
            # En PMP, les titres cédés n'ont pas de date d'acquisition propre.
            duree_detention_mois=None,
            date_acquisition=None,
        )
    )


def _ceder_fifo(
    transaction: Transaction,
    etat: _EtatLigne,
    resultat: ResultatSuivi,
    produit_net: int,
    mode_arrondi: ModeArrondi,
) -> None:
    """Consomme les lots les plus anciens, et produit une cession par lot.

    Une vente qui traverse trois lots donne trois cessions : c'est ce que réclame
    un calcul de plus-value quand le régime dépend de la durée de détention.
    """
    restant = transaction.quantite
    consommes: list[tuple[Lot, int]] = []

    while restant > 0 and etat.lots:
        lot = etat.lots[0]
        pris = min(restant, lot.quantite)
        consommes.append((lot, pris))
        restant -= pris
        if pris == lot.quantite:
            etat.lots.pop(0)
        else:
            etat.lots[0] = Lot(
                date_acquisition=lot.date_acquisition,
                quantite=lot.quantite - pris,
                cout_unitaire=lot.cout_unitaire,
                reference=lot.reference,
            )

    if restant > 0:
        raise ErreurValidation(
            f"Lots insuffisants pour céder {transaction.quantite} titres "
            f"{transaction.ticker} : il manque {restant} titre(s) dans le suivi FIFO "
            "alors que la quantité globale les comptait. Une opération sur titres a "
            "probablement déséquilibré les lots.",
            ticker=transaction.ticker,
            transaction=transaction.identifiant,
        )

    # Le produit net est réparti au prorata des titres de chaque lot. Le dernier
    # lot absorbe le résidu d'arrondi, pour que la somme des cessions rende
    # exactement le montant encaissé — un franc perdu ici fausserait la
    # réconciliation avec le relevé de la SGI.
    deja_reparti = 0
    for rang, (lot, pris) in enumerate(consommes):
        dernier = rang == len(consommes) - 1
        if dernier:
            produit_part = produit_net - deja_reparti
        else:
            part = Decimal(pris) / Decimal(transaction.quantite)
            produit_part = arrondi_xof(Decimal(produit_net) * part, mode_arrondi)
            deja_reparti += produit_part
        cout_part = arrondi_xof(lot.cout_unitaire * Decimal(pris), mode_arrondi)
        etat.quantite -= pris
        etat.cout_total -= cout_part
        resultat.cessions.append(
            Cession(
                ticker=transaction.ticker,
                date_operation=transaction.date_operation,
                quantite=pris,
                produit_net=produit_part,
                cout_de_revient=cout_part,
                methode=MethodeValorisation.FIFO,
                reference_transaction=transaction.identifiant,
                duree_detention_mois=mois_ecoules(lot.date_acquisition, transaction.date_operation),
                date_acquisition=lot.date_acquisition,
            )
        )

    if etat.quantite == 0:
        etat.cout_total = 0
    if etat.lots:
        etat.premiere_entree = etat.lots[0].date_acquisition


def suivre_les_deux(
    transactions: Sequence[Transaction],
    operations: Sequence[OperationSurTitre] = (),
    moteur: MoteurFrais | None = None,
    mode_arrondi: ModeArrondi = ModeArrondi.HALF_UP,
) -> Mapping[MethodeValorisation, ResultatSuivi]:
    """Calcule les deux méthodes en parallèle.

    Elles donnent le même prix de revient tant qu'aucune vente n'a eu lieu, et
    divergent ensuite sur le montant de plus-value réalisée.
    """
    return {
        methode: suivre(transactions, operations, methode, moteur, mode_arrondi)
        for methode in (MethodeValorisation.PMP, MethodeValorisation.FIFO)
    }
