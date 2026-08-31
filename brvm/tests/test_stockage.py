"""Stockage : idempotence, historisation des corrections, aller-retour typé."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from brvm.domain.enums import (
    BaseFrais,
    GraviteAnomalie,
    Pays,
    SensOperation,
    StatutCollecte,
    StatutFiabilite,
    StatutSeance,
    TypeFluxEspece,
    TypeOst,
)
from brvm.domain.modeles import (
    Anomalie,
    Cotation,
    FluxEspece,
    Instrument,
    JournalCollecte,
    LigneFrais,
    OperationSurTitre,
    Transaction,
)
from brvm.storage.base import VERSION_SCHEMA, BaseDonnees
from brvm.storage.depots import (
    DepotAnomalies,
    DepotCotations,
    DepotFluxEspeces,
    DepotInstruments,
    DepotJournalCollectes,
    DepotOperationsSurTitres,
    DepotParametres,
    DepotTransactions,
    EtatEcriture,
)
from brvm.utils.erreurs import ErreurStockage

T = datetime(2026, 3, 2, 15, 30, tzinfo=UTC)
J = date(2026, 3, 2)


class TestMigration:
    def test_schema_applique(self, base: BaseDonnees) -> None:
        assert base.version() == VERSION_SCHEMA

    def test_reouverture_ne_rejoue_pas_la_migration(self, tmp_path: Path) -> None:
        chemin = tmp_path / "base.sqlite3"
        with BaseDonnees(chemin) as premiere:
            DepotParametres(premiere).definir("marqueur", "présent")
        with BaseDonnees(chemin) as seconde:
            assert seconde.version() == VERSION_SCHEMA
            assert DepotParametres(seconde).obtenir("marqueur") == "présent"

    def test_base_plus_recente_refusee(self, tmp_path: Path) -> None:
        """Rétrograder le logiciel sur une base plus récente corromprait les données."""
        chemin = tmp_path / "base.sqlite3"
        with BaseDonnees(chemin) as ouverte:
            ouverte.connexion.execute(
                "INSERT INTO version_schema (version, applique_le) VALUES (?, ?)",
                (VERSION_SCHEMA + 1, T.isoformat()),
            )
        with pytest.raises(ErreurStockage, match="version plus récente"):
            BaseDonnees(chemin).ouvrir()

    def test_cles_etrangeres_actives(self, base: BaseDonnees) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            base.connexion.execute(
                """
                INSERT INTO frais_transaction
                    (transaction_id, ordre, libelle, base_calcul, assiette, montant)
                VALUES ('inexistante', 1, 'x', 'MONTANT_FIXE', 0, 100)
                """
            )


class TestIdempotence:
    def test_premiere_ecriture(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        resultat = DepotCotations(base).enregistrer(fabrique_cotation())
        assert resultat.etat is EtatEcriture.INSEREE
        assert resultat.revision == 1

    def test_rejouer_la_meme_collecte_ne_change_rien(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation())
        resultat = depot.enregistrer(fabrique_cotation())
        assert resultat.etat is EtatEcriture.INCHANGEE
        assert resultat.revision == 1
        assert len(depot.lire("TEST1")) == 1
        assert depot.revisions("TEST1", J, "fixture") == []

    def test_reconfirmation_rafraichit_l_horodatage(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Même donnée, collectée plus tard : elle est plus fraîche, pas corrigée."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation())
        plus_tard = T + timedelta(hours=4)
        depot.enregistrer(
            fabrique_cotation(horodatage_donnee=plus_tard, horodatage_collecte=plus_tard)
        )
        relue = depot.lire("TEST1")[0]
        assert relue.horodatage_donnee == plus_tard
        assert relue.revision == 1

    def test_horodatage_plus_ancien_ne_regresse_pas(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        recent = T + timedelta(hours=4)
        depot.enregistrer(fabrique_cotation(horodatage_donnee=recent, horodatage_collecte=recent))
        depot.enregistrer(fabrique_cotation())
        assert depot.lire("TEST1")[0].horodatage_donnee == recent

    def test_meme_seance_de_deux_sources_coexiste(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """La clé inclut la source : une source n'écrase jamais l'autre."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(source="source_a", cloture=1000))
        depot.enregistrer(fabrique_cotation(source="source_b", cloture=1005))
        assert len(depot.lire("TEST1")) == 2

    def test_lot(self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]) -> None:
        depot = DepotCotations(base)
        serie = [fabrique_cotation(jour=date(2026, 3, jour)) for jour in (2, 3, 4)]
        premier = depot.enregistrer_lot(serie)
        assert (premier.inserees, premier.inchangees, premier.corrigees) == (3, 0, 0)
        second = depot.enregistrer_lot(serie)
        assert (second.inserees, second.inchangees, second.corrigees) == (0, 3, 0)
        assert second.total == 3


class TestCorrectionDeCote:
    def test_correction_incremente_la_revision(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(cloture=1000))
        resultat = depot.enregistrer(fabrique_cotation(cloture=1010))
        assert resultat.etat is EtatEcriture.CORRIGEE
        assert resultat.revision == 2
        assert depot.lire("TEST1")[0].cloture == 1010

    def test_ancienne_valeur_archivee(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Aucune valeur observée n'est perdue : c'est ce qui permet de rejouer
        une analyse telle qu'elle était calculable avant la correction."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(cloture=1000))
        depot.enregistrer(fabrique_cotation(cloture=1010), motif="correction publiée")
        archives = depot.revisions("TEST1", J, "fixture")
        assert len(archives) == 1
        assert archives[0]["cloture"] == 1000
        assert archives[0]["revision"] == 1
        assert archives[0]["motif"] == "correction publiée"

    def test_corrections_successives_empilees(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        for cours in (1000, 1010, 1020):
            depot.enregistrer(fabrique_cotation(cloture=cours))
        archives = depot.revisions("TEST1", J, "fixture")
        assert [archive["cloture"] for archive in archives] == [1000, 1010]
        assert depot.lire("TEST1")[0].revision == 3

    def test_lot_compte_les_corrections(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        depot.enregistrer_lot([fabrique_cotation(cloture=1000)])
        resume = depot.enregistrer_lot([fabrique_cotation(cloture=1010)])
        assert resume.corrigees == 1
        assert resume.cles_corrigees == [("TEST1", J, "fixture")]


class TestLectureEtTypes:
    def test_aller_retour_conserve_les_valeurs(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        origine = fabrique_cotation(
            cloture=1000,
            ouverture=990,
            plus_haut=1010,
            plus_bas=985,
            cours_precedent=995,
            volume_titres=1234,
            volume_xof=1_234_000,
            nb_transactions=7,
            meilleure_limite_achat=995,
            meilleure_limite_vente=1005,
            commentaire="note de test",
        )
        depot.enregistrer(origine)
        relue = depot.lire("TEST1")[0]
        for champ in origine.CHAMPS_EMPREINTE:
            assert getattr(relue, champ) == getattr(origine, champ)
        assert relue.commentaire == "note de test"

    def test_relecture_repasse_par_la_validation(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Une base corrompue à la main ne doit pas produire un modèle invalide."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation())
        base.connexion.execute("UPDATE cotations SET cloture = -5")
        with pytest.raises(ValidationError):
            depot.lire("TEST1")

    def test_filtrage_par_periode(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        depot.enregistrer_lot(
            [fabrique_cotation(jour=date(2026, 3, jour)) for jour in (2, 3, 4, 5)]
        )
        extrait = depot.lire("TEST1", debut=date(2026, 3, 3), fin=date(2026, 3, 4))
        assert [cotation.date_seance.day for cotation in extrait] == [3, 4]

    def test_quarantaine_exclue_par_defaut(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Une donnée mise en quarantaine n'alimente aucun calcul, mais reste lisible
        pour investigation."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(jour=date(2026, 3, 2)))
        depot.enregistrer(
            fabrique_cotation(jour=date(2026, 3, 3), statut_fiabilite=StatutFiabilite.QUARANTAINE)
        )
        assert len(depot.lire("TEST1")) == 1
        assert len(depot.lire("TEST1", inclure_quarantaine=True)) == 2

    def test_horodatage_le_plus_ancien(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Indicateur de fraîcheur : chaque écran doit afficher l'âge de la donnée
        la plus périmée qu'il utilise."""
        depot = DepotCotations(base)
        ancien = T - timedelta(days=3)
        depot.enregistrer(
            fabrique_cotation(
                jour=date(2026, 3, 2), horodatage_donnee=ancien, horodatage_collecte=T
            )
        )
        depot.enregistrer(fabrique_cotation(jour=date(2026, 3, 3)))
        assert depot.horodatage_le_plus_ancien() == ancien

    def test_horodatage_le_plus_ancien_ignore_la_quarantaine(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(jour=date(2026, 3, 3)))
        depot.enregistrer(
            fabrique_cotation(
                jour=date(2026, 3, 2),
                horodatage_donnee=T - timedelta(days=10),
                statut_fiabilite=StatutFiabilite.QUARANTAINE,
            )
        )
        assert depot.horodatage_le_plus_ancien() == T

    def test_base_vide_n_a_pas_d_horodatage(self, base: BaseDonnees) -> None:
        assert DepotCotations(base).horodatage_le_plus_ancien() is None


class TestReferentiel:
    def test_aller_retour_instrument(self, base: BaseDonnees) -> None:
        depot = DepotInstruments(base)
        instrument = Instrument(
            ticker="TEST1",
            nom="Société fictive de test",
            pays=Pays.COTE_DIVOIRE,
            secteur="Secteur fictif",
            nombre_titres=1_000_000,
            date_maj=T,
        )
        depot.enregistrer(instrument)
        assert depot.obtenir("TEST1") == instrument

    def test_reecriture_met_a_jour(self, base: BaseDonnees) -> None:
        depot = DepotInstruments(base)
        depot.enregistrer(Instrument(ticker="TEST1", nom="Ancien nom", pays=Pays.COTE_DIVOIRE))
        depot.enregistrer(Instrument(ticker="TEST1", nom="Nouveau nom", pays=Pays.COTE_DIVOIRE))
        assert len(depot.lister()) == 1
        obtenu = depot.obtenir("TEST1")
        assert obtenu is not None and obtenu.nom == "Nouveau nom"

    def test_filtre_actifs(self, base: BaseDonnees) -> None:
        depot = DepotInstruments(base)
        depot.enregistrer(Instrument(ticker="TEST1", nom="Active", pays=Pays.COTE_DIVOIRE))
        depot.enregistrer(Instrument(ticker="TEST2", nom="Radiée", pays=Pays.SENEGAL, actif=False))
        assert [i.ticker for i in depot.lister(actifs_seulement=True)] == ["TEST1"]
        assert len(depot.lister()) == 2

    def test_ticker_cote_absent_du_referentiel_signale(
        self, base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
    ) -> None:
        """Une source peut publier un ticker inconnu : on l'écrit et on le signale,
        plutôt que de perdre la donnée ou de créer un instrument d'office."""
        depot = DepotCotations(base)
        depot.enregistrer(fabrique_cotation(ticker="TEST9"))
        assert depot.tickers_orphelins() == ["TEST9"]
        DepotInstruments(base).enregistrer(
            Instrument(ticker="TEST9", nom="Société fictive", pays=Pays.COTE_DIVOIRE)
        )
        assert depot.tickers_orphelins() == []


class TestOperationsSurTitres:
    def test_aller_retour(self, base: BaseDonnees) -> None:
        depot = DepotOperationsSurTitres(base)
        operation = OperationSurTitre(
            identifiant="OST1",
            ticker="TEST1",
            type_ost=TypeOst.DIVIDENDE,
            date_ex=J,
            date_paiement=date(2026, 3, 20),
            montant_brut_par_action=50,
            source="fixture",
        )
        depot.enregistrer(operation)
        assert depot.lister("TEST1") == [operation]

    def test_borne_de_connaissance(self, base: BaseDonnees) -> None:
        """`jusqu_a` sert au backtest : ne relire que les opérations déjà détachées."""
        depot = DepotOperationsSurTitres(base)
        for jour in (date(2026, 3, 2), date(2026, 6, 1)):
            depot.enregistrer(
                OperationSurTitre(
                    identifiant=f"OST-{jour}",
                    ticker="TEST1",
                    type_ost=TypeOst.DIVIDENDE,
                    date_ex=jour,
                    montant_brut_par_action=50,
                    source="fixture",
                )
            )
        assert len(depot.lister("TEST1", jusqu_a=date(2026, 4, 1))) == 1
        assert len(depot.lister("TEST1")) == 2


class TestPortefeuille:
    def transaction(self) -> Transaction:
        return Transaction(
            identifiant="T1",
            ticker="TEST1",
            date_operation=J,
            date_reglement=date(2026, 3, 5),
            sens=SensOperation.ACHAT,
            quantite=100,
            cours_unitaire=1000,
            frais=(
                LigneFrais(
                    libelle="Commission fictive",
                    base_calcul=BaseFrais.MONTANT_BRUT,
                    taux=Decimal("0.01"),
                    assiette=100_000,
                    montant=1000,
                ),
                LigneFrais(
                    libelle="Frais fixes fictifs",
                    base_calcul=BaseFrais.MONTANT_FIXE,
                    assiette=0,
                    montant=500,
                ),
            ),
            reference_sgi="REF-FICTIVE",
        )

    def test_aller_retour_avec_frais_ordonnes(self, base: BaseDonnees) -> None:
        depot = DepotTransactions(base)
        origine = self.transaction()
        depot.enregistrer(origine)
        relue = depot.lister("TEST1")[0]
        assert relue == origine
        assert [ligne.libelle for ligne in relue.frais] == [
            "Commission fictive",
            "Frais fixes fictifs",
        ]

    def test_taux_conserve_sa_precision(self, base: BaseDonnees) -> None:
        depot = DepotTransactions(base)
        depot.enregistrer(self.transaction())
        assert depot.lister()[0].frais[0].taux == Decimal("0.01")

    def test_reecriture_ne_duplique_pas_les_frais(self, base: BaseDonnees) -> None:
        depot = DepotTransactions(base)
        depot.enregistrer(self.transaction())
        depot.enregistrer(self.transaction())
        assert len(depot.lister()) == 1
        assert len(depot.lister()[0].frais) == 2

    def test_flux_especes(self, base: BaseDonnees) -> None:
        depot = DepotFluxEspeces(base)
        flux = FluxEspece(
            identifiant="F1",
            date_flux=J,
            type_flux=TypeFluxEspece.DIVIDENDE,
            ticker="TEST1",
            montant_brut=50_000,
            retenue_fiscale=5_000,
            source="fixture",
        )
        depot.enregistrer(flux)
        relu = depot.lister("TEST1")[0]
        assert relu == flux
        assert relu.montant_net == 45_000


class TestQualiteEtExploitation:
    def test_anomalie_aller_retour(self, base: BaseDonnees) -> None:
        depot = DepotAnomalies(base)
        anomalie = Anomalie(
            identifiant="A1",
            source="fixture",
            type_anomalie="variation_hors_seuil",
            gravite=GraviteAnomalie.BLOQUANTE,
            message="Variation supérieure au seuil réglementaire configuré",
            ticker="TEST1",
            date_seance=J,
            charge_utile={"cloture": 2000, "cours_precedent": 1000},
            detectee_le=T,
        )
        depot.enregistrer(anomalie)
        relue = depot.lister()[0]
        assert relue.charge_utile == {"cloture": 2000, "cours_precedent": 1000}
        assert relue.gravite is GraviteAnomalie.BLOQUANTE

    def test_anomalie_resolue_sort_de_la_liste_ouverte(self, base: BaseDonnees) -> None:
        depot = DepotAnomalies(base)
        depot.enregistrer(
            Anomalie(
                identifiant="A1",
                source="fixture",
                type_anomalie="doublon",
                gravite=GraviteAnomalie.AVERTISSEMENT,
                message="Doublon détecté",
                detectee_le=T,
            )
        )
        assert len(depot.lister()) == 1
        depot.marquer_resolue("A1")
        assert depot.lister() == []
        assert len(depot.lister(ouvertes_seulement=False)) == 1

    def test_journal_de_collecte(self, base: BaseDonnees) -> None:
        depot = DepotJournalCollectes(base)
        depot.enregistrer(
            JournalCollecte(
                identifiant="C1",
                source="fixture",
                debut=T,
                fin=T + timedelta(minutes=2),
                statut=StatutCollecte.SUCCES,
                nb_lignes_lues=48,
                nb_lignes_ecrites=48,
            )
        )
        derniere = depot.derniere("fixture")
        assert derniere is not None
        assert derniere.statut is StatutCollecte.SUCCES
        assert derniere.nb_lignes_lues == 48

    def test_parametres(self, base: BaseDonnees) -> None:
        depot = DepotParametres(base)
        assert depot.obtenir("inconnu", "défaut") == "défaut"
        depot.definir("derniere_collecte", T.isoformat())
        depot.definir("derniere_collecte", (T + timedelta(days=1)).isoformat())
        assert depot.obtenir("derniere_collecte") == (T + timedelta(days=1)).isoformat()


def test_statut_seance_conserve(
    base: BaseDonnees, fabrique_cotation: Callable[..., Cotation]
) -> None:
    """La distinction séance sans transaction / séance cotée doit survivre au stockage."""
    depot = DepotCotations(base)
    depot.enregistrer(
        fabrique_cotation(
            jour=date(2026, 3, 3),
            statut=StatutSeance.SANS_TRANSACTION,
            volume=0,
            cloture=1000,
        )
    )
    relue = depot.lire("TEST1")[0]
    assert relue.statut_seance is StatutSeance.SANS_TRANSACTION
    assert relue.cours_effectivement_traite is None
