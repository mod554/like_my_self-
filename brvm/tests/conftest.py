"""Fixtures partagées.

Toutes les données de test sont **fictives** et portent des tickers volontairement
improbables (``TEST1``, ``TEST2``…) : aucune valeur réelle de la cote n'apparaît
dans la suite de tests, pour qu'aucun chiffre du dépôt ne puisse être pris pour
une donnée de marché.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from brvm.config.chargement import charger_configuration
from brvm.config.modeles import Configuration
from brvm.domain.enums import StatutSeance
from brvm.domain.modeles import Cotation
from brvm.storage.base import BaseDonnees

DOSSIER_DONNEES = Path(__file__).parent / "donnees"

#: Horodatage de référence des fixtures : une clôture de séance fictive.
HORODATAGE = datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


@pytest.fixture
def dossier_config(tmp_path: Path) -> Path:
    """Copie les fichiers de configuration de test dans un dossier temporaire.

    Les tests n'écrivent jamais dans le dépôt.
    """
    cible = tmp_path / "config"
    shutil.copytree(DOSSIER_DONNEES, cible)
    return cible


@pytest.fixture
def configuration(dossier_config: Path) -> Configuration:
    return charger_configuration(dossier_config / "config_valide.yaml")


@pytest.fixture
def base(tmp_path: Path) -> Iterator[BaseDonnees]:
    with BaseDonnees(tmp_path / "test.sqlite3") as ouverte:
        yield ouverte


@pytest.fixture
def fabrique_cotation() -> Callable[..., Cotation]:
    """Fabrique de cotations de test, aux valeurs par défaut cohérentes."""

    def fabriquer(
        jour: date | str = date(2026, 3, 2),
        cloture: int | None = 1000,
        ticker: str = "TEST1",
        source: str = "fixture",
        statut: StatutSeance = StatutSeance.COTEE,
        volume: int = 100,
        horodatage_donnee: datetime = HORODATAGE,
        horodatage_collecte: datetime = HORODATAGE,
        **extras: object,
    ) -> Cotation:
        parametres: dict[str, object] = {
            "ticker": ticker,
            "date_seance": date.fromisoformat(jour) if isinstance(jour, str) else jour,
            "source": source,
            "statut_seance": statut,
            "cloture": cloture,
            "volume_titres": volume,
            "horodatage_donnee": horodatage_donnee,
            "horodatage_collecte": horodatage_collecte,
        }
        # Les extras peuvent redéfinir un défaut : un test doit pouvoir passer
        # `volume_titres` directement sans que la fabrique le duplique.
        parametres.update(extras)
        return Cotation(**parametres)  # type: ignore[arg-type]

    return fabriquer
