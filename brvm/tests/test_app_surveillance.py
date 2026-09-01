"""Ce qui déclenche une alerte, et ce qui n'en déclenche pas.

Toute la règle « quand alerter » est vérifiée ici sans envoyer un seul message :
c'est l'intérêt de l'avoir séparée de la diffusion.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from brvm.app.alertes import CategorieAlerte, NiveauAlerte
from brvm.app.surveillance import (
    MENTION_SIGNAL,
    depuis_anomalies,
    depuis_fraicheur,
    depuis_ingestion,
    depuis_risque,
    depuis_signaux,
    rassembler,
)
from brvm.config.modeles import Configuration
from brvm.domain.enums import GraviteAnomalie, StatutCollecte
from brvm.domain.modeles import Anomalie
from brvm.indicators.confiance import ScoreConfiance
from brvm.indicators.signaux import SensSignal, Signal
from brvm.ingestion.orchestrateur import BilanIngestion
from brvm.portfolio.valorisation import LigneValorisee, Portefeuille
from brvm.risk.controles import ConstatConcentration, ConstatLiquidite, Dimension, RapportRisque

INSTANT = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)


def ligne(
    ticker: str = "TEST1",
    horodatage: datetime | None = INSTANT,
    valorisee: bool = True,
) -> LigneValorisee:
    return LigneValorisee(
        ticker=ticker,
        quantite=10,
        cout_total=10_000,
        prix_revient_unitaire=Decimal(1000),
        cours=1000 if valorisee else None,
        horodatage_cours=horodatage if valorisee else None,
        date_cours=date(2026, 3, 2) if valorisee else None,
        valeur=10_000 if valorisee else None,
        plus_value_latente_brute=0 if valorisee else None,
        plus_value_latente_nette=0 if valorisee else None,
        frais_cession_estimes=0 if valorisee else None,
        impot_estime=0 if valorisee else None,
        dividendes_nets=0,
        poids=Decimal("1") if valorisee else None,
        motif_indisponible=None if valorisee else "aucun cours disponible",
    )


def portefeuille(*lignes: LigneValorisee) -> Portefeuille:
    horodatages = [poste.horodatage_cours for poste in lignes if poste.horodatage_cours is not None]
    return Portefeuille(
        lignes=tuple(lignes),
        cout_total=sum(poste.cout_total for poste in lignes),
        valeur_totale=sum(poste.valeur or 0 for poste in lignes),
        plus_value_latente_brute=0,
        plus_value_latente_nette=0,
        dividendes_nets_encaisses=0,
        plus_values_realisees=0,
        horodatage_le_plus_ancien=min(horodatages) if horodatages else None,
    )


def bilan(source: str = "src", statut: StatutCollecte = StatutCollecte.SUCCES) -> BilanIngestion:
    return BilanIngestion(source=source, statut=statut, lignes_lues=10, lignes_rejetees=2)


def signal(regle: str = "croisement", ticker: str = "TEST1") -> Signal:
    return Signal(
        ticker=ticker,
        date_constat=date(2026, 3, 2),
        date_execution=date(2026, 3, 3),
        sens=SensSignal.ACHAT,
        regle=regle,
        explication="Explication.",
        confiance=ScoreConfiance(
            valeur=Decimal("0.8"),
            assiduite=Decimal("0.9"),
            profondeur=Decimal("0.9"),
            etroitesse=Decimal("0.99"),
            seances_cotees=18,
            seances_attendues=20,
            montant_moyen_xof=Decimal(500_000),
            fourchette_moyenne=Decimal("0.01"),
        ),
    )


class TestIngestion:
    def test_echec_de_source_est_critique(self, configuration: Configuration) -> None:
        alertes = depuis_ingestion([bilan(statut=StatutCollecte.ECHEC)], configuration, INSTANT)
        assert [a.niveau for a in alertes] == [NiveauAlerte.CRITIQUE]
        assert alertes[0].categorie is CategorieAlerte.ECHEC_SOURCE

    def test_mode_degrade_est_signale_avec_son_motif(self, configuration: Configuration) -> None:
        alertes = depuis_ingestion([bilan(statut=StatutCollecte.DEGRADE)], configuration, INSTANT)
        assert alertes[0].niveau is NiveauAlerte.AVERTISSEMENT
        assert "cache local" in alertes[0].message

    def test_collecte_partielle_dit_combien_de_lignes_sont_rejetees(
        self, configuration: Configuration
    ) -> None:
        alertes = depuis_ingestion([bilan(statut=StatutCollecte.PARTIEL)], configuration, INSTANT)
        assert "2 ligne(s) rejetée(s) sur 10" in alertes[0].message

    def test_collecte_reussie_ne_dit_rien(self, configuration: Configuration) -> None:
        assert depuis_ingestion([bilan()], configuration, INSTANT) == []

    def test_desactivee_en_configuration(self, configuration: Configuration) -> None:
        muette = configuration.model_copy(
            update={
                "alertes": configuration.alertes.model_copy(update={"alerter_echec_source": False})
            }
        )
        assert depuis_ingestion([bilan(statut=StatutCollecte.ECHEC)], muette, INSTANT) == []


class TestAnomalies:
    @staticmethod
    def _anomalie(identifiant: str, type_anomalie: str = "ligne_illisible") -> Anomalie:
        return Anomalie(
            identifiant=identifiant,
            source="src",
            type_anomalie=type_anomalie,
            gravite=GraviteAnomalie.BLOQUANTE,
            message="Ligne illisible.",
            detectee_le=INSTANT,
        )

    def test_les_bloquantes_sont_regroupees_par_type(self, configuration: Configuration) -> None:
        """Dix lignes illisibles dans la même page sont un seul problème."""
        alertes = depuis_anomalies(
            [self._anomalie("a"), self._anomalie("b"), self._anomalie("c")],
            configuration,
            INSTANT,
        )
        assert len(alertes) == 1
        assert "3 cotation(s) en quarantaine" in alertes[0].titre

    def test_deux_types_donnent_deux_constats(self, configuration: Configuration) -> None:
        alertes = depuis_anomalies(
            [self._anomalie("a"), self._anomalie("b", "cours_hors_seuil")],
            configuration,
            INSTANT,
        )
        assert len(alertes) == 2

    def test_les_avertissements_ne_remontent_pas(self, configuration: Configuration) -> None:
        douce = Anomalie(
            identifiant="x",
            source="src",
            type_anomalie="donnee_perimee",
            gravite=GraviteAnomalie.AVERTISSEMENT,
            message="Vieille.",
            detectee_le=INSTANT,
        )
        assert depuis_anomalies([douce], configuration, INSTANT) == []


class TestFraicheur:
    def test_cours_recent_ne_dit_rien(self, configuration: Configuration) -> None:
        assert depuis_fraicheur(portefeuille(ligne()), configuration, INSTANT) == []

    def test_cours_trop_vieux_est_signale_avec_son_age(self, configuration: Configuration) -> None:
        seuil = configuration.alertes.age_donnee_max_minutes
        vieux = INSTANT.replace(year=2025)
        alertes = depuis_fraicheur(portefeuille(ligne(horodatage=vieux)), configuration, INSTANT)
        assert len(alertes) == 1
        assert alertes[0].categorie is CategorieAlerte.DONNEE_PERIMEE
        assert str(seuil) in alertes[0].message
        assert alertes[0].horodatage_donnee == vieux

    def test_ligne_non_valorisee_est_critique(self, configuration: Configuration) -> None:
        """Une ligne sans cours n'est pas comptée pour zéro, et c'est grave."""
        alertes = depuis_fraicheur(portefeuille(ligne(valorisee=False)), configuration, INSTANT)
        assert alertes[0].niveau is NiveauAlerte.CRITIQUE
        assert "n'est pas comptée pour zéro" in alertes[0].message


class TestRisque:
    def test_concentration_depassee_est_signalee(self, configuration: Configuration) -> None:
        rapport = RapportRisque(
            concentrations=(
                ConstatConcentration(
                    dimension=Dimension.LIGNE,
                    cle="TEST1",
                    poids=Decimal("0.9"),
                    limite=Decimal("0.3"),
                    valeur=90_000,
                ),
            )
        )
        alertes = depuis_risque(rapport, configuration, INSTANT)
        assert len(alertes) == 1
        assert alertes[0].ticker == "TEST1"
        assert alertes[0].categorie is CategorieAlerte.SEUIL_RISQUE

    def test_concentration_respectee_ne_dit_rien(self, configuration: Configuration) -> None:
        rapport = RapportRisque(
            concentrations=(
                ConstatConcentration(
                    dimension=Dimension.LIGNE,
                    cle="TEST1",
                    poids=Decimal("0.1"),
                    limite=Decimal("0.3"),
                    valeur=10_000,
                ),
            )
        )
        assert depuis_risque(rapport, configuration, INSTANT) == []

    @staticmethod
    def _liquidite(seances: Decimal | None) -> ConstatLiquidite:
        return ConstatLiquidite(
            ticker="TEST1",
            quantite_detenue=1000,
            volume_moyen=Decimal(100),
            seances_cotees=10,
            seances_observees=20,
            part_max_volume=Decimal("0.2"),
            debit_quotidien=Decimal(20),
            seances_pour_deboucler=seances,
            motif_indisponible=None if seances is not None else "aucune séance cotée",
        )

    def test_liquidite_non_mesurable_est_signalee(self, configuration: Configuration) -> None:
        """Ne pas savoir combien de temps il faut pour sortir n'est pas rassurant."""
        alertes = depuis_risque(
            RapportRisque(liquidites=(self._liquidite(None),)), configuration, INSTANT
        )
        assert len(alertes) == 1
        assert "ne le supposez pas court" in alertes[0].message

    def test_sans_seuil_declare_aucun_debouclage_nest_juge(
        self, configuration: Configuration
    ) -> None:
        """Aucun délai « raisonnable » n'est supposé à la place de l'utilisateur."""
        assert configuration.risque.seances_max_debouclage is None
        assert (
            depuis_risque(
                RapportRisque(liquidites=(self._liquidite(Decimal(500)),)),
                configuration,
                INSTANT,
            )
            == []
        )

    def test_avec_seuil_declare_le_debouclage_lent_est_signale(
        self, configuration: Configuration
    ) -> None:
        avec = configuration.model_copy(
            update={
                "risque": configuration.risque.model_copy(update={"seances_max_debouclage": 20})
            }
        )
        alertes = depuis_risque(
            RapportRisque(liquidites=(self._liquidite(Decimal(50)),)), avec, INSTANT
        )
        assert len(alertes) == 1
        assert "20 séance(s)" in alertes[0].message

    def test_desactive_en_configuration(self, configuration: Configuration) -> None:
        muette = configuration.model_copy(
            update={
                "alertes": configuration.alertes.model_copy(update={"alerter_seuil_risque": False})
            }
        )
        assert (
            depuis_risque(RapportRisque(liquidites=(self._liquidite(None),)), muette, INSTANT) == []
        )


class TestSignaux:
    def test_le_constat_porte_sa_date_dexecution(self, configuration: Configuration) -> None:
        alertes = depuis_signaux([signal()], configuration, INSTANT)
        assert "exécutable au plus tôt le 2026-03-03" in alertes[0].message

    def test_le_constat_nest_jamais_presente_comme_un_conseil(
        self, configuration: Configuration
    ) -> None:
        alertes = depuis_signaux([signal()], configuration, INSTANT)
        assert MENTION_SIGNAL in alertes[0].message
        assert "promet" not in alertes[0].titre

    def test_un_signal_reste_une_information(self, configuration: Configuration) -> None:
        """Un franchissement n'est pas une urgence : il n'écrase pas une source
        tombée dans la liste des constats."""
        assert depuis_signaux([signal()], configuration, INSTANT)[0].niveau is (
            NiveauAlerte.INFORMATION
        )

    def test_desactive_en_configuration(self, configuration: Configuration) -> None:
        muette = configuration.model_copy(
            update={
                "alertes": configuration.alertes.model_copy(
                    update={"alerter_signal_technique": False}
                )
            }
        )
        assert depuis_signaux([signal()], muette, INSTANT) == []


class TestRassemblement:
    def test_le_plus_grave_dabord(self, configuration: Configuration) -> None:
        alertes = rassembler(
            configuration,
            INSTANT,
            bilans=[bilan(statut=StatutCollecte.ECHEC)],
            portefeuille=portefeuille(ligne()),
            signaux=[signal()],
        )
        niveaux = [alerte.niveau for alerte in alertes]
        assert niveaux == sorted(niveaux, key=lambda n: -n.rang)
        assert niveaux[0] is NiveauAlerte.CRITIQUE

    def test_sans_rien_a_signaler_la_liste_est_vide(self, configuration: Configuration) -> None:
        assert rassembler(configuration, INSTANT, bilans=[bilan()]) == []
