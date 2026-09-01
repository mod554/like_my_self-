"""Serveur local de l'interface web.

Bibliothèque standard uniquement : aucune dépendance ajoutée pour afficher un
portefeuille. Le serveur fait trois choses et rien d'autre — servir les fichiers
de l'interface, servir l'état en JSON, et refuser tout le reste.

Deux garde-fous, tous deux volontaires :

* **écoute sur la boucle locale par défaut.** Cette interface montre la
  composition d'un portefeuille et n'a aucune authentification. La rendre
  accessible au réseau se demande explicitement, et le message le dit ;
* **les fichiers servis sont ceux du dossier ``web/``, et rien au-dessus.** Le
  chemin demandé est résolu puis vérifié comme descendant de ce dossier : une
  requête ``../../etc/passwd`` n'atteint rien.

Le serveur ne collecte jamais. Il lit la base telle qu'elle est ; c'est
l'ordonnanceur ou la commande `collecter` qui l'alimente.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from datetime import UTC, datetime
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from brvm.app.api import serialiser
from brvm.app.etat import assembler
from brvm.config.chargement import construire_calendrier_depuis_config
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.storage.base import BaseDonnees
from brvm.utils.erreurs import ErreurBrvm
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.serveur")

#: Dossier des fichiers de l'interface, livré avec le paquet.
RACINE_WEB: Final[Path] = Path(__file__).parent / "web"

#: Adresse d'écoute par défaut : la machine elle-même, personne d'autre.
HOTE_DEFAUT: Final[str] = "127.0.0.1"
PORT_DEFAUT: Final[int] = 8731

#: Types servis. Une extension absente de cette table n'est pas servie : mieux
#: vaut un 404 qu'un fichier remis avec le mauvais type.
TYPES: Final[dict[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}


class _Gestionnaire(BaseHTTPRequestHandler):
    """Routage minimal : l'état en JSON, les fichiers de l'interface, sinon 404."""

    server_version = "brvm"
    sys_version = ""

    def __init__(
        self,
        *args: Any,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        verrou: threading.Lock,
        **kwargs: Any,
    ) -> None:
        self.configuration = configuration
        self.calendrier = calendrier
        self.verrou = verrou
        super().__init__(*args, **kwargs)

    # ------------------------------------------------------------------ routes

    def do_GET(self) -> None:
        chemin = urlparse(self.path).path
        if chemin in {"/api/etat", "/api/etat/"}:
            self._servir_etat()
        elif chemin in {"/", ""}:
            self._servir_fichier("index.html")
        else:
            self._servir_fichier(chemin.lstrip("/"))

    def _servir_etat(self) -> None:
        try:
            # SQLite en mode WAL supporte les lectures concurrentes, mais une
            # seule connexion partagée ne le supporte pas : on sérialise.
            with (
                self.verrou,
                BaseDonnees(self.configuration.general.base_donnees) as base,
            ):
                etat = assembler(
                    base, self.configuration, self.calendrier, instant=datetime.now(UTC)
                )
                charge = serialiser(etat)
        except ErreurBrvm as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"erreur": str(exc)})
            return
        except Exception as exc:  # une vue en échec ne doit pas tuer le serveur
            _journal.exception("État non composable")
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"erreur": f"État du portefeuille non composable : {exc}"},
            )
            return
        self._json(HTTPStatus.OK, charge)

    def _servir_fichier(self, relatif: str) -> None:
        cible = (RACINE_WEB / relatif).resolve()
        racine = RACINE_WEB.resolve()
        # `is_relative_to` après résolution : un `..` dans l'URL ne sort pas du
        # dossier de l'interface.
        if not cible.is_relative_to(racine) or not cible.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"erreur": "Ressource inconnue."})
            return
        type_contenu = TYPES.get(cible.suffix.lower())
        if type_contenu is None:
            self._json(HTTPStatus.NOT_FOUND, {"erreur": "Type de fichier non servi."})
            return
        contenu = cible.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(contenu)))
        # Les polices ne changent jamais ; le reste doit pouvoir être rechargé.
        duree = 31536000 if cible.suffix == ".woff2" else 0
        self.send_header("Cache-Control", f"max-age={duree}" if duree else "no-store")
        self._entetes_de_prudence()
        self.end_headers()
        self.wfile.write(contenu)

    def _json(self, code: HTTPStatus, charge: dict[str, Any]) -> None:
        contenu = json.dumps(charge, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(contenu)))
        self.send_header("Cache-Control", "no-store")
        self._entetes_de_prudence()
        self.end_headers()
        self.wfile.write(contenu)

    def _entetes_de_prudence(self) -> None:
        """En-têtes de sécurité. L'interface n'appelle rien à l'extérieur.

        La politique de contenu interdit toute ressource distante : si un jour
        quelqu'un ajoute un script de CDN, la page cassera visiblement plutôt
        que d'exfiltrer discrètement la composition d'un portefeuille.
        """
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def log_message(self, format: str, *args: Any) -> None:
        """Journalise dans le journal du système plutôt que sur stderr."""
        _journal.debug("Requête servie", extra={"requete": format % args})


def construire_serveur(
    configuration: Configuration,
    hote: str = HOTE_DEFAUT,
    port: int = PORT_DEFAUT,
    calendrier: CalendrierSeances | None = None,
) -> ThreadingHTTPServer:
    """Prépare le serveur sans l'exécuter.

    Séparer la construction du démarrage permet aux tests d'interroger un vrai
    serveur sur un port éphémère, sans boucle bloquante.
    """
    gestionnaire = partial(
        _Gestionnaire,
        configuration=configuration,
        calendrier=calendrier or construire_calendrier_depuis_config(configuration),
        verrou=threading.Lock(),
    )
    for extension, type_contenu in TYPES.items():
        mimetypes.add_type(type_contenu.split(";")[0], extension)
    return ThreadingHTTPServer((hote, port), gestionnaire)


def servir(
    configuration: Configuration,
    hote: str = HOTE_DEFAUT,
    port: int = PORT_DEFAUT,
) -> None:
    """Lance l'interface et rend la main à l'interruption clavier."""
    serveur = construire_serveur(configuration, hote, port)
    adresse = f"http://{hote}:{serveur.server_address[1]}"
    if hote not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"⚠ L'interface écoute sur {hote} : elle est accessible depuis le "
            "réseau et ne demande aucun mot de passe. Elle montre la composition "
            "de votre portefeuille.",
        )
    print(f"Interface disponible sur {adresse}")
    print("Ctrl+C pour arrêter.")
    _journal.info("Interface démarrée", extra={"adresse": adresse})
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        serveur.server_close()
