"""Construction de la série ajustée des dividendes et des divisions.

La série brute (:class:`~brvm.domain.modeles.Cotation`) est conservée intacte.
L'ajustement est **recalculé**, jamais stocké comme vérité première : un facteur
figé devient faux dès qu'une opération sur titre est corrigée a posteriori.

Méthode retenue : ajustement rétroactif (« back-adjustment »). Le facteur d'une
séance est le produit des facteurs de toutes les opérations dont la date de
détachement est **strictement postérieure** à cette séance. Conséquence voulue :
le bord droit de la série ajustée est égal à la série brute.

Absence de biais d'anticipation
-------------------------------
Le paramètre ``jusqu_a`` borne les opérations prises en compte à celles connues à
cette date. Un backtest positionné à la barre *T* appelle ``jusqu_a=T`` et obtient
exactement la série qu'un opérateur aurait pu construire ce jour-là. Sans ce
paramètre, la série ajustée d'aujourd'hui incorpore des dividendes futurs et
introduirait un biais d'anticipation dans tout signal calculé dessus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from typing import Final

from brvm.domain.enums import StatutSeance, TypeOst
from brvm.domain.modeles import Cotation, OperationSurTitre
from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.utils.erreurs import ErreurValidation

#: Décimales conservées sur les facteurs et les cours ajustés. Six suffisent pour
#: que l'erreur cumulée reste sous le franc sur des séries de plusieurs milliers
#: de séances, tout en gardant des comparaisons de tests reproductibles.
DECIMALES_AJUSTEMENT: Final[int] = 6

_QUANTUM = Decimal(1).scaleb(-DECIMALES_AJUSTEMENT)

#: Types d'opérations dont l'effet sur le cours est modélisé ici.
OST_MODELISEES: Final[frozenset[TypeOst]] = frozenset(
    {
        TypeOst.DIVIDENDE,
        TypeOst.DIVISION,
        TypeOst.REGROUPEMENT,
        TypeOst.ATTRIBUTION_GRATUITE,
    }
)


@dataclass(frozen=True, slots=True)
class PointAjuste:
    """Une séance, avec son facteur d'ajustement et ses valeurs ajustées."""

    date_seance: date
    statut_seance: StatutSeance
    cloture_brute: int | None
    volume_brut: int
    facteur_cours: Decimal
    facteur_titres: Decimal
    cloture_ajustee: Decimal | None
    volume_ajuste: int

    @property
    def cotee(self) -> bool:
        return self.statut_seance is StatutSeance.COTEE


@dataclass(frozen=True, slots=True)
class SerieAjustee:
    """Résultat de l'ajustement, accompagné de sa traçabilité."""

    ticker: str
    points: tuple[PointAjuste, ...]
    #: Facteur unitaire de chaque opération retenue, indexé par date de détachement.
    facteurs_par_ost: Mapping[date, Decimal] = field(default_factory=dict)
    #: Opérations écartées et pourquoi. Rien n'est corrigé en silence.
    avertissements: tuple[str, ...] = ()
    #: Borne de connaissance appliquée (``None`` = tout l'historique fourni).
    jusqu_a: date | None = None

    def cloture_ajustee_par_date(self) -> dict[date, Decimal | None]:
        return {point.date_seance: point.cloture_ajustee for point in self.points}

    def seances_cotees(self) -> tuple[PointAjuste, ...]:
        """Sous-série des seules séances où une transaction a réellement eu lieu."""
        return tuple(point for point in self.points if point.cotee)


def _quantifier(valeur: Decimal) -> Decimal:
    return valeur.quantize(_QUANTUM)


def _derniere_cloture_traitee_avant(cotations: Sequence[Cotation], jour: date) -> int | None:
    """Dernier cours issu d'une transaction réelle strictement avant ``jour``.

    On remonte jusqu'à trouver une séance effectivement cotée : sur une valeur peu
    liquide, la veille du détachement peut n'avoir donné lieu à aucun échange, et
    un cours de référence reconduit ne dit rien du prix auquel le marché traitait.
    """
    for cotation in reversed(cotations):
        if cotation.date_seance >= jour:
            continue
        if cotation.statut_seance is StatutSeance.COTEE and cotation.cloture is not None:
            return cotation.cloture
    return None


def ajuster_serie(
    cotations: Sequence[Cotation],
    operations: Sequence[OperationSurTitre] = (),
    jusqu_a: date | None = None,
) -> SerieAjustee:
    """Calcule la série ajustée d'une valeur.

    Args:
        cotations: cotations brutes d'un seul ticker, dans un ordre quelconque.
        operations: opérations sur titres connues pour ce ticker.
        jusqu_a: date de connaissance. Seules les opérations détachées jusqu'à
            cette date sont appliquées. ``None`` applique tout l'historique fourni.

    Raises:
        ErreurValidation: si les cotations mélangent plusieurs tickers, comportent
            un doublon de séance, ou si une opération porte sur un autre ticker.
    """
    if not cotations:
        raise ErreurValidation("Série vide : aucune cotation à ajuster.")

    tickers = {cotation.ticker for cotation in cotations}
    if len(tickers) > 1:
        raise ErreurValidation(
            "L'ajustement porte sur une seule valeur à la fois.",
            tickers=sorted(tickers),
        )
    ticker = tickers.pop()

    ordonnees = sorted(cotations, key=lambda cotation: cotation.date_seance)
    dates = [cotation.date_seance for cotation in ordonnees]
    if len(set(dates)) != len(dates):
        doublons = sorted({jour.isoformat() for jour in dates if dates.count(jour) > 1})
        raise ErreurValidation(
            "Plusieurs cotations pour la même séance : dédoublonnez par source avant d'ajuster.",
            ticker=ticker,
            dates=doublons,
        )

    for operation in operations:
        if operation.ticker != ticker:
            raise ErreurValidation(
                "Opération sur titre rattachée à une autre valeur que la série.",
                ticker_serie=ticker,
                ticker_ost=operation.ticker,
            )

    avertissements: list[str] = []
    facteurs_ost: dict[date, Decimal] = {}
    facteurs_titres_ost: dict[date, Decimal] = {}

    connues = [
        operation
        for operation in sorted(operations, key=lambda ost: ost.date_ex)
        if jusqu_a is None or operation.date_ex <= jusqu_a
    ]

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        for operation in connues:
            if operation.type_ost not in OST_MODELISEES:
                avertissements.append(
                    f"Opération {operation.identifiant} ({operation.type_ost.value}, "
                    f"détachement {operation.date_ex.isoformat()}) non modélisée : la série "
                    "ajustée l'ignore. Vérifiez manuellement l'impact sur la continuité "
                    "des cours."
                )
                continue

            if operation.type_ost is TypeOst.DIVIDENDE:
                reference = _derniere_cloture_traitee_avant(ordonnees, operation.date_ex)
                if reference is None:
                    avertissements.append(
                        f"Dividende {operation.identifiant} du "
                        f"{operation.date_ex.isoformat()} ignoré : aucune séance réellement "
                        "cotée avant le détachement, le facteur d'ajustement serait arbitraire."
                    )
                    continue
                dividende = operation.montant_brut_par_action or 0
                if dividende >= reference:
                    avertissements.append(
                        f"Dividende {operation.identifiant} du "
                        f"{operation.date_ex.isoformat()} ignoré : montant ({dividende}) "
                        f"supérieur ou égal au dernier cours traité ({reference}). Donnée "
                        "à vérifier à la source."
                    )
                    continue
                facteur_cours = Decimal(reference - dividende) / Decimal(reference)
                facteur_titres = Decimal(1)
            else:
                facteur_titres = operation.facteur_titres
                facteur_cours = Decimal(1) / facteur_titres

            jour = operation.date_ex
            facteurs_ost[jour] = _quantifier(facteurs_ost.get(jour, Decimal(1)) * facteur_cours)
            facteurs_titres_ost[jour] = _quantifier(
                facteurs_titres_ost.get(jour, Decimal(1)) * facteur_titres
            )

        # Parcours à rebours : le facteur d'une séance est le produit des facteurs
        # des opérations détachées après elle.
        points_inverses: list[PointAjuste] = []
        cumul_cours = Decimal(1)
        cumul_titres = Decimal(1)

        for cotation in reversed(ordonnees):
            points_inverses.append(
                PointAjuste(
                    date_seance=cotation.date_seance,
                    statut_seance=cotation.statut_seance,
                    cloture_brute=cotation.cloture,
                    volume_brut=cotation.volume_titres,
                    facteur_cours=_quantifier(cumul_cours),
                    facteur_titres=_quantifier(cumul_titres),
                    cloture_ajustee=(
                        _quantifier(Decimal(cotation.cloture) * cumul_cours)
                        if cotation.cloture is not None
                        else None
                    ),
                    volume_ajuste=int(
                        (Decimal(cotation.volume_titres) * cumul_titres).to_integral_value()
                    ),
                )
            )

            # Une opération détachée le jour J affecte les séances antérieures à J.
            if cotation.date_seance in facteurs_ost:
                cumul_cours *= facteurs_ost[cotation.date_seance]
                cumul_titres *= facteurs_titres_ost[cotation.date_seance]

        # Opérations détachées avant la première séance connue : sans effet sur la
        # série, mais on le dit plutôt que de laisser croire qu'elles sont appliquées.
        premiere_seance = ordonnees[0].date_seance
        for jour in sorted(facteurs_ost):
            if jour < premiere_seance:
                avertissements.append(
                    f"Opération détachée le {jour.isoformat()}, antérieure à la première "
                    "séance de la série : sans effet sur l'ajustement."
                )

    return SerieAjustee(
        ticker=ticker,
        points=tuple(reversed(points_inverses)),
        facteurs_par_ost=dict(facteurs_ost),
        avertissements=tuple(avertissements),
        jusqu_a=jusqu_a,
    )
