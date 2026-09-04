"""Doublures de test partagées entre plusieurs modules.

Regroupées ici plutôt que dans ``conftest.py`` pour être importables
explicitement : une doublure est du code, pas une fixture implicite.
"""

from __future__ import annotations

import urllib.error
from typing import Any


class ReponseSimulee:
    """Réponse HTTP factice : juste ce que le client attend d'une vraie réponse."""

    def __init__(
        self, corps: bytes | str, entetes: dict[str, str] | None = None, status: int = 200
    ) -> None:
        self._corps = corps.encode("utf-8") if isinstance(corps, str) else corps
        self.headers = entetes or {}
        self.status = status

    def read(self) -> bytes:
        return self._corps


class OuvreurSimule:
    """Ouvreur injectable : sert des réponses programmées et compte les appels.

    Une entrée peut être une réponse, une exception à lever, ou une liste de l'un
    ou l'autre consommée appel après appel — de quoi simuler « échoue deux fois
    puis répond ».
    """

    def __init__(self, reponses: dict[str, object]) -> None:
        self.reponses = {
            url: list(valeur) if isinstance(valeur, list) else [valeur]
            for url, valeur in reponses.items()
        }
        self.appels: list[str] = []

    def __call__(self, requete: Any, timeout: float) -> ReponseSimulee:
        url = requete.full_url if hasattr(requete, "full_url") else str(requete)
        self.appels.append(url)
        file_attente = self.reponses.get(url)
        if not file_attente:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        element = file_attente[0] if len(file_attente) == 1 else file_attente.pop(0)
        if isinstance(element, Exception):
            raise element
        if not isinstance(element, ReponseSimulee):
            raise TypeError(f"Réponse simulée invalide : {element!r}")
        return element

    def nb_appels(self, url: str) -> int:
        return sum(1 for appel in self.appels if appel == url)
