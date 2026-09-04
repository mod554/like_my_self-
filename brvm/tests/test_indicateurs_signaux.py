"""Signaux : franchissements mécaniques, et interdiction du biais d'anticipation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.confiance import ScoreConfiance
from brvm.indicators.serie import SerieTechnique
from brvm.indicators.signaux import DetecteurSignaux, SensSignal, Signal


def detecteur(
    serie: SerieTechnique, configuration: Configuration, calendrier: CalendrierSeances
) -> DetecteurSignaux:
    return DetecteurSignaux(Indicateurs(serie, configuration), configuration, calendrier)


def _score_neutre() -> ScoreConfiance:
    """Score sans effet, pour les tests qui ne portent que sur les dates."""
    return ScoreConfiance(
        valeur=Decimal(1),
        assiduite=Decimal(1),
        profondeur=Decimal(1),
        etroitesse=Decimal(1),
        seances_cotees=1,
        seances_attendues=1,
        montant_moyen_xof=Decimal(1),
        fourchette_moyenne=None,
    )


class TestAntiAnticipation:
    """La règle centrale : une clôture n'est connue qu'après la séance."""

    def test_execution_toujours_apres_le_constat(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(30)] + [
            875 + index * 30 for index in range(30)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).tous()
        assert signaux, "le jeu de données doit produire au moins un franchissement"
        for signal in signaux:
            assert signal.date_execution > signal.date_constat

    def test_execution_est_la_seance_suivante_du_calendrier(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(30)] + [
            875 + index * 30 for index in range(30)
        ]
        for signal in detecteur(fabrique_serie(cours), configuration, calendrier).tous():
            assert signal.date_execution == calendrier.prochaine_seance(signal.date_constat)
            assert calendrier.est_jour_de_seance(signal.date_execution)

    def test_un_signal_execute_le_jour_meme_est_refuse(self) -> None:
        """Le modèle lui-même interdit de construire un tel signal."""
        with pytest.raises(ValueError, match="ne peut pas être exécuté"):
            Signal(
                ticker="TEST1",
                date_constat=date(2026, 3, 2),
                date_execution=date(2026, 3, 2),
                sens=SensSignal.ACHAT,
                regle="test",
                explication="test",
                confiance=_score_neutre(),
            )

    def test_signal_anterieur_refuse(self) -> None:
        with pytest.raises(ValueError, match="ne peut pas être exécuté"):
            Signal(
                ticker="TEST1",
                date_constat=date(2026, 3, 3),
                date_execution=date(2026, 3, 2),
                sens=SensSignal.VENTE,
                regle="test",
                explication="test",
                confiance=_score_neutre(),
            )


class TestCroisementMoyennes:
    def test_retournement_haussier_donne_un_achat(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(60)] + [
            705 + index * 40 for index in range(40)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).croisement_moyennes()
        assert any(signal.sens is SensSignal.ACHAT for signal in signaux)

    def test_retournement_baissier_donne_une_vente(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 + index * 20 for index in range(60)] + [
            2180 - index * 40 for index in range(40)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).croisement_moyennes()
        assert any(signal.sens is SensSignal.VENTE for signal in signaux)

    def test_serie_plate_ne_produit_aucun_signal(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        serie = fabrique_serie([1000] * 90)
        assert detecteur(serie, configuration, calendrier).croisement_moyennes() == []

    def test_croisement_de_part_et_d_autre_d_un_trou_ignore(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """Un franchissement supposé au travers d'un trou n'a pas été observé."""
        cours: list[int | None] = [1000 - index * 5 for index in range(60)]
        cours += [None] * 10
        cours += [705 + index * 40 for index in range(40)]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).croisement_moyennes()
        for signal in signaux:
            assert signal.date_constat not in {date(2026, 5, jour) for jour in range(20, 30)}


class TestRsi:
    def test_sortie_de_survente_donne_un_achat(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """Le signal est pris à la sortie de la zone, pas à l'entrée : un RSI peut
        rester sous 30 pendant des semaines."""
        cours = [1000 - index * 20 for index in range(30)] + [
            420 + index * 25 for index in range(30)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).seuils_rsi()
        achats = [signal for signal in signaux if signal.sens is SensSignal.ACHAT]
        assert achats
        assert "survente" in achats[0].regle

    def test_sortie_de_surachat_donne_une_vente(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 + index * 25 for index in range(30)] + [
            1725 - index * 20 for index in range(30)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).seuils_rsi()
        assert any(signal.sens is SensSignal.VENTE for signal in signaux)


class TestMacd:
    def test_croisement_detecte(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 8 for index in range(60)] + [
            520 + index * 30 for index in range(50)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).croisement_macd()
        assert signaux
        assert all(signal.regle == "croisement MACD/signal" for signal in signaux)


class TestQualification:
    def test_signal_sur_serie_trouee_avertit_du_report(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        """Une séance sur trois sans transaction : 33 % de report.

        C'est au-dessus du seuil d'alerte configuré (25 %) mais en dessous du
        seuil de refus (60 % de séances cotées exigées) — le signal est donc
        produit, et il doit dire sur quoi il repose.
        """
        cours: list[int | None] = []
        for index in range(120):
            valeur = 1000 - index * 5 if index < 60 else 700 + (index - 60) * 40
            cours.append(None if index % 3 == 2 else valeur)

        serie = fabrique_serie(cours)
        assert serie.taux_remplissage() > configuration.indicateurs.taux_remplissage_alerte

        signaux = detecteur(serie, configuration, calendrier).tous()
        assert signaux, "la série doit produire au moins un franchissement"
        for signal in signaux:
            assert any("cours reportés" in message for message in signal.avertissements), (
                f"signal du {signal.date_constat} sans avertissement sur le report"
            )

    def test_signal_porte_son_score_de_confiance(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(40)] + [
            805 + index * 40 for index in range(40)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).tous()
        assert signaux
        assert signaux[0].confiance.niveau in {"élevée", "moyenne", "faible"}
        assert "ACHAT" in signaux[0].resume() or "VENTE" in signaux[0].resume()

    def test_tri_chronologique(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(60)] + [
            705 + index * 40 for index in range(40)
        ]
        signaux = detecteur(fabrique_serie(cours), configuration, calendrier).tous()
        dates = [signal.date_constat for signal in signaux]
        assert dates == sorted(dates)

    def test_filtrage_depuis_une_date(
        self,
        fabrique_serie: Callable[..., SerieTechnique],
        configuration: Configuration,
        calendrier: CalendrierSeances,
    ) -> None:
        cours = [1000 - index * 5 for index in range(60)] + [
            705 + index * 40 for index in range(40)
        ]
        moteur = detecteur(fabrique_serie(cours), configuration, calendrier)
        tous = moteur.tous()
        assert tous
        seuil = tous[-1].date_constat
        assert all(signal.date_constat >= seuil for signal in moteur.derniers(depuis=seuil))
