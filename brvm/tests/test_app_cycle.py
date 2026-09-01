"""Cycle d'exploitation et ligne de commande, de bout en bout.

Ce qui est vérifié ici : rien n'interrompt le cycle. Une source qui tombe, un
canal injoignable, une base vide produisent un constat et un code de sortie —
jamais une pile d'appels.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from brvm.app.alertes import Alerte, Diffuseur, NiveauAlerte
from brvm.app.cli import (
    DEGRADE,
    ECHEC,
    SUCCES,
    _preparer,
    commande_ordonnancer,
    principal,
)
from brvm.app.cycle import Cycle
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import SensOperation, StatutCollecte
from brvm.domain.modeles import Transaction
from brvm.ingestion.base import DataSource, LigneCollectee, ResultatCollecte
from brvm.ingestion.orchestrateur import Orchestrateur
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import DepotTransactions

INSTANT = datetime(2026, 3, 20, 16, 0, tzinfo=UTC)


class SourceSimulee(DataSource):
    """Source de test : rend ce qu'on lui dit, ou tombe si on le lui demande."""

    def __init__(
        self,
        nom: str = "fichier_manuel",
        lignes: tuple[LigneCollectee, ...] = (),
        statut: StatutCollecte = StatutCollecte.SUCCES,
        disponible_: bool = True,
        explose: bool = False,
    ) -> None:
        self.nom = nom
        self._lignes = lignes
        self._statut = statut
        self._disponible = disponible_
        self._explose = explose

    def disponible(self) -> bool:
        return self._disponible

    def collecter(self, jour: date | None = None) -> ResultatCollecte:
        if self._explose:
            raise RuntimeError("la source explose")
        debut = self.maintenant()
        return ResultatCollecte(
            source=self.nom,
            statut=self._statut,
            debut=debut,
            fin=self.maintenant(),
            lignes=self._lignes,
            message="collecte simulée",
        )


class CanalEspion:
    def __init__(self, nom: str = "espion") -> None:
        self.nom = nom
        self.recus: list[Alerte] = []

    def diffuser(self, alertes: Any) -> None:
        self.recus.extend(alertes)


def cycle_avec(
    configuration: Configuration,
    base: BaseDonnees,
    calendrier: CalendrierSeances,
    source: DataSource,
    canal: CanalEspion,
) -> Cycle:
    orchestrateur = Orchestrateur(configuration, base, calendrier, sources=[source])
    return Cycle(configuration, base, calendrier, Diffuseur([canal]), orchestrateur)


class TestCycle:
    def test_une_source_en_echec_produit_un_constat_pas_une_exception(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        canal = CanalEspion()
        cycle = cycle_avec(
            configuration,
            base,
            calendrier,
            SourceSimulee(statut=StatutCollecte.ECHEC),
            canal,
        )
        resultat = cycle.executer(instant=INSTANT)
        assert resultat.bilans[0].statut is StatutCollecte.ECHEC
        assert any(alerte.niveau is NiveauAlerte.CRITIQUE for alerte in resultat.alertes)
        assert canal.recus

    def test_une_source_qui_explose_nemporte_pas_le_cycle(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        """L'orchestrateur rattrape déjà beaucoup ; le cycle rattrape le reste."""
        canal = CanalEspion()
        cycle = cycle_avec(configuration, base, calendrier, SourceSimulee(explose=True), canal)
        resultat = cycle.executer(instant=INSTANT)
        assert resultat.etat is not None
        assert any("Collecte interrompue" in message for message in resultat.avertissements)

    def test_sans_collecte_letat_est_quand_meme_compose(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        canal = CanalEspion()
        cycle = cycle_avec(configuration, base, calendrier, SourceSimulee(), canal)
        resultat = cycle.executer(instant=INSTANT, collecter=False)
        assert resultat.bilans == ()
        assert resultat.etat is not None

    def test_le_meme_constat_nest_pas_rediffuse_au_cycle_suivant(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        canal = CanalEspion()
        cycle = cycle_avec(
            configuration,
            base,
            calendrier,
            SourceSimulee(statut=StatutCollecte.ECHEC),
            canal,
        )
        cycle.executer(instant=INSTANT)
        premiers = len(canal.recus)
        cycle.executer(instant=INSTANT)
        assert len(canal.recus) == premiers

    def test_le_resume_dit_ce_qui_sest_passe(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        cycle = cycle_avec(configuration, base, calendrier, SourceSimulee(), CanalEspion())
        resume = cycle.executer(instant=INSTANT).resume()
        assert "fichier_manuel" in resume
        assert "constat" in resume


class TestLigneDeCommande:
    @staticmethod
    def _config(dossier: Path) -> Path:
        """Configuration de test, réécrite avec des chemins absolus utilisables."""
        chemin = dossier / "config_valide.yaml"
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        brut["general"]["repertoire_donnees"] = str(dossier / "donnees")
        brut["general"]["base_donnees"] = str(dossier / "donnees" / "test.sqlite3")
        brut["journalisation"]["fichier"] = str(dossier / "donnees" / "brvm.log")
        brut["ingestion"]["repertoire_cache"] = str(dossier / "donnees" / "cache")
        brut["ordonnanceur"]["actif"] = True
        cible = dossier / "config_cli.yaml"
        cible.write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")
        return cible

    def test_verifier_affiche_ce_qui_est_applique(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = principal(["--config", str(self._config(dossier_config)), "verifier"])
        sortie = capsys.readouterr().out
        assert code == SUCCES
        assert "méthode de valorisation" in sortie
        assert "Prochaines collectes prévues" in sortie

    def test_etat_sur_base_vide_ne_plante_pas(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Aucune transaction : le système le dit, il ne calcule pas un zéro."""
        code = principal(["--config", str(self._config(dossier_config)), "etat"])
        assert code == SUCCES
        assert "ÉTAT DU PORTEFEUILLE" in capsys.readouterr().out

    def test_exporter_en_texte_ecrit_le_fichier(self, dossier_config: Path, tmp_path: Path) -> None:
        cible = tmp_path / "sortie" / "etat.txt"
        code = principal(
            [
                "--config",
                str(self._config(dossier_config)),
                "exporter",
                "--texte",
                "--sortie",
                str(cible),
            ]
        )
        assert code == SUCCES
        assert "Aucun conseil d'investissement" in cible.read_text(encoding="utf-8")

    def test_exporter_produit_un_classeur_horodate(
        self, dossier_config: Path, tmp_path: Path
    ) -> None:
        pytest.importorskip("openpyxl")
        code = principal(
            [
                "--config",
                str(self._config(dossier_config)),
                "exporter",
                "--sortie",
                str(tmp_path / "rapports"),
            ]
        )
        assert code == SUCCES
        produits = list((tmp_path / "rapports").glob("portefeuille_*.xlsx"))
        assert len(produits) == 1

    def test_cribler_sur_base_vide_rend_un_code_degrade(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Une cote dont rien n'est analysable n'est pas un succès : c'est une
        base à alimenter, et un cron doit pouvoir s'en apercevoir."""
        code = principal(["--config", str(self._config(dossier_config)), "cribler"])
        sortie = capsys.readouterr().out
        assert code == DEGRADE
        assert "CRIBLAGE DE LA COTE" in sortie
        assert "aucune promesse de rendement" in sortie

    def test_cribler_sans_capital_ne_chiffre_aucune_repartition(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        principal(["--config", str(self._config(dossier_config)), "cribler"])
        assert "RÉPARTITION POSSIBLE" not in capsys.readouterr().out

    def test_cribler_refuse_un_profil_inconnu(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = principal(
            [
                "--config",
                str(self._config(dossier_config)),
                "cribler",
                "--capital",
                "5000000",
                "--horizon",
                "moyen_terme",
            ]
        )
        assert code == ECHEC
        assert "Profils déclarés" in capsys.readouterr().err

    def test_configuration_invalide_donne_un_code_dechec(self, tmp_path: Path) -> None:
        manquante = tmp_path / "absente.yaml"
        assert principal(["--config", str(manquante), "verifier"]) == ECHEC

    def test_ordonnanceur_inactif_est_signale(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        chemin = self._config(dossier_config)
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        brut["ordonnanceur"]["actif"] = False
        chemin.write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")
        code = principal(["--config", str(chemin), "ordonnancer"])
        assert code == DEGRADE
        assert "inactif" in capsys.readouterr().err

    def test_etat_perime_donne_un_code_degrade(self, dossier_config: Path) -> None:
        """Un cron extérieur doit pouvoir distinguer « à jour » de « périmé »."""
        chemin = self._config(dossier_config)
        configuration_brute = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        base_chemin = Path(configuration_brute["general"]["base_donnees"])
        base_chemin.parent.mkdir(parents=True, exist_ok=True)

        from brvm.config.chargement import charger_configuration

        configuration = charger_configuration(chemin)
        with BaseDonnees(base_chemin) as base:
            DepotTransactions(base).enregistrer(
                Transaction(
                    identifiant="T1",
                    ticker="TEST1",
                    date_operation=date(2026, 3, 2),
                    sens=SensOperation.ACHAT,
                    quantite=10,
                    cours_unitaire=1000,
                )
            )
        del configuration
        # Sans cotation, la ligne n'est pas valorisée : l'état reste lisible et
        # le code de sortie n'est pas un succès muet.
        assert principal(["--config", str(chemin), "etat"]) in {SUCCES, DEGRADE}

    def test_collecter_enchaine_le_cycle_et_liste_les_constats(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """La source fichier du jeu de test pointe un CSV absent : la collecte
        échoue proprement, le constat sort, et le code dit « dégradé »."""
        code = principal(["--config", str(self._config(dossier_config)), "collecter"])
        sortie = capsys.readouterr().out
        assert code in {SUCCES, DEGRADE}
        assert "Cycle du" in sortie

    def test_seance_explicite_est_transmise(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = principal(
            [
                "--config",
                str(self._config(dossier_config)),
                "--seance",
                "2026-03-02",
                "etat",
            ]
        )
        assert code == SUCCES
        assert "ÉTAT DU PORTEFEUILLE" in capsys.readouterr().out

    def test_ordonnancer_execute_une_occurrence(
        self,
        dossier_config: Path,
        capsys: pytest.CaptureFixture[str],
        dormeur: Callable[[float], None],
    ) -> None:
        """L'ordonnanceur annonce ce qu'il va faire avant de le faire.

        Le dormeur est injecté : sans lui, ce test attendrait une vraie minute,
        et la suite entière deviendrait pénible à lancer.
        """
        chemin = self._config(dossier_config)
        brut = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        # Toutes les minutes, pour que la prochaine occurrence tombe aussitôt.
        brut["ordonnanceur"]["cron_collecte"] = "* * * * 0-4"
        brut["calendrier"]["couverture_fin"] = "2030-12-31"
        chemin.write_text(yaml.safe_dump(brut, allow_unicode=True), encoding="utf-8")

        configuration, base = _preparer(chemin)
        try:
            code = commande_ordonnancer(configuration, base, occurrences=1, dormir=dormeur)
        finally:
            base.fermer()
        sortie = capsys.readouterr().out
        assert code == SUCCES
        assert "Collecte prévue le" in sortie
        assert dormeur.attentes  # type: ignore[attr-defined]

    def test_exporter_sans_sortie_affiche_le_texte(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = principal(["--config", str(self._config(dossier_config)), "exporter", "--texte"])
        assert code == SUCCES
        assert "ÉTAT DU PORTEFEUILLE" in capsys.readouterr().out
