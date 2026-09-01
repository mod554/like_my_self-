"""Chargement de l'univers suivi depuis un fichier CSV.

Le référentiel des valeurs est une donnée de configuration : il n'est pas déduit
de ce que les sources publient. Une source qui cesse de coter une valeur ne doit
pas la faire disparaître du portefeuille, et une source qui en invente une ne
doit pas l'y ajouter.

Format : voir ``config/univers.exemple.csv``. Les lignes commençant par ``#``
sont des commentaires.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from brvm.domain.enums import Pays
from brvm.domain.modeles import Instrument
from brvm.utils.erreurs import ErreurConfiguration

COLONNES_OBLIGATOIRES: Final[frozenset[str]] = frozenset({"ticker", "nom", "pays"})

#: Valeurs textuelles acceptées pour la colonne `actif`.
VRAI: Final[frozenset[str]] = frozenset({"true", "vrai", "oui", "1", "o", "y", "yes"})
FAUX: Final[frozenset[str]] = frozenset({"false", "faux", "non", "0", "n", "no"})


def _lignes_utiles(contenu: str) -> list[str]:
    return [
        ligne
        for ligne in contenu.splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    ]


def _booleen(valeur: str, ligne: int) -> bool:
    normalise = valeur.strip().lower()
    if not normalise:
        return True
    if normalise in VRAI:
        return True
    if normalise in FAUX:
        return False
    raise ErreurConfiguration(
        f"Ligne {ligne} : valeur illisible pour la colonne `actif` ({valeur!r}). "
        "Attendu true ou false.",
    )


def charger_univers(chemin: Path | str) -> list[Instrument]:
    """Lit le référentiel des valeurs suivies.

    Raises:
        ErreurConfiguration: fichier absent, colonnes obligatoires manquantes, ou
            ligne invalide. Le message nomme la ligne fautive : un référentiel à
            demi chargé serait pire qu'aucun référentiel.
    """
    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        raise ErreurConfiguration(
            "Fichier d'univers introuvable. Copiez config/univers.exemple.csv puis "
            "renseignez les valeurs que vous suivez.",
            fichier=str(fichier),
        )

    utiles = _lignes_utiles(fichier.read_text(encoding="utf-8-sig"))
    if not utiles:
        raise ErreurConfiguration("Fichier d'univers vide.", fichier=str(fichier))

    lecteur = csv.DictReader(utiles)
    presentes = {nom.strip() for nom in (lecteur.fieldnames or []) if nom}
    if manquantes := COLONNES_OBLIGATOIRES - presentes:
        raise ErreurConfiguration(
            "Colonnes obligatoires absentes du fichier d'univers : "
            + ", ".join(sorted(manquantes)),
            fichier=str(fichier),
        )

    instruments: list[Instrument] = []
    vus: set[str] = set()
    for numero, brut in enumerate(lecteur, start=2):
        ticker = (brut.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        if ticker in vus:
            raise ErreurConfiguration(
                f"Ligne {numero} : la valeur {ticker} apparaît deux fois dans "
                "l'univers. Un ticker identifie une valeur et une seule.",
                fichier=str(fichier),
            )
        vus.add(ticker)
        try:
            instruments.append(
                Instrument(
                    ticker=ticker,
                    nom=(brut.get("nom") or "").strip(),
                    isin=(brut.get("isin") or "").strip() or None,
                    pays=Pays((brut.get("pays") or "").strip().upper()),
                    secteur=(brut.get("secteur") or "").strip() or None,
                    compartiment=(brut.get("compartiment") or "").strip() or None,
                    actif=_booleen(brut.get("actif") or "", numero),
                )
            )
        except ValueError as exc:
            details = (
                "; ".join(
                    f"{'.'.join(str(p) for p in detail['loc'])} : {detail['msg']}"
                    for detail in exc.errors()
                )
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            raise ErreurConfiguration(
                f"Ligne {numero} du fichier d'univers rejetée — {details}",
                fichier=str(fichier),
            ) from exc

    if not instruments:
        raise ErreurConfiguration(
            "Aucune valeur dans le fichier d'univers : il ne contient que son en-tête.",
            fichier=str(fichier),
        )
    return instruments


def tickers(instruments: list[Instrument], actifs_seulement: bool = True) -> list[str]:
    """Liste des tickers, triée, éventuellement limitée aux valeurs actives."""
    return sorted(
        instrument.ticker for instrument in instruments if instrument.actif or not actifs_seulement
    )


def par_ticker(instruments: list[Instrument]) -> dict[str, Instrument]:
    return {instrument.ticker: instrument for instrument in instruments}


def parcourir(chemin: Path | str) -> Iterator[Instrument]:
    """Itère sur l'univers sans tout garder en mémoire."""
    yield from charger_univers(chemin)
