"""Référentiel de l'univers : lecture stricte, refus des à-peu-près."""

from __future__ import annotations

from pathlib import Path

import pytest

from brvm.domain.enums import Pays
from brvm.ingestion.univers import charger_univers, par_ticker, parcourir, tickers
from brvm.utils.erreurs import ErreurConfiguration

ENTETE = "ticker,nom,isin,pays,secteur,compartiment,actif"


def ecrire(tmp_path: Path, *lignes: str) -> Path:
    fichier = tmp_path / "univers.csv"
    fichier.write_text("\n".join([ENTETE, *lignes]) + "\n", encoding="utf-8")
    return fichier


class TestLecture:
    def test_lit_les_colonnes_declarees(self, dossier_config: Path) -> None:
        univers = charger_univers(dossier_config / "univers_test.csv")
        assert [instrument.ticker for instrument in univers] == ["TEST1", "TEST2", "TEST3"]
        assert univers[1].pays is Pays.SENEGAL
        assert univers[1].secteur == "Finances"

    def test_commentaires_et_lignes_vides_ignores(self, tmp_path: Path) -> None:
        fichier = tmp_path / "univers.csv"
        fichier.write_text(
            f"# un commentaire\n{ENTETE}\n\nTEST1,Test un,,CI,,,\n# encore\n",
            encoding="utf-8",
        )
        assert [i.ticker for i in charger_univers(fichier)] == ["TEST1"]

    def test_ticker_mis_en_majuscules(self, tmp_path: Path) -> None:
        """Une source qui publie « test1 » désigne la même valeur que « TEST1 »."""
        assert charger_univers(ecrire(tmp_path, "test1,Test un,,CI,,,"))[0].ticker == "TEST1"

    def test_actif_par_defaut_a_vrai(self, tmp_path: Path) -> None:
        assert charger_univers(ecrire(tmp_path, "TEST1,Test un,,CI,,,"))[0].actif is True

    def test_champs_vides_deviennent_none(self, tmp_path: Path) -> None:
        """Une case vide signifie « non renseigné », jamais une chaîne vide."""
        instrument = charger_univers(ecrire(tmp_path, "TEST1,Test un,,CI,,,"))[0]
        assert instrument.isin is None
        assert instrument.secteur is None
        assert instrument.compartiment is None

    def test_parcourir_donne_les_memes_valeurs(self, dossier_config: Path) -> None:
        chemin = dossier_config / "univers_test.csv"
        assert list(parcourir(chemin)) == charger_univers(chemin)


class TestRefus:
    def test_fichier_absent(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="introuvable"):
            charger_univers(tmp_path / "absent.csv")

    def test_fichier_vide(self, tmp_path: Path) -> None:
        fichier = tmp_path / "univers.csv"
        fichier.write_text("", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="vide"):
            charger_univers(fichier)

    def test_entete_seule(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="que son en-tête"):
            charger_univers(ecrire(tmp_path))

    def test_colonne_obligatoire_absente(self, tmp_path: Path) -> None:
        fichier = tmp_path / "univers.csv"
        fichier.write_text("ticker,nom\nTEST1,Test un\n", encoding="utf-8")
        with pytest.raises(ErreurConfiguration, match="pays"):
            charger_univers(fichier)

    def test_pays_inconnu_nomme_la_ligne(self, tmp_path: Path) -> None:
        """Un pays hors UEMOA est refusé, et le message dit quelle ligne corriger."""
        with pytest.raises(ErreurConfiguration, match="Ligne 3"):
            charger_univers(ecrire(tmp_path, "TEST1,Test un,,CI,,,", "TEST2,Test deux,,FR,,,"))

    def test_ticker_en_double_refuse(self, tmp_path: Path) -> None:
        """Deux lignes pour un même ticker rendraient la clé de base ambiguë."""
        with pytest.raises(ErreurConfiguration, match="deux fois"):
            charger_univers(ecrire(tmp_path, "TEST1,Test un,,CI,,,", "TEST1,Doublon,,SN,,,"))

    def test_actif_illisible_refuse(self, tmp_path: Path) -> None:
        with pytest.raises(ErreurConfiguration, match="illisible"):
            charger_univers(ecrire(tmp_path, "TEST1,Test un,,CI,,,peut-être"))

    def test_isin_non_conforme_refuse(self, tmp_path: Path) -> None:
        """La clé de contrôle de l'ISIN est vérifiée : un ISIN faux est une erreur
        de saisie, pas une donnée à propager."""
        with pytest.raises(ErreurConfiguration, match="Ligne 2"):
            charger_univers(ecrire(tmp_path, "TEST1,Test un,CI0000000001,CI,,,"))


class TestSelection:
    def test_tickers_actifs_seulement_par_defaut(self, dossier_config: Path) -> None:
        univers = charger_univers(dossier_config / "univers_test.csv")
        assert tickers(univers) == ["TEST1", "TEST2"]
        assert tickers(univers, actifs_seulement=False) == ["TEST1", "TEST2", "TEST3"]

    def test_par_ticker_indexe_toutes_les_valeurs(self, dossier_config: Path) -> None:
        index = par_ticker(charger_univers(dossier_config / "univers_test.csv"))
        assert set(index) == {"TEST1", "TEST2", "TEST3"}
        assert index["TEST3"].actif is False
