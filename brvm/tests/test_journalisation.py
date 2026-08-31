"""Journalisation : format structuré, contexte, rotation, reconfiguration."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from brvm.config.modeles import ConfigJournalisation
from brvm.utils.journalisation import (
    RACINE,
    FormateurJson,
    FormateurTexte,
    configurer_journalisation,
    obtenir_journal,
)


@pytest.fixture(autouse=True)
def journal_propre() -> Iterator[None]:
    """Retire les gestionnaires installés par un test avant de passer au suivant.

    Sans cela, un fichier de journal d'un test précédent resterait ouvert et les
    lignes se mélangeraient d'un test à l'autre.
    """
    yield
    journal = logging.getLogger(RACINE)
    for gestionnaire in list(journal.handlers):
        journal.removeHandler(gestionnaire)
        gestionnaire.close()


def config(tmp_path: Path, **extras: object) -> ConfigJournalisation:
    parametres: dict[str, object] = {
        "niveau": "INFO",
        "fichier": tmp_path / "brvm.log",
        "taille_max_octets": 4096,
        "nb_sauvegardes": 2,
        "format_json": True,
    }
    parametres.update(extras)
    return ConfigJournalisation(**parametres)  # type: ignore[arg-type]


def enregistrement(message: str, **contexte: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="brvm.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for cle, valeur in contexte.items():
        setattr(record, cle, valeur)
    return record


class TestFormateurJson:
    def test_une_ligne_json_par_enregistrement(self) -> None:
        sortie = FormateurJson().format(enregistrement("collecte terminée"))
        charge = json.loads(sortie)
        assert charge["message"] == "collecte terminée"
        assert charge["niveau"] == "INFO"
        assert charge["journal"] == "brvm.test"
        assert charge["horodatage"].endswith("+00:00")

    def test_contexte_serialise_a_part(self) -> None:
        """Le contexte est une structure, pas une phrase : c'est ce qui rend le
        journal relisible par une machine six mois plus tard."""
        sortie = FormateurJson().format(
            enregistrement("cotation écrite", ticker="TEST1", source="fixture", revision=2)
        )
        contexte = json.loads(sortie)["contexte"]
        assert contexte == {"ticker": "TEST1", "source": "fixture", "revision": 2}

    def test_sans_contexte_aucune_cle_vide(self) -> None:
        assert "contexte" not in json.loads(FormateurJson().format(enregistrement("rien")))

    def test_exception_incluse(self) -> None:
        try:
            raise ValueError("échec de la source")
        except ValueError:
            import sys

            record = enregistrement("collecte en échec")
            record.exc_info = sys.exc_info()
            charge = json.loads(FormateurJson().format(record))
        assert "échec de la source" in charge["exception"]

    def test_valeur_non_serialisable_ne_fait_pas_echouer_le_journal(self) -> None:
        """Un journal qui plante prive de l'information au pire moment."""
        charge = json.loads(FormateurJson().format(enregistrement("objet", curieux=object())))
        assert "curieux" in charge["contexte"]


class TestFormateurTexte:
    def test_contexte_accole_en_fin_de_ligne(self) -> None:
        sortie = FormateurTexte().format(enregistrement("cotation écrite", ticker="TEST1"))
        assert "cotation écrite" in sortie
        assert "ticker='TEST1'" in sortie


class TestConfiguration:
    def test_ecriture_dans_le_fichier(self, tmp_path: Path) -> None:
        parametres = config(tmp_path)
        configurer_journalisation(parametres, console=False)
        obtenir_journal("test").info("collecte terminée", extra={"source": "fixture"})
        logging.shutdown()
        lignes = parametres.fichier.read_text(encoding="utf-8").strip().splitlines()
        assert len(lignes) == 1
        assert json.loads(lignes[0])["contexte"]["source"] == "fixture"

    def test_dossier_cree_si_absent(self, tmp_path: Path) -> None:
        parametres = config(tmp_path, fichier=tmp_path / "journaux" / "brvm.log")
        configurer_journalisation(parametres, console=False)
        assert parametres.fichier.parent.is_dir()

    def test_reconfiguration_ne_double_pas_les_lignes(self, tmp_path: Path) -> None:
        """Un rechargement de configuration ne doit pas empiler les gestionnaires."""
        parametres = config(tmp_path)
        configurer_journalisation(parametres, console=False)
        configurer_journalisation(parametres, console=False)
        journal = logging.getLogger(RACINE)
        assert len(journal.handlers) == 1
        obtenir_journal("test").info("une seule fois")
        logging.shutdown()
        assert parametres.fichier.read_text(encoding="utf-8").count("une seule fois") == 1

    def test_niveau_respecte(self, tmp_path: Path) -> None:
        parametres = config(tmp_path, niveau="WARNING")
        configurer_journalisation(parametres, console=False)
        obtenir_journal("test").info("ignorée")
        obtenir_journal("test").warning("retenue")
        logging.shutdown()
        contenu = parametres.fichier.read_text(encoding="utf-8")
        assert "ignorée" not in contenu
        assert "retenue" in contenu

    def test_rotation(self, tmp_path: Path) -> None:
        parametres = config(tmp_path, taille_max_octets=512, nb_sauvegardes=1)
        configurer_journalisation(parametres, console=False)
        journal = obtenir_journal("test")
        for numero in range(50):
            journal.info("ligne de remplissage %s", numero, extra={"ticker": "TEST1"})
        logging.shutdown()
        assert parametres.fichier.is_file()
        assert (tmp_path / "brvm.log.1").is_file()

    def test_format_texte(self, tmp_path: Path) -> None:
        parametres = config(tmp_path, format_json=False)
        configurer_journalisation(parametres, console=False)
        obtenir_journal("test").info("message lisible")
        logging.shutdown()
        contenu = parametres.fichier.read_text(encoding="utf-8")
        assert "message lisible" in contenu
        assert not contenu.lstrip().startswith("{")


def test_nom_du_journal_prefixe() -> None:
    assert obtenir_journal("ingestion.source").name == f"{RACINE}.ingestion.source"
