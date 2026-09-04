"""Interface commune des sources de données.

Un connecteur a une seule responsabilité : **rapporter ce qu'il a lu**. Il ne
décide pas si une donnée est bonne, il ne la corrige pas, il ne l'écrit pas en
base. Il renvoie des lignes, chacune accompagnée soit d'une cotation validée,
soit de la raison pour laquelle elle ne l'est pas — et toujours de sa charge
brute, pour que la mise en quarantaine porte sur la donnée d'origine.

Cette séparation est ce qui permet d'ajouter une source sans toucher à la
logique métier, et de rejouer une anomalie six mois plus tard sur la donnée
telle qu'elle a été reçue.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from brvm.domain.enums import StatutCollecte
from brvm.domain.modeles import Cotation


@dataclass(frozen=True, slots=True)
class LigneCollectee:
    """Une ligne rapportée par un connecteur.

    Exactement l'un des deux cas est vrai : ``cotation`` est renseignée, ou
    ``erreur`` l'est. Dans les deux cas ``brut`` conserve ce que la source a
    réellement fourni.
    """

    brut: dict[str, Any]
    cotation: Cotation | None = None
    erreur: str | None = None

    def __post_init__(self) -> None:
        if (self.cotation is None) == (self.erreur is None):
            raise ValueError(
                "Une ligne collectée porte soit une cotation, soit une erreur, "
                "jamais les deux ni aucune des deux."
            )

    @property
    def exploitable(self) -> bool:
        return self.cotation is not None


@dataclass(frozen=True, slots=True)
class ResultatCollecte:
    """Bilan d'un appel à une source, indépendamment de ce qui en sera fait."""

    source: str
    statut: StatutCollecte
    debut: datetime
    fin: datetime
    lignes: tuple[LigneCollectee, ...] = ()
    #: D'où vient la donnée : URL interrogée, chemin du fichier lu, entrée de cache.
    origine: str | None = None
    #: Vrai si la source était injoignable et que le cache local a été servi.
    depuis_cache: bool = False
    message: str | None = None
    #: Difficultés non bloquantes rencontrées pendant la collecte.
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lignes_exploitables(self) -> tuple[LigneCollectee, ...]:
        return tuple(ligne for ligne in self.lignes if ligne.exploitable)

    @property
    def lignes_en_erreur(self) -> tuple[LigneCollectee, ...]:
        return tuple(ligne for ligne in self.lignes if not ligne.exploitable)

    @property
    def duree_secondes(self) -> float:
        return (self.fin - self.debut).total_seconds()


class DataSource(ABC):
    """Contrat que tout connecteur doit honorer.

    Règles auxquelles une implémentation ne doit jamais déroger :

    * ne jamais lever pour un échec réseau ou un contenu illisible — renvoyer un
      :class:`ResultatCollecte` en statut ``ECHEC`` ou ``DEGRADE``. Une source qui
      tombe ne doit pas emporter la collecte des autres ;
    * ne jamais fabriquer une valeur absente. Un champ manquant reste manquant ;
    * horodater chaque cotation avec la date annoncée par la source
      (``horodatage_donnee``) *et* l'instant de la collecte
      (``horodatage_collecte``). Sans les deux, la fraîcheur est incalculable.
    """

    #: Identifiant stable de la source, tel qu'il apparaît en base et en journal.
    nom: str

    @abstractmethod
    def collecter(self, jour: date | None = None) -> ResultatCollecte:
        """Collecte les cotations disponibles.

        Args:
            jour: séance visée. ``None`` demande la dernière disponible.
        """

    @abstractmethod
    def disponible(self) -> bool:
        """Indique si la source peut être interrogée maintenant.

        Une réponse ``False`` est une information d'exploitation, pas une erreur :
        l'orchestrateur passe à la source suivante et le consigne.
        """

    def echec(self, debut: datetime, message: str, origine: str | None = None) -> ResultatCollecte:
        """Fabrique un résultat en échec — raccourci pour les implémentations."""
        return ResultatCollecte(
            source=self.nom,
            statut=StatutCollecte.ECHEC,
            debut=debut,
            fin=datetime.now(UTC),
            origine=origine,
            message=message,
        )

    @staticmethod
    def maintenant() -> datetime:
        return datetime.now(UTC)


def statut_depuis_lignes(
    lignes: Sequence[LigneCollectee], depuis_cache: bool = False
) -> StatutCollecte:
    """Déduit le statut d'une collecte de la qualité de ses lignes."""
    if depuis_cache:
        return StatutCollecte.DEGRADE
    if not lignes:
        return StatutCollecte.ECHEC
    if any(not ligne.exploitable for ligne in lignes):
        return StatutCollecte.PARTIEL
    return StatutCollecte.SUCCES
