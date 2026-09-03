"""Contrôles de risque : concentration, liquidité, stops ATR."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.domain.enums import Pays, StatutSeance
from brvm.domain.modeles import Cotation, Instrument, Transaction
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import SerieTechnique
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.positions import suivre
from brvm.portfolio.valorisation import Portefeuille, valoriser
from brvm.risk.controles import (
    Dimension,
    calculer_stop_atr,
    controler,
    controler_concentration,
    controler_liquidite,
    dimensionner,
)

T = datetime(2026, 8, 28, 15, 30, tzinfo=UTC)


def cotation(ticker: str, cloture: int) -> Cotation:
    return Cotation(
        ticker=ticker,
        date_seance=date(2026, 8, 28),
        source="fixture",
        statut_seance=StatutSeance.COTEE,
        cloture=cloture,
        volume_titres=100,
        horodatage_donnee=T,
        horodatage_collecte=T,
    )


def instrument(ticker: str, secteur: str | None, pays: Pays) -> Instrument:
    return Instrument(ticker=ticker, nom=f"Société {ticker}", pays=pays, secteur=secteur)


def portefeuille_deux_lignes(
    moteur_frais: MoteurFrais,
    moteur_fiscal: MoteurFiscal,
    fabrique_transaction: Callable[..., Transaction],
) -> Portefeuille:
    suivi = suivre(
        [
            fabrique_transaction("T1", ticker="TEST1", quantite=10, cours=1_000),
            fabrique_transaction("T2", ticker="TEST2", quantite=10, cours=3_000),
        ]
    )
    return valoriser(
        suivi,
        {"TEST1": cotation("TEST1", 1_000), "TEST2": cotation("TEST2", 3_000)},
        moteur_frais,
        moteur_fiscal,
    )


class TestConcentration:
    def test_poids_par_ligne_secteur_et_pays(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        instruments = {
            "TEST1": instrument("TEST1", "Banque", Pays.COTE_DIVOIRE),
            "TEST2": instrument("TEST2", "Banque", Pays.SENEGAL),
        }
        constats, _ = controler_concentration(portefeuille, instruments, configuration)
        par_dimension = {(c.dimension, c.cle): c.poids for c in constats}
        assert par_dimension[(Dimension.LIGNE, "TEST2")] == Decimal("0.750000")
        assert par_dimension[(Dimension.SECTEUR, "Banque")] == Decimal("1.000000")
        assert par_dimension[(Dimension.PAYS, "SN")] == Decimal("0.750000")

    def test_depassement_signale(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """Le barème de test plafonne une ligne à 20 %."""
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        constats, _ = controler_concentration(portefeuille, {}, configuration)
        ligne = next(c for c in constats if c.cle == "TEST2")
        assert not ligne.respecte
        assert ligne.depassement == Decimal("0.550000")
        assert "DÉPASSÉ" in ligne.resume()

    def test_valeur_absente_du_referentiel_signalee(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """Elle n'est pas rangée dans une catégorie inventée."""
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        constats, avertissements = controler_concentration(
            portefeuille,
            {"TEST1": instrument("TEST1", "Banque", Pays.COTE_DIVOIRE)},
            configuration,
        )
        assert any("absent du référentiel" in message for message in avertissements)
        secteurs = {c.cle for c in constats if c.dimension is Dimension.SECTEUR}
        assert secteurs == {"Banque"}

    def test_secteur_manquant_signale(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        _, avertissements = controler_concentration(
            portefeuille,
            {
                "TEST1": instrument("TEST1", None, Pays.COTE_DIVOIRE),
                "TEST2": instrument("TEST2", None, Pays.SENEGAL),
            },
            configuration,
        )
        assert any("aucun secteur renseigné" in message for message in avertissements)

    def test_portefeuille_non_valorise(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        suivi = suivre([fabrique_transaction("T1", quantite=10, cours=1_000)])
        portefeuille = valoriser(suivi, {}, moteur_frais, moteur_fiscal)
        constats, avertissements = controler_concentration(portefeuille, {}, configuration)
        assert constats == ()
        assert any("non valorisé" in message for message in avertissements)


class TestLiquidite:
    def test_delai_de_debouclage_estime(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Volume moyen 100/séance, plafond 25 % → 25 titres cessibles par séance."""
        serie = fabrique_serie([1000] * 20, volume=100)
        constat = controler_liquidite("TEST1", 250, serie, configuration)
        assert constat.volume_moyen == Decimal("100.00")
        assert constat.debit_quotidien == Decimal("25.00")
        assert constat.seances_pour_deboucler == Decimal("10.0")
        assert "séance(s) pour solder" in constat.resume()

    def test_volume_moyen_ignore_les_seances_sans_echange(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        pleine = fabrique_serie([1000] * 10, volume=100)
        creuse = fabrique_serie([1000, None, 1000, None, 1000], volume=100)
        assert (
            controler_liquidite("TEST1", 100, pleine, configuration).volume_moyen
            == controler_liquidite("TEST1", 100, creuse, configuration).volume_moyen
        )

    def test_valeur_sans_echange_est_signalee_comme_non_cessible(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, None, None, None, None, None])
        constat = controler_liquidite("TEST1", 100, serie, configuration)
        # La première séance a coté, mais la fenêtre de volume moyen est de 20 :
        # on force un cas sans aucun échange en tronquant la série.
        vide = SerieTechnique(ticker="TEST1", barres=serie.barres[1:])
        constat_vide = controler_liquidite("TEST1", 100, vide, configuration)
        assert constat.mesurable
        assert not constat_vide.mesurable
        assert "aucun prix raisonnable" in (constat_vide.motif_indisponible or "")

    def test_dimensionnement_maximal(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000] * 20, volume=400)
        taille, motif = dimensionner(serie, configuration)
        assert taille == 100  # 25 % de 400
        assert motif is None

    def test_dimensionnement_impossible_sans_echange(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = SerieTechnique(ticker="TEST1", barres=fabrique_serie([1000, None, None]).barres[1:])
        taille, motif = dimensionner(serie, configuration)
        assert taille == 0
        assert motif is not None


class TestStopAtr:
    def test_stop_place_sous_le_cours(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000 + (index * 13) % 60 for index in range(40)], amplitude=30)
        atr = Indicateurs(serie, configuration).atr(fenetre=5)
        stop = calculer_stop_atr("TEST1", 1_000, atr, None, configuration)
        assert stop.niveau is not None
        assert stop.niveau < 1_000
        assert stop.distance is not None and stop.distance > 0

    def test_avertissement_systematique_sur_l_executabilite(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        """Un stop n'est pas une protection acquise sur une valeur peu liquide."""
        serie = fabrique_serie([1000 + index for index in range(40)], amplitude=30)
        atr = Indicateurs(serie, configuration).atr(fenetre=5)
        stop = calculer_stop_atr("TEST1", 1_000, atr, None, configuration)
        assert any("difficilement exécutable" in a for a in stop.avertissements)

    def test_atr_indisponible(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000, None, 1010])
        atr = Indicateurs(serie, configuration).atr(fenetre=14)
        stop = calculer_stop_atr("TEST1", 1_000, atr, None, configuration)
        assert stop.niveau is None
        assert stop.motif_indisponible is not None
        assert "non calculable" in stop.resume()

    def test_anciennete_de_l_atr_signalee(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        cours: list[int | None] = [1000 + index for index in range(30)]
        cours += [None, None]
        serie = fabrique_serie(cours, amplitude=30)
        atr = Indicateurs(serie, configuration).atr(fenetre=5)
        stop = calculer_stop_atr("TEST1", 1_000, atr, None, configuration)
        assert stop.anciennete_atr == 2
        assert any("date de 2 séance" in a for a in stop.avertissements)

    def test_delai_de_debouclage_ajoute_un_avertissement(
        self, configuration: Configuration, fabrique_serie: Callable[..., SerieTechnique]
    ) -> None:
        serie = fabrique_serie([1000 + index for index in range(40)], volume=100, amplitude=30)
        atr = Indicateurs(serie, configuration).atr(fenetre=5)
        liquidite = controler_liquidite("TEST1", 500, serie, configuration)
        stop = calculer_stop_atr("TEST1", 1_000, atr, liquidite, configuration)
        assert any("ne peut pas être exécuté d'un bloc" in a for a in stop.avertissements)


class TestRapportComplet:
    def test_controle_global(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
        fabrique_serie: Callable[..., SerieTechnique],
    ) -> None:
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        series = {
            "TEST1": fabrique_serie([1000] * 20, ticker="TEST1"),
            "TEST2": fabrique_serie([3000] * 20, ticker="TEST2"),
        }
        rapport = controler(portefeuille, {}, series, configuration)
        assert rapport.concentrations
        assert len(rapport.liquidites) == 2
        assert rapport.depassements()
        assert "Concentration :" in rapport.resume()

    def test_serie_manquante_signalee(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
        fabrique_serie: Callable[..., SerieTechnique],
    ) -> None:
        portefeuille = portefeuille_deux_lignes(moteur_frais, moteur_fiscal, fabrique_transaction)
        rapport = controler(portefeuille, {}, {"TEST1": fabrique_serie([1000] * 20)}, configuration)
        assert any("Aucune série de cours" in a for a in rapport.avertissements)


class TestCorrelationsEntreLignes:
    """Une limite de poids par ligne se contourne sans le vouloir.

    Trois lignes de 15 % qui varient ensemble font une position de 45 % qu'aucun
    contrôle de concentration ne voit. Le contrôle de corrélation existait et
    n'était appelé par aucun code de production : `seances_minimum_correlation`
    était un réglage mort, renseigné sans effet.
    """

    @staticmethod
    def _portefeuille(
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_transaction: Callable[..., Transaction],
    ) -> Portefeuille:
        suivi = suivre(
            [
                fabrique_transaction("T1", ticker="TEST1", quantite=10, cours=1_000),
                fabrique_transaction("T2", ticker="TEST2", quantite=10, cours=2_000),
            ]
        )
        return valoriser(
            suivi,
            {"TEST1": cotation("TEST1", 1_000), "TEST2": cotation("TEST2", 2_000)},
            moteur_frais,
            moteur_fiscal,
        )

    @staticmethod
    def _series_liees(
        fabrique_serie: Callable[..., SerieTechnique],
    ) -> dict[str, SerieTechnique]:
        cours = [1000 + int(200 * math.sin(i / 3)) for i in range(120)]
        return {
            "TEST1": fabrique_serie(cours, ticker="TEST1"),
            "TEST2": fabrique_serie([c * 2 for c in cours], ticker="TEST2"),
        }

    def test_deux_lignes_qui_varient_ensemble_sont_signalees(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_serie: Callable[..., SerieTechnique],
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        series = self._series_liees(fabrique_serie)
        portefeuille = self._portefeuille(moteur_frais, moteur_fiscal, fabrique_transaction)
        rapport = controler(portefeuille, {}, series, configuration)
        assert rapport.correlations, "les corrélations doivent être calculées"
        mesuree = rapport.correlations[0]
        assert mesuree.valeur is not None
        assert mesuree.valeur > Decimal("0.99"), "deux séries proportionnelles"
        assert any("fortement corrélées" in a for a in rapport.avertissements)

    def test_sous_le_minimum_de_seances_communes_rien_n_est_invente(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_serie: Callable[..., SerieTechnique],
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        """Apparier deux valeurs qui ne cotent pas les mêmes jours mesurerait le
        calendrier, pas le marché."""
        series = {
            "TEST1": fabrique_serie([1000, None, 1010, None, 1020], ticker="TEST1"),
            "TEST2": fabrique_serie([None, 900, None, 910, None], ticker="TEST2"),
        }
        portefeuille = self._portefeuille(moteur_frais, moteur_fiscal, fabrique_transaction)
        rapport = controler(portefeuille, {}, series, configuration)
        assert rapport.correlations
        assert rapport.correlations[0].valeur is None
        assert rapport.correlations[0].motif_indisponible
        assert not any("fortement corrélées" in a for a in rapport.avertissements)

    def test_le_seuil_declare_decide_de_l_alerte(
        self,
        configuration: Configuration,
        moteur_frais: MoteurFrais,
        moteur_fiscal: MoteurFiscal,
        fabrique_serie: Callable[..., SerieTechnique],
        fabrique_transaction: Callable[..., Transaction],
    ) -> None:
        series = self._series_liees(fabrique_serie)
        portefeuille = self._portefeuille(moteur_frais, moteur_fiscal, fabrique_transaction)
        tolerant = configuration.model_copy(
            update={
                "risque": configuration.risque.model_copy(
                    update={"correlation_alerte": Decimal("1.01")}
                )
            }
        )
        rapport = controler(portefeuille, {}, series, tolerant)
        assert not any("fortement corrélées" in a for a in rapport.avertissements)
