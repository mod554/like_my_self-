"""Métriques d'une simulation, y compris ce que les frais ont emporté.

Le chiffre le plus utile de ce module n'est pas le rendement : c'est la **part
des coûts dans la performance brute**. Sur un marché où chaque aller-retour coûte
deux commissions et deux TVA, une stratégie qui dégage 12 % brut et 4 % net n'est
pas une stratégie à 4 % : c'est une stratégie dont les deux tiers du travail sont
allés à l'intermédiaire. Le voir change la fréquence à laquelle on négocie.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Final

from brvm.config.modeles import Configuration
from brvm.domain.enums import BaseFrais, MethodeValorisation, SensOperation
from brvm.domain.modeles import LigneFrais, Transaction
from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.portfolio.positions import suivre
from brvm.risk.mesures import ResultatDrawdown, calculer_drawdown

from .moteur import Execution, ResultatBacktest

_DECIMALES: Final[Decimal] = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class Metriques:
    """Résultats chiffrés d'une simulation, avec leurs limites."""

    capital_initial: int
    valeur_finale: int
    performance_nette: int
    performance_brute: int
    total_frais: int
    rendement_total: Decimal
    #: Part des frais dans la performance avant frais. ``None`` si celle-ci est nulle
    #: ou négative — un ratio n'aurait alors aucun sens.
    part_des_couts: Decimal | None
    drawdown_maximum: Decimal
    drawdown_courant: Decimal
    volatilite_annualisee: Decimal | None
    sharpe: Decimal | None
    nb_transactions: int
    nb_refus: int
    nb_partielles: int
    nb_cessions: int
    taux_reussite: Decimal | None
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    def resume(self) -> str:
        lignes = [
            f"Capital initial{'':.<34}{self.capital_initial:>16}",
            f"Valeur finale{'':.<36}{self.valeur_finale:>16}",
            f"Rendement total{'':.<34}{self.rendement_total:>15.2%}",
            f"Drawdown maximum{'':.<33}{self.drawdown_maximum:>15.2%}",
        ]
        lignes.append(
            f"Volatilité annualisée{'':.<28}{self.volatilite_annualisee:>15.2%}"
            if self.volatilite_annualisee is not None
            else "Volatilité annualisée : non mesurable"
        )
        lignes.append(
            f"Ratio de Sharpe{'':.<34}{self.sharpe:>16.2f}"
            if self.sharpe is not None
            else "Ratio de Sharpe : non mesurable"
        )
        lignes.append(f"Transactions exécutées{'':.<27}{self.nb_transactions:>16}")
        lignes.append(f"Ordres refusés{'':.<35}{self.nb_refus:>16}")
        lignes.append(f"Exécutions partielles{'':.<28}{self.nb_partielles:>16}")
        lignes.append(
            f"Taux de réussite{'':.<33}{self.taux_reussite:>15.2%}"
            if self.taux_reussite is not None
            else "Taux de réussite : aucune cession pour le mesurer"
        )
        lignes.append(f"Frais cumulés{'':.<36}{self.total_frais:>16}")
        lignes.append(
            f"Part des coûts dans la performance brute{'':.<9}{self.part_des_couts:>15.2%}"
            if self.part_des_couts is not None
            else "Part des coûts : performance brute nulle ou négative, ratio sans objet"
        )
        return "\n".join(lignes)


def transactions_depuis(executions: Sequence[Execution]) -> list[Transaction]:
    """Convertit les exécutions simulées en transactions, pour rejouer les lignes.

    Les frais sont portés par une ligne unique de synthèse : le décompte détaillé
    a déjà été produit à l'exécution, et ce qui compte ici est le montant net.
    """
    transactions: list[Transaction] = []
    for rang, execution in enumerate(executions, start=1):
        if not execution.executee or execution.cours_execute is None:
            continue
        transactions.append(
            Transaction(
                identifiant=f"SIM-{rang:05d}",
                ticker=execution.ticker,
                date_operation=execution.date_seance,
                sens=execution.sens,
                quantite=execution.quantite_executee,
                cours_unitaire=execution.cours_execute,
                frais=(
                    LigneFrais(
                        libelle="Frais simulés",
                        base_calcul=BaseFrais.MONTANT_FIXE,
                        assiette=0,
                        montant=execution.frais,
                    ),
                )
                if execution.frais
                else (),
                note=execution.motif or None,
            )
        )
    return transactions


def _rendements(valeurs: Sequence[int]) -> list[Decimal]:
    rendements: list[Decimal] = []
    for precedente, courante in pairwise(valeurs):
        if precedente <= 0:
            continue
        rendements.append(Decimal(courante) / Decimal(precedente) - Decimal(1))
    return rendements


def calculer_metriques(resultat: ResultatBacktest, configuration: Configuration) -> Metriques:
    """Chiffre une simulation, en disant ce qui n'est pas mesurable."""
    avertissements: list[str] = list(resultat.avertissements)
    valeurs = [point.valeur_totale for point in resultat.courbe]
    valeur_finale = resultat.valeur_finale
    capital = resultat.capital_initial
    total_frais = resultat.total_frais

    performance_nette = valeur_finale - capital
    performance_brute = performance_nette + total_frais

    drawdown: ResultatDrawdown = calculer_drawdown(
        [(point.date_seance, point.valeur_totale) for point in resultat.courbe]
    )

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE
        rendement_total = (
            (Decimal(performance_nette) / Decimal(capital)).quantize(_DECIMALES)
            if capital > 0
            else Decimal(0)
        )
        part_des_couts = (
            (Decimal(total_frais) / Decimal(performance_brute)).quantize(_DECIMALES)
            if performance_brute > 0
            else None
        )
        if part_des_couts is None and total_frais > 0:
            avertissements.append(
                f"{total_frais} XOF de frais ont été payés pour une performance brute "
                "nulle ou négative : la totalité du résultat, et davantage, est partie "
                "en frais."
            )

        rendements = _rendements(valeurs)
        volatilite: Decimal | None = None
        sharpe: Decimal | None = None
        if len(rendements) >= 2:
            moyenne = sum(rendements, Decimal(0)) / Decimal(len(rendements))
            variance = sum(
                ((valeur - moyenne) ** 2 for valeur in rendements), Decimal(0)
            ) / Decimal(len(rendements) - 1)
            ecart = variance.sqrt()
            seances = Decimal(configuration.risque.seances_par_an)
            if ecart > 0:
                volatilite = (ecart * seances.sqrt()).quantize(_DECIMALES)
                exces = moyenne - configuration.backtest.taux_sans_risque / seances
                sharpe = ((exces / ecart) * seances.sqrt()).quantize(Decimal("0.0001"))
            else:
                avertissements.append(
                    "Volatilité nulle sur la période : ni la volatilité annualisée ni "
                    "le ratio de Sharpe ne sont définis. C'est le cas d'un portefeuille "
                    "resté en espèces, ou d'une valeur qui n'a pas coté."
                )
        else:
            avertissements.append(
                "Moins de deux variations de valorisation : volatilité et ratio de "
                "Sharpe non mesurables."
            )

    suivi = suivre(transactions_depuis(resultat.executions), methode=MethodeValorisation.FIFO)
    cessions = suivi.cessions
    taux_reussite = (
        (
            Decimal(sum(1 for c in cessions if c.plus_value_brute > 0)) / Decimal(len(cessions))
        ).quantize(_DECIMALES)
        if cessions
        else None
    )
    if not cessions:
        avertissements.append(
            "Aucune cession sur la période : le taux de réussite n'a rien à mesurer. "
            "Les positions encore ouvertes ne sont ni gagnantes ni perdantes."
        )

    achats = sum(1 for e in resultat.executions if e.executee and e.sens is SensOperation.ACHAT)
    ventes = sum(1 for e in resultat.executions if e.executee and e.sens is SensOperation.VENTE)

    return Metriques(
        capital_initial=capital,
        valeur_finale=valeur_finale,
        performance_nette=performance_nette,
        performance_brute=performance_brute,
        total_frais=total_frais,
        rendement_total=rendement_total,
        part_des_couts=part_des_couts,
        drawdown_maximum=drawdown.drawdown_maximum,
        drawdown_courant=drawdown.drawdown_courant,
        volatilite_annualisee=volatilite,
        sharpe=sharpe,
        nb_transactions=achats + ventes,
        nb_refus=len(resultat.refus),
        nb_partielles=sum(1 for e in resultat.executions if e.partielle),
        nb_cessions=len(cessions),
        taux_reussite=taux_reussite,
        avertissements=tuple(dict.fromkeys(avertissements)),
    )
