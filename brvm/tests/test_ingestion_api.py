"""Connecteur d'API JSON : refus de deviner un schéma, fenêtre, mode dégradé.

Toutes les réponses simulées portent des tickers fictifs. La *forme* des
réponses (une liste d'objets sous une clé, des dates en jj/mm/aaaa) reproduit
celle d'une API d'historique réellement observée ; les chiffres, eux, sont
inventés et ne valent comme donnée de marché en aucune manière.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from aides import OuvreurSimule, ReponseSimulee

from brvm.config.modeles import ConfigApi, ConfigSource, Configuration
from brvm.domain.enums import StatutCollecte, StatutSeance
from brvm.ingestion.api import SourceApiJson
from brvm.ingestion.fabrique import construire_source
from brvm.ingestion.http import ClientHttp
from brvm.ingestion.univers import charger_univers
from brvm.utils.erreurs import ErreurSource

HOTE = "https://api-test.invalid"
ROBOTS = f"{HOTE}/robots.txt"
API = f"{HOTE}/api/historiques"
ROBOTS_PERMISSIF = "User-agent: *\nDisallow:\n"

CHAMPS = {
    "Date": "date_seance",
    "Open": "ouverture",
    "High": "plus_haut",
    "Low": "plus_bas",
    "Close": "cloture",
    "Volume": "volume_titres",
}
CORPS = {"ticker": "{ticker}", "datedeb": "{debut}", "datefin": "{fin}", "xperiod": "0"}


def barre(jour: str, cloture: int = 1000, volume: int = 500) -> dict[str, object]:
    return {
        "Date": jour,
        "Open": cloture,
        "High": cloture + 20,
        "Low": cloture - 20,
        "Close": cloture,
        "Volume": volume,
    }


def reponse(*barres: dict[str, object]) -> ReponseSimulee:
    return ReponseSimulee(json.dumps({"lst": list(barres)}))


def config_api(**extras: object) -> ConfigApi:
    parametres: dict[str, object] = {
        "chemin_liste": "lst",
        "corps": CORPS,
        "champs": CHAMPS,
        "format_date": "%d/%m/%Y",
        "gabarit_ticker": "{ticker}.{pays_bas}",
        "fenetre_jours": 89,
    }
    parametres.update(extras)
    return ConfigApi(**parametres)  # type: ignore[arg-type]


def reglage(configuration: Configuration, **extras: object) -> ConfigSource:
    base = next(s for s in configuration.sources if s.type != "fichier_csv")
    parametres: dict[str, object] = {
        "nom": "api_test",
        "type": "api_json",
        "url_base": API,
        "chemin_fichier": None,
        "actif": True,
        "cache_minutes": 0,
        "tentatives_max": 1,
        "analyseur": None,
        "api": config_api(),
    }
    parametres.update(extras)
    return base.model_copy(update=parametres)


def source_api(
    configuration: Configuration,
    ouvreur: OuvreurSimule,
    dormeur: Callable[[float], None],
    tmp_path: Path,
    **extras: object,
) -> SourceApiJson:
    reglages = reglage(configuration, **extras)
    ingestion = configuration.ingestion.model_copy(update={"repertoire_cache": tmp_path / "cache"})
    client = ClientHttp(reglages, ingestion, ouvreur, dormeur)
    return SourceApiJson(reglages, configuration, client=client)


def ouvreur_avec(*reponses: object) -> OuvreurSimule:
    return OuvreurSimule({ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), API: list(reponses)})


class TestRefusDeDeviner:
    def test_sans_bloc_api_la_source_refuse_dexister(self, configuration: Configuration) -> None:
        """Un schéma deviné produirait des cours faux sans le dire : la source
        n'est pas construite du tout."""
        with pytest.raises(ErreurSource, match="ne devine aucun schéma"):
            SourceApiJson(reglage(configuration, api=None), configuration)

    def test_sans_url_la_source_refuse_dexister(self, configuration: Configuration) -> None:
        with pytest.raises(ErreurSource, match="url_base"):
            SourceApiJson(
                reglage(configuration, url_base=None, chemin_fichier=Path("x.csv")), configuration
            )

    def test_correspondance_sans_date_de_seance_refusee(self) -> None:
        with pytest.raises(ValueError, match="date_seance"):
            config_api(champs={"Close": "cloture"})

    def test_correspondance_vers_un_champ_inconnu_refusee(self) -> None:
        with pytest.raises(ValueError, match="Champs inconnus"):
            config_api(champs={"Date": "date_seance", "Cap": "capitalisation"})

    def test_user_agent_non_surchargeable_en_configuration(self) -> None:
        """L'identité annoncée aux serveurs doit rester vraie : une source ne peut
        pas se faire passer pour un navigateur."""
        with pytest.raises(ValueError, match="User-Agent"):
            config_api(entetes={"User-Agent": "Mozilla/5.0"})


class TestCollecteNominale:
    def test_une_requete_par_valeur_active(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """TEST3 est inactif dans le référentiel : il n'est pas interrogé."""
        ouvreur = ouvreur_avec(reponse(barre("02/03/2026")), reponse(barre("02/03/2026")))
        source = source_api(configuration, ouvreur, dormeur, tmp_path)
        source.collecter(date(2026, 3, 2))
        assert ouvreur.nb_appels(API) == 2

    def test_champs_traduits_et_seance_retenue(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(
            reponse(barre("27/02/2026", 900), barre("02/03/2026", 1000)),
            reponse(barre("02/03/2026", 2000)),
        )
        source = source_api(configuration, ouvreur, dormeur, tmp_path)
        resultat = source.collecter(date(2026, 3, 2))

        assert resultat.statut is StatutCollecte.SUCCES
        cotations = [ligne.cotation for ligne in resultat.lignes_exploitables]
        assert {c.ticker for c in cotations if c} == {"TEST1", "TEST2"}
        premiere = next(c for c in cotations if c and c.ticker == "TEST1")
        assert premiere.date_seance == date(2026, 3, 2)
        assert (premiere.ouverture, premiere.plus_haut, premiere.plus_bas) == (1000, 1020, 980)
        assert premiere.cloture == 1000
        assert premiere.volume_titres == 500
        # La barre du 27/02 était dans la fenêtre reçue mais hors de la séance visée.
        assert all(c and c.date_seance == date(2026, 3, 2) for c in cotations)

    def test_ticker_du_systeme_conserve_malgre_le_gabarit(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Le gabarit `{ticker}.{pays_bas}` est une convention d'appel de la source.
        La clé en base reste le ticker du référentiel."""
        source = source_api(
            configuration, ouvreur_avec(reponse(barre("02/03/2026"))), dormeur, tmp_path
        )
        univers = {i.ticker: i for i in source.instruments}
        assert source.ticker_source(univers["TEST1"]) == "TEST1.ci"
        assert source.ticker_source(univers["TEST2"]) == "TEST2.sn"

    def test_statut_de_seance_deduit_du_volume_seulement(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Un volume nul ne prouve pas une séance sans transaction : le statut
        reste INCONNU et un avertissement le dit."""
        ouvreur = ouvreur_avec(
            reponse(barre("02/03/2026", 1000, volume=0)),
            reponse(barre("02/03/2026", 1000, volume=7)),
        )
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        statuts = {c.ticker: c.statut_seance for ligne in resultat.lignes if (c := ligne.cotation)}
        assert statuts["TEST1"] is StatutSeance.INCONNU
        assert statuts["TEST2"] is StatutSeance.COTEE
        assert any("volume nul" in avertissement for avertissement in resultat.avertissements)

    def test_horodatage_porte_la_seance_pas_la_collecte(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une barre du 27 février collectée aujourd'hui date du 27 février : la
        dater d'aujourd'hui rendrait tout indicateur de fraîcheur mensonger."""
        ouvreur = ouvreur_avec(reponse(barre("27/02/2026")), reponse(barre("27/02/2026")))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(
            date(2026, 2, 27)
        )
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.horodatage_donnee.date() == date(2026, 2, 27)


class TestFenetreEtHistorique:
    def test_corps_porte_la_fenetre_demandee(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        envoyes: list[dict[str, str]] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                donnees = getattr(requete, "data", None)
                if donnees:
                    envoyes.append(json.loads(donnees.decode("utf-8")))
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), API: [reponse(), reponse()]}
        )
        source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))

        assert envoyes[0] == {
            "ticker": "TEST1.ci",
            "datedeb": "2025-12-03",  # 89 jours avant la séance visée
            "datefin": "2026-03-02",
            "xperiod": "0",
        }

    def test_format_de_date_de_requete_distinct_de_celui_de_la_reponse(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        envoyes: list[dict[str, str]] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                donnees = getattr(requete, "data", None)
                if donnees:
                    envoyes.append(json.loads(donnees.decode("utf-8")))
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), API: [reponse(), reponse()]}
        )
        source_api(
            configuration,
            ouvreur,
            dormeur,
            tmp_path,
            api=config_api(format_date_requete="%d/%m/%Y"),
        ).collecter(date(2026, 3, 2))
        assert envoyes[0]["datefin"] == "02/03/2026"

    def test_sans_seance_visee_seule_la_plus_recente_est_retenue(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """« Temps réel » se lit ici « dernière donnée disponible »."""
        ouvreur = ouvreur_avec(
            reponse(barre("27/02/2026", 900), barre("02/03/2026", 1000)),
            reponse(barre("26/02/2026", 800)),
        )
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter()
        seances = {c.ticker: c.date_seance for ligne in resultat.lignes if (c := ligne.cotation)}
        assert seances == {"TEST1": date(2026, 3, 2), "TEST2": date(2026, 2, 26)}

    def test_mode_historique_conserve_toute_la_fenetre(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(
            reponse(barre("27/02/2026", 900), barre("02/03/2026", 1000)),
            reponse(barre("27/02/2026", 900), barre("02/03/2026", 1000)),
        )
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(historique=True)
        ).collecter(date(2026, 3, 2))
        assert len(resultat.lignes) == 4

    def test_seance_absente_de_la_fenetre_ne_produit_rien(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une valeur qui n'a pas coté ce jour-là ne reçoit pas de cours reporté."""
        ouvreur = ouvreur_avec(reponse(barre("27/02/2026")), reponse(barre("27/02/2026")))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.lignes == ()


class TestEnTetes:
    def test_entetes_declares_sont_envoyes_avec_le_ticker(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        vus: list[str] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                referer = getattr(requete, "headers", {}).get("Referer")
                if referer:
                    vus.append(referer)
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), API: [reponse(), reponse()]}
        )
        source_api(
            configuration,
            ouvreur,
            dormeur,
            tmp_path,
            api=config_api(entetes={"Referer": f"{HOTE}/historiques/{{ticker}}"}),
        ).collecter(date(2026, 3, 2))
        assert vus == [f"{HOTE}/historiques/TEST1.ci", f"{HOTE}/historiques/TEST2.sn"]


class TestEchecsEtDegradation:
    def test_une_valeur_en_echec_nemporte_pas_les_autres(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        panne = urllib.error.HTTPError(API, 500, "Boom", None, None)  # type: ignore[arg-type]
        ouvreur = ouvreur_avec(panne, reponse(barre("02/03/2026", 2000)))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.statut is StatutCollecte.PARTIEL
        assert len(resultat.lignes) == 1
        assert any("TEST1" in avertissement for avertissement in resultat.avertissements)
        assert any("1 valeur(s) sur 2" in a for a in resultat.avertissements)

    def test_toutes_les_valeurs_en_echec_donnent_un_echec(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        panne = urllib.error.HTTPError(API, 500, "Boom", None, None)  # type: ignore[arg-type]
        resultat = source_api(configuration, ouvreur_avec(panne), dormeur, tmp_path).collecter(
            date(2026, 3, 2)
        )
        assert resultat.statut is StatutCollecte.ECHEC
        assert resultat.lignes == ()

    def test_chemin_de_liste_faux_nomme_les_cles_disponibles(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"donnees": []})))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.statut is StatutCollecte.ECHEC
        assert any("donnees" in avertissement for avertissement in resultat.avertissements)

    def test_reponse_non_json_est_signalee_telle_quelle(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee("<html>maintenance</html>"))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.statut is StatutCollecte.ECHEC
        assert any("pas renvoyé du JSON" in a for a in resultat.avertissements)

    def test_liste_dobjets_attendue(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"lst": ["1000", "1010"]})))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert any("et non un objet" in a for a in resultat.avertissements)

    def test_cache_perime_degrade_la_collecte_sans_masquer_lage(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """La source tombe après un appel réussi : le cache est servi, signalé."""
        panne = urllib.error.HTTPError(API, 500, "Boom", None, None)  # type: ignore[arg-type]
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                API: [reponse(barre("02/03/2026")), reponse(barre("02/03/2026")), panne, panne],
            }
        )
        source = source_api(configuration, ouvreur, dormeur, tmp_path)
        assert source.collecter(date(2026, 3, 2)).statut is StatutCollecte.SUCCES

        degradee = source.collecter(date(2026, 3, 2))
        assert degradee.statut is StatutCollecte.DEGRADE
        assert any("cache local" in a for a in degradee.avertissements)
        assert len(degradee.lignes) == 2


class TestRejetsDeLigne:
    def test_date_hors_format_declare_refuse_la_reponse(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une date qui ne respecte pas le format déclaré n'est pas réinterprétée :
        c'est la seule protection contre un 03/02 lu pour un 02/03. La valeur est
        écartée avec le message qui dit quoi vérifier, les autres sont collectées."""
        ouvreur = ouvreur_avec(
            reponse({**barre("02/03/2026"), "Date": "2026-03-02"}),
            reponse(barre("02/03/2026")),
        )
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.statut is StatutCollecte.PARTIEL
        assert [ligne.cotation.ticker for ligne in resultat.lignes if ligne.cotation] == ["TEST2"]
        assert any("api.format_date" in a for a in resultat.avertissements)

    def test_format_de_date_ambigu_nest_jamais_devine(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """03/02/2026 est le 3 février si le format déclaré est jj/mm/aaaa, et
        rien d'autre. Aucune heuristique ne vient « corriger » l'ordre."""
        ouvreur = ouvreur_avec(reponse(barre("03/02/2026")), reponse(barre("03/02/2026")))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 2, 3))
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None and cotation.date_seance == date(2026, 2, 3)

    def test_cours_decimal_rejete(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Un cours à décimales signale une mauvaise colonne ou une conversion de
        devise : le XOF ne circule pas en centimes."""
        ouvreur = ouvreur_avec(reponse({**barre("02/03/2026"), "Close": 1000.5}), reponse())
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert len(resultat.lignes_en_erreur) == 1
        assert "décimales" in (resultat.lignes_en_erreur[0].erreur or "")

    def test_nombre_json_entier_flottant_accepte(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """1000.0 est un entier écrit en flottant : c'est la valeur qui compte."""
        ouvreur = ouvreur_avec(reponse({**barre("02/03/2026"), "Close": 1000.0}), reponse())
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None and cotation.cloture == 1000


class TestFabrique:
    def test_type_api_json_construit_le_connecteur(
        self, configuration: Configuration, dossier_config: Path
    ) -> None:
        source = construire_source(reglage(configuration), configuration)
        assert isinstance(source, SourceApiJson)
        assert [i.ticker for i in source.instruments] == ["TEST1", "TEST2"]

    def test_univers_injecte_court_circuite_le_fichier(
        self, configuration: Configuration, dossier_config: Path
    ) -> None:
        univers = charger_univers(dossier_config / "univers_test.csv")[:1]
        source = SourceApiJson(reglage(configuration), configuration, instruments=univers)
        assert [i.ticker for i in source.instruments] == ["TEST1"]


class TestSchemaDeReponse:
    """Le chemin et la correspondance sont déclarés : ce qui n'y colle pas est dit."""

    def test_chemin_pointe_descend_dans_la_reponse(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(
            ReponseSimulee(json.dumps({"data": {"series": [barre("02/03/2026")]}})),
            ReponseSimulee(json.dumps({"data": {"series": []}})),
        )
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(chemin_liste="data.series")
        ).collecter(date(2026, 3, 2))
        assert len(resultat.lignes) == 1

    def test_segment_numerique_indexe_une_liste(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(
            ReponseSimulee(json.dumps({"lots": [[barre("02/03/2026")], []]})),
            ReponseSimulee(json.dumps({"lots": [[], []]})),
        )
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(chemin_liste="lots.0")
        ).collecter(date(2026, 3, 2))
        assert len(resultat.lignes) == 1

    def test_chemin_traversant_une_valeur_scalaire_est_dit(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"lst": 42})))
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(chemin_liste="lst.lignes")
        ).collecter(date(2026, 3, 2))
        assert any("ne se parcourt pas" in a for a in resultat.avertissements)

    def test_index_hors_liste_est_dit(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"lst": []})))
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(chemin_liste="lst.3")
        ).collecter(date(2026, 3, 2))
        assert any("0 élément(s)" in a for a in resultat.avertissements)

    def test_liste_nulle_vaut_absence_de_donnee_pas_erreur(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une API qui répond `null` dit « rien pour cette valeur », ce qui est une
        réponse valable sur un marché où beaucoup de titres ne cotent pas."""
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"lst": None})))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert resultat.lignes == ()
        assert not any("Chemin" in a for a in resultat.avertissements)

    def test_chemin_menant_a_un_objet_au_lieu_dune_liste_est_dit(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = ouvreur_avec(ReponseSimulee(json.dumps({"lst": {"Date": "02/03/2026"}})))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert any("ne mène pas à une liste" in a for a in resultat.avertissements)

    def test_reponse_vide_sans_seance_visee_ne_produit_rien(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Aucune barre reçue : le connecteur ne rapporte rien, et surtout pas la
        dernière valeur connue d'ailleurs."""
        resultat = source_api(
            configuration, ouvreur_avec(reponse(), reponse()), dormeur, tmp_path
        ).collecter()
        assert resultat.lignes == ()

    def test_enregistrement_sans_date_est_ignore_pas_devine(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Une barre sans date ne se voit pas attribuer la séance visée."""
        sans_date = {cle: valeur for cle, valeur in barre("02/03/2026").items() if cle != "Date"}
        ouvreur = ouvreur_avec(
            reponse(sans_date, barre("02/03/2026")), reponse(barre("02/03/2026"))
        )
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        assert len(resultat.lignes) == 2  # une par valeur, la barre sans date écartée

    def test_champ_declare_absent_de_la_reponse_reste_absent(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Un champ manquant reste manquant : il n'est jamais remplacé par zéro."""
        sans_ouverture = {
            cle: valeur for cle, valeur in barre("02/03/2026").items() if cle != "Open"
        }
        ouvreur = ouvreur_avec(reponse(sans_ouverture), reponse(barre("02/03/2026")))
        resultat = source_api(configuration, ouvreur, dormeur, tmp_path).collecter(date(2026, 3, 2))
        cotation = next(
            c for ligne in resultat.lignes if (c := ligne.cotation) and c.ticker == "TEST1"
        )
        assert cotation.ouverture is None
        assert cotation.cloture == 1000

    def test_ticker_fourni_par_la_reponse_prime_sur_le_referentiel(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Quand la source publie elle-même le ticker, c'est le sien qui fait foi —
        et le contrôle « ticker inconnu » de l'ingestion signalera un écart."""
        champs = {**CHAMPS, "Sym": "ticker"}
        ouvreur = ouvreur_avec(
            reponse({**barre("02/03/2026"), "Sym": "AUTRE"}), reponse(barre("02/03/2026"))
        )
        resultat = source_api(
            configuration, ouvreur, dormeur, tmp_path, api=config_api(champs=champs)
        ).collecter(date(2026, 3, 2))
        assert resultat.lignes[0].cotation is not None
        assert resultat.lignes[0].cotation.ticker == "AUTRE"

    def test_gabarit_a_jeton_inconnu_est_dit(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        source = source_api(
            configuration,
            ouvreur_avec(reponse()),
            dormeur,
            tmp_path,
            api=config_api(gabarit_ticker="{ticker}.{region}"),
        )
        with pytest.raises(ErreurSource, match="Jetons acceptés"):
            source.ticker_source(source.instruments[0])

    def test_sans_corps_declare_la_requete_reste_un_get(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        methodes: list[str] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                methodes.append(getattr(requete, "method", "?") or "?")
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), API: [reponse(), reponse()]}
        )
        source_api(configuration, ouvreur, dormeur, tmp_path, api=config_api(corps={})).collecter(
            date(2026, 3, 2)
        )
        assert set(methodes[1:]) == {"GET"}


class TestDisponibilite:
    def test_robots_interdisant_rend_la_source_indisponible(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Indisponible est une information d'exploitation : l'orchestrateur passe
        à la source suivante et le consigne, il ne plante pas."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee("User-agent: *\nDisallow: /\n"), API: [reponse()]}
        )
        assert source_api(configuration, ouvreur, dormeur, tmp_path).disponible() is False

    def test_robots_permissif_rend_la_source_disponible(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        assert source_api(configuration, ouvreur_avec(reponse()), dormeur, tmp_path).disponible()
