"""Référentiel des données fondamentales, renseigné par vous.

Aucune de ces valeurs n'est déductible d'une série de cours. Le dividende par
action, le résultat net par action, les capitaux propres : cela se lit dans un
rapport annuel ou un communiqué de résultats, et nulle part ailleurs.

Le système ne les invente donc pas. Tant que ce référentiel est vide, tout score
de long terme refuse de se calculer et dit pourquoi — plutôt que de classer sur
le seul prix un horizon qui, par définition, ne s'y résume pas.

Format : voir ``config/fondamentaux.exemple.csv``. Une ligne par valeur et par
exercice ; le système retient le plus récent et signale son ancienneté.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Final

from brvm.domain.monnaie import PRECISION_INTERNE
from brvm.utils.erreurs import ErreurConfiguration

COLONNES_OBLIGATOIRES: Final[frozenset[str]] = frozenset({"ticker", "exercice", "source"})

#: Colonnes chiffrées. Toutes facultatives : une donnée absente reste absente,
#: et le ratio qui en dépend refuse de se calculer.
COLONNES_CHIFFREES: Final[tuple[str, ...]] = (
    "dividende_par_action",
    "resultat_net_par_action",
    "capitaux_propres_par_action",
    "nombre_actions",
)

#: Au-delà de cette ancienneté, un exercice est signalé comme dépassé. Deux ans :
#: un bilan de 2023 ne décrit plus une société en 2026, et s'en servir sans le
#: dire produirait un rendement calculé sur un dividende qui n'existe plus.
EXERCICES_AVANT_PEREMPTION: Final[int] = 2


@dataclass(frozen=True, slots=True)
class Fondamentaux:
    """Les comptes d'une valeur pour un exercice, tels que VOUS les avez relevés."""

    ticker: str
    exercice: int
    #: D'où vient la donnée. Obligatoire : un chiffre sans source n'est pas auditable.
    source: str
    dividende_par_action: int | None = None
    resultat_net_par_action: int | None = None
    capitaux_propres_par_action: int | None = None
    nombre_actions: int | None = None
    date_releve: date | None = None
    commentaire: str | None = None

    def anciennete(self, annee_courante: int) -> int:
        return annee_courante - self.exercice

    def perime(self, annee_courante: int) -> bool:
        return self.anciennete(annee_courante) > EXERCICES_AVANT_PEREMPTION


@dataclass(frozen=True, slots=True)
class Ratios:
    """Ratios calculés contre un cours. Chacun absent si son entrée l'est."""

    ticker: str
    cours: int
    exercice: int
    #: Dividende rapporté au cours. Fraction, pas pourcentage.
    rendement_dividende: Decimal | None = None
    #: Cours rapporté au bénéfice par action.
    per: Decimal | None = None
    #: Cours rapporté aux capitaux propres par action.
    price_book: Decimal | None = None
    anciennete_exercice: int = 0
    avertissements: tuple[str, ...] = ()

    @property
    def exploitable(self) -> bool:
        """Vrai si au moins un ratio a pu être calculé."""
        return any(
            valeur is not None for valeur in (self.rendement_dividende, self.per, self.price_book)
        )


def calculer_ratios(fondamentaux: Fondamentaux, cours: int, annee_courante: int) -> Ratios:
    """Rapporte les comptes au cours du jour.

    Un dénominateur nul ou négatif ne donne pas un ratio infini : il donne
    l'absence de ratio, avec la raison. Un PER calculé sur une perte n'a pas de
    sens et se lirait pourtant comme un chiffre.
    """
    avertissements: list[str] = []
    rendement = per = price_book = None

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        if fondamentaux.dividende_par_action is not None and cours > 0:
            rendement = Decimal(fondamentaux.dividende_par_action) / Decimal(cours)

        benefice = fondamentaux.resultat_net_par_action
        if benefice is not None:
            if benefice > 0:
                per = Decimal(cours) / Decimal(benefice)
            else:
                avertissements.append(
                    "Résultat par action nul ou négatif : aucun PER n'est calculé. "
                    "Un PER sur une perte se lirait comme une valorisation."
                )

        capitaux = fondamentaux.capitaux_propres_par_action
        if capitaux is not None:
            if capitaux > 0:
                price_book = Decimal(cours) / Decimal(capitaux)
            else:
                avertissements.append(
                    "Capitaux propres par action nuls ou négatifs : aucun ratio "
                    "cours/actif net n'est calculé."
                )

    anciennete = fondamentaux.anciennete(annee_courante)
    if fondamentaux.perime(annee_courante):
        avertissements.append(
            f"Exercice {fondamentaux.exercice}, soit {anciennete} an(s) d'ancienneté. "
            "Ces ratios décrivent une société telle qu'elle était, pas telle "
            "qu'elle est."
        )

    return Ratios(
        ticker=fondamentaux.ticker,
        cours=cours,
        exercice=fondamentaux.exercice,
        rendement_dividende=rendement,
        per=per,
        price_book=price_book,
        anciennete_exercice=anciennete,
        avertissements=tuple(avertissements),
    )


def regularite_dividende(exercices: Sequence[Fondamentaux]) -> tuple[int, int]:
    """Exercices avec dividende, sur exercices renseignés.

    C'est la seule mesure de régularité honnête ici : elle ne dit pas qu'un
    dividende sera versé, elle dit combien de fois il l'a été parmi ce que vous
    avez saisi. Deux exercices renseignés sur dix ans ne prouvent rien, et le
    dénominateur le montre.
    """
    renseignes = [f for f in exercices if f.dividende_par_action is not None]
    verses = [f for f in renseignes if (f.dividende_par_action or 0) > 0]
    return len(verses), len(renseignes)


def _entier(valeur: str, champ: str, ligne: int) -> int | None:
    texte = valeur.strip().replace(" ", "").replace(" ", "")
    if not texte:
        return None
    try:
        nombre = float(texte.replace(",", "."))
    except ValueError as exc:
        raise ErreurConfiguration(
            f"Ligne {ligne} : {champ} illisible ({valeur!r}). Attendu un entier en XOF."
        ) from exc
    if nombre != int(nombre):
        raise ErreurConfiguration(
            f"Ligne {ligne} : {champ} comporte des décimales ({valeur!r}). "
            "Le XOF ne circule pas en centimes."
        )
    return int(nombre)


def charger_fondamentaux(chemin: Path | str) -> dict[str, list[Fondamentaux]]:
    """Lit le référentiel, groupé par valeur et trié du plus récent au plus ancien.

    Un fichier absent n'est pas une erreur : c'est l'état initial du système, et
    les scores fondamentaux s'abstiendront simplement de se calculer.
    """
    fichier = Path(chemin).expanduser()
    if not fichier.is_file():
        return {}

    utiles = [
        ligne
        for ligne in fichier.read_text(encoding="utf-8-sig").splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    ]
    if not utiles:
        return {}

    lecteur = csv.DictReader(utiles)
    presentes = {nom.strip() for nom in (lecteur.fieldnames or []) if nom}
    if manquantes := COLONNES_OBLIGATOIRES - presentes:
        raise ErreurConfiguration(
            "Colonnes obligatoires absentes du fichier de fondamentaux : "
            + ", ".join(sorted(manquantes)),
            fichier=str(fichier),
        )

    par_valeur: dict[str, list[Fondamentaux]] = {}
    vus: set[tuple[str, int]] = set()
    for numero, brut in enumerate(lecteur, start=2):
        ticker = (brut.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        exercice_texte = (brut.get("exercice") or "").strip()
        if not exercice_texte.isdigit():
            raise ErreurConfiguration(
                f"Ligne {numero} : exercice illisible ({exercice_texte!r}). "
                "Attendu une année, par exemple 2025.",
                fichier=str(fichier),
            )
        exercice = int(exercice_texte)
        if (ticker, exercice) in vus:
            raise ErreurConfiguration(
                f"Ligne {numero} : {ticker} exercice {exercice} figure deux fois. "
                "Un exercice n'a qu'un jeu de comptes.",
                fichier=str(fichier),
            )
        vus.add((ticker, exercice))

        source = (brut.get("source") or "").strip()
        if not source:
            raise ErreurConfiguration(
                f"Ligne {numero} : la colonne `source` est vide. Un chiffre sans "
                "provenance n'est pas auditable — indiquez le rapport annuel, le "
                "communiqué ou l'avis dont il vient.",
                fichier=str(fichier),
            )

        chiffres = {
            champ: _entier(brut.get(champ) or "", champ, numero) for champ in COLONNES_CHIFFREES
        }
        releve = (brut.get("date_releve") or "").strip()
        par_valeur.setdefault(ticker, []).append(
            Fondamentaux(
                ticker=ticker,
                exercice=exercice,
                source=source,
                date_releve=date.fromisoformat(releve) if releve else None,
                commentaire=(brut.get("commentaire") or "").strip() or None,
                **chiffres,
            )
        )

    for exercices in par_valeur.values():
        exercices.sort(key=lambda f: f.exercice, reverse=True)
    return par_valeur


def dernier_exercice(
    referentiel: Mapping[str, Iterable[Fondamentaux]], ticker: str
) -> Fondamentaux | None:
    exercices = list(referentiel.get(ticker, ()))
    return exercices[0] if exercices else None
