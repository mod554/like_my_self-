"""Outil de capture : plan de vérification, inspection de page, refus explicites."""

from __future__ import annotations

from pathlib import Path

import pytest

from brvm.ingestion.capture import capturer, main
from brvm.utils.erreurs import ErreurBrvm

PAGE = (
    "<html><body><table>"
    "<tr><th>Symbole</th><th>Cours</th></tr>"
    "<tr><td>TEST1</td><td>1 000</td></tr>"
    "</table></body></html>"
)


class TestPlan:
    def test_plan_affiche(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--plan"]) == 0
        sortie = capsys.readouterr().out
        assert "robots.txt" in sortie
        assert "conditions d'utilisation" in sortie


class TestInspection:
    def test_liste_des_tableaux(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        fichier = tmp_path / "page.html"
        fichier.write_text(PAGE, encoding="utf-8")
        assert main(["--lister-tableaux", str(fichier)]) == 0
        sortie = capsys.readouterr().out
        assert "index_tableau: 0" in sortie
        assert "Symbole" in sortie

    def test_fichier_absent(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["--lister-tableaux", str(tmp_path / "absent.html")]) == 2
        assert "introuvable" in capsys.readouterr().err


class TestArguments:
    def test_sans_argument_affiche_l_aide(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == 2
        assert "usage" in capsys.readouterr().out.lower()

    def test_source_inconnue(self, dossier_config: Path) -> None:
        with pytest.raises(ErreurBrvm, match="Source inconnue"):
            capturer(dossier_config / "config_valide.yaml", "inexistante", None, None)

    def test_source_sans_url(self, dossier_config: Path) -> None:
        """La source fichier n'a pas d'URL : on le dit plutôt que d'en deviner une."""
        with pytest.raises(ErreurBrvm, match="url_base"):
            capturer(dossier_config / "config_valide.yaml", "fichier_manuel", None, None)

    def test_erreur_remontee_en_code_de_sortie(
        self, dossier_config: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            ["--config", str(dossier_config / "config_valide.yaml"), "--source", "inexistante"]
        )
        assert code == 1
        assert "Source inconnue" in capsys.readouterr().err
