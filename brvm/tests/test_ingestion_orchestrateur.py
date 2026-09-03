"""Cycle d'ingestion complet : contrôles, quarantaine, écriture, journal."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import GraviteAnomalie, StatutCollecte, StatutFiabilite
from brvm.ingestion.base import DataSource, ResultatCollecte
from brvm.ingestion.fichier import SourceFichier
from brvm.ingestion.orchestrateur import BilanIngestion, Orchestrateur
from brvm.ingestion.univers import charger_univers
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import (
    DepotAnomalies,
    DepotCotations,
    DepotInstruments,
    DepotJournalCollectes,
)
from brvm.utils.erreurs import ErreurConfiguration

ENTETE = "ticker,date_seance,statut_seance,cloture,volume_titres,cours_precedent"
SEANCE = date(2026, 3, 2)
#: Instant de référence des contrôles : sans lui, l'ancienneté des séances de test
#: déclencherait une anomalie de péremption à chaque exécution.
MAINTENANT = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)


class LanceurCycle(Protocol):
    """Signature de la fixture `executer`."""

    def __call__(
        self,
        lignes: str,
        jour: date | None = None,
        maintenant: datetime = MAINTENANT,
    ) -> list[BilanIngestion]: ...


def source_fichier(configuration: Configuration, chemin: Path) -> SourceFichier:
    reglage = next(s for s in configuration.sources if s.type == "fichier_csv")
    return SourceFichier(reglage.model_copy(update={"chemin_fichier": chemin}), configuration)


#: Univers réduit à une seule valeur, pour vérifier qu'un ticker non déclaré
#: est bien signalé. Écrit tel quel : `ecrire` préfixe l'en-tête des cotations.
UNIVERS_PARTIEL = (
    "ticker,nom,isin,pays,secteur,compartiment,actif\n"
    "TEST2,Société de test deux,,SN,Finances,Principal,true\n"
)


def ecrire(chemin: Path, lignes: str) -> Path:
    chemin.write_text(f"{ENTETE}\n{lignes}", encoding="utf-8")
    return chemin


@pytest.fixture
def orchestre(
    configuration: Configuration,
    base: BaseDonnees,
    calendrier: CalendrierSeances,
    tmp_path: Path,
) -> Callable[[str], Orchestrateur]:
    def construire(lignes: str) -> Orchestrateur:
        fichier = ecrire(tmp_path / "cotations.csv", lignes)
        return Orchestrateur(
            configuration, base, calendrier, sources=[source_fichier(configuration, fichier)]
        )

    return construire


@pytest.fixture
def executer(orchestre: Callable[[str], Orchestrateur]) -> LanceurCycle:
    """Lance un cycle à l'instant de référence des tests."""

    def lancer(
        lignes: str, jour: date | None = None, maintenant: datetime = MAINTENANT
    ) -> list[BilanIngestion]:
        return orchestre(lignes).executer(jour=jour, maintenant=maintenant)

    return lancer


class TestCycleNominal:
    def test_cotations_ecrites_et_journal_rempli(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        bilans = executer(
            "TEST1,2026-03-02,COTEE,1000,500,995\nTEST2,2026-03-02,COTEE,2500,10,2500\n"
        )
        bilan = bilans[0]
        assert bilan.statut is StatutCollecte.SUCCES
        assert (bilan.lignes_lues, bilan.inserees, bilan.en_quarantaine) == (2, 2, 0)
        assert len(DepotCotations(base).lire("TEST1")) == 1

        journal = DepotJournalCollectes(base).derniere("fichier_manuel")
        assert journal is not None
        assert journal.nb_lignes_lues == 2
        assert journal.nb_lignes_ecrites == 2

    def test_rejeu_idempotent(self, executer: LanceurCycle, base: BaseDonnees) -> None:
        """Rejouer une collecte ne crée ni doublon, ni révision, ni anomalie en double."""
        lignes = "TEST1,2026-03-02,COTEE,1000,500,995\n"
        premier = executer(lignes)[0]
        second = executer(lignes)[0]
        assert premier.inserees == 1
        assert (second.inserees, second.inchangees, second.corrigees) == (0, 1, 0)
        assert len(DepotCotations(base).lire("TEST1")) == 1

    def test_correction_de_source_archivee(self, executer: LanceurCycle, base: BaseDonnees) -> None:
        executer("TEST1,2026-03-02,COTEE,1000,500,995\n")
        bilan = executer("TEST1,2026-03-02,COTEE,1005,500,995\n")[0]
        assert bilan.corrigees == 1
        archives = DepotCotations(base).revisions("TEST1", SEANCE, "fichier_manuel")
        assert [archive["cloture"] for archive in archives] == [1000]

    def test_resume_lisible(self, executer: LanceurCycle) -> None:
        bilan = executer("TEST1,2026-03-02,COTEE,1000,500,995\n")[0]
        assert "fichier_manuel" in bilan.resume()
        assert "SUCCES" in bilan.resume()


class TestQuarantaine:
    def test_variation_hors_seuil_mise_en_quarantaine(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        """La cotation est écrite pour investigation, mais n'alimente aucun calcul."""
        bilan = executer("TEST1,2026-03-02,COTEE,1500,500,1000\n")[0]
        assert bilan.en_quarantaine == 1

        depot = DepotCotations(base)
        assert depot.lire("TEST1") == []
        conservee = depot.lire("TEST1", inclure_quarantaine=True)
        assert len(conservee) == 1
        assert conservee[0].statut_fiabilite is StatutFiabilite.QUARANTAINE

    def test_anomalie_porte_la_donnee_fautive(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        executer("TEST1,2026-03-02,COTEE,1500,500,1000\n")
        anomalies = DepotAnomalies(base).lister()
        assert len(anomalies) == 1
        assert anomalies[0].type_anomalie == "variation_hors_seuil"
        assert anomalies[0].gravite is GraviteAnomalie.BLOQUANTE
        assert anomalies[0].ticker == "TEST1"
        assert anomalies[0].charge_utile["variation"].startswith("0.5")

    def test_ligne_illisible_consignee_sans_bloquer_les_autres(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        bilan = executer(
            "TEST1,2026-03-02,COTEE,1000,500,995\nTEST2,2026-03-02,COTEE,-50,10,100\n"
        )[0]
        assert bilan.statut is StatutCollecte.PARTIEL
        assert (bilan.inserees, bilan.lignes_rejetees) == (1, 1)
        anomalies = DepotAnomalies(base).lister()
        assert anomalies[0].type_anomalie == "ligne_illisible"

    def test_doublon_dans_la_collecte_mis_en_quarantaine(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        bilan = executer(
            "TEST1,2026-03-02,COTEE,1000,500,995\nTEST1,2026-03-02,COTEE,1002,500,995\n"
        )[0]
        assert bilan.en_quarantaine == 1
        assert any(a.type_anomalie == "doublon" for a in DepotAnomalies(base).lister())

    def test_anomalies_non_dupliquees_au_rejeu(
        self, executer: LanceurCycle, base: BaseDonnees
    ) -> None:
        """L'identifiant d'anomalie est déterministe : rejouer ne les multiplie pas."""
        lignes = "TEST1,2026-03-02,COTEE,1500,500,1000\n"
        executer(lignes)
        executer(lignes)
        assert len(DepotAnomalies(base).lister()) == 1


class TestReferentiel:
    """Le référentiel est une donnée de CONFIGURATION, la base en est le reflet.

    Rien n'écrivait ce reflet : `DepotInstruments` restait vide en exploitation,
    et tout ce qui en dépend s'éteignait sans un mot — la détection de ticker
    inconnu ne se déclenchait jamais, le criblage ne voyait aucun univers, les
    concentrations sectorielles n'avaient pas de secteur.
    """

    def test_le_cycle_recopie_l_univers_declare(
        self, executer: LanceurCycle, base: BaseDonnees, configuration: Configuration
    ) -> None:
        executer("TEST1,2026-03-02,COTEE,1000,500,995\n")
        en_base = {i.ticker for i in DepotInstruments(base).lister()}
        attendus = {i.ticker for i in charger_univers(configuration.marche.fichier_univers)}
        assert en_base == attendus

    def test_ticker_absent_de_l_univers_rend_la_cotation_suspecte(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        univers = tmp_path / "univers_partiel.csv"
        univers.write_text(UNIVERS_PARTIEL, encoding="utf-8")
        reglages = configuration.model_copy(
            update={"marche": configuration.marche.model_copy(update={"fichier_univers": univers})}
        )
        fichier = ecrire(tmp_path / "cotations.csv", "TEST1,2026-03-02,COTEE,1000,500,995\n")
        bilan = Orchestrateur(
            reglages, base, calendrier, sources=[source_fichier(reglages, fichier)]
        ).executer(maintenant=MAINTENANT)[0]

        assert bilan.suspectes == 1
        cotation = DepotCotations(base).lire("TEST1")[0]
        assert cotation.statut_fiabilite is StatutFiabilite.SUSPECTE
        assert any(a.type_anomalie == "ticker_inconnu" for a in DepotAnomalies(base).lister())

    def test_ticker_declare_reste_fiable(self, executer: LanceurCycle, base: BaseDonnees) -> None:
        executer("TEST1,2026-03-02,COTEE,1000,500,995\n")
        assert DepotCotations(base).lire("TEST1")[0].statut_fiabilite is StatutFiabilite.FIABLE

    def test_une_valeur_retiree_du_fichier_n_est_pas_effacee_de_la_base(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        """Des cotations et des transactions la référencent : effacer son libellé
        rendrait un historique illisible. On la marque inactive, on ne l'ôte pas."""
        fichier = ecrire(tmp_path / "cotations.csv", "TEST1,2026-03-02,COTEE,1000,500,995\n")
        Orchestrateur(
            configuration, base, calendrier, sources=[source_fichier(configuration, fichier)]
        ).executer(maintenant=MAINTENANT)
        complet = {i.ticker for i in DepotInstruments(base).lister()}

        reduit = tmp_path / "univers_reduit.csv"
        reduit.write_text(UNIVERS_PARTIEL, encoding="utf-8")
        reglages = configuration.model_copy(
            update={"marche": configuration.marche.model_copy(update={"fichier_univers": reduit})}
        )
        Orchestrateur(
            reglages, base, calendrier, sources=[source_fichier(reglages, fichier)]
        ).executer(maintenant=MAINTENANT)
        assert {i.ticker for i in DepotInstruments(base).lister()} == complet

    def test_univers_illisible_n_interrompt_pas_la_collecte(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        """On peut collecter avant d'avoir saisi la cote : ce n'est pas une erreur."""
        reglages = configuration.model_copy(
            update={
                "marche": configuration.marche.model_copy(
                    update={"fichier_univers": tmp_path / "jamais_ecrit.csv"}
                )
            }
        )
        fichier = ecrire(tmp_path / "cotations.csv", "TEST1,2026-03-02,COTEE,1000,500,995\n")
        bilans = Orchestrateur(
            reglages, base, calendrier, sources=[source_fichier(reglages, fichier)]
        ).executer(maintenant=MAINTENANT)
        assert bilans[0].lignes_lues == 1


class TestResilience:
    def test_source_indisponible_ne_stoppe_pas_le_cycle(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        absente = source_fichier(configuration, tmp_path / "absent.csv")
        presente = source_fichier(
            configuration, ecrire(tmp_path / "ok.csv", "TEST1,2026-03-02,COTEE,1000,500,995\n")
        )
        bilans = Orchestrateur(
            configuration, base, calendrier, sources=[absente, presente]
        ).executer()
        assert bilans[0].statut is StatutCollecte.ECHEC
        assert bilans[1].statut is StatutCollecte.SUCCES
        assert len(DepotCotations(base).lire("TEST1")) == 1
        assert any(a.type_anomalie == "source_indisponible" for a in DepotAnomalies(base).lister())

    def test_echec_de_source_journalise(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        tmp_path: Path,
    ) -> None:
        Orchestrateur(
            configuration,
            base,
            calendrier,
            sources=[source_fichier(configuration, tmp_path / "absent.csv")],
        ).executer()
        journal = DepotJournalCollectes(base).derniere("fichier_manuel")
        assert journal is not None
        assert journal.statut is StatutCollecte.ECHEC


def test_collecte_ciblee_sur_une_seance(executer: LanceurCycle, base: BaseDonnees) -> None:
    bilan = executer(
        "TEST1,2026-03-02,COTEE,1000,500,995\nTEST1,2026-03-03,COTEE,1005,300,1000\n",
        jour=date(2026, 3, 3),
        maintenant=datetime(2026, 3, 3, 16, 0, tzinfo=UTC),
    )[0]
    assert bilan.lignes_lues == 1
    assert [c.date_seance for c in DepotCotations(base).lire("TEST1")] == [date(2026, 3, 3)]


def test_seance_posterieure_a_l_instant_de_reference_mise_en_quarantaine(
    executer: LanceurCycle, base: BaseDonnees
) -> None:
    """Garde-fou contre une analyse de source décalée d'une ligne ou d'un format de date."""
    bilan = executer("TEST1,2026-03-03,COTEE,1005,300,1000\n")[0]
    assert bilan.en_quarantaine == 1
    assert DepotCotations(base).lire("TEST1") == []
    assert any(a.type_anomalie == "date_future" for a in DepotAnomalies(base).lister())


class TestSourceNonDeclaree:
    def test_un_connecteur_hors_configuration_est_nomme(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
    ) -> None:
        """Les seuils de contrôle sont propres à chaque source : sans son bloc de
        configuration, on ne saurait pas selon quels critères la juger."""

        class Inconnue(DataSource):
            nom = "source_fantome"

            def disponible(self) -> bool:
                return True

            def collecter(self, jour: date | None = None) -> ResultatCollecte:
                raise AssertionError("ne doit jamais être appelée")

        orchestrateur = Orchestrateur(configuration, base, calendrier, sources=[Inconnue()])
        with pytest.raises(ErreurConfiguration, match="source_fantome"):
            orchestrateur.executer()
