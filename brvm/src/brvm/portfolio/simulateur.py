"""Simulateur d'ordre : ce que coûte vraiment une intention d'achat ou de vente.

Le chiffre que ce module existe pour produire est le **seuil de rentabilité** :
le cours à partir duquel l'opération devient bénéficiaire, une fois payés les
frais d'achat, les frais de revente et l'impôt éventuel.

Ce seuil est toujours plus haut que le cours d'achat, et l'écart surprend sur les
petits montants : avec un minimum de perception, acheter pour 50 000 XOF peut
demander plusieurs points de hausse avant d'espérer sortir à l'équilibre. Le
voir avant de passer l'ordre change les décisions.

Le seuil est cherché par dichotomie plutôt que par formule fermée : minimums de
perception, plafonds et paliers d'imposition rendent la fonction de coût
discontinue, et une formule fermée cesserait d'être juste dès qu'un barème
comporte un palier.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from brvm.domain.enums import MethodeValorisation, SensOperation
from brvm.domain.monnaie import format_xof
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import DecompteFrais, MoteurFrais
from brvm.portfolio.positions import Position
from brvm.utils.erreurs import ErreurValidation

#: Nombre maximal de doublements pour encadrer le seuil avant de renoncer.
MAX_DOUBLEMENTS: Final[int] = 40

#: Cours plancher exploré. Le XOF n'ayant pas de subdivision, 1 est le minimum.
COURS_PLANCHER: Final[int] = 1


@dataclass(frozen=True, slots=True)
class SimulationOrdre:
    """Résultat d'une intention d'ordre, frais et fiscalité compris."""

    ticker: str
    sens: SensOperation
    quantite: int
    cours_unitaire: int
    decompte: DecompteFrais
    position_avant: Position | None
    quantite_apres: int
    cout_total_apres: int
    prix_revient_apres: Decimal
    #: Cours à partir duquel l'opération devient bénéficiaire, net de tout.
    seuil_rentabilite: int | None
    motif_seuil: str | None = None

    @property
    def hausse_necessaire(self) -> Decimal | None:
        """Écart entre le seuil de rentabilité et le cours de l'opération."""
        if self.seuil_rentabilite is None or self.cours_unitaire == 0:
            return None
        return Decimal(self.seuil_rentabilite) / Decimal(self.cours_unitaire) - Decimal(1)

    def detail(self) -> str:
        lignes = [self.decompte.detail()]
        if self.sens is SensOperation.ACHAT:
            lignes.append(
                f"  Position après{'':.<42}"
                f"{self.quantite_apres} titres, prix de revient "
                f"{self.prix_revient_apres.quantize(Decimal('0.01'))} XOF"
            )
        else:
            lignes.append(f"  Position après{'':.<42}{self.quantite_apres} titres")

        if self.seuil_rentabilite is None:
            lignes.append(f"  Seuil de rentabilité : indéterminé — {self.motif_seuil}")
        else:
            hausse = self.hausse_necessaire
            complement = f" soit {hausse:+.2%}" if hausse is not None else ""
            lignes.append(
                f"  Seuil de rentabilité{'':.<36}"
                f"{format_xof(self.seuil_rentabilite):>20}{complement}"
            )
            lignes.append(
                "  (cours à partir duquel une revente couvre frais d'achat, frais de "
                "revente et impôt)"
            )
        return "\n".join(lignes)


def _resultat_net_a(
    cours: int,
    quantite: int,
    cout_de_revient: int,
    moteur_frais: MoteurFrais,
    moteur_fiscal: MoteurFiscal,
    duree_detention_mois: int | None,
) -> int:
    """Ce qu'il resterait en poche si l'on vendait ``quantite`` titres à ``cours``."""
    decompte = moteur_frais.calculer(SensOperation.VENTE, quantite, cours)
    plus_value = decompte.montant_net - cout_de_revient
    return moteur_fiscal.plus_value(plus_value, duree_detention_mois).plus_value_nette


def seuil_rentabilite(
    quantite: int,
    cout_de_revient: int,
    moteur_frais: MoteurFrais,
    moteur_fiscal: MoteurFiscal,
    duree_detention_mois: int | None = None,
) -> tuple[int | None, str | None]:
    """Plus petit cours entier auquel une revente couvre tout.

    Returns:
        Le seuil et, s'il n'a pas été trouvé, le motif.
    """
    if quantite <= 0:
        raise ErreurValidation("La quantité doit être strictement positive.", quantite=quantite)

    def net(cours: int) -> int:
        return _resultat_net_a(
            cours,
            quantite,
            cout_de_revient,
            moteur_frais,
            moteur_fiscal,
            duree_detention_mois,
        )

    if net(COURS_PLANCHER) >= 0:
        return COURS_PLANCHER, None

    haut = max(COURS_PLANCHER + 1, cout_de_revient // quantite + 1)
    for _ in range(MAX_DOUBLEMENTS):
        if net(haut) >= 0:
            break
        haut *= 2
    else:
        return None, (
            "aucun cours atteignable ne rend l'opération bénéficiaire dans les bornes "
            "explorées — vérifiez le barème, en particulier un minimum de perception "
            "disproportionné par rapport au montant de l'ordre"
        )

    bas = COURS_PLANCHER
    # Invariant : net(bas) < 0 <= net(haut). On resserre jusqu'à l'unité.
    while haut - bas > 1:
        milieu = (bas + haut) // 2
        if net(milieu) >= 0:
            haut = milieu
        else:
            bas = milieu
    return haut, None


def simuler(
    ticker: str,
    sens: SensOperation,
    quantite: int,
    cours_unitaire: int,
    moteur_frais: MoteurFrais,
    moteur_fiscal: MoteurFiscal,
    position_avant: Position | None = None,
    duree_detention_mois: int | None = None,
) -> SimulationOrdre:
    """Simule une intention d'ordre sur une ligne existante ou nouvelle.

    Raises:
        ErreurValidation: vente portant sur plus de titres que détenus.
    """
    decompte = moteur_frais.calculer(sens, quantite, cours_unitaire)
    detenus = position_avant.quantite if position_avant else 0
    cout_detenu = position_avant.cout_total if position_avant else 0

    if sens is SensOperation.ACHAT:
        quantite_apres = detenus + quantite
        cout_apres = cout_detenu + decompte.montant_net
        seuil, motif = seuil_rentabilite(
            quantite_apres, cout_apres, moteur_frais, moteur_fiscal, duree_detention_mois
        )
    else:
        if quantite > detenus:
            raise ErreurValidation(
                f"Vente de {quantite} titres {ticker} simulée alors que {detenus} "
                "seulement sont détenus.",
                ticker=ticker,
                detenus=detenus,
            )
        quantite_apres = detenus - quantite
        part_cedee = (
            0
            if detenus == 0
            else int(
                (Decimal(cout_detenu) * Decimal(quantite) / Decimal(detenus)).to_integral_value()
            )
        )
        cout_apres = cout_detenu - part_cedee
        # Pour une vente, le seuil porte sur les titres cédés : à partir de quel
        # cours cette cession précise couvre-t-elle leur coût de revient ?
        seuil, motif = seuil_rentabilite(
            quantite, part_cedee, moteur_frais, moteur_fiscal, duree_detention_mois
        )

    prix_revient_apres = (
        Decimal(cout_apres) / Decimal(quantite_apres) if quantite_apres > 0 else Decimal(0)
    )

    return SimulationOrdre(
        ticker=ticker,
        sens=sens,
        quantite=quantite,
        cours_unitaire=cours_unitaire,
        decompte=decompte,
        position_avant=position_avant,
        quantite_apres=quantite_apres,
        cout_total_apres=cout_apres,
        prix_revient_apres=prix_revient_apres,
        seuil_rentabilite=seuil,
        motif_seuil=motif,
    )


def position_vide(ticker: str) -> Position:
    """Position de départ pour simuler un premier achat."""
    return Position(
        ticker=ticker,
        quantite=0,
        cout_total=0,
        date_premiere_entree=None,
        methode=MethodeValorisation.PMP,
    )
