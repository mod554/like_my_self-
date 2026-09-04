"""Construction des connecteurs à partir de la configuration.

Un seul endroit décide quelle classe correspond à quel ``type`` de source. Ajouter
un connecteur, c'est ajouter une entrée ici — pas modifier l'orchestrateur.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from brvm.config.modeles import ConfigSource, Configuration
from brvm.ingestion.api import SourceApiJson
from brvm.ingestion.base import DataSource
from brvm.ingestion.csv_distant import SourceCsvDistant
from brvm.ingestion.fichier import SourceFichier
from brvm.ingestion.sikafinance import construire_analyseur
from brvm.ingestion.web import SourceWeb
from brvm.utils.erreurs import ErreurConfiguration

#: Types de source acceptés dans la configuration, et ce qu'ils recouvrent.
TYPES_CONNUS: Final[Mapping[str, str]] = {
    "fichier_csv": "Fichier CSV ou Excel local, alimenté à la main ou par export.",
    "web": "Page interrogée en HTTP, analysée selon la structure que vous décrivez.",
    "api_json": (
        "API JSON interrogée valeur par valeur, selon le schéma que vous décrivez "
        "dans le bloc `api`. Requiert un référentiel d'univers renseigné."
    ),
    "csv_distant": (
        "Dépôt de fichiers CSV servis en HTTP, un par valeur, selon les colonnes "
        "que vous décrivez dans le bloc `csv_distant`. Requiert un référentiel "
        "d'univers renseigné."
    ),
}


def construire_source(source: ConfigSource, configuration: Configuration) -> DataSource:
    """Instancie le connecteur décrit par un bloc `sources[]`.

    Raises:
        ErreurConfiguration: type inconnu. Le message énumère les types acceptés
            plutôt que de retomber sur un connecteur par défaut.
    """
    match source.type:
        case "fichier_csv":
            return SourceFichier(source, configuration)
        case "web":
            return SourceWeb(source, configuration, construire_analyseur(source, configuration))
        case "api_json":
            return SourceApiJson(source, configuration)
        case "csv_distant":
            return SourceCsvDistant(source, configuration)
        case _:
            raise ErreurConfiguration(
                f"Type de source inconnu : {source.type!r}. Types acceptés : "
                + ", ".join(f"{cle} ({texte})" for cle, texte in TYPES_CONNUS.items()),
                source=source.nom,
            )


def construire_sources_actives(configuration: Configuration) -> list[DataSource]:
    """Instancie toutes les sources actives, par ordre de priorité croissante."""
    return [construire_source(source, configuration) for source in configuration.sources_actives()]
