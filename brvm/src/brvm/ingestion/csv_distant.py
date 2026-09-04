"""Connecteur de fichiers CSV servis en HTTP, un par valeur.

Ce format est celui des dépôts de données publiés et tenus à jour par un tiers :
un fichier par valeur, une ligne par séance, servi par un hébergeur statique. Il
appelle un connecteur propre, distinct des trois autres :

* le connecteur **fichier** lit le disque local et ne fait pas de réseau ;
* le connecteur **web** analyse une page HTML dont la structure varie ;
* le connecteur **API** interroge un service par requête paramétrée.

Ici, la ressource est un CSV stable, adressé par un gabarit contenant
``{ticker}``. La politique réseau reste celle de tout le système — robots.txt,
temporisation, reprises, cache, mode dégradé — parce qu'elle est portée par
:class:`~brvm.ingestion.http.ClientHttp` et non par le connecteur.

Trois traits gouvernent la conception, tous dictés par ce que ces dépôts font
réellement :

**Une séance sans transaction est ABSENTE du fichier, elle n'y figure pas à
zéro.** Le connecteur ne comble donc rien : il rapporte les lignes publiées, et
c'est la construction de série, calendrier en main, qui distingue ensuite une
séance non cotée d'une séance manquante. Inventer ici une barre
``SANS_TRANSACTION`` reviendrait à affirmer qu'aucun échange n'a eu lieu, ce que
le fichier ne dit pas.

**Les indices cotent en décimales et sans volume.** Ils partagent l'arborescence
des actions mais n'en sont pas. Le connecteur ne les écarte pas de lui-même : il
collecte l'univers déclaré dans ``marche.fichier_univers``, et un indice qui s'y
trouverait par erreur sera rejeté par les contrôles d'ingestion, avec le motif.

**Le fichier est servi avec ses en-têtes HTTP.** ``Last-Modified`` et ``ETag``
disent l'âge réel de la ressource ; le contrôle de fraîcheur s'en sert plutôt que
de supposer que « téléchargé » veut dire « à jour ».
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from brvm.config.modeles import ConfigCsvDistant, ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte
from brvm.domain.modeles import Instrument
from brvm.ingestion.base import DataSource, LigneCollectee, ResultatCollecte, statut_depuis_lignes
from brvm.ingestion.conversion import ConvertisseurCotation
from brvm.ingestion.http import ClientHttp
from brvm.ingestion.univers import charger_univers
from brvm.utils.erreurs import ErreurBrvm, ErreurSource
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("ingestion.csv_distant")


def _substituer(gabarit: str, instrument: Instrument, ou: str) -> str:
    """Remplit un gabarit d'URL, ou dit précisément quel jeton est inconnu."""
    jetons = {
        "ticker": instrument.ticker,
        "pays": instrument.pays.value,
        "pays_bas": instrument.pays.value.lower(),
    }
    try:
        return gabarit.format(**jetons)
    except (KeyError, IndexError, ValueError) as exc:
        raise ErreurSource(
            f"Gabarit invalide dans {ou} : {gabarit!r} ({exc}). Jetons acceptés : "
            + ", ".join(f"{{{nom}}}" for nom in sorted(jetons))
        ) from exc


class SourceCsvDistant(DataSource):
    """Un CSV par valeur, servi en HTTP, décrit par une correspondance déclarée."""

    def __init__(
        self,
        source: ConfigSource,
        configuration: Configuration,
        client: ClientHttp | None = None,
    ) -> None:
        if source.url_base is None:
            raise ErreurSource(
                f"La source {source.nom!r} est de type csv_distant mais aucune url_base "
                "n'est renseignée. Indiquez le gabarit d'URL que vous avez vérifié, "
                "par exemple « https://…/data/{ticker}/{ticker}.daily.csv ».",
                source=source.nom,
            )
        if source.csv_distant is None:
            raise ErreurSource(
                f"La source {source.nom!r} est de type csv_distant mais aucun bloc "
                "`csv_distant` ne décrit ses colonnes. Le système ne devine aucune "
                "correspondance : une colonne mal appariée produirait des cours faux "
                "sans le dire. Ouvrez un fichier de la source et recopiez ses en-têtes.",
                source=source.nom,
            )
        self.nom = source.nom
        self.source = source
        self.configuration = configuration
        self.reglages: ConfigCsvDistant = source.csv_distant
        self.client = client or ClientHttp(source, configuration.ingestion)
        self._convertisseur = ConvertisseurCotation(self.nom, configuration)

    # ------------------------------------------------------------------ univers

    def _univers(self) -> Sequence[Instrument]:
        instruments = charger_univers(self.configuration.marche.fichier_univers)
        return [i for i in instruments if i.actif]

    def disponible(self) -> bool:
        if self.source.url_base is None:
            return False
        try:
            univers = self._univers()
        except ErreurBrvm:
            return False
        if not univers:
            return False
        try:
            return self.client.autorise(_substituer(self.source.url_base, univers[0], "url_base"))
        except ErreurSource:
            return False

    # ---------------------------------------------------------------- collecte

    def collecter(self, jour: date | None = None) -> ResultatCollecte:
        debut = self.maintenant()
        assert self.source.url_base is not None  # garanti par le constructeur

        try:
            univers = self._univers()
        except ErreurBrvm as exc:
            # Un référentiel absent, vide ou fautif se rapporte, il ne fait pas
            # tomber la collecte : le bilan dira quoi corriger.
            return self.echec(debut, str(exc))
        if not univers:
            return self.echec(
                debut,
                "Le référentiel des valeurs est vide : cette source interroge une "
                "ressource par valeur et n'a rien à demander. Renseignez "
                f"{self.configuration.marche.fichier_univers}.",
            )

        collectees: list[LigneCollectee] = []
        avertissements: list[str] = []
        echecs: list[str] = []
        depuis_cache = False
        plus_ancien: datetime | None = None

        for instrument in univers:
            url = _substituer(self.source.url_base, instrument, "url_base")
            try:
                reponse = self.client.recuperer(url)
            except ErreurSource as exc:
                # Une valeur injoignable n'interrompt pas les autres : sur une
                # cote de cinquante lignes, tout arrêter pour une ressource
                # absente rendrait la collecte inutilisable.
                echecs.append(f"{instrument.ticker} : {exc}")
                continue

            depuis_cache = depuis_cache or reponse.depuis_cache
            if reponse.cache_perime:
                avertissements.append(
                    f"{instrument.ticker} : source injoignable, données servies depuis "
                    f"le cache local du {reponse.horodatage_collecte.isoformat()}."
                )
            if plus_ancien is None or reponse.horodatage_collecte < plus_ancien:
                plus_ancien = reponse.horodatage_collecte

            try:
                brutes = list(self._analyser(reponse.texte(), instrument, jour))
            except ErreurSource as exc:
                echecs.append(f"{instrument.ticker} : {exc}")
                continue

            for position, brut in enumerate(brutes, start=1):
                ligne, avertissement = self._convertisseur.convertir(
                    brut,
                    collecte=reponse.horodatage_collecte,
                    horodatage_donnee=reponse.horodatage_donnee,
                    repere=f"{instrument.ticker} entrée {position}",
                )
                collectees.append(ligne)
                if avertissement:
                    avertissements.append(avertissement)

        if echecs:
            avertissements.append(
                f"{len(echecs)} valeur(s) non collectée(s) : " + " | ".join(echecs[:10])
            )

        if not collectees:
            return self.echec(
                debut,
                "Aucune ligne collectée sur l'ensemble de l'univers. "
                + (" ".join(echecs[:5]) if echecs else "La source n'a rien publié."),
            )

        statut = statut_depuis_lignes(collectees)
        if avertissements and statut is StatutCollecte.SUCCES:
            statut = StatutCollecte.DEGRADE

        return ResultatCollecte(
            source=self.nom,
            statut=statut,
            debut=debut,
            fin=self.maintenant(),
            lignes=tuple(collectees),
            origine=self.source.url_base,
            depuis_cache=depuis_cache,
            avertissements=tuple(avertissements),
            message=(
                f"{len(collectees)} entrée(s) sur {len(univers) - len(echecs)}/{len(univers)} "
                "valeur(s) de l'univers"
            ),
        )

    # ----------------------------------------------------------------- analyse

    def _analyser(
        self, contenu: str, instrument: Instrument, jour: date | None
    ) -> Iterable[dict[str, Any]]:
        """Transforme un CSV en dictionnaires du vocabulaire du système.

        Aucune valeur n'est convertie ni arrondie ici : la conversion, la
        validation et le rejet sont faits en aval, au même endroit pour toutes
        les sources.
        """
        lecteur = csv.DictReader(io.StringIO(contenu))
        entetes = set(lecteur.fieldnames or ())
        attendues = {self.reglages.colonne_date, *self.reglages.colonnes.values()}
        manquantes = attendues - entetes
        if manquantes:
            raise ErreurSource(
                "Colonnes absentes du fichier : "
                + ", ".join(sorted(manquantes))
                + ". En-têtes réellement publiés : "
                + ", ".join(sorted(entetes))
                + ". La correspondance déclarée ne correspond plus à la source ; "
                "corrigez-la plutôt que de collecter des colonnes appariées au hasard.",
                source=self.nom,
            )

        borne_basse = self._borne_basse(jour)
        for rang in lecteur:
            brut_date = (rang.get(self.reglages.colonne_date) or "").strip()
            if not brut_date:
                continue
            try:
                seance = datetime.strptime(brut_date, self.reglages.format_date).date()
            except ValueError as exc:
                # Une date au mauvais format n'est jamais réinterprétée : c'est
                # le seul garde-fou entre un 03/02 et un 02/03.
                raise ErreurSource(
                    f"Date {brut_date!r} non conforme au format déclaré "
                    f"{self.reglages.format_date!r} ({exc}). Le système ne devine pas "
                    "un format : vérifiez-le sur le fichier réel.",
                    source=self.nom,
                ) from exc

            if jour is not None and not self.reglages.historique and seance != jour:
                continue
            if borne_basse is not None and seance < borne_basse:
                continue

            entree: dict[str, Any] = {
                "ticker": instrument.ticker,
                "date_seance": seance.isoformat(),
            }
            for champ, colonne in self.reglages.colonnes.items():
                valeur = (rang.get(colonne) or "").strip()
                # Une cellule vide veut dire « non publié », jamais zéro.
                if valeur:
                    entree[champ] = valeur

            self._deriver_montant(entree)
            yield entree

    def _deriver_montant(self, entree: dict[str, Any]) -> None:
        """Calcule le montant échangé, si et seulement si la configuration le demande.

        Le champ dérivé est marqué comme tel dans le commentaire de la cotation :
        un montant calculé ne doit pas pouvoir se confondre avec un montant
        publié par la source, ni dans la base, ni dans un export.
        """
        if not self.reglages.volume_xof_depuis_cours:
            return
        if "volume_xof" in entree:
            return  # la source le publie : on ne recouvre jamais une donnée réelle
        cloture, titres = entree.get("cloture"), entree.get("volume_titres")
        if cloture is None or titres is None:
            return
        try:
            montant = int(Decimal(str(cloture)) * Decimal(str(titres)))
        except (ArithmeticError, ValueError):
            return
        entree["volume_xof"] = str(montant)
        mention = "montant échangé calculé (clôture × volume), non publié par la source"
        commentaire = entree.get("commentaire")
        entree["commentaire"] = f"{commentaire} ; {mention}" if commentaire else mention

    def _borne_basse(self, jour: date | None) -> date | None:
        """Plus ancienne séance retenue, quand un rattrapage est demandé."""
        if not self.reglages.historique or self.reglages.profondeur_jours is None:
            return None
        reference = jour or datetime.now(UTC).date()
        return reference - timedelta(days=self.reglages.profondeur_jours)
