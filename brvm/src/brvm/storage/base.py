"""Connexion et migration de la base de données.

SQLite est retenu : le volume attendu (une cinquantaine de valeurs, une séance
par jour) tient largement dans un fichier local, et le moteur est dans la
bibliothèque standard — une dépendance de moins à maintenir. Toute la couche
d'accès passe par ce module et par :mod:`brvm.storage.depots`, de sorte qu'un
remplacement par DuckDB resterait circonscrit à ces deux fichiers.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from brvm.utils.erreurs import ErreurStockage

#: Version du schéma embarqué dans ce module.
VERSION_SCHEMA: Final[int] = 2

_FICHIER_SCHEMA: Final[Path] = Path(__file__).with_name("schema.sql")


def lire_schema() -> str:
    if not _FICHIER_SCHEMA.is_file():
        raise ErreurStockage(
            "Fichier de schéma introuvable : l'installation du paquet est incomplète.",
            fichier=str(_FICHIER_SCHEMA),
        )
    return _FICHIER_SCHEMA.read_text(encoding="utf-8")


class BaseDonnees:
    """Enveloppe d'une connexion SQLite, avec migration au premier accès."""

    def __init__(self, chemin: Path | str) -> None:
        self.chemin = Path(chemin).expanduser()
        self._connexion: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ cycle de vie

    def ouvrir(self) -> sqlite3.Connection:
        if self._connexion is not None:
            return self._connexion
        if self.chemin.parent and str(self.chemin) != ":memory:":
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
        connexion = sqlite3.connect(
            self.chemin,
            isolation_level=None,  # transactions pilotées explicitement
            detect_types=0,  # aucune conversion implicite : tout est converti à la main
        )
        connexion.row_factory = sqlite3.Row
        connexion.execute("PRAGMA foreign_keys = ON")
        connexion.execute("PRAGMA journal_mode = WAL")
        connexion.execute("PRAGMA synchronous = NORMAL")
        self._connexion = connexion
        self.migrer()
        return connexion

    def fermer(self) -> None:
        if self._connexion is not None:
            self._connexion.close()
            self._connexion = None

    def __enter__(self) -> BaseDonnees:
        self.ouvrir()
        return self

    def __exit__(self, *_: object) -> None:
        self.fermer()

    @property
    def connexion(self) -> sqlite3.Connection:
        return self.ouvrir()

    # -------------------------------------------------------------------- migration

    def version(self) -> int:
        connexion = self._connexion
        if connexion is None:
            raise ErreurStockage("Base non ouverte.")
        existe = connexion.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'version_schema'"
        ).fetchone()
        if existe is None:
            return 0
        ligne = connexion.execute("SELECT MAX(version) AS v FROM version_schema").fetchone()
        return int(ligne["v"] or 0)

    def migrer(self) -> int:
        """Applique le schéma s'il manque. Idempotent."""
        connexion = self._connexion
        if connexion is None:
            raise ErreurStockage("Base non ouverte.")
        version_actuelle = self.version()
        if version_actuelle > VERSION_SCHEMA:
            raise ErreurStockage(
                "La base a été écrite par une version plus récente du logiciel. "
                "Mettez le logiciel à jour plutôt que de rétrograder la base.",
                version_base=version_actuelle,
                version_logiciel=VERSION_SCHEMA,
            )
        if version_actuelle == VERSION_SCHEMA:
            return version_actuelle
        # `executescript` valide implicitement toute transaction en cours : on ne
        # l'enveloppe donc pas dans la nôtre. Le script est idempotent
        # (CREATE TABLE IF NOT EXISTS), un passage interrompu est rejouable.
        connexion.executescript(lire_schema())
        connexion.execute(
            "INSERT OR REPLACE INTO version_schema (version, applique_le) VALUES (?, ?)",
            (VERSION_SCHEMA, datetime.now(UTC).isoformat()),
        )
        return VERSION_SCHEMA

    # ------------------------------------------------------------------ transactions

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transaction explicite : tout ou rien.

        Une collecte partiellement écrite laisserait une base incohérente ; on
        préfère perdre le cycle et le rejouer.
        """
        connexion = self.connexion
        deja_ouverte = connexion.in_transaction
        if not deja_ouverte:
            connexion.execute("BEGIN")
        try:
            yield connexion
        except Exception:
            # `in_transaction` est retesté : une instruction DDL peut avoir validé
            # implicitement, auquel cas il n'y a plus rien à annuler.
            if not deja_ouverte and connexion.in_transaction:
                connexion.execute("ROLLBACK")
            raise
        else:
            if not deja_ouverte and connexion.in_transaction:
                connexion.execute("COMMIT")
