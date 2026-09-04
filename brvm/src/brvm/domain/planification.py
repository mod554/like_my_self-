"""Expression cron : analyse stricte, convention unique.

Une expression de planification est une donnée de configuration comme une autre :
elle est validée au chargement, pas au premier réveil manqué. Ce module vit dans
le domaine pour que le schéma de configuration puisse le vérifier sans dépendre
de la couche d'exploitation.

**Convention du jour de la semaine : 0 = lundi**, comme `date.weekday()` et comme
partout ailleurs dans ce système. Ce n'est pas la convention Unix (0 = dimanche),
et c'est délibéré : une seule convention dans tout le projet vaut mieux qu'une
fidélité partielle à un usage qui n'est lui-même pas universel. Se tromper d'un
jour ici ne produit pas d'erreur — seulement une séance jamais collectée.

L'analyseur couvre `*`, les valeurs, les listes, les plages et les pas. Il ne
dépend d'aucune bibliothèque : la politique reste vérifiable sans moteur installé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from brvm.utils.erreurs import ErreurConfiguration

#: Bornes de chaque champ cron, dans l'ordre des champs.
BORNES: Final[tuple[tuple[int, int], ...]] = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))

NOMS_CHAMPS: Final[tuple[str, ...]] = (
    "minute",
    "heure",
    "jour du mois",
    "mois",
    "jour de la semaine",
)

#: Horizon maximal exploré pour trouver la prochaine occurrence, en minutes.
#: Deux ans : au-delà, c'est l'expression qui est fautive, pas le calendrier.
HORIZON_MINUTES: Final[int] = 366 * 2 * 24 * 60


def _champ(expression: str, position: int) -> frozenset[int]:
    """Traduit un champ cron en ensemble de valeurs acceptées."""
    minimum, maximum = BORNES[position]
    nom = NOMS_CHAMPS[position]
    valeurs: set[int] = set()

    for morceau in expression.split(","):
        morceau = morceau.strip()
        if not morceau:
            raise ErreurConfiguration(
                f"Champ « {nom} » vide dans l'expression cron.", expression=expression
            )
        pas = 1
        if "/" in morceau:
            morceau, _, texte_pas = morceau.partition("/")
            if not texte_pas.isdigit() or int(texte_pas) < 1:
                raise ErreurConfiguration(
                    f"Pas illisible dans le champ « {nom} » : {texte_pas!r}.",
                    expression=expression,
                )
            pas = int(texte_pas)
        if morceau in {"*", ""}:
            debut, fin = minimum, maximum
        elif "-" in morceau:
            gauche, _, droite = morceau.partition("-")
            debut, fin = _entier(gauche, nom, expression), _entier(droite, nom, expression)
        else:
            debut = fin = _entier(morceau, nom, expression)
        if debut > fin:
            raise ErreurConfiguration(
                f"Plage inversée dans le champ « {nom} » : {morceau!r}.", expression=expression
            )
        for valeur in range(debut, fin + 1, pas):
            if not minimum <= valeur <= maximum:
                raise ErreurConfiguration(
                    f"Valeur {valeur} hors bornes pour le champ « {nom} » "
                    f"(attendu {minimum}–{maximum}).",
                    expression=expression,
                )
            valeurs.add(valeur)
    return frozenset(valeurs)


def _entier(texte: str, nom: str, expression: str) -> int:
    texte = texte.strip()
    try:
        return int(texte)
    except ValueError as exc:
        raise ErreurConfiguration(
            f"Valeur illisible dans le champ « {nom} » : {texte!r}. Le format attendu "
            "est « minute heure jour_du_mois mois jour_de_semaine », "
            "par exemple « 30 15 * * 1-5 ».",
            expression=expression,
        ) from exc


@dataclass(frozen=True, slots=True)
class Cron:
    """Expression cron à cinq champs, analysée une fois pour toutes.

    Convention du jour de la semaine : **0 = lundi**, comme partout ailleurs dans
    le système (`date.weekday()`), et non 0 = dimanche. Une convention unique
    dans tout le projet vaut mieux qu'une fidélité partielle à un usage Unix.
    """

    expression: str
    minutes: frozenset[int]
    heures: frozenset[int]
    jours_du_mois: frozenset[int]
    mois: frozenset[int]
    jours_de_semaine: frozenset[int]

    @classmethod
    def analyser(cls, expression: str) -> Cron:
        champs = expression.split()
        if len(champs) != 5:
            raise ErreurConfiguration(
                f"Expression cron à {len(champs)} champ(s) au lieu de 5 : "
                f"{expression!r}. Format attendu : "
                "« minute heure jour_du_mois mois jour_de_semaine », "
                "avec 0 = lundi pour le jour de la semaine.",
                expression=expression,
            )
        return cls(
            expression=expression,
            minutes=_champ(champs[0], 0),
            heures=_champ(champs[1], 1),
            jours_du_mois=_champ(champs[2], 2),
            mois=_champ(champs[3], 3),
            jours_de_semaine=_champ(champs[4], 4),
        )

    def correspond(self, instant: datetime) -> bool:
        return (
            instant.minute in self.minutes
            and instant.hour in self.heures
            and instant.day in self.jours_du_mois
            and instant.month in self.mois
            and instant.weekday() in self.jours_de_semaine
        )
