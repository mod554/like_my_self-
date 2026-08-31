"""Conversion d'une ligne brute en cotation validée.

Tous les connecteurs, quelle que soit leur source, passent par ici. Une seule
implémentation du chemin « champs bruts → :class:`Cotation` » signifie une seule
définition de ce qu'est une donnée acceptable, et un seul endroit à corriger.

Le vocabulaire de champs est celui du système (voir
:mod:`brvm.ingestion.fichier` pour le format documenté) ; c'est au connecteur de
traduire le vocabulaire de sa source vers celui-ci.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from brvm.config.modeles import Configuration
from brvm.domain.enums import StatutSeance
from brvm.domain.modeles import Cotation
from brvm.ingestion.base import LigneCollectee
from brvm.utils.erreurs import ErreurSource

#: Nom de champ brut → nom de champ du modèle.
CHAMPS: Final[Mapping[str, str]] = {
    "ticker": "ticker",
    "date_seance": "date_seance",
    "statut_seance": "statut_seance",
    "ouverture": "ouverture",
    "plus_haut": "plus_haut",
    "plus_bas": "plus_bas",
    "cloture": "cloture",
    "cours_precedent": "cours_precedent",
    "volume_titres": "volume_titres",
    "volume_xof": "volume_xof",
    "nb_transactions": "nb_transactions",
    "limite_achat": "meilleure_limite_achat",
    "limite_vente": "meilleure_limite_vente",
    "commentaire": "commentaire",
}

CHAMPS_OBLIGATOIRES: Final[frozenset[str]] = frozenset({"ticker", "date_seance"})

CHAMPS_ENTIERS: Final[frozenset[str]] = frozenset(
    {
        "ouverture",
        "plus_haut",
        "plus_bas",
        "cloture",
        "cours_precedent",
        "volume_titres",
        "volume_xof",
        "nb_transactions",
        "meilleure_limite_achat",
        "meilleure_limite_vente",
    }
)

#: Caractères tolérés comme séparateurs de milliers dans les exports et les pages
#: web : espace ordinaire, espace insécable, espace fine insécable, apostrophe.
SEPARATEURS_MILLIERS: Final[str] = "   '"


def nettoyer(valeur: object) -> str:
    """Normalise une cellule ou un fragment de page en texte comparable."""
    if valeur is None:
        return ""
    return str(valeur).replace(" ", " ").strip()


def entier_xof(valeur: str, champ: str) -> int | None:
    """Convertit un texte en entier XOF.

    Une valeur vide signifie « non publié » et devient ``None`` — jamais zéro :
    sur ce marché, confondre « pas de cours publié » et « cours à zéro » fausse
    tout ce qui suit.
    """
    texte = valeur
    for caractere in SEPARATEURS_MILLIERS:
        texte = texte.replace(caractere, "")
    texte = texte.replace(",", ".")
    if not texte or texte in {"-", "—", "ND", "N/D", "n/d"}:
        return None
    try:
        nombre = float(texte)
    except ValueError as exc:
        raise ValueError(f"{champ} : « {valeur} » n'est pas un nombre.") from exc
    if nombre != int(nombre):
        raise ValueError(
            f"{champ} : « {valeur} » comporte des décimales. Le XOF ne circule pas en "
            "centimes ; une valeur décimale signale une mauvaise colonne ou une "
            "conversion de devise implicite."
        )
    return int(nombre)


class ConvertisseurCotation:
    """Transforme des champs bruts en :class:`Cotation`, ou explique pourquoi non."""

    def __init__(self, nom_source: str, configuration: Configuration) -> None:
        self.nom_source = nom_source
        self.configuration = configuration

    def convertir(
        self,
        brut: Mapping[str, Any],
        collecte: datetime,
        horodatage_donnee: datetime | None = None,
        repere: str | None = None,
    ) -> tuple[LigneCollectee, str | None]:
        """Convertit une ligne.

        Args:
            brut: champs bruts, dans le vocabulaire du système.
            collecte: instant de la collecte.
            horodatage_donnee: date annoncée par la source. À défaut, la clôture
                de la séance dans le fuseau configuré est retenue.
            repere: identifiant de la ligne dans sa source (numéro, ancre HTML),
                pour que le message d'erreur soit localisable.

        Returns:
            La ligne collectée et, le cas échéant, un avertissement non bloquant.
        """
        charge: dict[str, Any] = {cle: nettoyer(val) for cle, val in brut.items()}
        if repere:
            charge["repere"] = repere
        avertissement: str | None = None

        try:
            champs = self._champs(brut)
            statut, avertissement = self._statut(brut, champs, repere)
            champs["statut_seance"] = statut
            horodatage = horodatage_donnee or self._cloture_de_seance(champs["date_seance"])
            cotation = Cotation(
                source=self.nom_source,
                horodatage_donnee=horodatage,
                # Une donnée ne peut pas avoir été collectée avant d'exister : si la
                # source annonce une date postérieure à notre collecte, c'est la
                # collecte qui est recalée, et l'écart sera vu comme un âge négatif.
                horodatage_collecte=max(horodatage, collecte),
                **champs,
            )
        except (ValueError, ValidationError) as exc:
            return LigneCollectee(brut=charge, erreur=self._message(repere, exc)), None
        return LigneCollectee(brut=charge, cotation=cotation), avertissement

    def _champs(self, brut: Mapping[str, Any]) -> dict[str, Any]:
        champs: dict[str, Any] = {}
        for nom_brut, champ in CHAMPS.items():
            valeur = nettoyer(brut.get(nom_brut))
            if champ in CHAMPS_ENTIERS:
                champs[champ] = entier_xof(valeur, nom_brut)
            elif valeur:
                champs[champ] = valeur
        manquants = CHAMPS_OBLIGATOIRES - {
            nom for nom in CHAMPS_OBLIGATOIRES if nettoyer(brut.get(nom))
        }
        if manquants:
            raise ValueError("champ obligatoire absent : " + ", ".join(sorted(manquants)))
        if champs.get("volume_titres") is None:
            champs["volume_titres"] = 0
        return champs

    def _statut(
        self, brut: Mapping[str, Any], champs: dict[str, Any], repere: str | None
    ) -> tuple[str, str | None]:
        """Détermine le statut de séance sans jamais le supposer à tort.

        Un statut déclaré fait foi. Sinon, un volume strictement positif prouve
        qu'il y a eu des échanges (``COTEE``). Un volume nul ou absent ne prouve
        **rien** — ni séance sans transaction, ni séance cotée — et donne
        ``INCONNU``, qui n'alimentera aucun indicateur.
        """
        declare = nettoyer(brut.get("statut_seance")).upper()
        if declare:
            return declare, None
        if champs.get("volume_titres", 0) > 0:
            return StatutSeance.COTEE.value, None
        localisation = f" ({repere})" if repere else ""
        return (
            StatutSeance.INCONNU.value,
            f"Statut de séance non renseigné et volume nul{localisation} : statut fixé à "
            "INCONNU. Le système ne suppose pas qu'il s'agit d'une séance sans "
            "transaction — un volume absent n'est pas un volume nul.",
        )

    def _cloture_de_seance(self, jour_texte: str) -> datetime:
        jour = date.fromisoformat(jour_texte)
        heures, minutes = self.configuration.marche.heure_cloture_locale.split(":")
        return datetime.combine(
            jour, time(int(heures), int(minutes)), tzinfo=self._fuseau()
        ).astimezone(UTC)

    def _fuseau(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.configuration.general.fuseau_horaire)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ErreurSource(
                f"Fuseau horaire inconnu : {self.configuration.general.fuseau_horaire!r}.",
                source=self.nom_source,
            ) from exc

    @staticmethod
    def _message(repere: str | None, exc: Exception) -> str:
        localisation = f"{repere} " if repere else ""
        if isinstance(exc, ValidationError):
            details = "; ".join(
                f"{'.'.join(str(p) for p in detail['loc']) or 'ligne'} : {detail['msg']}"
                for detail in exc.errors()
            )
            return f"{localisation}rejetée — {details}".strip()
        return f"{localisation}rejetée — {exc}".strip()
