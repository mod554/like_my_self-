"""Chargement et validation du fichier de configuration.

Le rôle de ce module est de transformer une ``ValidationError`` pydantic — utile
mais aride — en un message qui dit à l'utilisateur *quel* paramètre manque et
*où* aller le chercher. Un barème de frais non renseigné doit produire une phrase
qui renvoie à la grille tarifaire de la SGI, pas un ``Field required``.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances, construire_calendrier
from brvm.domain.enums import Pays
from brvm.utils.erreurs import ErreurConfiguration

#: Chemins de la configuration exprimés relativement au fichier de configuration.
CHEMINS_A_RESOUDRE: Final[tuple[tuple[str, ...], ...]] = (
    ("general", "repertoire_donnees"),
    ("general", "base_donnees"),
    ("marche", "fichier_univers"),
    ("calendrier", "fichier_feries"),
    ("journalisation", "fichier"),
)

#: Explications attachées aux champs que le système s'interdit de deviner.
#: La clé est un motif ``fnmatch`` appliqué au chemin pointé du champ fautif.
AIDES: Final[dict[str, str]] = {
    "frais.lignes.*.taux": (
        "Relevez ce taux sur la grille tarifaire de votre SGI. Le système ne fournit "
        "aucune valeur par défaut et n'invente aucun barème."
    ),
    "frais.lignes.*.montant_fixe": (
        "Montant forfaitaire à relever sur la grille tarifaire de votre SGI."
    ),
    "frais.lignes*": (
        "Recopiez ligne à ligne le barème de votre SGI : commission de courtage, "
        "commission de l'entreprise de marché, commission du dépositaire central, "
        "TVA applicable, frais fixes et minimum de perception."
    ),
    "frais.source_bareme": (
        "Indiquez d'où vient le barème (nom de la SGI et date de la grille) : un barème "
        "sans provenance n'est pas auditable."
    ),
    "fiscalite.retenue_dividendes": (
        "Taux de retenue à la source sur les dividendes applicable à votre résidence "
        "fiscale. À relever dans les textes en vigueur ou sur un avis de paiement."
    ),
    "fiscalite.plus_values*": (
        "Régime des plus-values de cession pour votre pays de résidence fiscale."
    ),
    "fiscalite.source_reference": (
        "Indiquez le texte ou le document d'où les taux de fiscalité sont tirés."
    ),
    "marche.seuil_variation_journaliere": (
        "Seuil réglementaire de variation d'un cours sur une séance, exprimé en fraction "
        "(par exemple 0.075 pour 7,5 %). À relever dans les textes en vigueur de "
        "l'entreprise de marché : un seuil inventé fausserait la détection d'anomalies."
    ),
    "sources.*.url_base": (
        "Adresse de la source, à vérifier vous-même. Le système ne devine aucune URL et "
        "aucune structure de page qu'il n'a pas constatée."
    ),
    "calendrier.*": (
        "Le calendrier de séances est une donnée de configuration : renseignez la période "
        "de couverture et le fichier des jours fériés UEMOA."
    ),
}


def _aide_pour(chemin: str) -> str | None:
    for motif, texte in AIDES.items():
        if fnmatch.fnmatch(chemin, motif):
            return texte
    return None


def _chemin_pointe(localisation: Iterable[Any]) -> str:
    return ".".join(str(element) for element in localisation)


#: Message substitué lorsqu'un paramètre obligatoire est simplement vide : le
#: libellé technique de pydantic (« Input should be a valid boolean ») n'aide pas.
MESSAGE_MANQUANT: Final[str] = "paramètre obligatoire non renseigné (laissé vide dans le fichier)"


def _message_lisible(detail: Mapping[str, Any]) -> str:
    """Traduit l'erreur pydantic en formulation utile à qui remplit le fichier."""
    if detail.get("type") == "missing" or detail.get("input", ...) is None:
        return MESSAGE_MANQUANT
    message = str(detail.get("msg", "valeur invalide"))
    # Les messages de nos propres validateurs sont déjà rédigés pour l'utilisateur.
    return message.removeprefix("Value error, ")


def _erreurs_utiles(erreur: ValidationError) -> list[tuple[str, str]]:
    """Écarte les erreurs de cascade (un parent invalide parce qu'un enfant l'est)."""
    bruts = [
        (_chemin_pointe(detail["loc"]), _message_lisible(detail)) for detail in erreur.errors()
    ]
    chemins = {chemin for chemin, _ in bruts}
    return [
        (chemin, message)
        for chemin, message in bruts
        if not any(autre.startswith(f"{chemin}.") for autre in chemins)
    ]


def _formater_erreurs(erreur: ValidationError, fichier: Path) -> str:
    utiles = _erreurs_utiles(erreur)
    lignes = [
        f"Configuration invalide : {fichier}",
        f"{len(utiles)} paramètre(s) à corriger.",
        "",
    ]
    for chemin, message in utiles:
        lignes.append(f"  • {chemin} : {message}")
        aide = _aide_pour(chemin)
        if aide:
            lignes.append(f"      → {aide}")
    lignes.append("")
    lignes.append(
        "Aucune valeur par défaut n'est substituée : le système refuse de démarrer "
        "plutôt que de calculer sur un paramètre inventé."
    )
    return "\n".join(lignes)


def _lire_yaml(chemin: Path) -> dict[str, Any]:
    if not chemin.is_file():
        raise ErreurConfiguration(
            "Fichier de configuration introuvable. Copiez config/config.exemple.yaml "
            "puis renseignez les champs obligatoires.",
            fichier=str(chemin),
        )
    try:
        contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ErreurConfiguration(
            f"Fichier de configuration illisible (YAML invalide) : {exc}",
            fichier=str(chemin),
        ) from exc
    if contenu is None:
        raise ErreurConfiguration("Fichier de configuration vide.", fichier=str(chemin))
    if not isinstance(contenu, dict):
        raise ErreurConfiguration(
            "Le fichier de configuration doit contenir un dictionnaire à sa racine.",
            fichier=str(chemin),
        )
    return contenu


def _resoudre_chemins(brut: dict[str, Any], racine: Path) -> dict[str, Any]:
    """Rend absolus les chemins relatifs, par rapport au dossier de configuration."""

    def absolu(valeur: Any) -> Any:
        if not isinstance(valeur, str):
            return valeur
        chemin = Path(valeur).expanduser()
        return str(chemin if chemin.is_absolute() else (racine / chemin).resolve())

    for section, cle in CHEMINS_A_RESOUDRE:
        bloc = brut.get(section)
        if isinstance(bloc, dict) and cle in bloc:
            bloc[cle] = absolu(bloc[cle])

    sources = brut.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict) and source.get("chemin_fichier") is not None:
                source["chemin_fichier"] = absolu(source["chemin_fichier"])
    return brut


def charger_configuration(chemin: Path | str) -> Configuration:
    """Charge, valide et renvoie la configuration.

    Raises:
        ErreurConfiguration: fichier absent, illisible, ou paramètre obligatoire
            manquant. Le message énumère tous les champs fautifs d'un coup.
    """
    fichier = Path(chemin).expanduser().resolve()
    brut = _resoudre_chemins(_lire_yaml(fichier), fichier.parent)
    try:
        return Configuration.model_validate(brut)
    except ValidationError as exc:
        raise ErreurConfiguration(_formater_erreurs(exc, fichier)) from exc


# ------------------------------------------------------------------ jours fériés


def charger_jours_feries(chemin: Path | str) -> dict[Pays, frozenset[date]]:
    """Charge le fichier des jours fériés, indexé par code pays UEMOA.

    Format attendu ::

        CI:
          - 2026-01-01
        SN:
          - 2026-04-04

    Un fichier absent est une erreur : le système ne suppose jamais un calendrier.
    """
    fichier = Path(chemin).expanduser().resolve()
    if not fichier.is_file():
        raise ErreurConfiguration(
            "Fichier de jours fériés introuvable. Le calendrier de séances est une donnée "
            "de configuration : renseignez les jours fériés des pays concernés.",
            fichier=str(fichier),
        )
    try:
        contenu = yaml.safe_load(fichier.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ErreurConfiguration(
            f"Fichier de jours fériés illisible (YAML invalide) : {exc}",
            fichier=str(fichier),
        ) from exc
    if not isinstance(contenu, dict):
        raise ErreurConfiguration(
            "Le fichier de jours fériés doit associer un code pays à une liste de dates.",
            fichier=str(fichier),
        )

    codes_connus = {pays.value: pays for pays in Pays}
    resultat: dict[Pays, frozenset[date]] = {}
    for code, jours in contenu.items():
        code_normalise = str(code).strip().upper()
        if code_normalise not in codes_connus:
            raise ErreurConfiguration(
                f"Code pays inconnu dans le fichier de jours fériés : {code!r}. "
                f"Attendu parmi {sorted(codes_connus)}.",
                fichier=str(fichier),
            )
        if jours is None:
            resultat[codes_connus[code_normalise]] = frozenset()
            continue
        if not isinstance(jours, list):
            raise ErreurConfiguration(
                f"Les jours fériés de {code_normalise} doivent être une liste de dates.",
                fichier=str(fichier),
            )
        dates: set[date] = set()
        for jour in jours:
            if not isinstance(jour, date):
                raise ErreurConfiguration(
                    f"Date de jour férié invalide pour {code_normalise} : {jour!r}. "
                    "Format attendu AAAA-MM-JJ.",
                    fichier=str(fichier),
                )
            dates.add(jour)
        resultat[codes_connus[code_normalise]] = frozenset(dates)
    return resultat


def construire_calendrier_depuis_config(configuration: Configuration) -> CalendrierSeances:
    """Assemble le calendrier de séances à partir de la configuration validée."""
    feries = charger_jours_feries(configuration.calendrier.fichier_feries)
    return construire_calendrier(
        pays_place=configuration.marche.pays_place,
        couverture_debut=configuration.calendrier.couverture_debut,
        couverture_fin=configuration.calendrier.couverture_fin,
        jours_ouvres=configuration.calendrier.jours_ouvres,
        feries_par_pays=feries,
        fermetures_exceptionnelles=configuration.calendrier.fermetures_exceptionnelles,
    )


def resume_configuration(configuration: Configuration) -> Mapping[str, str]:
    """Résumé affichable au démarrage, pour vérifier ce qui est réellement appliqué."""
    return {
        "devise": configuration.general.devise.value,
        "méthode de valorisation": configuration.general.methode_valorisation.value,
        "mode d'arrondi": configuration.general.mode_arrondi.value,
        "place de cotation": configuration.marche.pays_place.value,
        "résidence fiscale": configuration.fiscalite.pays_residence.value,
        "barème de frais": configuration.frais.source_bareme,
        "lignes de frais": str(len(configuration.frais.lignes)),
        "sources actives": ", ".join(source.nom for source in configuration.sources_actives())
        or "aucune",
        "base de données": str(configuration.general.base_donnees),
    }
