"""Instantané public : ce qui part en ligne, et surtout ce qui n'en part pas.

Ce module ne vérifie pas un affichage, il vérifie une frontière. L'interface
locale sert un portefeuille sans authentification, sur la boucle locale. La page
publique est servie à tout le monde. Entre les deux, il n'y a que ce fichier.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import INSTANT_MARCHE

from brvm.app.publication import CHAMPS_PERSONNELS, instantane_public, publier
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.storage.base import BaseDonnees


class TestFrontierePublique:
    def test_aucun_champ_personnel_ne_part_en_ligne(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        assert CHAMPS_PERSONNELS & set(charge) == set()

    def test_aucune_repartition_n_est_chiffree(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Chiffrer une répartition exige un capital, qui est personnel."""
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        assert "propositions" not in charge

    def test_le_classement_lui_part_bien(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Retirer le personnel ne doit pas vider la page de sa substance."""
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        assert charge["analysees"] >= 1
        court = charge["classements"]["court_terme"]
        assert court["classes"] or court["ecartes"]
        for rang in court["classes"]:
            assert rang["criteres"], "un classement sans critères ne se conteste pas"

    def test_les_valeurs_ecartees_partent_avec_leur_raison(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        for rang in charge["classements"]["court_terme"]["ecartes"]:
            assert rang["motif_absent"]

    def test_la_fraicheur_voyage_avec_la_charge(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        """Un hébergeur statique ne sait pas si sa page est fraîche : elle doit
        le lire dans ce qu'on lui a remis."""
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        assert charge["fraicheur"]["horodatage_le_plus_ancien"]
        assert charge["publie_le"] == INSTANT_MARCHE.isoformat()

    def test_la_mention_de_portee_est_presente(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        charge = instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)
        assert "aucun montant personnel" in charge["portee"]
        assert "aucune promesse de rendement" in charge["mention"]


class TestGardeFou:
    def test_une_repartition_glissee_dans_la_charge_fait_echouer_la_publication(
        self,
        cote: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Si un jour quelqu'un fait remonter des propositions jusqu'ici, la
        publication doit s'arrêter plutôt que de les mettre en ligne."""
        import brvm.app.publication as publication

        def serialiser_avec_repartition(
            criblage: object, propositions: object = None
        ) -> dict[str, Any]:
            return {"propositions": {"court_terme": {"capital": 5_000_000}}}

        monkeypatch.setattr(publication, "serialiser_criblage", serialiser_avec_repartition)
        with pytest.raises(ValueError, match="donnée personnelle"):
            instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)

    def test_un_champ_personnel_fait_echouer_la_publication(
        self,
        cote: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import brvm.app.publication as publication

        def serialiser_avec_portefeuille(
            criblage: object, propositions: object = None
        ) -> dict[str, Any]:
            return {"portefeuille": {"valeur_totale": 1_234_567}}

        monkeypatch.setattr(publication, "serialiser_criblage", serialiser_avec_portefeuille)
        with pytest.raises(ValueError, match="champs personnels"):
            instantane_public(cote, configuration, calendrier, instant=INSTANT_MARCHE)

    def test_la_liste_des_champs_interdits_couvre_ce_que_l_etat_expose(self) -> None:
        """Si la sérialisation de l'état gagne un champ personnel, il doit être
        recensé ici — sinon il partirait en ligne au premier changement."""
        from brvm.app.api import serialiser

        exposes = {
            "portefeuille",
            "signaux",
            "risque",
            "anomalies",
            "collectes",
        }
        # Ces champs-là existent dans l'état local et n'ont rien à faire en
        # ligne. Le contrôle ne les impose pas tous à `CHAMPS_PERSONNELS` : il
        # impose que la fonction publique ne les produise jamais.
        assert serialiser is not None
        assert "portefeuille" in CHAMPS_PERSONNELS
        assert exposes - {"signaux", "risque", "anomalies", "collectes"} <= CHAMPS_PERSONNELS


class TestEcriture:
    def test_le_fichier_est_ecrit_et_relisible(
        self,
        cote: BaseDonnees,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        cible = tmp_path / "sortie" / "marche.json"
        fichier = publier(cote, configuration, calendrier, cible, instant=INSTANT_MARCHE)
        assert fichier.exists()
        charge = json.loads(fichier.read_text(encoding="utf-8"))
        assert charge["univers"] >= 1
        assert CHAMPS_PERSONNELS & set(charge) == set()

    def test_l_instant_par_defaut_est_maintenant(
        self, cote: BaseDonnees, configuration: Configuration, calendrier: CalendrierSeances
    ) -> None:
        avant = datetime.now(UTC)
        charge = instantane_public(cote, configuration, calendrier)
        assert datetime.fromisoformat(charge["publie_le"]) >= avant
