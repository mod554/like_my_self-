"""Fixtures partagées.

Toutes les données de test sont **fictives** et portent des tickers volontairement
improbables (``TEST1``, ``TEST2``…) : aucune valeur réelle de la cote n'apparaît
dans la suite de tests, pour qu'aucun chiffre du dépôt ne puisse être pris pour
une donnée de marché.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from brvm.config.chargement import charger_configuration, construire_calendrier_depuis_config
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import StatutSeance
from brvm.domain.modeles import Cotation, OperationSurTitre
from brvm.indicators.serie import SerieTechnique, construire_serie
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


# --------------------------------------------------------------------- ingestion


@pytest.fixture
def calendrier(configuration: Configuration) -> CalendrierSeances:
    return construire_calendrier_depuis_config(configuration)


@pytest.fixture
def dormeur() -> Callable[[float], None]:
    """Remplace `time.sleep` : les tests vérifient les reculs sans les subir."""

    def dormir(secondes: float) -> None:
        attentes.append(secondes)

    attentes: list[float] = []
    dormir.attentes = attentes  # type: ignore[attr-defined]
    return dormir


# -------------------------------------------------------------------- technique


@pytest.fixture
def fabrique_serie(
    configuration: Configuration,
    calendrier: CalendrierSeances,
    fabrique_cotation: Callable[..., Cotation],
) -> Callable[..., SerieTechnique]:
    """Construit une série technique à partir d'une suite de clôtures.

    ``None`` dans la suite signifie « séance sans transaction » : c'est ainsi que
    l'on reproduit l'illiquidité dans les tests.
    """

    def construire(
        clotures: Sequence[int | None],
        debut: date = date(2026, 3, 2),
        ticker: str = "TEST1",
        amplitude: int = 10,
        volume: int = 100,
        operations: Sequence[OperationSurTitre] = (),
        jusqu_a: date | None = None,
        **extras: object,
    ) -> SerieTechnique:
        seances = calendrier.seances(debut, date(2026, 12, 31))[: len(clotures)]
        cotations: list[Cotation] = []
        for jour, cloture in zip(seances, clotures, strict=False):
            if cloture is None:
                cotations.append(
                    fabrique_cotation(
                        jour=jour,
                        ticker=ticker,
                        cloture=None,
                        statut=StatutSeance.SANS_TRANSACTION,
                        volume=0,
                    )
                )
            else:
                cotations.append(
                    fabrique_cotation(
                        jour=jour,
                        ticker=ticker,
                        cloture=cloture,
                        volume=volume,
                        ouverture=cloture,
                        plus_haut=cloture + amplitude,
                        plus_bas=max(1, cloture - amplitude),
                        volume_xof=cloture * volume,
                        **extras,
                    )
                )
        return construire_serie(cotations, calendrier, configuration, operations, jusqu_a=jusqu_a)

    return construire
