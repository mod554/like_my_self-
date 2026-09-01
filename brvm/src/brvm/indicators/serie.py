"""Série technique : passage des cotations brutes à une série calculable.

Trois décisions structurent ce module, et elles sont toutes rendues visibles
dans la sortie plutôt que dissimulées dans le calcul.

**1. Les indicateurs tournent sur la série ajustée.** Un détachement de dividende
crée une marche dans la série brute ; sans ajustement, toute moyenne mobile et
tout RSI la lisent comme un mouvement de marché.

**2. Le report de cours est borné, et compté.** Une séance sans transaction n'a
pas de cours de marché. On peut reporter le dernier cours traité sur quelques
séances — c'est ce que fait tout opérateur qui lit un graphique — mais pas
indéfiniment : au-delà de ``indicateurs.remplissage_max_seances``, le trou reste
un trou et les indicateurs refuseront de se calculer dessus. Chaque sortie
indique quelle part de sa fenêtre était reportée.

**3. Toutes les séances ne nourrissent pas tous les indicateurs.** Un cours
reporté est une information de prix acceptable (le marché n'a pas bougé faute
d'échange), mais son amplitude et son volume sont *nuls par construction*, pas
par observation. Les alimenter à l'ATR ferait tendre la volatilité vers zéro sur
une valeur qui ne cote pas — et donc placer des stops absurdement serrés. Les
indicateurs d'amplitude et de volume ne consomment donc que les séances
réellement cotées.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from brvm.config.modeles import Configuration
from brvm.domain.ajustement import PointAjuste, ajuster_serie
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import StatutFiabilite, StatutSeance
from brvm.domain.modeles import Cotation, OperationSurTitre
from brvm.utils.erreurs import ErreurCalendrier, ErreurValidation


class OrigineValeur(StrEnum):
    """D'où vient le cours porté par une barre."""

    #: Une transaction a réellement eu lieu ce jour-là.
    COTEE = "COTEE"
    #: Aucune transaction : le dernier cours traité est reporté, dans la limite
    #: autorisée par la configuration.
    REPORTEE = "REPORTEE"
    #: Aucune transaction et limite de report dépassée : le trou reste un trou.
    ABSENTE = "ABSENTE"


@dataclass(frozen=True, slots=True)
class BarreTechnique:
    """Une séance du calendrier, telle que les indicateurs la voient."""

    date_seance: date
    origine: OrigineValeur
    ouverture: Decimal | None
    haut: Decimal | None
    bas: Decimal | None
    cloture: Decimal | None
    volume: int
    volume_xof: int | None
    #: Largeur de fourchette achat/vente rapportée à son milieu, si publiée.
    fourchette_relative: Decimal | None
    #: Séances écoulées depuis le dernier cours réellement traité. 0 si cotée.
    anciennete: int

    @property
    def cotee(self) -> bool:
        return self.origine is OrigineValeur.COTEE

    @property
    def exploitable(self) -> bool:
        """Vrai si la barre porte un cours utilisable, reporté ou non."""
        return self.cloture is not None


@dataclass(frozen=True, slots=True)
class SerieTechnique:
    """Série alignée sur le calendrier de séances, prête pour les indicateurs."""

    ticker: str
    barres: tuple[BarreTechnique, ...]
    avertissements: tuple[str, ...] = ()
    #: Borne de connaissance appliquée à l'ajustement (absence de biais d'anticipation).
    jusqu_a: date | None = None

    def __len__(self) -> int:
        return len(self.barres)

    # ------------------------------------------------------------------ accès

    def dates(self) -> list[date]:
        return [barre.date_seance for barre in self.barres]

    def clotures(self) -> list[Decimal | None]:
        """Cours de clôture ajustés, report borné compris."""
        return [barre.cloture for barre in self.barres]

    def hauts(self) -> list[Decimal | None]:
        return [barre.haut for barre in self.barres]

    def bas(self) -> list[Decimal | None]:
        return [barre.bas for barre in self.barres]

    def volumes(self) -> list[int]:
        return [barre.volume for barre in self.barres]

    def barres_cotees(self) -> tuple[BarreTechnique, ...]:
        """Sous-série des seules séances où une transaction a eu lieu.

        C'est elle qui alimente les indicateurs d'amplitude et de volume.
        """
        return tuple(barre for barre in self.barres if barre.cotee)

    def index_cotees(self) -> list[int]:
        """Positions des séances cotées dans la série complète."""
        return [position for position, barre in enumerate(self.barres) if barre.cotee]

    # ------------------------------------------------------------- diagnostics

    def nb_cotees(self) -> int:
        return sum(1 for barre in self.barres if barre.cotee)

    def nb_reportees(self) -> int:
        return sum(1 for barre in self.barres if barre.origine is OrigineValeur.REPORTEE)

    def nb_absentes(self) -> int:
        return sum(1 for barre in self.barres if barre.origine is OrigineValeur.ABSENTE)

    def taux_remplissage(self) -> Decimal:
        """Part de séances dont le cours est reporté et non observé."""
        if not self.barres:
            return Decimal(0)
        return Decimal(self.nb_reportees()) / Decimal(len(self.barres))

    def volume_moyen(self, fenetre: int | None = None) -> Decimal:
        """Volume quotidien moyen sur les séances **cotées** de la fenêtre.

        Moyenner sur les séances sans transaction diviserait par un nombre de
        jours où, par construction, rien ne pouvait s'échanger.
        """
        cotees = self.barres_cotees()
        if fenetre is not None:
            cotees = cotees[-fenetre:]
        if not cotees:
            return Decimal(0)
        return Decimal(sum(barre.volume for barre in cotees)) / Decimal(len(cotees))

    def montant_moyen_xof(self, fenetre: int | None = None) -> Decimal:
        """Montant quotidien moyen échangé, sur les séances cotées qui le publient."""
        montants = [
            barre.volume_xof for barre in self.barres_cotees() if barre.volume_xof is not None
        ]
        if fenetre is not None:
            montants = montants[-fenetre:]
        if not montants:
            return Decimal(0)
        return Decimal(sum(montants)) / Decimal(len(montants))

    def fourchette_moyenne(self, fenetre: int | None = None) -> Decimal | None:
        """Largeur moyenne de fourchette, ``None`` si aucune source ne la publie."""
        largeurs = [
            barre.fourchette_relative
            for barre in self.barres_cotees()
            if barre.fourchette_relative is not None
        ]
        if fenetre is not None:
            largeurs = largeurs[-fenetre:]
        if not largeurs:
            return None
        return sum(largeurs, Decimal(0)) / Decimal(len(largeurs))


def construire_serie(
    cotations: Sequence[Cotation],
    calendrier: CalendrierSeances,
    configuration: Configuration,
    operations: Sequence[OperationSurTitre] = (),
    jusqu_a: date | None = None,
) -> SerieTechnique:
    """Assemble la série technique d'une valeur.

    Args:
        cotations: cotations brutes d'un seul ticker. Les enregistrements en
            quarantaine sont écartés : ils n'alimentent aucun calcul.
        calendrier: sert à savoir quelles séances étaient attendues, donc à
            distinguer un trou de collecte d'une séance qui n'existait pas.
        configuration: fournit la limite de report.
        operations: opérations sur titres, pour l'ajustement.
        jusqu_a: borne de connaissance. Les opérations détachées après cette date
            sont ignorées, et la série s'arrête à cette séance.

    Raises:
        ErreurValidation: série vide, ou mélangeant plusieurs valeurs.
        ErreurCalendrier: la période couverte par les cotations sort du calendrier.
    """
    retenues = [
        cotation
        for cotation in cotations
        if cotation.statut_fiabilite is not StatutFiabilite.QUARANTAINE
    ]
    if not retenues:
        raise ErreurValidation(
            "Aucune cotation exploitable : la série est vide, ou tous ses "
            "enregistrements sont en quarantaine.",
            ticker=next((cotation.ticker for cotation in cotations), "?"),
        )

    avertissements: list[str] = []
    ecartees = len(cotations) - len(retenues)
    if ecartees:
        avertissements.append(
            f"{ecartees} cotation(s) en quarantaine écartée(s) de la série : les trous "
            "correspondants sont traités comme des séances non cotées."
        )

    ajustee = ajuster_serie(retenues, operations, jusqu_a=jusqu_a)
    avertissements.extend(ajustee.avertissements)
    par_date: dict[date, PointAjuste] = {point.date_seance: point for point in ajustee.points}
    fourchettes = {cotation.date_seance: cotation.fourchette_relative for cotation in retenues}
    montants = {cotation.date_seance: cotation.volume_xof for cotation in retenues}

    debut = ajustee.points[0].date_seance
    fin = ajustee.points[-1].date_seance
    if jusqu_a is not None and jusqu_a < fin:
        fin = jusqu_a
    if debut > fin:
        raise ErreurValidation(
            "La borne de connaissance précède la première séance de la série.",
            ticker=ajustee.ticker,
            jusqu_a=fin.isoformat(),
        )

    try:
        seances = calendrier.seances(debut, fin)
    except ErreurCalendrier as exc:
        raise ErreurCalendrier(
            f"{exc.message} La série technique ne peut pas être construite sans savoir "
            "quelles séances étaient attendues.",
            **exc.contexte,
        ) from exc

    limite_report = configuration.indicateurs.remplissage_max_seances
    barres: list[BarreTechnique] = []
    derniere_cloture: Decimal | None = None
    anciennete = 0

    for jour in seances:
        point = par_date.get(jour)
        cotee = (
            point is not None
            and point.statut_seance is StatutSeance.COTEE
            and point.cloture_ajustee is not None
        )
        if cotee and point is not None:
            derniere_cloture = point.cloture_ajustee
            anciennete = 0
            barres.append(
                BarreTechnique(
                    date_seance=jour,
                    origine=OrigineValeur.COTEE,
                    ouverture=point.ouverture_ajustee,
                    haut=point.plus_haut_ajuste,
                    bas=point.plus_bas_ajuste,
                    cloture=point.cloture_ajustee,
                    volume=point.volume_ajuste,
                    volume_xof=montants.get(jour),
                    fourchette_relative=fourchettes.get(jour),
                    anciennete=0,
                )
            )
            continue

        anciennete += 1
        reportable = derniere_cloture is not None and anciennete <= limite_report
        barres.append(
            BarreTechnique(
                date_seance=jour,
                origine=OrigineValeur.REPORTEE if reportable else OrigineValeur.ABSENTE,
                # Une séance sans transaction n'a ni ouverture, ni amplitude
                # observées : les inventer égales à la clôture reportée ferait
                # croire à une volatilité nulle, ce qui est une affirmation, pas
                # une absence d'information.
                ouverture=None,
                haut=None,
                bas=None,
                cloture=derniere_cloture if reportable else None,
                volume=0,
                volume_xof=None,
                fourchette_relative=None,
                anciennete=anciennete,
            )
        )

    serie = SerieTechnique(
        ticker=ajustee.ticker,
        barres=tuple(barres),
        avertissements=tuple(avertissements),
        jusqu_a=jusqu_a,
    )

    if (
        serie.barres
        and serie.taux_remplissage() > configuration.indicateurs.taux_remplissage_alerte
    ):
        avertissements.append(
            f"{serie.taux_remplissage():.0%} des séances de la série portent un cours "
            f"reporté et non observé, au-delà du seuil d'alerte configuré "
            f"({configuration.indicateurs.taux_remplissage_alerte:.0%}). Les indicateurs "
            "calculés dessus décrivent surtout l'absence d'échanges."
        )
    return SerieTechnique(
        ticker=serie.ticker,
        barres=serie.barres,
        avertissements=tuple(avertissements),
        jusqu_a=jusqu_a,
    )
