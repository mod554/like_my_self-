"""Solde espèces du portefeuille, et ce qui l'empêche d'être connu.

Le compte espèces était stockable — la table `flux_especes` existe, et l'énum
distingue apport, retrait, dividende et frais de garde — mais seuls les
dividendes étaient lus. Apports, retraits et frais de garde n'atteignaient aucun
calcul : le portefeuille ignorait qu'il avait des liquidités.

Cela bloquait tout ce qui en dépend : la performance (un TWR mesuré sur la seule
valeur des titres part à −100 % dès qu'une ligne est soldée), le repli, et toute
alerte de trésorerie.

**Le solde n'est pas toujours connaissable, et c'est le point important.** Il se
calcule à partir des apports déclarés :

    solde = apports − retraits + dividendes nets − frais de garde
            − décaissements d'achat + encaissements de vente

Si aucun apport n'a été saisi, la somme est négative : elle ne mesure alors pas
une trésorerie, mais l'argent que les achats ont consommé. Afficher ce nombre
comme un solde serait faux. On rend donc `None` avec le motif, plutôt qu'un
chiffre plausible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from brvm.domain.enums import SensOperation, TypeFluxEspece
from brvm.domain.modeles import FluxEspece, Transaction
from brvm.domain.monnaie import format_xof
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.positions import montant_net_effectif

#: Motif rendu quand aucun apport n'a été déclaré. Le solde reste inconnu, il
#: n'est pas supposé nul : le système ne sait pas avec quoi les achats ont été
#: financés.
MOTIF_SANS_APPORT: str = (
    "Aucun apport d'espèces n'a été déclaré. Le solde ne peut pas être calculé : "
    "sans savoir avec quoi les achats ont été financés, la somme des mouvements "
    "mesure l'argent dépensé, pas la trésorerie disponible. Enregistrez vos "
    "versements en flux d'espèces de type APPORT."
)


@dataclass(frozen=True, slots=True)
class Tresorerie:
    """Le compte espèces, décomposé par nature de mouvement.

    Chaque poste est conservé séparément : un solde juste dont on ne peut pas
    expliquer la composition ne se vérifie pas contre un relevé de compte.
    """

    apports: int = 0
    retraits: int = 0
    dividendes_nets: int = 0
    frais_garde: int = 0
    autres: int = 0
    decaissements_achats: int = 0
    encaissements_ventes: int = 0
    #: Renseigné quand le solde n'est pas calculable. Le solde vaut alors None.
    motif_indisponible: str | None = None

    @property
    def mouvements_declares(self) -> int:
        """Somme des flux d'espèces saisis, hors achats et ventes de titres."""
        return self.apports - self.retraits + self.dividendes_nets - self.frais_garde + self.autres

    @property
    def solde(self) -> int | None:
        """Espèces disponibles, ou ``None`` si la question n'a pas de réponse."""
        if self.motif_indisponible is not None:
            return None
        return self.mouvements_declares - self.decaissements_achats + self.encaissements_ventes

    @property
    def mesurable(self) -> bool:
        return self.motif_indisponible is None

    def resume(self) -> str:
        if not self.mesurable:
            return f"Espèces : non calculables — {self.motif_indisponible}"
        lignes = [
            f"Apports{'':.<44}{format_xof(self.apports):>20}",
            f"Retraits{'':.<43}{format_xof(-self.retraits):>20}",
            f"Dividendes nets{'':.<36}{format_xof(self.dividendes_nets):>20}",
            f"Frais de garde{'':.<37}{format_xof(-self.frais_garde):>20}",
        ]
        if self.autres:
            lignes.append(f"Autres mouvements{'':.<34}{format_xof(self.autres):>20}")
        lignes += [
            f"Achats de titres{'':.<35}{format_xof(-self.decaissements_achats):>20}",
            f"Ventes de titres{'':.<35}{format_xof(self.encaissements_ventes):>20}",
            f"Solde espèces{'':.<38}{format_xof(self.solde or 0):>20}",
        ]
        return "\n".join(lignes)


def calculer_tresorerie(
    transactions: Sequence[Transaction],
    flux: Sequence[FluxEspece],
    moteur_frais: MoteurFrais | None = None,
) -> Tresorerie:
    """Reconstitue le compte espèces à partir des mouvements enregistrés.

    Les achats et ventes sont pris à leur montant **réellement** décaissé ou
    encaissé — les frais consignés sur l'avis d'opéré l'emportent sur ceux que
    le barème recalculerait.
    """
    postes: dict[TypeFluxEspece, int] = dict.fromkeys(TypeFluxEspece, 0)
    for mouvement in flux:
        postes[mouvement.type_flux] += mouvement.montant_net

    decaissements = 0
    encaissements = 0
    for transaction in transactions:
        montant = montant_net_effectif(transaction, moteur_frais)
        if transaction.sens is SensOperation.ACHAT:
            decaissements += montant
        else:
            encaissements += montant

    motif = None if postes[TypeFluxEspece.APPORT] > 0 else MOTIF_SANS_APPORT

    return Tresorerie(
        apports=postes[TypeFluxEspece.APPORT],
        retraits=postes[TypeFluxEspece.RETRAIT],
        dividendes_nets=postes[TypeFluxEspece.DIVIDENDE],
        frais_garde=postes[TypeFluxEspece.FRAIS_GARDE],
        autres=postes[TypeFluxEspece.AUTRE],
        decaissements_achats=decaissements,
        encaissements_ventes=encaissements,
        motif_indisponible=motif,
    )
