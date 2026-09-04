"""Connecteur d'API JSON : politique réseau partagée, schéma déclaré.

Même partage des rôles que pour le connecteur web, transposé à une API :

* **ce module** sait interroger une API correctement — robots.txt, temporisation,
  reprises, cache, mode dégradé —, parcourir la réponse selon le schéma déclaré,
  et confier la conversion au chemin commun ;
* **la configuration** dit où se trouve la liste d'enregistrements, à quel champ
  du système correspond chaque champ de la réponse, et quel corps envoyer. Cette
  connaissance ne s'écrit qu'après avoir observé une vraie réponse.

Aucun schéma n'est fourni « par défaut ». Sans bloc ``api``, la source refuse de
collecter : une correspondance devinée produirait des cours faux en silence.

Deux traits propres aux API d'historique gouvernent la conception :

* elles répondent **par valeur**, pas par séance : il faut donc un référentiel de
  l'univers (``marche.fichier_univers``) et une requête par valeur. Une valeur
  injoignable n'interrompt pas la collecte des autres ;
* elles répondent **par fenêtre de dates**, pas pour un jour. Par défaut, seule
  la séance visée est retenue ; le reste de la fenêtre n'est écrit que si
  ``api.historique`` le demande explicitement, parce qu'un rattrapage fait
  remonter des barres anciennes que le contrôle de fraîcheur signalera.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from brvm.config.modeles import ConfigApi, ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte
from brvm.domain.modeles import Instrument
from brvm.ingestion.base import DataSource, LigneCollectee, ResultatCollecte, statut_depuis_lignes
from brvm.ingestion.conversion import ConvertisseurCotation
from brvm.ingestion.http import ClientHttp
from brvm.ingestion.univers import charger_univers
from brvm.utils.erreurs import ErreurSource
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("ingestion.api")


def _substituer(gabarit: str, jetons: Mapping[str, str], ou: str) -> str:
    """Remplace les jetons d'un gabarit de configuration, ou dit lequel est inconnu."""
    try:
        return gabarit.format(**jetons)
    except (KeyError, IndexError, ValueError) as exc:
        raise ErreurSource(
            f"Gabarit invalide dans {ou} : {gabarit!r} ({exc}). Jetons acceptés : "
            + ", ".join(f"{{{nom}}}" for nom in sorted(jetons))
        ) from exc


def _chemin(charge: Any, chemin: str) -> Any:
    """Descend dans une réponse JSON selon un chemin pointé.

    Un segment entièrement numérique indexe une liste. Un chemin vide renvoie la
    charge telle quelle, pour une API qui répond directement par une liste.
    """
    noeud = charge
    for segment in (morceau for morceau in chemin.split(".") if morceau):
        if isinstance(noeud, Mapping):
            if segment not in noeud:
                raise ErreurSource(
                    f"Chemin {chemin!r} introuvable dans la réponse : la clé "
                    f"{segment!r} est absente. Clés disponibles : "
                    + (", ".join(sorted(map(str, noeud))) or "aucune")
                )
            noeud = noeud[segment]
        elif isinstance(noeud, list) and segment.isdigit():
            position = int(segment)
            if position >= len(noeud):
                raise ErreurSource(
                    f"Chemin {chemin!r} introuvable : la liste ne compte que "
                    f"{len(noeud)} élément(s)."
                )
            noeud = noeud[position]
        else:
            raise ErreurSource(
                f"Chemin {chemin!r} inapplicable : le segment {segment!r} porte sur "
                f"une valeur de type {type(noeud).__name__}, qui ne se parcourt pas."
            )
    return noeud


def _enregistrements(charge: Any, chemin: str) -> list[Mapping[str, Any]]:
    """Extrait la liste d'enregistrements, ou dit précisément ce qui a été trouvé."""
    noeud = _chemin(charge, chemin)
    if noeud is None:
        return []
    if not isinstance(noeud, list):
        raise ErreurSource(
            f"Le chemin {chemin!r} ne mène pas à une liste mais à un "
            f"{type(noeud).__name__}. Vérifiez `api.chemin_liste` sur une réponse réelle."
        )
    for position, element in enumerate(noeud, start=1):
        if not isinstance(element, Mapping):
            raise ErreurSource(
                f"L'élément {position} de la liste est un {type(element).__name__} et non "
                "un objet : le schéma déclaré ne correspond pas à cette réponse."
            )
    return list(noeud)


class SourceApiJson(DataSource):
    """Source interrogée par API JSON, valeur par valeur, sur une fenêtre de dates."""

    def __init__(
        self,
        source: ConfigSource,
        configuration: Configuration,
        instruments: Sequence[Instrument] | None = None,
        client: ClientHttp | None = None,
    ) -> None:
        if source.url_base is None:
            raise ErreurSource(
                f"La source {source.nom!r} est de type api_json mais aucune url_base "
                "n'est renseignée. Renseignez l'adresse que vous avez vous-même vérifiée.",
                source=source.nom,
            )
        if source.api is None:
            raise ErreurSource(
                f"La source {source.nom!r} est de type api_json mais aucun bloc `api` "
                "ne décrit sa réponse. Observez une réponse réelle, puis déclarez "
                "`chemin_liste`, `corps` et `champs`. Le système ne devine aucun schéma.",
                source=source.nom,
            )
        self.nom = source.nom
        self.source = source
        self.api: ConfigApi = source.api
        self.configuration = configuration
        self.client = client or ClientHttp(source, configuration.ingestion)
        self._convertisseur = ConvertisseurCotation(self.nom, configuration)
        self._instruments = list(instruments) if instruments is not None else None

    # ------------------------------------------------------------------ univers

    @property
    def instruments(self) -> list[Instrument]:
        """Univers interrogé, chargé une seule fois depuis le référentiel."""
        if self._instruments is None:
            self._instruments = [
                instrument
                for instrument in charger_univers(self.configuration.marche.fichier_univers)
                if instrument.actif
            ]
        return self._instruments

    def ticker_source(self, instrument: Instrument) -> str:
        """Identifiant attendu par la source, selon le gabarit déclaré."""
        return _substituer(
            self.api.gabarit_ticker,
            {
                "ticker": instrument.ticker,
                "pays": instrument.pays.value,
                "pays_bas": instrument.pays.value.lower(),
            },
            "api.gabarit_ticker",
        )

    # ----------------------------------------------------------------- collecte

    def disponible(self) -> bool:
        if self.source.url_base is None:
            return False
        try:
            return self.client.autorise(self.source.url_base)
        except ErreurSource:
            return False

    def collecter(self, jour: date | None = None) -> ResultatCollecte:
        debut = self.maintenant()
        url = self.source.url_base
        assert url is not None  # garanti par le constructeur

        fin = jour or datetime.now(UTC).date()
        depart = fin - timedelta(days=self.api.fenetre_jours)

        lignes: list[LigneCollectee] = []
        avertissements: list[str] = []
        depuis_cache = False
        cache_perime = False
        interroges = 0
        en_echec = 0

        for instrument in self.instruments:
            interroges += 1
            identifiant = self.ticker_source(instrument)
            try:
                reponse = self.client.recuperer(
                    url,
                    corps_json=self._corps(identifiant, depart, fin),
                    entetes=self._entetes(identifiant),
                )
            except ErreurSource as exc:
                en_echec += 1
                avertissements.append(f"{instrument.ticker} : {exc}")
                continue

            depuis_cache = depuis_cache or reponse.depuis_cache
            cache_perime = cache_perime or reponse.cache_perime
            try:
                brutes = self._extraire(reponse.texte(), instrument, jour)
            except ErreurSource as exc:
                en_echec += 1
                avertissements.append(f"{instrument.ticker} : {exc}")
                continue

            for position, brut in enumerate(brutes, start=1):
                ligne, avertissement = self._convertisseur.convertir(
                    brut,
                    collecte=reponse.horodatage_collecte,
                    # Une API d'historique renvoie des barres de séances passées :
                    # l'horodatage de la donnée est celui de la séance, pas celui
                    # des en-têtes de la réponse, qui daterait tout du jour même.
                    horodatage_donnee=None,
                    repere=f"{instrument.ticker} entrée {position}",
                )
                lignes.append(ligne)
                if avertissement:
                    avertissements.append(avertissement)

        if cache_perime:
            avertissements.append(
                "Source injoignable : données servies depuis le cache local. Leur âge "
                "est à vérifier avant toute décision."
            )
        if en_echec:
            avertissements.append(
                f"{en_echec} valeur(s) sur {interroges} n'ont pas pu être collectées. "
                "Les autres ont été traitées normalement."
            )

        statut = self._statut(lignes, interroges, en_echec, cache_perime)
        _journal.info(
            "Collecte API terminée",
            extra={
                "source": self.nom,
                "valeurs": interroges,
                "echecs": en_echec,
                "lignes": len(lignes),
            },
        )
        return ResultatCollecte(
            source=self.nom,
            statut=statut,
            debut=debut,
            fin=self.maintenant(),
            lignes=tuple(lignes),
            origine=url,
            depuis_cache=depuis_cache,
            avertissements=tuple(avertissements),
            message=(
                f"{len(lignes)} entrée(s) sur {interroges} valeur(s) interrogée(s) "
                f"depuis {url} pour la fenêtre {depart.isoformat()} → {fin.isoformat()}"
            ),
        )

    # ------------------------------------------------------------------ requête

    def _corps(self, identifiant: str, depart: date, fin: date) -> dict[str, str] | None:
        if not self.api.corps:
            return None
        jetons = {
            "ticker": identifiant,
            "debut": depart.strftime(self.api.format_date_requete),
            "fin": fin.strftime(self.api.format_date_requete),
        }
        return {
            cle: _substituer(gabarit, jetons, f"api.corps.{cle}")
            for cle, gabarit in self.api.corps.items()
        }

    def _entetes(self, identifiant: str) -> dict[str, str] | None:
        if not self.api.entetes:
            return None
        return {
            cle: _substituer(gabarit, {"ticker": identifiant}, f"api.entetes.{cle}")
            for cle, gabarit in self.api.entetes.items()
        }

    # ------------------------------------------------------------------ réponse

    def _extraire(
        self, contenu: str, instrument: Instrument, jour: date | None
    ) -> list[dict[str, Any]]:
        """Traduit la réponse en lignes brutes dans le vocabulaire du système."""
        try:
            charge = json.loads(contenu)
        except json.JSONDecodeError as exc:
            raise ErreurSource(
                f"Réponse illisible : {exc}. La source n'a pas renvoyé du JSON.",
                source=self.nom,
            ) from exc

        brutes: list[dict[str, Any]] = []
        for enregistrement in _enregistrements(charge, self.api.chemin_liste):
            ligne = self._traduire(enregistrement, instrument)
            if ligne is not None:
                brutes.append(ligne)
        return self._retenir(brutes, jour)

    def _traduire(
        self, enregistrement: Mapping[str, Any], instrument: Instrument
    ) -> dict[str, Any] | None:
        """Applique la correspondance de champs à un enregistrement.

        Une date illisible fait renoncer à l'enregistrement plutôt qu'à la valeur
        entière : la ligne est comptée comme rejetée par le convertisseur, avec la
        donnée brute qui l'a causée.
        """
        ligne: dict[str, Any] = {}
        for champ_source, champ_cible in self.api.champs.items():
            if champ_source not in enregistrement:
                continue
            ligne[champ_cible] = enregistrement[champ_source]
        if "ticker" not in ligne:
            # Le ticker du système, pas celui de la source : c'est lui qui fait la
            # clé en base, et le gabarit n'est qu'une convention d'appel.
            ligne["ticker"] = instrument.ticker
        brut_date = ligne.get("date_seance")
        if brut_date is None:
            return None
        ligne["date_seance"] = self._date(brut_date)
        return ligne

    def _date(self, valeur: Any) -> str:
        """Normalise une date de séance en ISO selon le format déclaré.

        Un texte non conforme n'est **jamais** réinterprété : le format déclaré
        est précisément ce qui distingue le 3 février du 2 mars dans « 03/02 ».
        Tolérer un autre format reviendrait à deviner lequel des deux est écrit,
        et à importer une séance décalée sans que rien ne le signale. La réponse
        entière est donc refusée, avec le message qui dit quoi vérifier — un
        format de date qui change, change pour toutes les lignes à la fois.
        """
        texte = str(valeur).strip()
        try:
            return datetime.strptime(texte, self.api.format_date).date().isoformat()
        except ValueError as exc:
            raise ErreurSource(
                f"Date de séance « {texte} » non conforme au format déclaré "
                f"{self.api.format_date!r}. Relevez le format sur une réponse réelle "
                "et corrigez `api.format_date` : le système ne devine pas quel jour "
                "et quel mois sont écrits.",
                source=self.nom,
            ) from exc

    def _retenir(self, brutes: list[dict[str, Any]], jour: date | None) -> list[dict[str, Any]]:
        """Filtre la fenêtre reçue selon ce qui a été demandé.

        En mode historique, tout est conservé. Sinon, seule la séance visée est
        retenue — ou, à défaut de séance visée, la plus récente rapportée, qui est
        la définition opérationnelle de « dernière donnée disponible ».
        """
        if self.api.historique:
            return brutes
        if jour is not None:
            cible = jour.isoformat()
            return [ligne for ligne in brutes if ligne.get("date_seance") == cible]
        dates = [str(ligne.get("date_seance") or "") for ligne in brutes]
        if not any(dates):
            return []
        derniere = max(dates)
        return [ligne for ligne in brutes if str(ligne.get("date_seance") or "") == derniere]

    # ------------------------------------------------------------------- statut

    @staticmethod
    def _statut(
        lignes: Iterable[LigneCollectee], interroges: int, en_echec: int, cache_perime: bool
    ) -> StatutCollecte:
        lignes = list(lignes)
        if interroges and en_echec == interroges:
            return StatutCollecte.ECHEC
        if cache_perime:
            return StatutCollecte.DEGRADE
        if en_echec:
            return StatutCollecte.PARTIEL
        return statut_depuis_lignes(lignes)
