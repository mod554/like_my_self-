"""Modèles du domaine : validation aux frontières, dérivés, empreinte."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from brvm.domain.enums import (
    BaseFrais,
    GraviteAnomalie,
    Pays,
    SensOperation,
    StatutSeance,
    TypeFluxEspece,
    TypeOst,
)
from brvm.domain.modeles import (
    Anomalie,
    Cotation,
    FluxEspece,
    Instrument,
    LigneFrais,
    OperationSurTitre,
    Transaction,
    isin_conforme,
)

T = datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


class TestInstrument:
    def test_instrument_minimal(self) -> None:
        instrument = Instrument(ticker="TEST1", nom="Société fictive", pays=Pays.COTE_DIVOIRE)
        assert instrument.devise.value == "XOF"
        assert instrument.actif is True

    def test_ticker_minuscule_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Instrument(ticker="test1", nom="Société fictive", pays=Pays.COTE_DIVOIRE)

    def test_champ_surnumeraire_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Instrument(
                ticker="TEST1",
                nom="Société fictive",
                pays=Pays.COTE_DIVOIRE,
                secteur_bis="typo",  # type: ignore[call-arg]
            )

    def test_immuable(self) -> None:
        instrument = Instrument(ticker="TEST1", nom="Société fictive", pays=Pays.COTE_DIVOIRE)
        with pytest.raises(ValidationError):
            instrument.nom = "Autre"

    def test_date_maj_naive_refusee(self) -> None:
        with pytest.raises(ValidationError):
            Instrument(
                ticker="TEST1",
                nom="Société fictive",
                pays=Pays.COTE_DIVOIRE,
                date_maj=datetime(2026, 3, 2, 15, 30),
            )


class TestIsin:
    """Le chiffre de contrôle est vérifié, sans référence à un titre réel.

    Propriété testée : pour un corps donné, une seule des dix terminaisons
    possibles est valide. C'est vrai de tout code à clé modulo 10.
    """

    CORPS = "CI0000000AB"

    def test_une_seule_cle_valide_par_corps(self) -> None:
        valides = [chiffre for chiffre in range(10) if isin_conforme(f"{self.CORPS}{chiffre}")]
        assert len(valides) == 1

    def test_isin_valide_accepte_par_le_modele(self) -> None:
        cle = next(c for c in range(10) if isin_conforme(f"{self.CORPS}{c}"))
        instrument = Instrument(
            ticker="TEST1",
            nom="Société fictive",
            pays=Pays.COTE_DIVOIRE,
            isin=f"{self.CORPS}{cle}",
        )
        assert instrument.isin is not None

    def test_cle_fausse_refusee(self) -> None:
        cle = next(c for c in range(10) if isin_conforme(f"{self.CORPS}{c}"))
        fausse = (cle + 1) % 10
        with pytest.raises(ValidationError) as capture:
            Instrument(
                ticker="TEST1",
                nom="Société fictive",
                pays=Pays.COTE_DIVOIRE,
                isin=f"{self.CORPS}{fausse}",
            )
        assert "contrôle" in str(capture.value)

    @pytest.mark.parametrize("mauvais", ["CI0000000AB", "ci0000000ab1", "CI-000000AB1", ""])
    def test_formats_invalides(self, mauvais: str) -> None:
        with pytest.raises(ValidationError):
            Instrument(ticker="TEST1", nom="Société fictive", pays=Pays.COTE_DIVOIRE, isin=mauvais)


class TestCotation:
    def base(self, **extras: object) -> dict[str, object]:
        parametres: dict[str, object] = {
            "ticker": "TEST1",
            "date_seance": date(2026, 3, 2),
            "source": "fixture",
            "statut_seance": StatutSeance.COTEE,
            "cloture": 1000,
            "volume_titres": 100,
            "horodatage_donnee": T,
            "horodatage_collecte": T,
        }
        parametres.update(extras)
        return parametres

    def test_cotation_valide(self) -> None:
        cotation = Cotation(**self.base())  # type: ignore[arg-type]
        assert cotation.cle == ("TEST1", date(2026, 3, 2), "fixture")
        assert cotation.revision == 1

    def test_cours_nul_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Cotation(**self.base(cloture=0))  # type: ignore[arg-type]

    def test_cours_negatif_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Cotation(**self.base(cloture=-10))  # type: ignore[arg-type]

    def test_seance_cotee_exige_un_cours(self) -> None:
        with pytest.raises(ValidationError) as capture:
            Cotation(**self.base(cloture=None))  # type: ignore[arg-type]
        assert "clôture" in str(capture.value)

    def test_seance_cotee_exige_un_volume(self) -> None:
        with pytest.raises(ValidationError) as capture:
            Cotation(**self.base(volume_titres=0))  # type: ignore[arg-type]
        assert "SANS_TRANSACTION" in str(capture.value)

    def test_seance_sans_transaction_refuse_un_volume(self) -> None:
        with pytest.raises(ValidationError):
            Cotation(
                **self.base(statut_seance=StatutSeance.SANS_TRANSACTION, volume_titres=5)  # type: ignore[arg-type]
            )

    def test_seance_fermee_refuse_cours_et_volume(self) -> None:
        with pytest.raises(ValidationError):
            Cotation(**self.base(statut_seance=StatutSeance.FERMEE, volume_titres=0))  # type: ignore[arg-type]

    def test_incoherence_haut_bas(self) -> None:
        with pytest.raises(ValidationError) as capture:
            Cotation(**self.base(plus_haut=900, plus_bas=1100))  # type: ignore[arg-type]
        assert "plus_haut" in str(capture.value)

    def test_plus_haut_inferieur_a_la_cloture(self) -> None:
        with pytest.raises(ValidationError):
            Cotation(**self.base(plus_haut=950, plus_bas=900, cloture=1000))  # type: ignore[arg-type]

    def test_horodatage_naif_refuse(self) -> None:
        """Un horodatage sans fuseau rendrait l'âge de la donnée incalculable."""
        with pytest.raises(ValidationError) as capture:
            Cotation(**self.base(horodatage_donnee=datetime(2026, 3, 2, 15, 30)))  # type: ignore[arg-type]
        assert capture.value.errors()[0]["type"] == "timezone_aware"

    def test_donnee_posterieure_a_sa_collecte_refusee(self) -> None:
        with pytest.raises(ValidationError) as capture:
            Cotation(**self.base(horodatage_donnee=T + timedelta(hours=1)))  # type: ignore[arg-type]
        assert "collectée avant d'exister" in str(capture.value)


class TestDistinctionSansTransaction:
    """Le cœur de l'adaptation à l'illiquidité : ne pas confondre « pas d'échange »
    et « cours inchangé »."""

    def test_seance_cotee_expose_un_cours_traite(self) -> None:
        cotation = Cotation(
            ticker="TEST1",
            date_seance=date(2026, 3, 2),
            source="fixture",
            statut_seance=StatutSeance.COTEE,
            cloture=1000,
            volume_titres=100,
            horodatage_donnee=T,
            horodatage_collecte=T,
        )
        assert cotation.cours_effectivement_traite == 1000

    def test_seance_sans_transaction_n_expose_aucun_cours_traite(self) -> None:
        """Le cours de référence reconduit est conservé, mais n'est pas un prix
        de marché : il ne doit pas alimenter un indicateur."""
        cotation = Cotation(
            ticker="TEST1",
            date_seance=date(2026, 3, 2),
            source="fixture",
            statut_seance=StatutSeance.SANS_TRANSACTION,
            cloture=1000,
            cours_precedent=1000,
            volume_titres=0,
            horodatage_donnee=T,
            horodatage_collecte=T,
        )
        assert cotation.cloture == 1000
        assert cotation.cours_effectivement_traite is None


class TestFraicheurEtEmpreinte:
    def cotation(self, **extras: object) -> Cotation:
        parametres: dict[str, object] = {
            "ticker": "TEST1",
            "date_seance": date(2026, 3, 2),
            "source": "fixture",
            "statut_seance": StatutSeance.COTEE,
            "cloture": 1000,
            "volume_titres": 100,
            "horodatage_donnee": T,
            "horodatage_collecte": T,
        }
        parametres.update(extras)
        return Cotation(**parametres)  # type: ignore[arg-type]

    def test_age_en_minutes(self) -> None:
        assert self.cotation().age_minutes(T + timedelta(hours=2)) == Decimal(120)

    def test_age_exige_une_reference_horodatee(self) -> None:
        with pytest.raises(ValueError, match="fuseau"):
            self.cotation().age_minutes(datetime(2026, 3, 2, 17, 30))

    def test_empreinte_ignore_les_metadonnees_de_collecte(self) -> None:
        """Deux collectes de la même séance inchangée doivent donner la même
        empreinte, sinon chaque passage créerait une fausse correction de cote."""
        premiere = self.cotation()
        seconde = self.cotation(horodatage_collecte=T + timedelta(hours=3))
        assert premiere.empreinte() == seconde.empreinte()

    def test_empreinte_change_si_le_cours_change(self) -> None:
        assert self.cotation().empreinte() != self.cotation(cloture=1010).empreinte()

    def test_empreinte_change_si_le_volume_change(self) -> None:
        assert self.cotation().empreinte() != self.cotation(volume_titres=101).empreinte()

    def test_fourchette_relative(self) -> None:
        cotation = self.cotation(meilleure_limite_achat=990, meilleure_limite_vente=1010)
        assert cotation.fourchette_relative == Decimal("0.02")

    def test_fourchette_absente_si_carnet_non_renseigne(self) -> None:
        assert self.cotation().fourchette_relative is None


class TestOperationSurTitre:
    def test_dividende_exige_un_montant(self) -> None:
        with pytest.raises(ValidationError):
            OperationSurTitre(
                identifiant="OST1",
                ticker="TEST1",
                type_ost=TypeOst.DIVIDENDE,
                date_ex=date(2026, 3, 2),
                source="fixture",
            )

    def test_division_exige_un_ratio(self) -> None:
        with pytest.raises(ValidationError) as capture:
            OperationSurTitre(
                identifiant="OST1",
                ticker="TEST1",
                type_ost=TypeOst.DIVISION,
                date_ex=date(2026, 3, 2),
                source="fixture",
            )
        assert "ratio" in str(capture.value)

    def test_ratio_incomplet_refuse(self) -> None:
        with pytest.raises(ValidationError):
            OperationSurTitre(
                identifiant="OST1",
                ticker="TEST1",
                type_ost=TypeOst.DIVISION,
                date_ex=date(2026, 3, 2),
                ratio_numerateur=2,
                source="fixture",
            )

    @pytest.mark.parametrize(
        ("numerateur", "denominateur", "attendu"),
        [(5, 1, "5"), (1, 10, "0.1"), (11, 10, "1.1")],
    )
    def test_facteur_titres(self, numerateur: int, denominateur: int, attendu: str) -> None:
        operation = OperationSurTitre(
            identifiant="OST1",
            ticker="TEST1",
            type_ost=TypeOst.DIVISION,
            date_ex=date(2026, 3, 2),
            ratio_numerateur=numerateur,
            ratio_denominateur=denominateur,
            source="fixture",
        )
        assert operation.facteur_titres == Decimal(attendu)

    def test_paiement_avant_detachement_refuse(self) -> None:
        with pytest.raises(ValidationError):
            OperationSurTitre(
                identifiant="OST1",
                ticker="TEST1",
                type_ost=TypeOst.DIVIDENDE,
                date_ex=date(2026, 3, 2),
                date_paiement=date(2026, 3, 1),
                montant_brut_par_action=50,
                source="fixture",
            )


class TestTransaction:
    def ligne(self, montant: int) -> LigneFrais:
        return LigneFrais(
            libelle="Commission fictive",
            base_calcul=BaseFrais.MONTANT_BRUT,
            taux=Decimal("0.01"),
            assiette=100_000,
            montant=montant,
        )

    def test_achat_ajoute_les_frais(self) -> None:
        transaction = Transaction(
            identifiant="T1",
            ticker="TEST1",
            date_operation=date(2026, 3, 2),
            sens=SensOperation.ACHAT,
            quantite=100,
            cours_unitaire=1000,
            frais=(self.ligne(1000), self.ligne(180)),
        )
        assert transaction.montant_brut == 100_000
        assert transaction.total_frais == 1180
        assert transaction.montant_net == 101_180

    def test_vente_retranche_les_frais(self) -> None:
        transaction = Transaction(
            identifiant="T2",
            ticker="TEST1",
            date_operation=date(2026, 3, 2),
            sens=SensOperation.VENTE,
            quantite=100,
            cours_unitaire=1000,
            frais=(self.ligne(1000),),
        )
        assert transaction.montant_net == 99_000

    def test_quantite_nulle_refusee(self) -> None:
        with pytest.raises(ValidationError):
            Transaction(
                identifiant="T3",
                ticker="TEST1",
                date_operation=date(2026, 3, 2),
                sens=SensOperation.ACHAT,
                quantite=0,
                cours_unitaire=1000,
            )

    def test_reglement_avant_operation_refuse(self) -> None:
        with pytest.raises(ValidationError):
            Transaction(
                identifiant="T4",
                ticker="TEST1",
                date_operation=date(2026, 3, 2),
                date_reglement=date(2026, 3, 1),
                sens=SensOperation.ACHAT,
                quantite=100,
                cours_unitaire=1000,
            )

    def test_ligne_forfaitaire_sans_taux(self) -> None:
        ligne = LigneFrais(
            libelle="Frais fixes",
            base_calcul=BaseFrais.MONTANT_FIXE,
            assiette=0,
            montant=500,
        )
        assert ligne.taux is None

    def test_ligne_forfaitaire_avec_taux_refusee(self) -> None:
        with pytest.raises(ValidationError):
            LigneFrais(
                libelle="Frais fixes",
                base_calcul=BaseFrais.MONTANT_FIXE,
                taux=Decimal("0.01"),
                assiette=0,
                montant=500,
            )

    def test_ligne_proportionnelle_sans_taux_refusee(self) -> None:
        with pytest.raises(ValidationError) as capture:
            LigneFrais(
                libelle="Commission",
                base_calcul=BaseFrais.MONTANT_BRUT,
                assiette=100_000,
                montant=1000,
            )
        assert "taux" in str(capture.value)


class TestFluxEspece:
    def test_dividende_net_de_retenue(self) -> None:
        flux = FluxEspece(
            identifiant="F1",
            date_flux=date(2026, 3, 2),
            type_flux=TypeFluxEspece.DIVIDENDE,
            ticker="TEST1",
            montant_brut=50_000,
            retenue_fiscale=5_000,
            source="fixture",
        )
        assert flux.montant_net == 45_000

    def test_dividende_sans_valeur_refuse(self) -> None:
        with pytest.raises(ValidationError) as capture:
            FluxEspece(
                identifiant="F2",
                date_flux=date(2026, 3, 2),
                type_flux=TypeFluxEspece.DIVIDENDE,
                montant_brut=50_000,
                source="fixture",
            )
        assert "ticker" in str(capture.value)

    def test_retenue_superieure_au_brut_refusee(self) -> None:
        with pytest.raises(ValidationError):
            FluxEspece(
                identifiant="F3",
                date_flux=date(2026, 3, 2),
                type_flux=TypeFluxEspece.APPORT,
                montant_brut=1_000,
                retenue_fiscale=2_000,
                source="fixture",
            )


def test_anomalie_conserve_la_donnee_fautive() -> None:
    """Une anomalie transporte la charge brute : on investigue sur la donnée
    d'origine, pas sur une version « nettoyée »."""
    anomalie = Anomalie(
        identifiant="A1",
        source="fixture",
        type_anomalie="cours_negatif",
        gravite=GraviteAnomalie.BLOQUANTE,
        message="Cours négatif publié par la source",
        ticker="TEST1",
        date_seance=date(2026, 3, 2),
        charge_utile={"cloture": "-10", "ligne_brute": "TEST1;-10;0"},
        detectee_le=T,
    )
    assert anomalie.charge_utile["cloture"] == "-10"
    assert anomalie.resolue is False
