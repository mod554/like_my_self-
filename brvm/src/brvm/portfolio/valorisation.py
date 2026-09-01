"""Valorisation du portefeuille, frais et fiscalité de sortie compris.

Deux exigences gouvernent ce module.

**La plus-value latente nette n'est pas la plus-value latente brute.** Ce qui
resterait si vous vendiez aujourd'hui, c'est le produit *après* frais de cession
et après impôt. Sur une petite ligne, l'écart entre les deux dépasse souvent le
gain affiché.

**Toute valorisation dit l'âge de sa donnée la plus ancienne.** Sur un marché où
une valeur peut ne pas coter pendant une semaine, un portefeuille valorisé sans
horodatage laisse croire à une photographie du jour. Chaque ligne porte donc la
date du cours utilisé, et l'ensemble porte celle du plus ancien.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, localcontext

from brvm.domain.enums import SensOperation, TypeFluxEspece
from brvm.domain.modeles import Cotation, FluxEspece
from brvm.domain.monnaie import PRECISION_INTERNE, format_xof
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.performance import ContributionLigne, DonneesLigne, calculer_contributions
from brvm.portfolio.positions import Position, ResultatSuivi

_DECIMALES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class LigneValorisee:
    """Une ligne du portefeuille, valorisée au dernier cours connu."""

    ticker: str
    quantite: int
    cout_total: int
    prix_revient_unitaire: Decimal
    cours: int | None
    horodatage_cours: datetime | None
    date_cours: date | None
    valeur: int | None
    plus_value_latente_brute: int | None
    #: Ce qui resterait après frais de cession et impôt, si vous vendiez aujourd'hui.
    plus_value_latente_nette: int | None
    frais_cession_estimes: int | None
    impot_estime: int | None
    dividendes_nets: int
    poids: Decimal | None
    motif_indisponible: str | None = None

    @property
    def valorisee(self) -> bool:
        return self.valeur is not None

    def age_minutes(self, reference: datetime) -> Decimal | None:
        if self.horodatage_cours is None:
            return None
        secondes = (reference - self.horodatage_cours).total_seconds()
        return Decimal(str(secondes)) / Decimal(60)


@dataclass(frozen=True, slots=True)
class Portefeuille:
    """Photographie du portefeuille, avec la fraîcheur de ce sur quoi elle repose."""

    lignes: tuple[LigneValorisee, ...]
    cout_total: int
    valeur_totale: int
    plus_value_latente_brute: int
    plus_value_latente_nette: int
    dividendes_nets_encaisses: int
    plus_values_realisees: int
    #: Horodatage du cours le plus ancien utilisé. À afficher sur chaque écran.
    horodatage_le_plus_ancien: datetime | None
    contributions: tuple[ContributionLigne, ...] = ()
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    @property
    def lignes_non_valorisees(self) -> tuple[LigneValorisee, ...]:
        return tuple(ligne for ligne in self.lignes if not ligne.valorisee)

    def age_donnee_la_plus_ancienne(self, reference: datetime) -> Decimal | None:
        if self.horodatage_le_plus_ancien is None:
            return None
        secondes = (reference - self.horodatage_le_plus_ancien).total_seconds()
        return Decimal(str(secondes)) / Decimal(60)

    def entete_fraicheur(self, reference: datetime) -> str:
        """Bandeau de fraîcheur, à afficher en tête de toute restitution."""
        if self.horodatage_le_plus_ancien is None:
            return "Aucun cours disponible : le portefeuille n'est pas valorisé."
        age = self.age_donnee_la_plus_ancienne(reference)
        return (
            f"Donnée la plus ancienne utilisée : "
            f"{self.horodatage_le_plus_ancien.isoformat()} "
            f"({age:.0f} minutes)"
            if age is not None
            else f"Donnée la plus ancienne : {self.horodatage_le_plus_ancien.isoformat()}"
        )

    def resume(self, reference: datetime) -> str:
        lignes = [
            self.entete_fraicheur(reference),
            f"Coût engagé{'':.<40}{format_xof(self.cout_total):>20}",
            f"Valeur actuelle{'':.<36}{format_xof(self.valeur_totale):>20}",
            f"Plus-value latente brute{'':.<27}{format_xof(self.plus_value_latente_brute):>20}",
            f"Plus-value latente nette de frais et d'impôt{'':.<7}"
            f"{format_xof(self.plus_value_latente_nette):>20}",
            f"Dividendes nets encaissés{'':.<26}{format_xof(self.dividendes_nets_encaisses):>20}",
        ]
        if self.lignes_non_valorisees:
            manquants = ", ".join(ligne.ticker for ligne in self.lignes_non_valorisees)
            lignes.append(f"Lignes non valorisées faute de cours : {manquants}")
        return "\n".join(lignes)


def dividendes_par_ticker(flux: Sequence[FluxEspece]) -> dict[str, int]:
    """Somme des dividendes **nets** encaissés, par valeur."""
    totaux: dict[str, int] = {}
    for mouvement in flux:
        if mouvement.type_flux is TypeFluxEspece.DIVIDENDE and mouvement.ticker:
            totaux[mouvement.ticker] = totaux.get(mouvement.ticker, 0) + mouvement.montant_net
    return totaux


def valoriser(
    suivi: ResultatSuivi,
    cours: Mapping[str, Cotation],
    moteur_frais: MoteurFrais,
    moteur_fiscal: MoteurFiscal,
    flux: Sequence[FluxEspece] = (),
    reference: date | None = None,
) -> Portefeuille:
    """Valorise les lignes ouvertes au dernier cours connu.

    Args:
        suivi: positions issues du rejeu des transactions.
        cours: dernière cotation retenue par valeur. Une valeur absente n'est pas
            valorisée — elle n'est pas comptée à zéro.
        moteur_frais: pour estimer les frais d'une cession immédiate.
        moteur_fiscal: pour estimer l'impôt d'une cession immédiate.
        flux: mouvements d'espèces, pour les dividendes encaissés.
        reference: date servant au calcul des durées de détention.
    """
    dividendes = dividendes_par_ticker(flux)
    aujourdhui = reference or date.today()
    lignes: list[LigneValorisee] = []
    avertissements: list[str] = []
    horodatages: list[datetime] = []

    ouvertes = suivi.lignes_ouvertes()
    valeur_totale = 0

    with localcontext() as contexte:
        contexte.prec = PRECISION_INTERNE

        for ticker, position in sorted(ouvertes.items()):
            cotation = cours.get(ticker)
            dividende_net = dividendes.get(ticker, 0)

            if cotation is None or cotation.cloture is None:
                avertissements.append(
                    f"{ticker} : aucun cours disponible, la ligne n'est pas valorisée. "
                    "Elle n'est pas comptée pour zéro : le total du portefeuille est "
                    "incomplet."
                )
                lignes.append(
                    _ligne_non_valorisee(position, dividende_net, "aucun cours disponible")
                )
                continue

            horodatages.append(cotation.horodatage_donnee)
            valeur = position.quantite * cotation.cloture
            valeur_totale += valeur

            decompte = moteur_frais.calculer(
                SensOperation.VENTE, position.quantite, cotation.cloture
            )
            plus_value_brute = valeur - position.cout_total
            plus_value_apres_frais = decompte.montant_net - position.cout_total
            fiscal = moteur_fiscal.plus_value(
                plus_value_apres_frais, position.duree_detention_mois(aujourdhui)
            )

            lignes.append(
                LigneValorisee(
                    ticker=ticker,
                    quantite=position.quantite,
                    cout_total=position.cout_total,
                    prix_revient_unitaire=position.prix_revient_unitaire,
                    cours=cotation.cloture,
                    horodatage_cours=cotation.horodatage_donnee,
                    date_cours=cotation.date_seance,
                    valeur=valeur,
                    plus_value_latente_brute=plus_value_brute,
                    plus_value_latente_nette=fiscal.plus_value_nette,
                    frais_cession_estimes=decompte.total,
                    impot_estime=fiscal.impot,
                    dividendes_nets=dividende_net,
                    poids=None,
                )
            )

        lignes = [_avec_poids(ligne, valeur_totale) for ligne in lignes]

    cout_total = sum(ligne.cout_total for ligne in lignes)
    contributions = (
        calculer_contributions(
            [
                DonneesLigne(
                    ticker=ligne.ticker,
                    cout_engage=ligne.cout_total,
                    valeur_actuelle=ligne.valeur or ligne.cout_total,
                    dividendes_nets=ligne.dividendes_nets,
                )
                for ligne in lignes
            ]
        )
        if cout_total > 0
        else ()
    )

    return Portefeuille(
        lignes=tuple(lignes),
        cout_total=cout_total,
        valeur_totale=valeur_totale,
        plus_value_latente_brute=sum(ligne.plus_value_latente_brute or 0 for ligne in lignes),
        plus_value_latente_nette=sum(ligne.plus_value_latente_nette or 0 for ligne in lignes),
        dividendes_nets_encaisses=sum(dividendes.values()),
        plus_values_realisees=suivi.plus_values_realisees(),
        horodatage_le_plus_ancien=min(horodatages) if horodatages else None,
        contributions=contributions,
        avertissements=tuple(avertissements),
    )


def _ligne_non_valorisee(position: Position, dividende_net: int, motif: str) -> LigneValorisee:
    return LigneValorisee(
        ticker=position.ticker,
        quantite=position.quantite,
        cout_total=position.cout_total,
        prix_revient_unitaire=position.prix_revient_unitaire,
        cours=None,
        horodatage_cours=None,
        date_cours=None,
        valeur=None,
        plus_value_latente_brute=None,
        plus_value_latente_nette=None,
        frais_cession_estimes=None,
        impot_estime=None,
        dividendes_nets=dividende_net,
        poids=None,
        motif_indisponible=motif,
    )


def _avec_poids(ligne: LigneValorisee, valeur_totale: int) -> LigneValorisee:
    if ligne.valeur is None or valeur_totale <= 0:
        return ligne
    poids = (Decimal(ligne.valeur) / Decimal(valeur_totale)).quantize(_DECIMALES)
    return LigneValorisee(
        ticker=ligne.ticker,
        quantite=ligne.quantite,
        cout_total=ligne.cout_total,
        prix_revient_unitaire=ligne.prix_revient_unitaire,
        cours=ligne.cours,
        horodatage_cours=ligne.horodatage_cours,
        date_cours=ligne.date_cours,
        valeur=ligne.valeur,
        plus_value_latente_brute=ligne.plus_value_latente_brute,
        plus_value_latente_nette=ligne.plus_value_latente_nette,
        frais_cession_estimes=ligne.frais_cession_estimes,
        impot_estime=ligne.impot_estime,
        dividendes_nets=ligne.dividendes_nets,
        poids=poids,
        motif_indisponible=ligne.motif_indisponible,
    )
