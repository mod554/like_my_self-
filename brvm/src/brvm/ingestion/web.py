"""Connecteur web générique : politique réseau complète, analyse déléguée.

La séparation est stricte et volontaire :

* **ce module** sait interroger un serveur correctement — robots.txt,
  temporisation, reprises, cache, mode dégradé — et transformer des champs bruts
  en cotations validées ;
* **l'analyseur** sait où, dans une page donnée, se trouvent le ticker, le cours
  et le volume. Cette connaissance est propre à un site et ne peut être écrite
  qu'après avoir regardé une vraie page.

Un analyseur n'est donc jamais fourni « par défaut » : tant qu'il n'a pas été
écrit d'après une capture réelle, la source refuse de collecter et explique
comment procéder. Un analyseur deviné produirait des cours faux sans le dire,
ce qui est le pire résultat possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from brvm.config.modeles import ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte
from brvm.ingestion.base import DataSource, LigneCollectee, ResultatCollecte, statut_depuis_lignes
from brvm.ingestion.conversion import ConvertisseurCotation
from brvm.ingestion.http import ClientHttp
from brvm.utils.erreurs import ErreurSource
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("ingestion.web")


@dataclass(frozen=True, slots=True)
class ContexteAnalyse:
    """Ce que l'analyseur sait de la requête dont provient le contenu."""

    url: str
    jour: date | None
    horodatage_collecte: datetime
    #: Date annoncée par le serveur, si elle a pu être lue dans les en-têtes.
    horodatage_donnee: datetime | None = None


@runtime_checkable
class Analyseur(Protocol):
    """Contrat d'analyse d'une page.

    L'analyseur renvoie des dictionnaires dans le **vocabulaire du système**
    (voir :mod:`brvm.ingestion.conversion`), sans convertir ni arrondir : la
    conversion, la validation et le rejet sont faits en aval, au même endroit
    pour toutes les sources.
    """

    nom: str

    def url_pour(self, url_base: str, jour: date | None) -> str:
        """Construit l'URL à interroger pour la séance demandée."""
        ...

    def analyser(self, contenu: str, contexte: ContexteAnalyse) -> list[dict[str, Any]]:
        """Extrait les lignes brutes d'une page."""
        ...


class AnalyseurNonVerifie:
    """Analyseur qui refuse de deviner la structure d'une page jamais observée.

    C'est l'implémentation par défaut de toute source web. Elle transforme une
    ignorance en message d'exploitation clair, au lieu de la transformer en
    données silencieusement fausses.
    """

    def __init__(self, nom: str, instructions: str) -> None:
        self.nom = nom
        self.instructions = instructions

    def url_pour(self, url_base: str, jour: date | None) -> str:
        return url_base

    def analyser(self, contenu: str, contexte: ContexteAnalyse) -> list[dict[str, Any]]:
        raise ErreurSource(
            f"Aucun analyseur vérifié pour la source {self.nom!r}. {self.instructions}",
            source=self.nom,
            url=contexte.url,
        )


class SourceWeb(DataSource):
    """Source interrogée par HTTP, dont l'analyse est déléguée à un analyseur."""

    def __init__(
        self,
        source: ConfigSource,
        configuration: Configuration,
        analyseur: Analyseur,
        client: ClientHttp | None = None,
    ) -> None:
        if source.url_base is None:
            raise ErreurSource(
                f"La source {source.nom!r} est de type web mais aucune url_base n'est "
                "renseignée. Renseignez l'adresse que vous avez vous-même vérifiée.",
                source=source.nom,
            )
        self.nom = source.nom
        self.source = source
        self.configuration = configuration
        self.analyseur = analyseur
        self.client = client or ClientHttp(source, configuration.ingestion)
        self._convertisseur = ConvertisseurCotation(self.nom, configuration)

    def disponible(self) -> bool:
        """Vrai si le robots.txt de l'hôte autorise la collecte."""
        if self.source.url_base is None:
            return False
        try:
            return self.client.autorise(self.analyseur.url_pour(self.source.url_base, None))
        except ErreurSource:
            return False

    def collecter(self, jour: date | None = None) -> ResultatCollecte:
        debut = self.maintenant()
        assert self.source.url_base is not None  # garanti par le constructeur
        url = self.analyseur.url_pour(self.source.url_base, jour)

        try:
            reponse = self.client.recuperer(url)
        except ErreurSource as exc:
            return self.echec(debut, str(exc), origine=url)

        contexte = ContexteAnalyse(
            url=url,
            jour=jour,
            horodatage_collecte=reponse.horodatage_collecte,
            horodatage_donnee=reponse.horodatage_donnee,
        )
        try:
            brutes = self.analyseur.analyser(reponse.texte(), contexte)
        except ErreurSource as exc:
            return self.echec(debut, str(exc), origine=url)
        except Exception as exc:  # analyseur tiers : on ne le laisse pas casser la collecte
            _journal.exception("Analyseur en échec", extra={"source": self.nom, "url": url})
            return self.echec(debut, f"Analyse de la page en échec : {exc}", origine=url)

        collectees: list[LigneCollectee] = []
        avertissements: list[str] = []
        for position, brut in enumerate(brutes, start=1):
            ligne, avertissement = self._convertisseur.convertir(
                brut,
                collecte=reponse.horodatage_collecte,
                horodatage_donnee=reponse.horodatage_donnee,
                repere=f"entrée {position}",
            )
            collectees.append(ligne)
            if avertissement:
                avertissements.append(avertissement)

        if reponse.cache_perime:
            avertissements.append(
                "Source injoignable : données servies depuis le cache local, collectées le "
                f"{reponse.horodatage_collecte.isoformat()}. Leur âge est à vérifier avant "
                "toute décision."
            )
        statut = (
            StatutCollecte.DEGRADE if reponse.cache_perime else statut_depuis_lignes(collectees)
        )
        return ResultatCollecte(
            source=self.nom,
            statut=statut,
            debut=debut,
            fin=self.maintenant(),
            lignes=tuple(collectees),
            origine=url,
            depuis_cache=reponse.depuis_cache,
            avertissements=tuple(avertissements),
            message=f"{len(collectees)} entrée(s) analysée(s) depuis {url}",
        )
