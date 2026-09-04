"""Diffusion des alertes : fichier, courriel, webhook.

Une alerte est un **constat daté**, jamais une recommandation. Elle dit ce qui a
été observé et sur quelle donnée ; elle ne dit jamais quoi faire, et ne promet
aucun rendement.

Deux règles gouvernent ce module :

* **un canal qui tombe n'emporte pas les autres.** Un serveur SMTP injoignable
  ou un webhook en erreur devient un avertissement dans le résultat de diffusion,
  pas une exception qui interromprait la collecte. Une alerte non diffusée est
  quand même journalisée : elle ne disparaît pas ;
* **aucun paramètre n'est deviné.** Un canal courriel sans serveur déclaré, un
  webhook sans URL, échouent à la construction avec le nom du paramètre manquant
  plutôt que de retomber sur une valeur par défaut silencieuse.
"""

from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from brvm.config.modeles import ConfigAlertes, ConfigCanalAlerte, ConfigIngestion
from brvm.utils.erreurs import ErreurConfiguration
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.alertes")

#: Délai d'attente des canaux réseau, en secondes.
TIMEOUT_S: Final[float] = 15.0


class NiveauAlerte(StrEnum):
    """Gravité d'un constat, de la simple information au blocage de décision.

    L'ordre de gravité est **déclaré**, pas déduit du texte : un `StrEnum` se
    compare alphabétiquement, et « INFORMATION » y passerait devant « CRITIQUE ».
    """

    INFORMATION = "INFORMATION"
    AVERTISSEMENT = "AVERTISSEMENT"
    CRITIQUE = "CRITIQUE"

    @property
    def rang(self) -> int:
        return ORDRE_GRAVITE.index(self)


#: Du moins grave au plus grave. Seule référence d'ordre du module.
ORDRE_GRAVITE: Final[tuple[NiveauAlerte, ...]] = (
    NiveauAlerte.INFORMATION,
    NiveauAlerte.AVERTISSEMENT,
    NiveauAlerte.CRITIQUE,
)


class CategorieAlerte(StrEnum):
    """Ce sur quoi porte le constat. Chaque catégorie s'active en configuration."""

    SIGNAL_TECHNIQUE = "SIGNAL_TECHNIQUE"
    SEUIL_RISQUE = "SEUIL_RISQUE"
    DONNEE_PERIMEE = "DONNEE_PERIMEE"
    ECHEC_SOURCE = "ECHEC_SOURCE"
    #: Recul du portefeuille sous son plus-haut. Distinct de SEUIL_RISQUE, qui
    #: porte sur la composition : un portefeuille parfaitement diversifié peut
    #: reculer, et un portefeuille concentré peut ne pas reculer.
    REPLI_PORTEFEUILLE = "REPLI_PORTEFEUILLE"
    #: Un réglage obligatoire est absent, ou déclaré sans pouvoir servir.
    CONFIGURATION = "CONFIGURATION"


@dataclass(frozen=True, slots=True)
class Alerte:
    """Un constat, daté et rattaché à ce qui l'a produit."""

    categorie: CategorieAlerte
    niveau: NiveauAlerte
    titre: str
    message: str
    emise_le: datetime
    ticker: str | None = None
    #: Horodatage de la donnée sur laquelle repose le constat. Sans lui, le
    #: destinataire ne peut pas juger si l'alerte est encore d'actualité.
    horodatage_donnee: datetime | None = None
    contexte: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.emise_le.tzinfo is None:
            raise ValueError(
                "Une alerte porte un horodatage avec fuseau : une heure sans fuseau "
                "n'est pas comparable entre la machine qui l'émet et celle qui la lit."
            )

    def cle(self) -> tuple[str, str, str]:
        """Identité d'un constat, indépendante de son heure d'émission.

        Deux cycles successifs qui constatent la même chose produisent la même
        clé : c'est ce qui permet de ne pas renvoyer dix fois la même alerte.
        """
        return (self.categorie.value, self.ticker or "", self.titre)

    def resume(self) -> str:
        marque = f"[{self.niveau.value}] {self.categorie.value}"
        cible = f" {self.ticker}" if self.ticker else ""
        return f"{marque}{cible} — {self.titre} : {self.message}"

    def en_dict(self) -> dict[str, Any]:
        return {
            "categorie": self.categorie.value,
            "niveau": self.niveau.value,
            "titre": self.titre,
            "message": self.message,
            "emise_le": self.emise_le.isoformat(),
            "ticker": self.ticker,
            "horodatage_donnee": (
                self.horodatage_donnee.isoformat() if self.horodatage_donnee else None
            ),
            "contexte": dict(self.contexte),
        }


@runtime_checkable
class CanalAlerte(Protocol):
    """Contrat d'un canal de diffusion."""

    nom: str

    def diffuser(self, alertes: Sequence[Alerte]) -> None:
        """Transmet le lot. Peut lever : le diffuseur rattrape et consigne."""
        ...


def _parametre(canal: ConfigCanalAlerte, nom: str) -> str:
    valeur = canal.parametres.get(nom, "").strip()
    if not valeur:
        raise ErreurConfiguration(
            f"Le canal d'alerte {canal.nom!r} est de type {canal.type} mais son "
            f"paramètre {nom!r} n'est pas renseigné. Aucune valeur par défaut n'est "
            "fournie : une alerte envoyée au mauvais endroit ne prévient personne.",
            canal=canal.nom,
        )
    return valeur


class CanalFichier:
    """Journal d'alertes en JSON par ligne, relisible par une machine.

    C'est le canal qui fonctionne sans rien configurer d'autre, et celui qui garde
    la trace : les canaux réseau peuvent échouer, le fichier reste.
    """

    def __init__(self, nom: str, chemin: Path) -> None:
        self.nom = nom
        self.chemin = Path(chemin)

    @classmethod
    def depuis_config(cls, canal: ConfigCanalAlerte) -> CanalFichier:
        return cls(canal.nom, Path(_parametre(canal, "chemin")).expanduser())

    def diffuser(self, alertes: Sequence[Alerte]) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self.chemin.open("a", encoding="utf-8") as fichier:
            for alerte in alertes:
                fichier.write(json.dumps(alerte.en_dict(), ensure_ascii=False) + "\n")


class CanalEmail:
    """Envoi SMTP. Tous les paramètres sont déclarés, aucun n'est supposé.

    Paramètres attendus : ``serveur``, ``port``, ``expediteur``, ``destinataires``
    (séparés par des virgules). Facultatifs : ``utilisateur``, ``motdepasse``,
    ``starttls`` (``true`` par défaut), ``objet_prefixe``.
    """

    def __init__(
        self,
        nom: str,
        serveur: str,
        port: int,
        expediteur: str,
        destinataires: Sequence[str],
        utilisateur: str | None = None,
        motdepasse: str | None = None,
        starttls: bool = True,
        objet_prefixe: str = "[BRVM]",
        fabrique: Any = None,
    ) -> None:
        self.nom = nom
        self.serveur = serveur
        self.port = port
        self.expediteur = expediteur
        self.destinataires = list(destinataires)
        self.utilisateur = utilisateur
        self.motdepasse = motdepasse
        self.starttls = starttls
        self.objet_prefixe = objet_prefixe
        # Point d'injection pour les tests : rien n'oblige à ouvrir une vraie
        # connexion SMTP pour vérifier qu'un message est bien formé.
        self._fabrique = fabrique or smtplib.SMTP

    @classmethod
    def depuis_config(cls, canal: ConfigCanalAlerte) -> CanalEmail:
        destinataires = [
            adresse.strip()
            for adresse in _parametre(canal, "destinataires").split(",")
            if adresse.strip()
        ]
        if not destinataires:
            raise ErreurConfiguration(
                f"Le canal {canal.nom!r} ne désigne aucun destinataire exploitable.",
                canal=canal.nom,
            )
        port_texte = _parametre(canal, "port")
        try:
            port = int(port_texte)
        except ValueError as exc:
            raise ErreurConfiguration(
                f"Le canal {canal.nom!r} déclare un port illisible : {port_texte!r}.",
                canal=canal.nom,
            ) from exc
        return cls(
            nom=canal.nom,
            serveur=_parametre(canal, "serveur"),
            port=port,
            expediteur=_parametre(canal, "expediteur"),
            destinataires=destinataires,
            utilisateur=canal.parametres.get("utilisateur") or None,
            motdepasse=canal.parametres.get("motdepasse") or None,
            starttls=(canal.parametres.get("starttls", "true").strip().lower() != "false"),
            objet_prefixe=canal.parametres.get("objet_prefixe", "[BRVM]"),
        )

    def _message(self, alertes: Sequence[Alerte]) -> EmailMessage:
        pire = max((alerte.niveau for alerte in alertes), key=lambda n: n.rang)
        message = EmailMessage()
        message["From"] = self.expediteur
        message["To"] = ", ".join(self.destinataires)
        message["Subject"] = f"{self.objet_prefixe} {len(alertes)} constat(s) — {pire.value}"
        message.set_content(
            "\n".join(
                [
                    "Constats du système de suivi. Aucune recommandation, "
                    "aucune promesse de rendement.",
                    "",
                    *(alerte.resume() for alerte in alertes),
                    "",
                    "Chaque constat porte l'horodatage de la donnée sur laquelle il "
                    "repose ; vérifiez-le avant d'agir.",
                ]
            )
        )
        return message

    def diffuser(self, alertes: Sequence[Alerte]) -> None:
        with self._fabrique(self.serveur, self.port, timeout=TIMEOUT_S) as session:
            if self.starttls:
                session.starttls()
            if self.utilisateur and self.motdepasse:
                session.login(self.utilisateur, self.motdepasse)
            session.send_message(self._message(alertes))


class CanalWebhook:
    """POST JSON vers une URL déclarée, en ``https`` exclusivement.

    Paramètres attendus : ``url``. Facultatif : ``entete_autorisation``.

    Le refus du HTTP en clair est le même que pour la collecte : une alerte porte
    la composition d'un portefeuille, ce qui n'a rien à faire en clair sur le
    réseau.
    """

    def __init__(
        self,
        nom: str,
        url: str,
        agent_utilisateur: str,
        entete_autorisation: str | None = None,
        ouvreur: Any = None,
    ) -> None:
        if not url.lower().startswith("https://"):
            raise ErreurConfiguration(
                f"Le canal {nom!r} déclare une URL en clair. Seul https est accepté : "
                "une alerte décrit votre portefeuille.",
                canal=nom,
                url=url,
            )
        self.nom = nom
        self.url = url
        self.agent_utilisateur = agent_utilisateur
        self.entete_autorisation = entete_autorisation
        self._ouvreur = ouvreur or urllib.request.urlopen

    @classmethod
    def depuis_config(cls, canal: ConfigCanalAlerte, ingestion: ConfigIngestion) -> CanalWebhook:
        return cls(
            nom=canal.nom,
            url=_parametre(canal, "url"),
            agent_utilisateur=ingestion.agent_utilisateur,
            entete_autorisation=canal.parametres.get("entete_autorisation") or None,
        )

    def diffuser(self, alertes: Sequence[Alerte]) -> None:
        charge = json.dumps(
            {"alertes": [alerte.en_dict() for alerte in alertes]}, ensure_ascii=False
        ).encode("utf-8")
        entetes = {
            "Content-Type": "application/json",
            "User-Agent": self.agent_utilisateur,
        }
        if self.entete_autorisation:
            entetes["Authorization"] = self.entete_autorisation
        requete = urllib.request.Request(self.url, data=charge, headers=entetes, method="POST")
        reponse = self._ouvreur(requete, timeout=TIMEOUT_S)
        fermeture = getattr(reponse, "close", None)
        if callable(fermeture):
            fermeture()


@dataclass(frozen=True, slots=True)
class ResultatDiffusion:
    """Ce qui est parti, et ce qui n'est pas parti."""

    alertes: tuple[Alerte, ...]
    canaux_servis: tuple[str, ...] = ()
    canaux_en_echec: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()

    @property
    def diffusee(self) -> bool:
        return bool(self.canaux_servis)


def construire_canaux(alertes: ConfigAlertes, ingestion: ConfigIngestion) -> list[CanalAlerte]:
    """Instancie les canaux actifs déclarés en configuration."""
    canaux: list[CanalAlerte] = []
    for declaration in alertes.canaux:
        if not declaration.actif:
            continue
        match declaration.type:
            case "fichier":
                canaux.append(CanalFichier.depuis_config(declaration))
            case "email":
                canaux.append(CanalEmail.depuis_config(declaration))
            case "webhook":
                canaux.append(CanalWebhook.depuis_config(declaration, ingestion))
    return canaux


class Diffuseur:
    """Envoie un lot d'alertes sur tous les canaux, sans jamais lever.

    Il tient aussi la mémoire des constats déjà diffusés : réémettre chaque jour
    la même alerte de concentration finit par la rendre invisible. Un constat
    revient seulement s'il a disparu puis réapparu.
    """

    def __init__(
        self, canaux: Sequence[CanalAlerte], niveau_minimum: NiveauAlerte | None = None
    ) -> None:
        self.canaux = list(canaux)
        self.niveau_minimum = niveau_minimum
        self._deja_vues: set[tuple[str, str, str]] = set()

    def retenir(self, alertes: Iterable[Alerte]) -> list[Alerte]:
        """Écarte les constats déjà diffusés et ceux sous le niveau minimum."""
        seuil = self.niveau_minimum.rang if self.niveau_minimum else 0
        return [
            alerte
            for alerte in alertes
            if alerte.niveau.rang >= seuil and alerte.cle() not in self._deja_vues
        ]

    def oublier_absents(self, alertes: Iterable[Alerte]) -> None:
        """Un constat qui a disparu redevient diffusable s'il réapparaît."""
        self._deja_vues &= {alerte.cle() for alerte in alertes}

    def diffuser(self, alertes: Sequence[Alerte]) -> ResultatDiffusion:
        """Diffuse le lot. Les échecs de canal sont rapportés, jamais propagés."""
        if not alertes:
            return ResultatDiffusion(alertes=())

        # Journalisé d'abord : une alerte dont aucun canal ne veut doit rester
        # retrouvable dans le journal du système.
        for alerte in alertes:
            _journal.warning(
                alerte.titre,
                extra={
                    "categorie": alerte.categorie.value,
                    "niveau": alerte.niveau.value,
                    "ticker": alerte.ticker,
                    # Surtout pas « message » : `logging` réserve ce nom et lève
                    # une KeyError, ce qui ferait tomber la diffusion elle-même.
                    "detail": alerte.message,
                },
            )

        servis: list[str] = []
        echecs: list[str] = []
        avertissements: list[str] = []
        for canal in self.canaux:
            try:
                canal.diffuser(alertes)
            except (OSError, urllib.error.URLError, smtplib.SMTPException) as exc:
                echecs.append(canal.nom)
                avertissements.append(
                    f"Canal {canal.nom} injoignable : {exc}. Les constats restent "
                    "dans le journal du système."
                )
                _journal.error(
                    "Canal d'alerte en échec", extra={"canal": canal.nom, "erreur": str(exc)}
                )
            except Exception as exc:  # canal tiers : il ne casse pas le cycle
                echecs.append(canal.nom)
                avertissements.append(f"Canal {canal.nom} en erreur : {exc}")
                _journal.exception("Canal d'alerte en erreur", extra={"canal": canal.nom})
            else:
                servis.append(canal.nom)

        if not self.canaux:
            avertissements.append(
                "Aucun canal d'alerte actif : les constats ne sont visibles que dans "
                "le journal du système."
            )

        self._deja_vues |= {alerte.cle() for alerte in alertes}
        return ResultatDiffusion(
            alertes=tuple(alertes),
            canaux_servis=tuple(servis),
            canaux_en_echec=tuple(echecs),
            avertissements=tuple(avertissements),
        )


def maintenant() -> datetime:
    return datetime.now(UTC)
