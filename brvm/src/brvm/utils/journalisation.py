"""Journalisation structurée.

Un journal lisible par une machine est ce qui permet, six mois plus tard, de
répondre à « d'où venait ce cours ? » et « pourquoi ce signal a-t-il été émis ? ».
Chaque enregistrement peut porter un contexte arbitraire (ticker, source, séance)
sérialisé avec la ligne, plutôt que noyé dans le texte du message.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from brvm.config.modeles import ConfigJournalisation

#: Nom racine des journaux du système.
RACINE: Final[str] = "brvm"

#: Attributs standard de ``LogRecord``, à ne pas recopier dans le contexte.
_ATTRIBUTS_STANDARD: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class FormateurJson(logging.Formatter):
    """Une ligne JSON par enregistrement, horodatée en UTC."""

    def format(self, record: logging.LogRecord) -> str:
        charge: dict[str, Any] = {
            "horodatage": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "journal": record.name,
            "message": record.getMessage(),
        }
        contexte = {
            cle: valeur
            for cle, valeur in record.__dict__.items()
            if cle not in _ATTRIBUTS_STANDARD and not cle.startswith("_")
        }
        if contexte:
            charge["contexte"] = contexte
        if record.exc_info:
            charge["exception"] = self.formatException(record.exc_info)
        return json.dumps(charge, ensure_ascii=False, default=str)


class FormateurTexte(logging.Formatter):
    """Format lisible à l'écran, contexte accolé en fin de ligne."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s  %(levelname)-8s %(name)s : %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        contexte = {
            cle: valeur
            for cle, valeur in record.__dict__.items()
            if cle not in _ATTRIBUTS_STANDARD and not cle.startswith("_")
        }
        if contexte:
            details = " ".join(f"{cle}={valeur!r}" for cle, valeur in sorted(contexte.items()))
            base = f"{base}  [{details}]"
        return base


def configurer_journalisation(
    configuration: ConfigJournalisation, console: bool = True
) -> logging.Logger:
    """Installe les gestionnaires de journal et renvoie le journal racine du système.

    Appelable plusieurs fois : les gestionnaires précédents sont retirés, de sorte
    qu'un rechargement de configuration ne double pas les lignes.
    """
    journal = logging.getLogger(RACINE)
    journal.setLevel(configuration.niveau)
    journal.propagate = False
    for gestionnaire in list(journal.handlers):
        journal.removeHandler(gestionnaire)
        gestionnaire.close()

    fichier = Path(configuration.fichier)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    rotation = logging.handlers.RotatingFileHandler(
        fichier,
        maxBytes=configuration.taille_max_octets,
        backupCount=configuration.nb_sauvegardes,
        encoding="utf-8",
    )
    rotation.setFormatter(FormateurJson() if configuration.format_json else FormateurTexte())
    journal.addHandler(rotation)

    if console:
        ecran = logging.StreamHandler()
        ecran.setFormatter(FormateurTexte())
        journal.addHandler(ecran)

    return journal


def obtenir_journal(nom: str) -> logging.Logger:
    """Journal enfant, nommé d'après le module appelant.

    Exemple : ``obtenir_journal("ingestion.brvm_site")``.
    """
    return logging.getLogger(f"{RACINE}.{nom}")
