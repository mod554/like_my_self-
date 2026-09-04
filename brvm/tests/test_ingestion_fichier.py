"""Connecteur fichier : format, tolérances de saisie, refus explicites."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.enums import StatutCollecte, StatutSeance
from brvm.ingestion.fichier import MODELE_ENTETE, SourceFichier

ENTETE = "ticker,date_seance,statut_seance,cloture,volume_titres,cours_precedent"


def source_pour(configuration: Configuration, chemin: Path) -> SourceFichier:
    reglage = next(s for s in configuration.sources if s.type == "fichier_csv")
    return SourceFichier(reglage.model_copy(update={"chemin_fichier": chemin}), configuration)


def ecrire(chemin: Path, contenu: str) -> Path:
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


class TestLectureNominale:
    def test_lignes_converties(self, configuration: Configuration, tmp_path: Path) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"{ENTETE}\nTEST1,2026-03-02,COTEE,1000,500,995\nTEST2,2026-03-02,COTEE,2500,10,2500\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        assert resultat.statut is StatutCollecte.SUCCES
        assert len(resultat.lignes_exploitables) == 2
        premiere = resultat.lignes_exploitables[0].cotation
        assert premiere is not None
        assert premiere.ticker == "TEST1"
        assert premiere.cloture == 1000
        assert premiere.volume_titres == 500

    def test_separateur_point_virgule(self, configuration: Configuration, tmp_path: Path) -> None:
        """Les exports francophones utilisent couramment le point-virgule."""
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"{ENTETE.replace(',', ';')}\nTEST1;2026-03-02;COTEE;1000;500;995\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        assert len(resultat.lignes_exploitables) == 1

    def test_separateurs_de_milliers_toleres(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f'{ENTETE}\nTEST1,2026-03-02,COTEE,"12 500",1 000,12500\n',
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.cloture == 12_500
        assert cotation.volume_titres == 1_000

    def test_lignes_de_commentaire_ignorees(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"# relevé du 2 mars\n{ENTETE}\nTEST1,2026-03-02,COTEE,1000,500,995\n",
        )
        assert len(source_pour(configuration, fichier).collecter().lignes_exploitables) == 1

    def test_filtrage_par_seance(self, configuration: Configuration, tmp_path: Path) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"{ENTETE}\nTEST1,2026-03-02,COTEE,1000,500,995\n"
            "TEST1,2026-03-03,COTEE,1010,300,1000\n",
        )
        resultat = source_pour(configuration, fichier).collecter(jour=date(2026, 3, 3))
        assert len(resultat.lignes) == 1
        cotation = resultat.lignes[0].cotation
        assert cotation is not None and cotation.cloture == 1010


class TestCelluleVide:
    def test_cellule_vide_vaut_non_publie_et_non_zero(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        """Confondre « pas de cours publié » et « cours à zéro » fausserait tout."""
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,statut_seance,cloture,ouverture,volume_titres\n"
            "TEST1,2026-03-02,COTEE,1000,,500\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.ouverture is None

    @pytest.mark.parametrize("valeur", ["-", "ND", "n/d"])
    def test_marqueurs_de_non_publication(
        self, configuration: Configuration, tmp_path: Path, valeur: str
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,statut_seance,cloture,volume_xof,volume_titres\n"
            f"TEST1,2026-03-02,COTEE,1000,{valeur},500\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.volume_xof is None


class TestStatutDeSeance:
    def test_volume_positif_sans_statut_donne_cotee(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,cloture,volume_titres\nTEST1,2026-03-02,1000,500\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.statut_seance is StatutSeance.COTEE

    def test_volume_nul_sans_statut_donne_inconnu_et_avertit(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        """Un volume nul ne prouve pas qu'il n'y a pas eu de transaction : il peut
        simplement ne pas avoir été publié. Le système refuse de trancher."""
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,cloture,volume_titres\nTEST1,2026-03-02,1000,0\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.statut_seance is StatutSeance.INCONNU
        assert cotation.cours_effectivement_traite is None
        assert any("INCONNU" in message for message in resultat.avertissements)

    def test_statut_declare_fait_foi(self, configuration: Configuration, tmp_path: Path) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,statut_seance,cloture,volume_titres\n"
            "TEST1,2026-03-02,SANS_TRANSACTION,1000,0\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.statut_seance is StatutSeance.SANS_TRANSACTION


class TestRefus:
    def test_fichier_absent(self, configuration: Configuration, tmp_path: Path) -> None:
        resultat = source_pour(configuration, tmp_path / "absent.csv").collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        assert "introuvable" in (resultat.message or "")

    def test_colonne_obligatoire_absente(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(tmp_path / "cotations.csv", "ticker,cloture\nTEST1,1000\n")
        resultat = source_pour(configuration, fichier).collecter()
        assert resultat.statut is StatutCollecte.ECHEC
        assert "date_seance" in (resultat.message or "")

    def test_ligne_fautive_isolee_sans_perdre_les_autres(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"{ENTETE}\nTEST1,2026-03-02,COTEE,1000,500,995\nTEST2,2026-03-02,COTEE,-50,10,100\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        assert resultat.statut is StatutCollecte.PARTIEL
        assert len(resultat.lignes_exploitables) == 1
        rejetee = resultat.lignes_en_erreur[0]
        assert "ligne 3" in (rejetee.erreur or "")
        assert rejetee.brut["cloture"] == "-50"

    def test_valeur_decimale_refusee(self, configuration: Configuration, tmp_path: Path) -> None:
        """Une décimale sur un montant XOF signale une mauvaise colonne ou une
        conversion de devise implicite."""
        fichier = ecrire(
            tmp_path / "cotations.csv",
            f"{ENTETE}\nTEST1,2026-03-02,COTEE,1000.75,500,995\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        assert "décimales" in (resultat.lignes_en_erreur[0].erreur or "")

    def test_horodatage_sans_fuseau_refuse(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,cloture,volume_titres,horodatage_donnee\n"
            "TEST1,2026-03-02,1000,500,2026-03-02T15:30:00\n",
        )
        resultat = source_pour(configuration, fichier).collecter()
        assert "fuseau" in (resultat.lignes_en_erreur[0].erreur or "")

    def test_fichier_vide(self, configuration: Configuration, tmp_path: Path) -> None:
        fichier = ecrire(tmp_path / "cotations.csv", "# rien que des commentaires\n")
        assert source_pour(configuration, fichier).collecter().statut is StatutCollecte.ECHEC


class TestHorodatage:
    def test_horodatage_declare_conserve(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,cloture,volume_titres,horodatage_donnee\n"
            "TEST1,2026-03-02,1000,500,2026-03-02T15:30:00+00:00\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.horodatage_donnee.isoformat() == "2026-03-02T15:30:00+00:00"

    def test_horodatage_par_defaut_est_la_cloture_de_seance(
        self, configuration: Configuration, tmp_path: Path
    ) -> None:
        """Sans horodatage déclaré, la donnée est datée de la clôture configurée,
        exprimée dans le fuseau du marché — pas de l'instant de lecture."""
        fichier = ecrire(
            tmp_path / "cotations.csv",
            "ticker,date_seance,cloture,volume_titres\nTEST1,2026-03-02,1000,500\n",
        )
        cotation = source_pour(configuration, fichier).collecter().lignes_exploitables[0].cotation
        assert cotation is not None
        # Africa/Abidjan est à UTC+00 : la clôture 15:00 locale vaut 15:00 UTC.
        assert cotation.horodatage_donnee.isoformat() == "2026-03-02T15:00:00+00:00"


class TestTableur:
    def test_lecture_xlsx(self, configuration: Configuration, tmp_path: Path) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        classeur = openpyxl.Workbook()
        feuille = classeur.active
        feuille.append(["ticker", "date_seance", "statut_seance", "cloture", "volume_titres"])
        feuille.append(["TEST1", "2026-03-02", "COTEE", 1000, 500])
        fichier = tmp_path / "cotations.xlsx"
        classeur.save(fichier)
        resultat = source_pour(configuration, fichier).collecter()
        cotation = resultat.lignes_exploitables[0].cotation
        assert cotation is not None
        assert cotation.cloture == 1000


def test_modele_contient_toutes_les_colonnes(tmp_path: Path) -> None:
    chemin = SourceFichier.ecrire_modele(tmp_path / "modele.csv")
    contenu = chemin.read_text(encoding="utf-8")
    assert MODELE_ENTETE in contenu
    assert "ticker" in contenu and "date_seance" in contenu
    assert "INCONNU" in contenu
