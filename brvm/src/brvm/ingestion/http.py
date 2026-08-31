"""Politique réseau : robots.txt, temporisation, reprises, cache, mode dégradé.

Ce module ne connaît rien au marché. Il sait seulement récupérer une ressource
en se comportant correctement vis-à-vis du serveur interrogé, et rendre la main
sans jamais lever pour un incident réseau : une source qui tombe ne doit pas
emporter la collecte des autres.

Ordre des garde-fous, du plus contraignant au moins :

1. **robots.txt** — consulté avant toute requête et respecté. Un ``Crawl-delay``
   annoncé l'emporte sur le délai configuré s'il est plus long. Un robots.txt
   injoignable pour cause d'erreur serveur interdit la collecte : dans le doute,
   on s'abstient.
2. **Temporisation** — délai minimal entre deux requêtes vers le même hôte.
3. **Cache local** — une réponse encore fraîche évite une requête inutile.
4. **Reprises avec recul exponentiel** — sur incident transitoire seulement.
5. **Mode dégradé** — toutes les tentatives ayant échoué, une entrée de cache
   périmée est servie, explicitement signalée comme telle. Jamais de valeur
   fabriquée.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final, Protocol

from brvm.config.modeles import ConfigIngestion, ConfigSource
from brvm.utils.erreurs import ErreurSource
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("ingestion.http")

#: Codes justifiant une nouvelle tentative : incident transitoire côté serveur.
CODES_REESSAYABLES: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Durée de validité d'un robots.txt en mémoire et sur disque.
TTL_ROBOTS_MINUTES: Final[int] = 60

#: Plafond appliqué à un ``Retry-After`` annoncé par le serveur, pour ne pas
#: bloquer une collecte pendant des heures sur la parole d'un serveur en panne.
RETRY_AFTER_MAX_S: Final[float] = 120.0


@dataclass(frozen=True, slots=True)
class ReponseHttp:
    """Ressource récupérée, avec ce qu'il faut pour juger de sa fraîcheur."""

    url: str
    contenu: bytes
    code: int
    #: Instant de la récupération effective (ou de la mise en cache si servie du cache).
    horodatage_collecte: datetime
    #: Date annoncée par le serveur (en-tête ``Last-Modified``, à défaut ``Date``).
    #: ``None`` si le serveur n'annonce rien d'exploitable.
    horodatage_donnee: datetime | None
    depuis_cache: bool = False
    #: Vrai si le cache a été servi faute de pouvoir joindre la source.
    cache_perime: bool = False

    def texte(self, encodage: str = "utf-8") -> str:
        return self.contenu.decode(encodage, errors="replace")

    def age_minutes(self, reference: datetime | None = None) -> Decimal:
        instant = reference or datetime.now(UTC)
        base = self.horodatage_donnee or self.horodatage_collecte
        return Decimal(str((instant - base).total_seconds())) / Decimal(60)


class ReponseBrute(Protocol):
    """Ce que le système attend d'une réponse HTTP, réelle ou simulée."""

    def read(self) -> bytes: ...


class Ouvreur(Protocol):
    """Point d'injection pour les tests : remplace l'appel réseau réel."""

    def __call__(self, requete: urllib.request.Request, timeout: float) -> ReponseBrute: ...


def _ouvreur_par_defaut(requete: urllib.request.Request, timeout: float) -> ReponseBrute:
    # Le schéma est validé en amont par ClientHttp.recuperer : seul https passe.
    reponse: ReponseBrute = urllib.request.urlopen(requete, timeout=timeout)
    return reponse


def _horodatage_entete(entetes: Any) -> datetime | None:
    """Extrait une date exploitable des en-têtes, ``Last-Modified`` en priorité."""
    if entetes is None:
        return None
    for nom in ("Last-Modified", "Date"):
        brut = entetes.get(nom)
        if not brut:
            continue
        try:
            horodatage = parsedate_to_datetime(brut)
        except (TypeError, ValueError):
            continue
        if horodatage.tzinfo is None:
            horodatage = horodatage.replace(tzinfo=UTC)
        return horodatage.astimezone(UTC)
    return None


class CacheFichier:
    """Cache disque très simple : un corps et une fiche de métadonnées par URL."""

    def __init__(self, repertoire: Path) -> None:
        self.repertoire = Path(repertoire)

    def _cles(self, url: str) -> tuple[Path, Path]:
        empreinte = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return (
            self.repertoire / f"{empreinte}.corps",
            self.repertoire / f"{empreinte}.meta.json",
        )

    def lire(self, url: str) -> tuple[bytes, dict[str, str]] | None:
        corps, meta = self._cles(url)
        if not corps.is_file() or not meta.is_file():
            return None
        try:
            return corps.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def ecrire(self, url: str, contenu: bytes, metadonnees: dict[str, str]) -> None:
        corps, meta = self._cles(url)
        try:
            self.repertoire.mkdir(parents=True, exist_ok=True)
            corps.write_bytes(contenu)
            meta.write_text(
                json.dumps({"url": url, **metadonnees}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            # Un cache indisponible dégrade les performances, jamais la correction.
            _journal.warning("Écriture de cache impossible", extra={"url": url, "erreur": str(exc)})


class ClientHttp:
    """Client HTTP appliquant la politique réseau d'une source donnée."""

    def __init__(
        self,
        source: ConfigSource,
        ingestion: ConfigIngestion,
        ouvreur: Ouvreur | None = None,
        dormir: Callable[[float], None] | None = None,
    ) -> None:
        self.source = source
        self.ingestion = ingestion
        self._ouvreur: Ouvreur = ouvreur or _ouvreur_par_defaut
        self._cache = CacheFichier(ingestion.repertoire_cache)
        self._robots: dict[str, tuple[urllib.robotparser.RobotFileParser | None, datetime]] = {}
        self._dernier_appel: dict[str, float] = {}
        # Injectable pour que les tests vérifient les reculs sans les subir.
        self._dormir: Callable[[float], None] = dormir if dormir is not None else time.sleep

    # ------------------------------------------------------------------- robots

    def _robots_pour(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """Renvoie l'analyseur de robots.txt de l'hôte, ``None`` si indéterminable."""
        morceaux = urllib.parse.urlsplit(url)
        hote = f"{morceaux.scheme}://{morceaux.netloc}"
        en_memoire = self._robots.get(hote)
        if en_memoire is not None:
            analyseur, expire = en_memoire
            if datetime.now(UTC) < expire:
                return analyseur

        adresse = f"{hote}/robots.txt"
        analyseur = urllib.robotparser.RobotFileParser()
        analyseur.set_url(adresse)
        try:
            requete = urllib.request.Request(
                adresse, headers={"User-Agent": self.ingestion.agent_utilisateur}
            )
            reponse = self._ouvreur(requete, float(self.source.timeout_s))
            corps = reponse.read()
            analyseur.parse(corps.decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                # Pas de robots.txt publié : la collecte est permise par défaut.
                # Un jeu de règles vide vaut autorisation générale.
                analyseur.parse([])
            else:
                # Erreur serveur : on ne sait pas ce qui est permis, donc on s'abstient.
                self._robots[hote] = (None, datetime.now(UTC) + timedelta(minutes=1))
                return None
        except (urllib.error.URLError, OSError, TimeoutError):
            self._robots[hote] = (None, datetime.now(UTC) + timedelta(minutes=1))
            return None

        self._robots[hote] = (analyseur, datetime.now(UTC) + timedelta(minutes=TTL_ROBOTS_MINUTES))
        return analyseur

    def autorise(self, url: str) -> bool:
        """Vrai si le robots.txt de l'hôte permet d'aller chercher cette URL."""
        if not self.source.respecter_robots:
            return True
        analyseur = self._robots_pour(url)
        if analyseur is None:
            _journal.warning(
                "robots.txt indéterminable : collecte refusée par prudence",
                extra={"url": url, "source": self.source.nom},
            )
            return False
        return analyseur.can_fetch(self.ingestion.agent_utilisateur, url)

    def _delai_applicable(self, url: str) -> float:
        """Délai retenu : le plus long entre celui configuré et le ``Crawl-delay``."""
        configure = float(self.ingestion.delai_entre_requetes_s)
        if not self.source.respecter_robots:
            return configure
        analyseur = self._robots.get(
            f"{urllib.parse.urlsplit(url).scheme}://{urllib.parse.urlsplit(url).netloc}"
        )
        if analyseur is None or analyseur[0] is None:
            return configure
        annonce = analyseur[0].crawl_delay(self.ingestion.agent_utilisateur)
        return max(configure, float(annonce)) if annonce is not None else configure

    def _temporiser(self, url: str) -> None:
        hote = urllib.parse.urlsplit(url).netloc
        delai = self._delai_applicable(url)
        if delai <= 0:
            self._dernier_appel[hote] = time.monotonic()
            return
        precedent = self._dernier_appel.get(hote)
        if precedent is not None:
            reste = delai - (time.monotonic() - precedent)
            if reste > 0:
                self._dormir(reste)
        self._dernier_appel[hote] = time.monotonic()

    # ---------------------------------------------------------------- requêtes

    def recuperer(self, url: str) -> ReponseHttp:
        """Récupère une ressource en appliquant toute la politique réseau.

        Raises:
            ErreurSource: uniquement si la ressource est inaccessible *et* qu'aucune
                entrée de cache ne permet un mode dégradé. Les incidents réseau
                ordinaires sont absorbés, pas propagés.
        """
        if not url.lower().startswith("https://"):
            raise ErreurSource(
                "Seul le schéma https est accepté : une collecte en clair exposerait "
                "la requête et la réponse.",
                url=url,
                source=self.source.nom,
            )

        frais = self._cache_frais(url)
        if frais is not None:
            return frais

        if not self.autorise(url):
            raise ErreurSource(
                "Le robots.txt de la source interdit cette collecte, ou n'a pas pu être "
                "lu. Le système s'abstient plutôt que de passer outre.",
                url=url,
                source=self.source.nom,
            )

        derniere_erreur = "aucune tentative effectuée"
        for tentative in range(1, self.source.tentatives_max + 1):
            self._temporiser(url)
            try:
                return self._appel_unique(url)
            except urllib.error.HTTPError as exc:
                derniere_erreur = f"HTTP {exc.code}"
                if exc.code not in CODES_REESSAYABLES:
                    break
                self._reculer(tentative, self._retry_after(exc))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                derniere_erreur = f"{type(exc).__name__}: {exc}"
                self._reculer(tentative, None)

        _journal.warning(
            "Source injoignable, passage en mode dégradé si un cache existe",
            extra={"url": url, "source": self.source.nom, "erreur": derniere_erreur},
        )
        degrade = self._cache_perime(url)
        if degrade is not None:
            return degrade
        raise ErreurSource(
            "Source injoignable et aucune donnée en cache : le système ne produit rien "
            "plutôt que d'inventer une valeur.",
            url=url,
            source=self.source.nom,
            derniere_erreur=derniere_erreur,
        )

    def _appel_unique(self, url: str) -> ReponseHttp:
        requete = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.ingestion.agent_utilisateur,
                "Accept-Language": "fr",
            },
        )
        reponse = self._ouvreur(requete, float(self.source.timeout_s))
        contenu: bytes = reponse.read()
        code = int(getattr(reponse, "status", 200) or 200)
        entetes = getattr(reponse, "headers", None)
        horodatage_donnee = _horodatage_entete(entetes)
        maintenant = datetime.now(UTC)
        self._cache.ecrire(
            url,
            contenu,
            {
                "collecte": maintenant.isoformat(),
                "donnee": horodatage_donnee.isoformat() if horodatage_donnee else "",
                "code": str(code),
            },
        )
        return ReponseHttp(
            url=url,
            contenu=contenu,
            code=code,
            horodatage_collecte=maintenant,
            horodatage_donnee=horodatage_donnee,
        )

    def _reculer(self, tentative: int, retry_after: float | None) -> None:
        """Recul exponentiel, éventuellement rallongé par un ``Retry-After``."""
        attente = float(self.source.backoff_initial_s) * float(self.source.backoff_facteur) ** (
            tentative - 1
        )
        if retry_after is not None:
            attente = max(attente, min(retry_after, RETRY_AFTER_MAX_S))
        if attente > 0:
            self._dormir(attente)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError) -> float | None:
        brut = exc.headers.get("Retry-After") if exc.headers else None
        if not brut:
            return None
        try:
            return float(brut)
        except ValueError:
            try:
                cible = parsedate_to_datetime(brut)
            except (TypeError, ValueError):
                return None
            if cible.tzinfo is None:
                cible = cible.replace(tzinfo=UTC)
            return max(0.0, (cible - datetime.now(UTC)).total_seconds())

    # ------------------------------------------------------------------- cache

    def _entree_cache(self, url: str) -> tuple[bytes, dict[str, str], datetime] | None:
        entree = self._cache.lire(url)
        if entree is None:
            return None
        contenu, metadonnees = entree
        try:
            collecte = datetime.fromisoformat(metadonnees["collecte"])
        except (KeyError, ValueError):
            return None
        return contenu, metadonnees, collecte

    @staticmethod
    def _donnee_depuis_meta(metadonnees: dict[str, str]) -> datetime | None:
        brut = metadonnees.get("donnee") or ""
        try:
            return datetime.fromisoformat(brut) if brut else None
        except ValueError:
            return None

    def _cache_frais(self, url: str) -> ReponseHttp | None:
        if self.source.cache_minutes <= 0:
            return None
        entree = self._entree_cache(url)
        if entree is None:
            return None
        contenu, metadonnees, collecte = entree
        if datetime.now(UTC) - collecte > timedelta(minutes=self.source.cache_minutes):
            return None
        return ReponseHttp(
            url=url,
            contenu=contenu,
            code=int(metadonnees.get("code", 200)),
            horodatage_collecte=collecte,
            horodatage_donnee=self._donnee_depuis_meta(metadonnees),
            depuis_cache=True,
        )

    def _cache_perime(self, url: str) -> ReponseHttp | None:
        entree = self._entree_cache(url)
        if entree is None:
            return None
        contenu, metadonnees, collecte = entree
        return ReponseHttp(
            url=url,
            contenu=contenu,
            code=int(metadonnees.get("code", 200)),
            horodatage_collecte=collecte,
            horodatage_donnee=self._donnee_depuis_meta(metadonnees),
            depuis_cache=True,
            cache_perime=True,
        )
