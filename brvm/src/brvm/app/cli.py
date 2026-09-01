"""Ligne de commande d'exploitation.

Cinq commandes, une seule mécanique dessous :

* ``etat`` — recompose l'état et l'affiche, sans toucher au réseau ;
* ``collecter`` — un cycle complet : collecte, constats, alertes ;
* ``exporter`` — écrit le classeur du jour ;
* ``ordonnancer`` — laisse tourner la collecte aux heures déclarées ;
* ``verifier`` — contrôle la configuration et annonce les prochaines séances.

Toutes commencent par afficher le bandeau de fraîcheur, et toutes rendent un
code de sortie non nul si quelque chose n'a pas pu être fait — pour qu'un cron
extérieur puisse s'en apercevoir.

Exemples ::

    python -m brvm.app.cli verifier --config config/config.yaml
    python -m brvm.app.cli collecter --config config/config.yaml
    python -m brvm.app.cli exporter --config config/config.yaml --sortie rapports/
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from brvm.app.alertes import Diffuseur, construire_canaux
from brvm.app.cycle import Cycle, ResultatCycle
from brvm.app.etat import assembler
from brvm.app.export import exporter, horodater, restituer
from brvm.app.ordonnanceur import Ordonnanceur, PolitiqueOrdonnancement, seances_a_venir
from brvm.config.chargement import (
    charger_configuration,
    construire_calendrier_depuis_config,
    resume_configuration,
)
from brvm.config.modeles import Configuration
from brvm.storage.base import BaseDonnees
from brvm.utils.erreurs import ErreurBrvm
from brvm.utils.journalisation import configurer_journalisation

#: Codes de sortie. Distinguer « rien à faire » de « quelque chose a échoué »
#: est ce qui permet à un cron extérieur de réagir correctement.
SUCCES: int = 0
ECHEC: int = 1
#: Le cycle a tourné, mais une source ou un canal n'a pas répondu.
DEGRADE: int = 2


def construire_analyseur_arguments() -> argparse.ArgumentParser:
    analyseur = argparse.ArgumentParser(
        prog="python -m brvm.app.cli",
        description="Exploitation du suivi de portefeuille BRVM.",
    )
    analyseur.add_argument("--config", type=Path, required=True, help="Fichier de configuration.")
    analyseur.add_argument(
        "--seance",
        type=date.fromisoformat,
        help="Séance visée (AAAA-MM-JJ). Par défaut, la dernière disponible.",
    )
    sous = analyseur.add_subparsers(dest="commande", required=True)

    sous.add_parser("verifier", help="Contrôle la configuration et annonce les prochaines séances.")
    sous.add_parser("etat", help="Recompose et affiche l'état, sans réseau.")
    sous.add_parser("collecter", help="Cycle complet : collecte, constats, alertes.")

    export = sous.add_parser("exporter", help="Écrit le classeur de l'état courant.")
    export.add_argument("--sortie", type=Path, help="Dossier ou fichier de destination.")
    export.add_argument(
        "--texte",
        action="store_true",
        help="Produit la restitution texte au lieu du classeur (aucune dépendance).",
    )

    ordonnancer = sous.add_parser("ordonnancer", help="Collecte aux heures déclarées.")
    ordonnancer.add_argument(
        "--occurrences",
        type=int,
        default=1,
        help="Nombre de collectes à exécuter avant de rendre la main.",
    )
    return analyseur


def _preparer(chemin: Path) -> tuple[Configuration, BaseDonnees]:
    configuration = charger_configuration(chemin)
    configurer_journalisation(configuration.journalisation)
    base = BaseDonnees(configuration.general.base_donnees)
    base.ouvrir()
    return configuration, base


def _avertir(configuration: Configuration) -> None:
    for message in configuration.avertissements():
        print(f"⚠ {message}", file=sys.stderr)


def commande_verifier(configuration: Configuration) -> int:
    """Affiche ce qui est réellement appliqué, et quand la prochaine collecte part."""
    print("Configuration chargée. Voici ce qui est appliqué :")
    for cle, valeur in resume_configuration(configuration).items():
        print(f"  {cle:<28} {valeur}")

    calendrier = construire_calendrier_depuis_config(configuration)
    for message in calendrier.avertissements():
        print(f"⚠ {message}", file=sys.stderr)

    politique = PolitiqueOrdonnancement(configuration.ordonnanceur, calendrier)
    prochaines = seances_a_venir(politique, datetime.now(UTC), combien=5)
    if prochaines:
        print("\nProchaines collectes prévues :")
        for instant in prochaines:
            print(f"  {instant.isoformat()}")
    else:
        print(
            "\nAucune collecte prévue : ordonnanceur inactif, ou calendrier épuisé.",
            file=sys.stderr,
        )
    _avertir(configuration)
    return SUCCES


def commande_etat(configuration: Configuration, base: BaseDonnees, seance: date | None) -> int:
    calendrier = construire_calendrier_depuis_config(configuration)
    etat = assembler(base, configuration, calendrier, jusqu_a=seance)
    print(restituer(etat))
    return DEGRADE if etat.donnee_perimee() else SUCCES


def _cycle(configuration: Configuration, base: BaseDonnees) -> Cycle:
    calendrier = construire_calendrier_depuis_config(configuration)
    diffuseur = Diffuseur(construire_canaux(configuration.alertes, configuration.ingestion))
    return Cycle(configuration, base, calendrier, diffuseur)


def _code_de_sortie(resultat: ResultatCycle) -> int:
    if resultat.avertissements:
        return DEGRADE
    if resultat.diffusion is not None and resultat.diffusion.canaux_en_echec:
        return DEGRADE
    return SUCCES


def commande_collecter(configuration: Configuration, base: BaseDonnees, seance: date | None) -> int:
    resultat = _cycle(configuration, base).executer(seance=seance)
    print(resultat.resume())
    if resultat.alertes:
        print("\nConstats :")
        for alerte in resultat.alertes:
            print(f"  {alerte.resume()}")
    return _code_de_sortie(resultat)


def commande_exporter(
    configuration: Configuration,
    base: BaseDonnees,
    seance: date | None,
    sortie: Path | None,
    texte: bool,
) -> int:
    calendrier = construire_calendrier_depuis_config(configuration)
    etat = assembler(base, configuration, calendrier, jusqu_a=seance)

    if texte:
        contenu = restituer(etat)
        if sortie is None:
            print(contenu)
        else:
            cible = sortie / "etat.txt" if sortie.is_dir() else sortie
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_text(contenu + "\n", encoding="utf-8")
            print(f"Restitution écrite : {cible}")
        return DEGRADE if etat.donnee_perimee() else SUCCES

    base_sortie = sortie or configuration.general.repertoire_donnees / "rapports"
    cible = base_sortie / "portefeuille.xlsx" if not base_sortie.suffix else base_sortie
    chemin = exporter(etat, horodater(cible, etat.instant))
    print(etat.entete_fraicheur())
    print(f"Classeur écrit : {chemin}")
    return DEGRADE if etat.donnee_perimee() else SUCCES


def commande_ordonnancer(
    configuration: Configuration,
    base: BaseDonnees,
    occurrences: int,
    dormir: Callable[[float], None] | None = None,
) -> int:
    """Laisse tourner la collecte aux heures déclarées.

    Le sommeil est injectable, comme partout ailleurs dans le système : sans
    cela, vérifier l'enchaînement des séances demanderait d'attendre une vraie
    minute à chaque exécution des tests.
    """
    calendrier = construire_calendrier_depuis_config(configuration)
    cycle = _cycle(configuration, base)
    ordonnanceur = Ordonnanceur(
        configuration, calendrier, action=lambda jour: cycle.executer(seance=jour)
    )
    if not configuration.ordonnanceur.actif:
        print(
            "Ordonnanceur inactif en configuration : rien ne sera collecté.",
            file=sys.stderr,
        )
        return DEGRADE

    prochaines = seances_a_venir(ordonnanceur.politique, datetime.now(UTC), combien=occurrences)
    for instant in prochaines:
        print(f"Collecte prévue le {instant.isoformat()}")
    if not prochaines:
        print("Aucune séance à venir dans l'horizon exploré.", file=sys.stderr)
        return DEGRADE

    resultats = ordonnanceur.boucle(datetime.now(UTC), occurrences=occurrences, dormir=dormir)
    for verdict in resultats:
        print(f"{verdict.instant.isoformat()} — {verdict.motif}")
    return SUCCES if resultats else DEGRADE


def principal(arguments: list[str] | None = None) -> int:
    options = construire_analyseur_arguments().parse_args(arguments)
    try:
        configuration, base = _preparer(options.config)
    except ErreurBrvm as exc:
        print(str(exc), file=sys.stderr)
        return ECHEC

    try:
        match options.commande:
            case "verifier":
                return commande_verifier(configuration)
            case "etat":
                return commande_etat(configuration, base, options.seance)
            case "collecter":
                return commande_collecter(configuration, base, options.seance)
            case "exporter":
                return commande_exporter(
                    configuration, base, options.seance, options.sortie, options.texte
                )
            case "ordonnancer":
                return commande_ordonnancer(configuration, base, options.occurrences)
            case _:  # pragma: no cover - argparse impose le choix
                return ECHEC
    except ErreurBrvm as exc:
        print(str(exc), file=sys.stderr)
        return ECHEC
    finally:
        base.fermer()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(principal())
