"""Publication d'un instantané public du criblage de la cote.

L'interface locale sert un état complet — portefeuille compris — sur la boucle
locale, sans authentification. **Cet instantané ne contient rien de personnel** :
ni ligne détenue, ni montant investi, ni plus-value, ni capital. Uniquement le
criblage de la cote, dont chaque chiffre provient d'une source publique.

C'est la seule forme sous laquelle ce système peut être mis en ligne sans mot de
passe. La séparation est faite ici, à la source, et non par une vue qui
masquerait des champs : un champ masqué reste présent dans la charge, et une
faute d'affichage suffirait à le révéler.

Le fichier produit porte son propre horodatage et l'âge de la donnée la plus
ancienne employée. Une page servie par un hébergeur statique ne peut pas savoir
si elle est fraîche ; elle doit le lire dans ce qu'on lui a remis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brvm.app.api import serialiser_criblage
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.market.criblage import cribler
from brvm.storage.base import BaseDonnees
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.publication")

#: Champs de la charge qui ne doivent JAMAIS partir vers une page publique.
#: La liste est vérifiée par un test : si la sérialisation en ajoute un, il
#: faudra décider explicitement de son sort plutôt que de le laisser filer.
CHAMPS_PERSONNELS: frozenset[str] = frozenset(
    {"portefeuille", "lignes", "propositions", "capital", "transactions", "signaux"}
)


def instantane_public(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    instant: datetime | None = None,
) -> dict[str, Any]:
    """Crible la cote et rend la charge publiable.

    Aucune proposition de répartition n'est produite : elle exige un capital,
    qui est une donnée personnelle. La page publique classe, elle ne répartit pas.
    """
    maintenant = instant or datetime.now(UTC)
    criblage = cribler(base, configuration, calendrier, instant=maintenant)
    charge = serialiser_criblage(criblage)

    # `serialiser_criblage` émet toujours la clé, vide faute de capital. On la
    # RETIRE plutôt que de publier une clé vide : une clé vide invite à la
    # remplir, et la prochaine main qui passera ne saura pas qu'elle ne doit pas.
    repartitions = charge.pop("propositions", {})
    if repartitions:
        raise ValueError(
            "Des répartitions chiffrées figurent dans la charge à publier. Elles "
            "reposent sur votre capital, qui est une donnée personnelle : elles "
            "n'ont pas leur place sur une page publique."
        )

    presents = CHAMPS_PERSONNELS & set(charge)
    if presents:
        raise ValueError(
            "La charge publique contient des champs personnels : "
            + ", ".join(sorted(presents))
            + ". Retirez-les avant publication."
        )

    charge["publie_le"] = maintenant.isoformat()
    charge["portee"] = (
        "Criblage public de la cote BRVM. Aucune donnée de portefeuille, aucun "
        "montant personnel, aucune proposition de répartition."
    )
    return charge


def publier(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    cible: Path,
    instant: datetime | None = None,
) -> Path:
    """Écrit l'instantané public, en créant le dossier au besoin."""
    charge = instantane_public(base, configuration, calendrier, instant)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(
        json.dumps(charge, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    _journal.info(
        "Instantané public écrit",
        extra={
            "fichier": str(cible),
            "valeurs": charge["analysees"],
            "octets": cible.stat().st_size,
        },
    )
    return cible
