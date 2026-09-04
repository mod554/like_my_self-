"""Connecteur de CSV distants : correspondance déclarée, rien de deviné.

Le point vérifié ici n'est pas qu'un fichier soit lu — c'est que le connecteur
refuse bruyamment tout ce qu'il ne peut pas établir : colonne absente, date au
mauvais format, montant non publié.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from aides import OuvreurSimule, ReponseSimulee

from brvm.config.modeles import ConfigCsvDistant, ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte
from brvm.ingestion.csv_distant import SourceCsvDistant
from brvm.ingestion.http import ClientHttp
from brvm.utils.erreurs import ErreurSource

GABARIT = "https://exemple.test/data/{ticker}/{ticker}.daily.csv"
ROBOTS = "https://exemple.test/robots.txt"

CSV_TEST1 = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-03-02,1000,1010,990,1005,500\n"
    "2026-03-03,1005,1020,1000,1015,300\n"
)
CSV_TEST2 = "Date,Open,High,Low,Close,Volume\n2026-03-02,2000,2010,1990,2005,100\n"


def reglages(**extras: object) -> ConfigCsvDistant:
    defauts: dict[str, object] = {
        "colonne_date": "Date",
        "format_date": "%Y-%m-%d",
        "colonnes": {
            "ouverture": "Open",
            "plus_haut": "High",
            "plus_bas": "Low",
            "cloture": "Close",
            "volume_titres": "Volume",
        },
        "historique": True,
    }
    defauts.update(extras)
    return ConfigCsvDistant(**defauts)  # type: ignore[arg-type]


def source_config(**extras: object) -> ConfigSource:
    defauts: dict[str, object] = {
        "nom": "depot_test",
        "type": "csv_distant",
        "actif": True,
        "priorite": 1,
        "url_base": GABARIT,
        "timeout_s": 5,
        "tentatives_max": 1,
        "backoff_initial_s": 1,
        "backoff_facteur": 2,
        "respecter_robots": False,
        "cache_minutes": 0,
        "age_max_minutes": 10_000,
        "csv_distant": reglages(),
    }
    defauts.update(extras)
    return ConfigSource(**defauts)  # type: ignore[arg-type]


def construire(
    configuration: Configuration, reponses: dict[str, object], **extras: object
) -> SourceCsvDistant:
    reglage = source_config(**extras)
    ouvreur = OuvreurSimule({ROBOTS: ReponseSimulee(""), **reponses})
    return SourceCsvDistant(
        reglage,
        configuration,
        client=ClientHttp(reglage, configuration.ingestion, ouvreur=ouvreur),
    )


def url(ticker: str) -> str:
    return GABARIT.format(ticker=ticker)


class TestRefusExplicites:
    def test_sans_url_base_la_source_refuse_de_se_construire(
        self, configuration: Configuration
    ) -> None:
        with pytest.raises(ErreurSource, match="aucune url_base"):
            SourceCsvDistant(source_config(url_base=None, actif=False), configuration)

    def test_sans_bloc_de_colonnes_la_source_refuse_de_se_construire(
        self, configuration: Configuration
    ) -> None:
        with pytest.raises(ErreurSource, match="ne devine aucune"):
            SourceCsvDistant(source_config(csv_distant=None), configuration)

    def test_une_correspondance_sans_cloture_est_refusee_a_la_configuration(self) -> None:
        with pytest.raises(ValueError, match="colonne de clôture"):
            reglages(colonnes={"ouverture": "Open"})

    def test_un_champ_inconnu_est_refuse_a_la_configuration(self) -> None:
        with pytest.raises(ValueError, match="Champs inconnus"):
            reglages(colonnes={"cloture": "Close", "cours_magique": "X"})


class TestCollecte:
    def test_toutes_les_valeurs_de_l_univers_sont_interrogees(
        self, configuration: Configuration
    ) -> None:
        source = construire(
            configuration,
            {url("TEST1"): ReponseSimulee(CSV_TEST1), url("TEST2"): ReponseSimulee(CSV_TEST2)},
        )
        resultat = source.collecter()
        tickers = {ligne.brut.get("ticker") for ligne in resultat.lignes}
        assert tickers == {"TEST1", "TEST2"}
        assert len(resultat.lignes) == 3

    def test_une_valeur_injoignable_n_interrompt_pas_les_autres(
        self, configuration: Configuration
    ) -> None:
        """Sur une cote de cinquante lignes, tout arrêter pour une ressource
        absente rendrait la collecte inutilisable."""
        source = construire(configuration, {url("TEST1"): ReponseSimulee(CSV_TEST1)})
        resultat = source.collecter()
        assert resultat.statut is StatutCollecte.DEGRADE
        assert any("TEST2" in a for a in resultat.avertissements)
        assert len(resultat.lignes) == 2

    def test_aucune_valeur_collectee_est_un_echec_pas_un_succes_vide(
        self, configuration: Configuration
    ) -> None:
        source = construire(configuration, {})
        resultat = source.collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        assert resultat.lignes == ()

    def test_une_seance_precise_ne_ramene_que_celle_la(self, configuration: Configuration) -> None:
        source = construire(
            configuration,
            {url("TEST1"): ReponseSimulee(CSV_TEST1), url("TEST2"): ReponseSimulee(CSV_TEST2)},
            csv_distant=reglages(historique=False),
        )
        resultat = source.collecter(jour=date(2026, 3, 3))
        assert len(resultat.lignes) == 1
        assert resultat.lignes[0].brut["date_seance"] == "2026-03-03"


class TestFidelite:
    def test_une_colonne_absente_est_nommee_et_la_valeur_ecartee(
        self, configuration: Configuration
    ) -> None:
        """La correspondance déclarée ne correspond plus : on le dit, on ne
        collecte pas des colonnes appariées au hasard."""
        source = construire(
            configuration,
            {url("TEST1"): ReponseSimulee("Date,Cours\n2026-03-02,1000\n")},
        )
        resultat = source.collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        joints = " ".join(resultat.avertissements) + (resultat.message or "")
        assert "Close" in joints

    def test_une_date_au_mauvais_format_n_est_jamais_reinterpretee(
        self, configuration: Configuration
    ) -> None:
        """Seul garde-fou entre un 03/02 et un 02/03."""
        source = construire(
            configuration,
            {
                url("TEST1"): ReponseSimulee(
                    "Date,Open,High,Low,Close,Volume\n03/02/2026,1,1,1,1,1\n"
                )
            },
        )
        resultat = source.collecter()
        joints = " ".join(resultat.avertissements) + (resultat.message or "")
        assert "non conforme au format déclaré" in joints

    def test_une_cellule_vide_vaut_non_publie_jamais_zero(
        self, configuration: Configuration
    ) -> None:
        source = construire(
            configuration,
            {
                url("TEST1"): ReponseSimulee(
                    "Date,Open,High,Low,Close,Volume\n2026-03-02,,,,1000,\n"
                )
            },
        )
        resultat = source.collecter()
        brut = resultat.lignes[0].brut
        assert "ouverture" not in brut
        assert "volume_titres" not in brut
        assert brut["cloture"] == "1000"


class TestMontantDerive:
    def test_desactive_par_defaut(self, configuration: Configuration) -> None:
        source = construire(configuration, {url("TEST1"): ReponseSimulee(CSV_TEST1)})
        assert all("volume_xof" not in ligne.brut for ligne in source.collecter().lignes)

    def test_active_le_montant_est_calcule_et_marque_comme_tel(
        self, configuration: Configuration
    ) -> None:
        """Un montant calculé ne doit pas pouvoir se confondre avec un publié."""
        source = construire(
            configuration,
            {url("TEST1"): ReponseSimulee(CSV_TEST1)},
            csv_distant=reglages(volume_xof_depuis_cours=True),
        )
        brut = source.collecter().lignes[0].brut
        assert brut["volume_xof"] == str(1005 * 500)
        assert "calculé" in brut["commentaire"]

    def test_un_montant_publie_n_est_jamais_recouvert(self, configuration: Configuration) -> None:
        colonnes = dict(reglages().colonnes, volume_xof="Montant")
        source = construire(
            configuration,
            {
                url("TEST1"): ReponseSimulee(
                    "Date,Open,High,Low,Close,Volume,Montant\n"
                    "2026-03-02,1000,1010,990,1005,500,999999\n"
                )
            },
            csv_distant=reglages(colonnes=colonnes, volume_xof_depuis_cours=True),
        )
        brut = source.collecter().lignes[0].brut
        assert brut["volume_xof"] == "999999"
        assert "commentaire" not in brut


class TestDisponibilite:
    def test_univers_vide_rend_la_source_indisponible(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        vide = tmp_path / "univers_vide.csv"
        vide.write_text("ticker,nom,isin,pays,secteur,compartiment,actif\n", encoding="utf-8")
        reglage = configuration.model_copy(
            update={"marche": configuration.marche.model_copy(update={"fichier_univers": vide})}
        )
        source = construire(reglage, {})
        assert source.disponible() is False
        assert source.collecter().statut is StatutCollecte.ECHEC
