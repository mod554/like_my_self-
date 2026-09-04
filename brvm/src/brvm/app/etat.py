"""Assemblage de l'état du système, lu une fois et servi à toutes les sorties.

Le tableau de bord, l'export tableur et les alertes doivent montrer **la même
chose au même instant**. Un écran qui recalcule pour son compte finit par
afficher un total qui ne correspond à aucun autre, et personne ne sait lequel
croire. Tout part donc d'ici.

L'objet produit porte, en un seul endroit, l'horodatage de la donnée la plus
ancienne qu'il a fallu employer. C'est ce qui permet à chaque restitution
d'afficher son bandeau de fraîcheur sans le recalculer — et de ne jamais laisser
croire qu'un chiffre est plus récent qu'il ne l'est.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import MethodeValorisation
from brvm.domain.modeles import Anomalie, Cotation, OperationSurTitre
from brvm.indicators.catalogue import Indicateurs
from brvm.indicators.serie import SerieTechnique, construire_serie
from brvm.indicators.signaux import DetecteurSignaux, Signal
from brvm.portfolio.fiscalite import MoteurFiscal
from brvm.portfolio.frais import MoteurFrais
from brvm.portfolio.historique import points_de_performance
from brvm.portfolio.performance import ResultatTwr, calculer_twr
from brvm.portfolio.positions import ResultatSuivi, suivre_les_deux
from brvm.portfolio.valorisation import Portefeuille, valoriser
from brvm.risk.controles import RapportRisque, controler
from brvm.storage.base import BaseDonnees
from brvm.storage.depots import (
    DepotAnomalies,
    DepotCotations,
    DepotFluxEspeces,
    DepotInstruments,
    DepotJournalCollectes,
    DepotOperationsSurTitres,
    DepotTransactions,
    DepotValorisations,
)
from brvm.utils.erreurs import ErreurValidation
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.etat")

#: Pourquoi aucun rendement chiffré n'apparaît dans les restitutions.
#:
#: Un TWR mesuré sur la seule valeur des titres est faux dès qu'une ligne est
#: entièrement vendue : la sous-période se termine sur un portefeuille de valeur
#: nulle, et le rendement part à -100 % alors que l'argent est simplement passé
#: en liquidités. Le mesurer correctement suppose de tenir un **compte espèces**
#: — apports, retraits, produit net des ventes, dividendes encaissés, frais de
#: garde — que le système n'enregistre pas encore.
#:
#: `brvm.portfolio.performance.calculer_twr` est écrit, testé, et attend cette
#: suite de valorisations. Tant qu'elle n'existe pas, aucune performance n'est
#: publiée : un chiffre plausible et faux serait pire que pas de chiffre.
#: Rendu quand la performance ne peut pas encore être mesurée. Le motif exact
#: vient du calcul lui-même — série trop courte, espèces inconnues — et non de
#: cette constante, qui ne sert que de repli.
MOTIF_PERFORMANCE_ABSENTE: str = (
    "Aucune performance chiffrée n'est publiée : l'historique de valorisation ne "
    "comporte pas encore assez de points. Il se remplit à chaque cycle de "
    "collecte ; deux séances suffisent pour un premier rendement."
)

#: Profondeur d'historique relue par valeur, en séances. Assez pour toutes les
#: fenêtres d'indicateur configurables, sans relire toute la base à chaque écran.
PROFONDEUR_SEANCES: int = 400


@dataclass(frozen=True, slots=True)
class EtatValeur:
    """Ce que le système sait d'une valeur à l'instant de la lecture."""

    ticker: str
    serie: SerieTechnique
    indicateurs: Indicateurs
    signaux: tuple[Signal, ...] = ()

    @property
    def confiance(self) -> Decimal:
        return self.indicateurs.confiance.valeur


@dataclass(frozen=True, slots=True)
class EtatSysteme:
    """Photographie complète, à un instant donné, avec sa fraîcheur.

    Rien ici n'est recalculé par les consommateurs : le tableau de bord et
    l'export lisent les mêmes objets.
    """

    instant: datetime
    configuration: Configuration
    portefeuille: Portefeuille
    #: Suivi par méthode : PMP et FIFO sont conservés côte à côte, parce qu'ils
    #: répondent à deux questions différentes.
    suivis: Mapping[MethodeValorisation, ResultatSuivi]
    risque: RapportRisque
    valeurs: Mapping[str, EtatValeur] = field(default_factory=dict)
    anomalies: tuple[Anomalie, ...] = ()
    journal_collectes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()
    #: Rendement pondéré par le temps, quand il est mesurable. Les apports et
    #: retraits en sont neutralisés : ils ne sont pas de la performance.
    performance: ResultatTwr | None = None
    #: Pourquoi aucune performance chiffrée n'est publiée. Voir
    #: MOTIF_PERFORMANCE_ABSENTE.
    motif_performance_absente: str = ""

    @property
    def signaux(self) -> tuple[Signal, ...]:
        """Tous les signaux constatés, valeurs confondues, du plus récent au plus ancien."""
        rassembles = [signal for etat in self.valeurs.values() for signal in etat.signaux]
        return tuple(sorted(rassembles, key=lambda s: (s.date_constat, s.ticker), reverse=True))

    @property
    def horodatage_le_plus_ancien(self) -> datetime | None:
        return self.portefeuille.horodatage_le_plus_ancien

    def age_minutes(self) -> Decimal | None:
        return self.portefeuille.age_donnee_la_plus_ancienne(self.instant)

    def entete_fraicheur(self) -> str:
        """Bandeau obligatoire de toute restitution.

        Il dit l'âge de la donnée **la plus ancienne** employée, pas d'une
        moyenne : c'est elle qui limite ce sur quoi on peut décider.
        """
        return self.portefeuille.entete_fraicheur(self.instant)

    def donnee_perimee(self) -> bool:
        age = self.age_minutes()
        return age is not None and age > self.configuration.alertes.age_donnee_max_minutes


def _derniere_cotation(cotations: Sequence[Cotation]) -> Cotation | None:
    """Cotation la plus récente réellement exploitable pour une valorisation."""
    utilisables = [cotation for cotation in cotations if cotation.cloture is not None]
    if not utilisables:
        return None
    return max(utilisables, key=lambda cotation: (cotation.date_seance, cotation.horodatage_donnee))


def assembler(
    base: BaseDonnees,
    configuration: Configuration,
    calendrier: CalendrierSeances,
    instant: datetime | None = None,
    jusqu_a: date | None = None,
) -> EtatSysteme:
    """Lit la base et compose l'état complet du système.

    Args:
        jusqu_a: borne de connaissance. Rien de postérieur n'est lu, ce qui rend
            une restitution rejouable à une date passée sans qu'aucun calcul ne
            puisse consulter une séance qui n'existait pas encore.
    """
    maintenant = instant or datetime.now(UTC)
    borne = jusqu_a or maintenant.date()

    transactions = DepotTransactions(base).lister()
    operations = DepotOperationsSurTitres(base).lister()
    flux = DepotFluxEspeces(base).lister()
    instruments = {instrument.ticker: instrument for instrument in DepotInstruments(base).lister()}

    moteur_frais = MoteurFrais(configuration)
    moteur_fiscal = MoteurFiscal(configuration)
    suivis = suivre_les_deux(
        transactions, operations, moteur_frais, configuration.general.mode_arrondi
    )
    suivi = suivis[configuration.general.methode_valorisation]

    depot_cotations = DepotCotations(base)
    tickers = sorted(suivi.lignes_ouvertes())
    avertissements: list[str] = []

    cours: dict[str, Cotation] = {}
    valeurs: dict[str, EtatValeur] = {}

    for ticker in tickers:
        cotations = [
            cotation
            for cotation in depot_cotations.lire(ticker, fin=borne)
            if cotation.date_seance <= borne
        ]
        derniere = _derniere_cotation(cotations)
        if derniere is not None:
            cours[ticker] = derniere
        etat = _etat_valeur(
            ticker, cotations, operations, configuration, calendrier, borne, avertissements
        )
        if etat is not None:
            valeurs[ticker] = etat

    portefeuille = valoriser(
        suivi,
        cours,
        moteur_frais,
        moteur_fiscal,
        flux=flux,
        reference=borne,
        transactions=transactions,
    )
    risque = controler(
        portefeuille,
        instruments,
        {ticker: etat.serie for ticker, etat in valeurs.items()},
        configuration,
        atr_par_ticker={
            ticker: etat.indicateurs.atr() for ticker, etat in valeurs.items() if etat.serie.barres
        },
    )

    # La performance se mesure sur l'historique de valorisation, pas sur la
    # photographie du jour : un rendement a besoin d'un avant et d'un après.
    valorisations = DepotValorisations(base).lire(fin=borne)
    points, motif_serie = points_de_performance(valorisations, flux)
    if motif_serie is not None:
        performance = None
        motif_performance = motif_serie
    else:
        performance = calculer_twr(points)
        motif_performance = performance.motif_indisponible or ""

    return EtatSysteme(
        instant=maintenant,
        configuration=configuration,
        portefeuille=portefeuille,
        suivis=suivis,
        risque=risque,
        valeurs=valeurs,
        anomalies=tuple(DepotAnomalies(base).lister(ouvertes_seulement=True)),
        journal_collectes=_journal_recent(base),
        avertissements=tuple(avertissements) + tuple(suivi.avertissements),
        performance=performance,
        motif_performance_absente=motif_performance,
    )


def _etat_valeur(
    ticker: str,
    cotations: Sequence[Cotation],
    operations: Sequence[OperationSurTitre],
    configuration: Configuration,
    calendrier: CalendrierSeances,
    borne: date,
    avertissements: list[str],
) -> EtatValeur | None:
    """Construit série, indicateurs et signaux d'une valeur, ou dit pourquoi non."""
    if not cotations:
        avertissements.append(
            f"{ticker} : aucune cotation en base. Ni indicateur, ni signal, ni contrôle "
            "de liquidité ne sont calculés pour cette ligne."
        )
        return None
    recentes = list(cotations)[-PROFONDEUR_SEANCES:]
    try:
        serie = construire_serie(
            recentes,
            calendrier,
            configuration,
            operations=operations,
            jusqu_a=borne,
        )
    except ErreurValidation as exc:
        avertissements.append(f"{ticker} : série inexploitable — {exc}")
        _journal.warning("Série inexploitable", extra={"ticker": ticker, "erreur": str(exc)})
        return None

    indicateurs = Indicateurs(serie, configuration)
    detecteur = DetecteurSignaux(indicateurs, configuration, calendrier)
    try:
        signaux = tuple(detecteur.tous())
    except ErreurValidation as exc:
        avertissements.append(f"{ticker} : signaux non calculés — {exc}")
        signaux = ()
    return EtatValeur(ticker=ticker, serie=serie, indicateurs=indicateurs, signaux=signaux)


def _journal_recent(base: BaseDonnees, combien: int = 20) -> tuple[str, ...]:
    """Dernières collectes, telles qu'elles sont consignées."""
    depot = DepotJournalCollectes(base)
    lignes: list[str] = []
    for ligne in base.connexion.execute(
        "SELECT source, debut, statut, nb_lignes_lues, nb_lignes_ecrites, nb_anomalies, message "
        "FROM journal_collectes ORDER BY debut DESC LIMIT ?",
        (combien,),
    ):
        lignes.append(
            f"{ligne['debut']} [{ligne['source']}] {ligne['statut']} — "
            f"{ligne['nb_lignes_lues']} lue(s), {ligne['nb_lignes_ecrites']} écrite(s), "
            f"{ligne['nb_anomalies']} anomalie(s)"
        )
    del depot
    return tuple(lignes)
