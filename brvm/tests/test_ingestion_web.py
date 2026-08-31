"""Connecteur web : refus de deviner, analyse déclarée, mode dégradé, fabrique."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from aides import OuvreurSimule, ReponseSimulee

from brvm.config.modeles import ConfigAnalyseur, ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte
from brvm.ingestion.analyseurs import AnalyseurTableauHtml
from brvm.ingestion.fabrique import construire_source
from brvm.ingestion.fichier import SourceFichier
from brvm.ingestion.http import ClientHttp
from brvm.ingestion.sikafinance import (
    INSTRUCTIONS,
    PLAN_DE_VERIFICATION,
    construire_analyseur,
    plan_de_verification,
)
from brvm.ingestion.web import AnalyseurNonVerifie, SourceWeb
from brvm.utils.erreurs import ErreurConfiguration, ErreurSource

HOTE = "https://exemple-test.invalid"
ROBOTS = f"{HOTE}/robots.txt"
PAGE = f"{HOTE}/cote"
ROBOTS_PERMISSIF = "User-agent: *\nDisallow:\n"

CONTENU = """
<table>
  <tr><th>Symbole</th><th>Cours</th><th>Volume</th></tr>
  <tr><td>TEST1</td><td>1 000</td><td>500</td></tr>
</table>
"""

COLONNES = {"Symbole": "ticker", "Cours": "cloture", "Volume": "volume_titres"}


def reglage(configuration: Configuration, **extras: object) -> ConfigSource:
    base = next(s for s in configuration.sources if s.type != "fichier_csv")
    parametres: dict[str, object] = {
        "type": "web",
        "url_base": PAGE,
        "actif": True,
        "cache_minutes": 0,
        "tentatives_max": 1,
    }
    parametres.update(extras)
    return base.model_copy(update=parametres)


def analyseur_tableau(configuration: Configuration) -> AnalyseurTableauHtml:
    return AnalyseurTableauHtml(
        "web_test",
        ConfigAnalyseur(
            type="tableau_html",
            index_tableau=0,
            colonnes=COLONNES,
            date_seance_depuis="jour_de_collecte",
        ),
        configuration,
    )


def source_web(
    configuration: Configuration,
    ouvreur: OuvreurSimule,
    dormeur: Callable[[float], None],
    analyseur: object,
    cache: Path | None = None,
    **extras: object,
) -> SourceWeb:
    reglages = reglage(configuration, **extras)
    ingestion = configuration.ingestion
    if cache is not None:
        ingestion = ingestion.model_copy(update={"repertoire_cache": cache})
    client = ClientHttp(reglages, ingestion, ouvreur, dormeur)
    return SourceWeb(reglages, configuration, analyseur, client)  # type: ignore[arg-type]


class TestRefusDeDeviner:
    def test_sans_analyseur_la_collecte_echoue_avec_la_marche_a_suivre(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Une source dont la structure n'a pas été constatée ne produit rien —
        et surtout pas des cours inventés."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee(CONTENU)}
        )
        source = source_web(
            configuration, ouvreur, dormeur, AnalyseurNonVerifie("web_test", INSTRUCTIONS)
        )
        resultat = source.collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        assert resultat.lignes == ()
        assert "capturé" in (resultat.message or "")

    def test_plan_de_verification_disponible(self) -> None:
        assert len(PLAN_DE_VERIFICATION) >= 5
        texte = plan_de_verification()
        assert "robots.txt" in texte
        assert "conditions d'utilisation" in texte

    def test_analyseur_par_defaut_refuse(self, configuration: Configuration) -> None:
        source = reglage(configuration, analyseur=None)
        assert isinstance(construire_analyseur(source, configuration), AnalyseurNonVerifie)

    def test_analyseur_declare_est_construit(self, configuration: Configuration) -> None:
        source = reglage(
            configuration,
            analyseur=ConfigAnalyseur(
                type="tableau_html",
                colonnes={"Symbole": "ticker", "Séance": "date_seance"},
            ),
        )
        assert isinstance(construire_analyseur(source, configuration), AnalyseurTableauHtml)

    def test_url_base_absente_refusee(self, configuration: Configuration) -> None:
        with pytest.raises(ErreurSource, match="url_base"):
            SourceWeb(
                reglage(configuration, url_base=None),
                configuration,
                AnalyseurNonVerifie("web_test", INSTRUCTIONS),
            )


class TestCollecte:
    def test_collecte_nominale(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee(CONTENU)}
        )
        resultat = source_web(
            configuration, ouvreur, dormeur, analyseur_tableau(configuration)
        ).collecter()
        assert resultat.statut is StatutCollecte.SUCCES
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.ticker == "TEST1"
        assert cotation.cloture == 1000

    def test_source_injoignable_ne_leve_pas(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une source qui tombe doit rendre un échec, pas casser le cycle."""
        ouvreur = OuvreurSimule({ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF)})
        resultat = source_web(
            configuration,
            ouvreur,
            dormeur,
            analyseur_tableau(configuration),
            cache=tmp_path,
        ).collecter()
        assert resultat.statut is StatutCollecte.ECHEC

    def test_mode_degrade_signale_l_age_des_donnees(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        import urllib.error

        analyseur = analyseur_tableau(configuration)
        premier = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee(CONTENU)}
        )
        source_web(configuration, premier, dormeur, analyseur, cache=tmp_path).collecter()

        tombee = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: urllib.error.URLError("injoignable"),
            }
        )
        resultat = source_web(configuration, tombee, dormeur, analyseur, cache=tmp_path).collecter()
        assert resultat.statut is StatutCollecte.DEGRADE
        assert any("cache local" in message for message in resultat.avertissements)
        assert len(resultat.lignes_exploitables) == 1

    def test_analyseur_defaillant_n_interrompt_pas_le_cycle(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        class AnalyseurCasse:
            nom = "casse"

            def url_pour(self, url_base: str, jour: object) -> str:
                return url_base

            def analyser(self, contenu: str, contexte: object) -> list[dict[str, object]]:
                raise RuntimeError("bogue dans l'analyseur")

        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee(CONTENU)}
        )
        resultat = source_web(configuration, ouvreur, dormeur, AnalyseurCasse()).collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        assert "bogue dans l'analyseur" in (resultat.message or "")

    def test_disponible_suit_le_robots_txt(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        interdit = OuvreurSimule({ROBOTS: ReponseSimulee("User-agent: *\nDisallow: /\n")})
        source = source_web(configuration, interdit, dormeur, analyseur_tableau(configuration))
        assert source.disponible() is False


class TestFabrique:
    def test_type_fichier(self, configuration: Configuration) -> None:
        source = next(s for s in configuration.sources if s.type == "fichier_csv")
        assert isinstance(construire_source(source, configuration), SourceFichier)

    def test_type_web(self, configuration: Configuration) -> None:
        assert isinstance(construire_source(reglage(configuration), configuration), SourceWeb)

    def test_type_inconnu_enumere_les_types_acceptes(self, configuration: Configuration) -> None:
        source = reglage(configuration, type="magie")
        with pytest.raises(ErreurConfiguration) as capture:
            construire_source(source, configuration)
        assert "fichier_csv" in str(capture.value)
        assert "web" in str(capture.value)
