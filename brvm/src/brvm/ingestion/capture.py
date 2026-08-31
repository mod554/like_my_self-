"""Capture d'une page, pour écrire un analyseur d'après une structure réelle.

Le système n'invente jamais la mise en page d'un site. Cet outil sert à obtenir
la page telle que le serveur la renvoie, à en lister les tableaux, et à conserver
la capture comme témoin : le jour où le site change, la comparaison avec la
capture d'origine explique immédiatement pourquoi la collecte a cessé de marcher.

La capture passe par la même politique réseau que la collecte : robots.txt
respecté, temporisation, identité annoncée. Ce n'est pas un contournement.

Exemples ::

    python -m brvm.ingestion.capture --plan
    python -m brvm.ingestion.capture --config config/config.yaml --source sikafinance
    python -m brvm.ingestion.capture --lister-tableaux data/captures/sikafinance-….html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from brvm.config.chargement import charger_configuration
from brvm.ingestion.analyseurs import resumer_tableaux
from brvm.ingestion.http import ClientHttp
from brvm.ingestion.sikafinance import plan_de_verification
from brvm.utils.erreurs import ErreurBrvm

#: Sous-dossier des captures, sous le répertoire de données configuré.
DOSSIER_CAPTURES = "captures"


def construire_analyseur_arguments() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="python -m brvm.ingestion.capture",
        description="Capture une page de source et inspecte ses tableaux.",
    )
    analyseur.add_argument("--config", type=Path, help="Fichier de configuration.")
    analyseur.add_argument("--source", help="Nom de la source à capturer.")
    analyseur.add_argument("--url", help="URL à capturer, à défaut celle de la source.")
    analyseur.add_argument("--sortie", type=Path, help="Dossier de destination.")
    analyseur.add_argument(
        "--lister-tableaux",
        type=Path,
        metavar="FICHIER",
        help="Décrit les tableaux d'une page déjà capturée.",
    )
    analyseur.add_argument(
        "--plan",
        action="store_true",
        help="Affiche la marche à suivre avant d'activer une source web.",
    )
    return analyseur


def capturer(config: Path, nom_source: str, url: str | None, sortie: Path | None) -> Path:
    """Récupère la page et l'écrit sur disque avec ses métadonnées."""
    configuration = charger_configuration(config)
    reglages = {source.nom: source for source in configuration.sources}
    if nom_source not in reglages:
        raise ErreurBrvm(
            f"Source inconnue : {nom_source!r}. Sources déclarées : " + ", ".join(sorted(reglages))
        )
    reglage = reglages[nom_source]
    adresse = url or reglage.url_base
    if not adresse:
        raise ErreurBrvm(
            f"La source {nom_source!r} n'a pas d'url_base et aucune URL n'a été passée. "
            "Renseignez l'adresse que vous avez vous-même vérifiée."
        )

    client = ClientHttp(reglage, configuration.ingestion)
    reponse = client.recuperer(adresse)

    dossier = sortie or (configuration.general.repertoire_donnees / DOSSIER_CAPTURES)
    dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fichier = dossier / f"{nom_source}-{horodatage}.html"
    fichier.write_bytes(reponse.contenu)
    fichier.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "source": nom_source,
                "url": adresse,
                "code": reponse.code,
                "horodatage_collecte": reponse.horodatage_collecte.isoformat(),
                "horodatage_donnee": (
                    reponse.horodatage_donnee.isoformat() if reponse.horodatage_donnee else None
                ),
                "depuis_cache": reponse.depuis_cache,
                "octets": len(reponse.contenu),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return fichier


def main(argv: list[str] | None = None) -> int:
    analyseur = construire_analyseur_arguments()
    arguments = analyseur.parse_args(argv)

    if arguments.plan:
        print(plan_de_verification())
        return 0

    if arguments.lister_tableaux:
        chemin = arguments.lister_tableaux
        if not chemin.is_file():
            print(f"Fichier introuvable : {chemin}", file=sys.stderr)
            return 2
        print(resumer_tableaux(chemin.read_text(encoding="utf-8", errors="replace")))
        return 0

    if not arguments.config or not arguments.source:
        analyseur.print_help()
        return 2

    try:
        fichier = capturer(arguments.config, arguments.source, arguments.url, arguments.sortie)
    except ErreurBrvm as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Page capturée : {fichier}")
    print(f"Inspectez ses tableaux : python -m brvm.ingestion.capture --lister-tableaux {fichier}")
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
