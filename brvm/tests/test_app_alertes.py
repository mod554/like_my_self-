"""Alertes : construction des canaux, diffusion tolérante à la panne, dédoublonnage."""

from __future__ import annotations

import json
import smtplib
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from brvm.app.alertes import (
    ORDRE_GRAVITE,
    Alerte,
    CanalEmail,
    CanalFichier,
    CanalWebhook,
    CategorieAlerte,
    Diffuseur,
    NiveauAlerte,
    construire_canaux,
)
from brvm.config.modeles import ConfigAlertes, ConfigCanalAlerte, Configuration
from brvm.utils.erreurs import ErreurConfiguration

INSTANT = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)


def alerte(
    titre: str = "Constat",
    niveau: NiveauAlerte = NiveauAlerte.AVERTISSEMENT,
    ticker: str | None = "TEST1",
    categorie: CategorieAlerte = CategorieAlerte.DONNEE_PERIMEE,
) -> Alerte:
    return Alerte(
        categorie=categorie,
        niveau=niveau,
        titre=titre,
        message="Message de test.",
        emise_le=INSTANT,
        ticker=ticker,
    )


class CanalEspion:
    def __init__(self, nom: str = "espion", panne: Exception | None = None) -> None:
        self.nom = nom
        self.panne = panne
        self.recus: list[Alerte] = []

    def diffuser(self, alertes: Any) -> None:
        if self.panne is not None:
            raise self.panne
        self.recus.extend(alertes)


class TestGravite:
    def test_lordre_est_declare_pas_alphabetique(self) -> None:
        """« INFORMATION » passerait devant « CRITIQUE » dans un tri de texte."""
        assert ORDRE_GRAVITE[-1] is NiveauAlerte.CRITIQUE
        assert NiveauAlerte.CRITIQUE.rang > NiveauAlerte.AVERTISSEMENT.rang
        assert NiveauAlerte.AVERTISSEMENT.rang > NiveauAlerte.INFORMATION.rang
        assert max(NiveauAlerte) == "INFORMATION"  # le piège que l'on évite

    def test_horodatage_sans_fuseau_refuse(self) -> None:
        with pytest.raises(ValueError, match="fuseau"):
            Alerte(
                categorie=CategorieAlerte.ECHEC_SOURCE,
                niveau=NiveauAlerte.CRITIQUE,
                titre="x",
                message="y",
                emise_le=datetime(2026, 3, 2, 16, 0),
            )


class TestCanalFichier:
    def test_ecrit_une_ligne_json_par_alerte(self, tmp_path: Path) -> None:
        canal = CanalFichier("journal", tmp_path / "sous" / "alertes.jsonl")
        canal.diffuser([alerte("Un"), alerte("Deux")])
        lignes = (tmp_path / "sous" / "alertes.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(ligne)["titre"] for ligne in lignes] == ["Un", "Deux"]

    def test_ajoute_sans_ecraser(self, tmp_path: Path) -> None:
        canal = CanalFichier("journal", tmp_path / "alertes.jsonl")
        canal.diffuser([alerte("Un")])
        canal.diffuser([alerte("Deux")])
        assert len((tmp_path / "alertes.jsonl").read_text(encoding="utf-8").splitlines()) == 2

    def test_chemin_manquant_refuse_a_la_construction(self) -> None:
        with pytest.raises(ErreurConfiguration, match="chemin"):
            CanalFichier.depuis_config(
                ConfigCanalAlerte(nom="journal", type="fichier", actif=True, parametres={})
            )


class SessionSmtpSimulee:
    """Doublure SMTP : enregistre ce qui aurait été envoyé."""

    envoyes: ClassVar[list[Any]] = []
    connexions: ClassVar[list[tuple[str, int]]] = []

    def __init__(self, serveur: str, port: int, timeout: float) -> None:
        SessionSmtpSimulee.connexions.append((serveur, port))
        self.starttls_appele = False

    def __enter__(self) -> SessionSmtpSimulee:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self) -> None:
        self.starttls_appele = True

    def login(self, utilisateur: str, motdepasse: str) -> None:
        return None

    def send_message(self, message: Any) -> None:
        SessionSmtpSimulee.envoyes.append(message)


class TestCanalEmail:
    def test_objet_porte_la_pire_gravite(self) -> None:
        SessionSmtpSimulee.envoyes.clear()
        canal = CanalEmail(
            "courriel",
            "smtp.test.invalid",
            587,
            "robot@test.invalid",
            ["moi@test.invalid"],
            fabrique=SessionSmtpSimulee,
        )
        canal.diffuser(
            [alerte("Info", NiveauAlerte.INFORMATION), alerte("Grave", NiveauAlerte.CRITIQUE)]
        )
        message = SessionSmtpSimulee.envoyes[-1]
        assert "CRITIQUE" in message["Subject"]
        assert "2 constat(s)" in message["Subject"]

    def test_le_corps_rappelle_quil_ne_sagit_pas_dun_conseil(self) -> None:
        SessionSmtpSimulee.envoyes.clear()
        canal = CanalEmail(
            "courriel",
            "smtp.test.invalid",
            587,
            "robot@test.invalid",
            ["moi@test.invalid"],
            fabrique=SessionSmtpSimulee,
        )
        canal.diffuser([alerte()])
        corps = SessionSmtpSimulee.envoyes[-1].get_content()
        assert "Aucune recommandation" in corps
        assert "promesse de rendement" in corps

    @pytest.mark.parametrize("manquant", ["serveur", "port", "expediteur", "destinataires"])
    def test_parametre_manquant_nomme(self, manquant: str) -> None:
        parametres = {
            "serveur": "smtp.test.invalid",
            "port": "587",
            "expediteur": "robot@test.invalid",
            "destinataires": "moi@test.invalid",
        }
        del parametres[manquant]
        with pytest.raises(ErreurConfiguration, match=manquant):
            CanalEmail.depuis_config(
                ConfigCanalAlerte(nom="c", type="email", actif=True, parametres=parametres)
            )

    def test_port_illisible_refuse(self) -> None:
        with pytest.raises(ErreurConfiguration, match="port illisible"):
            CanalEmail.depuis_config(
                ConfigCanalAlerte(
                    nom="c",
                    type="email",
                    actif=True,
                    parametres={
                        "serveur": "s",
                        "port": "cinq-cent",
                        "expediteur": "a@b.c",
                        "destinataires": "d@e.f",
                    },
                )
            )


class TestCanalWebhook:
    def test_http_en_clair_refuse(self) -> None:
        """Une alerte décrit la composition d'un portefeuille."""
        with pytest.raises(ErreurConfiguration, match="https"):
            CanalWebhook("hook", "http://test.invalid/hook", "agent/1.0")

    def test_envoie_le_lot_en_json(self) -> None:
        vues: list[tuple[str, bytes, dict[str, str]]] = []

        def ouvreur(requete: Any, timeout: float) -> Any:
            vues.append((requete.full_url, requete.data, dict(requete.headers)))
            return None

        canal = CanalWebhook(
            "hook", "https://test.invalid/hook", "agent/1.0", "Bearer x", ouvreur=ouvreur
        )
        canal.diffuser([alerte("Un"), alerte("Deux")])
        url, corps, entetes = vues[0]
        charge = json.loads(corps.decode("utf-8"))
        assert url == "https://test.invalid/hook"
        assert [a["titre"] for a in charge["alertes"]] == ["Un", "Deux"]
        assert entetes["Authorization"] == "Bearer x"
        assert entetes["User-agent"] == "agent/1.0"


class TestConstruction:
    def test_seuls_les_canaux_actifs_sont_construits(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        alertes = ConfigAlertes(
            canaux=(
                ConfigCanalAlerte(
                    nom="journal",
                    type="fichier",
                    actif=True,
                    parametres={"chemin": str(tmp_path / "a.jsonl")},
                ),
                ConfigCanalAlerte(
                    nom="hook", type="webhook", actif=False, parametres={"url": "https://x.invalid"}
                ),
            ),
            age_donnee_max_minutes=1440,
            alerter_signal_technique=True,
            alerter_seuil_risque=True,
            alerter_echec_source=True,
        )
        canaux = construire_canaux(alertes, configuration.ingestion)
        assert [canal.nom for canal in canaux] == ["journal"]


class TestDiffuseur:
    def test_un_canal_en_panne_nempeche_pas_les_autres(self) -> None:
        bon = CanalEspion("bon")
        casse = CanalEspion("casse", urllib.error.URLError("injoignable"))
        resultat = Diffuseur([casse, bon]).diffuser([alerte()])
        assert resultat.canaux_servis == ("bon",)
        assert resultat.canaux_en_echec == ("casse",)
        assert len(bon.recus) == 1
        assert any("injoignable" in message for message in resultat.avertissements)

    def test_une_erreur_smtp_est_rattrapee(self) -> None:
        casse = CanalEspion("smtp", smtplib.SMTPException("refus"))
        resultat = Diffuseur([casse]).diffuser([alerte()])
        assert resultat.canaux_en_echec == ("smtp",)
        assert resultat.diffusee is False

    def test_une_erreur_inattendue_ne_casse_pas_le_cycle(self) -> None:
        casse = CanalEspion("bizarre", RuntimeError("boum"))
        resultat = Diffuseur([casse]).diffuser([alerte()])
        assert resultat.canaux_en_echec == ("bizarre",)

    def test_sans_canal_le_constat_reste_signale(self) -> None:
        """Une alerte que personne ne reçoit doit rester retrouvable."""
        resultat = Diffuseur([]).diffuser([alerte()])
        assert resultat.canaux_servis == ()
        assert any("journal du système" in message for message in resultat.avertissements)

    def test_lot_vide_ne_derange_personne(self) -> None:
        canal = CanalEspion()
        assert Diffuseur([canal]).diffuser([]).alertes == ()
        assert canal.recus == []

    def test_un_constat_deja_diffuse_nest_pas_reemis(self) -> None:
        """Réémettre chaque jour la même alerte finit par la rendre invisible."""
        diffuseur = Diffuseur([CanalEspion()])
        premier = diffuseur.retenir([alerte("Concentration dépassée")])
        assert len(premier) == 1
        diffuseur.diffuser(premier)
        assert diffuseur.retenir([alerte("Concentration dépassée")]) == []

    def test_un_constat_disparu_puis_revenu_est_reemis(self) -> None:
        diffuseur = Diffuseur([CanalEspion()])
        diffuseur.diffuser(diffuseur.retenir([alerte("Concentration dépassée")]))
        diffuseur.oublier_absents([])  # le constat a disparu
        assert len(diffuseur.retenir([alerte("Concentration dépassée")])) == 1

    def test_niveau_minimum_filtre(self) -> None:
        diffuseur = Diffuseur([CanalEspion()], niveau_minimum=NiveauAlerte.AVERTISSEMENT)
        retenues = diffuseur.retenir(
            [alerte("Info", NiveauAlerte.INFORMATION), alerte("Alerte", NiveauAlerte.CRITIQUE)]
        )
        assert [a.titre for a in retenues] == ["Alerte"]

    def test_deux_valeurs_differentes_ne_se_confondent_pas(self) -> None:
        diffuseur = Diffuseur([CanalEspion()])
        diffuseur.diffuser(diffuseur.retenir([alerte("Cours périmé", ticker="TEST1")]))
        assert len(diffuseur.retenir([alerte("Cours périmé", ticker="TEST2")])) == 1
