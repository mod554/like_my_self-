"""Politique réseau : robots.txt, reprises, temporisation, cache, mode dégradé."""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aides import OuvreurSimule, ReponseSimulee

from brvm.config.modeles import ConfigSource, Configuration
from brvm.ingestion.http import ClientHttp
from brvm.utils.erreurs import ErreurSource

HOTE = "https://exemple-test.invalid"
ROBOTS = f"{HOTE}/robots.txt"
PAGE = f"{HOTE}/cote"

ROBOTS_PERMISSIF = "User-agent: *\nDisallow:\n"
ROBOTS_INTERDIT = "User-agent: *\nDisallow: /\n"


def reglage(configuration: Configuration, **extras: object) -> ConfigSource:
    base = next(s for s in configuration.sources if s.type != "fichier_csv")
    parametres: dict[str, object] = {
        "url_base": PAGE,
        "actif": True,
        "tentatives_max": 3,
        "backoff_initial_s": 1,
        "backoff_facteur": 2,
        "cache_minutes": 0,
        "timeout_s": 5,
    }
    parametres.update(extras)
    return base.model_copy(update=parametres)


def client(
    configuration: Configuration,
    ouvreur: OuvreurSimule,
    dormeur: Callable[[float], None],
    cache: Path | None = None,
    **extras: object,
) -> ClientHttp:
    ingestion = configuration.ingestion
    if cache is not None:
        ingestion = ingestion.model_copy(update={"repertoire_cache": cache})
    return ClientHttp(reglage(configuration, **extras), ingestion, ouvreur, dormeur)


class TestSchema:
    def test_http_en_clair_refuse(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule({})
        with pytest.raises(ErreurSource, match="https"):
            client(configuration, ouvreur, dormeur).recuperer("http://exemple-test.invalid/cote")
        assert ouvreur.appels == []


class TestRobots:
    def test_robots_permissif_autorise(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("<html/>")}
        )
        reponse = client(configuration, ouvreur, dormeur).recuperer(PAGE)
        assert reponse.code == 200
        assert ouvreur.nb_appels(ROBOTS) == 1

    def test_robots_interdit_bloque_la_collecte(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_INTERDIT), PAGE: ReponseSimulee("<html/>")}
        )
        with pytest.raises(ErreurSource, match=r"robots\.txt"):
            client(configuration, ouvreur, dormeur).recuperer(PAGE)
        assert ouvreur.nb_appels(PAGE) == 0

    def test_robots_absent_vaut_autorisation(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Un 404 sur robots.txt signifie qu'aucune règle n'est publiée."""
        ouvreur = OuvreurSimule(
            {
                ROBOTS: urllib.error.HTTPError(ROBOTS, 404, "Not Found", None, None),  # type: ignore[arg-type]
                PAGE: ReponseSimulee("<html/>"),
            }
        )
        assert client(configuration, ouvreur, dormeur).recuperer(PAGE).code == 200

    def test_robots_en_erreur_serveur_bloque(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Dans le doute on s'abstient : un robots.txt illisible n'est pas une permission."""
        ouvreur = OuvreurSimule(
            {
                ROBOTS: urllib.error.HTTPError(ROBOTS, 503, "Unavailable", None, None),  # type: ignore[arg-type]
                PAGE: ReponseSimulee("<html/>"),
            }
        )
        with pytest.raises(ErreurSource, match=r"robots\.txt"):
            client(configuration, ouvreur, dormeur).recuperer(PAGE)
        assert ouvreur.nb_appels(PAGE) == 0

    def test_robots_ignore_si_configure(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Le contournement existe mais doit être un choix explicite et tracé."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_INTERDIT), PAGE: ReponseSimulee("<html/>")}
        )
        connexion = client(configuration, ouvreur, dormeur, respecter_robots=False)
        assert connexion.recuperer(PAGE).code == 200

    def test_robots_relu_une_seule_fois(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("<html/>")}
        )
        connexion = client(configuration, ouvreur, dormeur)
        connexion.recuperer(PAGE)
        connexion.recuperer(PAGE)
        assert ouvreur.nb_appels(ROBOTS) == 1

    def test_crawl_delay_annonce_prime_sur_le_delai_configure(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee("User-agent: *\nCrawl-delay: 5\nDisallow:\n"),
                PAGE: ReponseSimulee("<html/>"),
            }
        )
        connexion = client(configuration, ouvreur, dormeur)
        connexion.recuperer(PAGE)
        connexion.recuperer(PAGE)
        attentes = dormeur.attentes  # type: ignore[attr-defined]
        assert attentes and max(attentes) == pytest.approx(5, abs=0.5)


class TestReprises:
    def test_reprise_apres_erreur_transitoire(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: [
                    urllib.error.HTTPError(PAGE, 503, "Unavailable", None, None),  # type: ignore[arg-type]
                    ReponseSimulee("<html/>"),
                ],
            }
        )
        assert client(configuration, ouvreur, dormeur).recuperer(PAGE).code == 200
        assert ouvreur.nb_appels(PAGE) == 2

    def test_pas_de_reprise_sur_erreur_definitive(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Réessayer un 404 ne fait qu'importuner le serveur."""
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: urllib.error.HTTPError(PAGE, 404, "Not Found", None, None),  # type: ignore[arg-type]
            }
        )
        with pytest.raises(ErreurSource):
            client(configuration, ouvreur, dormeur).recuperer(PAGE)
        assert ouvreur.nb_appels(PAGE) == 1

    def test_recul_exponentiel(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: urllib.error.HTTPError(PAGE, 503, "Unavailable", None, None),  # type: ignore[arg-type]
            }
        )
        with pytest.raises(ErreurSource):
            client(
                configuration, ouvreur, dormeur, tentatives_max=4, backoff_initial_s=1
            ).recuperer(PAGE)
        assert ouvreur.nb_appels(PAGE) == 4
        assert dormeur.attentes == [1.0, 2.0, 4.0, 8.0]  # type: ignore[attr-defined]

    def test_erreur_reseau_donne_lieu_a_reprise(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: [urllib.error.URLError("connexion refusée"), ReponseSimulee("<html/>")],
            }
        )
        assert client(configuration, ouvreur, dormeur).recuperer(PAGE).code == 200


class TestCache:
    def test_cache_frais_evite_une_requete(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("<html/>")}
        )
        connexion = client(configuration, ouvreur, dormeur, cache=tmp_path, cache_minutes=60)
        connexion.recuperer(PAGE)
        seconde = connexion.recuperer(PAGE)
        assert ouvreur.nb_appels(PAGE) == 1
        assert seconde.depuis_cache is True
        assert seconde.cache_perime is False

    def test_mode_degrade_sert_un_cache_perime(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Source tombée : on sert la dernière donnée connue, explicitement datée."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("<html>vieux</html>")}
        )
        connexion = client(configuration, ouvreur, dormeur, cache=tmp_path, cache_minutes=0)
        connexion.recuperer(PAGE)

        tombee = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: urllib.error.URLError("serveur injoignable"),
            }
        )
        degradee = client(configuration, tombee, dormeur, cache=tmp_path, cache_minutes=0)
        reponse = degradee.recuperer(PAGE)
        assert reponse.cache_perime is True
        assert reponse.texte() == "<html>vieux</html>"

    def test_sans_cache_et_source_tombee_rien_n_est_invente(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: urllib.error.URLError("serveur injoignable"),
            }
        )
        with pytest.raises(ErreurSource, match="aucune donnée en cache"):
            client(configuration, ouvreur, dormeur, cache=tmp_path).recuperer(PAGE)


class TestRequetePost:
    """Une API interrogée en POST reste une requête adressée à un hôte."""

    def test_corps_json_declenche_un_post_type(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        vues: list[tuple[str, bytes | None, str | None]] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                vues.append(
                    (
                        getattr(requete, "method", "?") or "?",
                        getattr(requete, "data", None),
                        getattr(requete, "headers", {}).get("Content-type"),
                    )
                )
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("{}")}
        )
        client(configuration, ouvreur, dormeur).recuperer(PAGE, corps_json={"ticker": "TEST1"})

        methode, corps, type_contenu = vues[-1]
        assert methode == "POST"
        assert corps == b'{"ticker": "TEST1"}'
        assert type_contenu == "application/json"

    def test_le_robots_txt_est_consulte_aussi_pour_un_post(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_INTERDIT), PAGE: ReponseSimulee("{}")}
        )
        with pytest.raises(ErreurSource, match=r"robots\.txt"):
            client(configuration, ouvreur, dormeur).recuperer(PAGE, corps_json={"a": "1"})
        assert ouvreur.nb_appels(PAGE) == 0

    def test_deux_corps_differents_ne_partagent_pas_leur_cache(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        """Sur une API interrogée valeur par valeur, l'URL est la même pour toutes :
        confondre leurs caches servirait le cours d'une valeur pour une autre."""
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: [ReponseSimulee('{"v": 1}'), ReponseSimulee('{"v": 2}')],
            }
        )
        connexion = client(configuration, ouvreur, dormeur, cache=tmp_path, cache_minutes=60)
        premiere = connexion.recuperer(PAGE, corps_json={"ticker": "TEST1"})
        seconde = connexion.recuperer(PAGE, corps_json={"ticker": "TEST2"})
        assert (premiere.texte(), seconde.texte()) == ('{"v": 1}', '{"v": 2}')
        assert ouvreur.nb_appels(PAGE) == 2

        # Le même corps, lui, retrouve bien son entrée de cache.
        assert connexion.recuperer(PAGE, corps_json={"ticker": "TEST1"}).depuis_cache is True
        assert ouvreur.nb_appels(PAGE) == 2

    def test_ordre_des_cles_du_corps_sans_effet_sur_le_cache(
        self, configuration: Configuration, dormeur: Callable[[float], None], tmp_path: Path
    ) -> None:
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("{}")}
        )
        connexion = client(configuration, ouvreur, dormeur, cache=tmp_path, cache_minutes=60)
        connexion.recuperer(PAGE, corps_json={"a": "1", "b": "2"})
        rejoue = connexion.recuperer(PAGE, corps_json={"b": "2", "a": "1"})
        assert rejoue.depuis_cache is True
        assert ouvreur.nb_appels(PAGE) == 1

    def test_entetes_declares_sont_transmis(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        vus: list[str | None] = []

        class OuvreurEspion(OuvreurSimule):
            def __call__(self, requete: object, timeout: float) -> ReponseSimulee:
                vus.append(getattr(requete, "headers", {}).get("Referer"))
                return super().__call__(requete, timeout)

        ouvreur = OuvreurEspion(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("{}")}
        )
        client(configuration, ouvreur, dormeur).recuperer(PAGE, entetes={"Referer": HOTE})
        assert vus[-1] == HOTE

    def test_identite_non_surchargeable(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Se faire passer pour un navigateur contredirait l'engagement de respecter
        les conditions d'utilisation de la source. La requête n'est pas émise."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("{}")}
        )
        with pytest.raises(ErreurSource, match="User-Agent"):
            client(configuration, ouvreur, dormeur).recuperer(
                PAGE, entetes={"user-agent": "Mozilla/5.0"}
            )
        assert ouvreur.nb_appels(PAGE) == 0


class TestFraicheur:
    def test_last_modified_devient_l_horodatage_de_donnee(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: ReponseSimulee("<html/>", {"Last-Modified": "Mon, 02 Mar 2026 15:30:00 GMT"}),
            }
        )
        reponse = client(configuration, ouvreur, dormeur).recuperer(PAGE)
        assert reponse.horodatage_donnee == datetime(2026, 3, 2, 15, 30, tzinfo=UTC)

    def test_sans_en_tete_de_date_l_horodatage_reste_inconnu(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        """Le système ne fabrique pas une date de donnée à partir de rien."""
        ouvreur = OuvreurSimule(
            {ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF), PAGE: ReponseSimulee("<html/>")}
        )
        assert client(configuration, ouvreur, dormeur).recuperer(PAGE).horodatage_donnee is None

    def test_age_calcule_depuis_la_date_de_donnee(
        self, configuration: Configuration, dormeur: Callable[[float], None]
    ) -> None:
        ouvreur = OuvreurSimule(
            {
                ROBOTS: ReponseSimulee(ROBOTS_PERMISSIF),
                PAGE: ReponseSimulee("<html/>", {"Last-Modified": "Mon, 02 Mar 2026 15:30:00 GMT"}),
            }
        )
        reponse = client(configuration, ouvreur, dormeur).recuperer(PAGE)
        age = reponse.age_minutes(datetime(2026, 3, 2, 17, 30, tzinfo=UTC))
        assert age == 120
