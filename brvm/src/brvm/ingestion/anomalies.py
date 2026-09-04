"""Détection d'anomalies à l'ingestion.

Principe unique : **signaler, jamais corriger**. Chaque contrôle produit un
constat qui porte sa gravité, son message et la donnée fautive telle qu'elle a
été reçue. Rien n'est réparé, rien n'est deviné, rien n'est supprimé.

La gravité décide seule du sort de l'enregistrement :

* ``INFO`` — consigné, la donnée reste pleinement exploitable ;
* ``AVERTISSEMENT`` — la cotation est marquée ``SUSPECTE`` : elle reste lisible
  et alimente les calculs, mais l'écran qui l'affiche le signale ;
* ``BLOQUANTE`` — la cotation est mise en ``QUARANTAINE`` : elle est écrite en
  base pour investigation, mais n'alimente plus aucun calcul.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from brvm.config.modeles import ConfigSource, Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.enums import GraviteAnomalie, StatutFiabilite, StatutSeance
from brvm.domain.modeles import Cotation
from brvm.utils.erreurs import ErreurCalendrier


class TypeAnomalie(StrEnum):
    """Familles de contrôles. Le libellé sert de clé de regroupement en base."""

    LIGNE_ILLISIBLE = "ligne_illisible"
    VARIATION_HORS_SEUIL = "variation_hors_seuil"
    VOLUME_INCOHERENT = "volume_incoherent"
    DOUBLON = "doublon"
    SEANCE_HORS_CALENDRIER = "seance_hors_calendrier"
    DATE_FUTURE = "date_future"
    DONNEE_PERIMEE = "donnee_perimee"
    TICKER_INCONNU = "ticker_inconnu"
    FOURCHETTE_INVERSEE = "fourchette_inversee"
    SEANCE_MANQUANTE = "seance_manquante"


@dataclass(frozen=True, slots=True)
class Constat:
    """Résultat d'un contrôle qui a échoué."""

    type_anomalie: TypeAnomalie
    gravite: GraviteAnomalie
    message: str
    ticker: str | None = None
    date_seance: date | None = None
    charge_utile: dict[str, Any] = field(default_factory=dict)


def statut_depuis_constats(constats: Iterable[Constat]) -> StatutFiabilite:
    """Traduit un ensemble de constats en statut de fiabilité."""
    gravites = {constat.gravite for constat in constats}
    if GraviteAnomalie.BLOQUANTE in gravites:
        return StatutFiabilite.QUARANTAINE
    if GraviteAnomalie.AVERTISSEMENT in gravites:
        return StatutFiabilite.SUSPECTE
    return StatutFiabilite.FIABLE


class DetecteurAnomalies:
    """Applique les contrôles d'ingestion à une cotation ou à un lot.

    Le détecteur ne connaît ni le réseau ni la base : il prend une cotation déjà
    validée par le modèle et dit ce qui, dans son contenu, ne tient pas debout.
    """

    def __init__(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        tickers_connus: Iterable[str] | None = None,
    ) -> None:
        self.configuration = configuration
        self.calendrier = calendrier
        self.tickers_connus: frozenset[str] | None = (
            frozenset(tickers_connus) if tickers_connus is not None else None
        )

    # ---------------------------------------------------------------- unitaire

    def examiner(
        self,
        cotation: Cotation,
        source: ConfigSource,
        brut: dict[str, Any] | None = None,
        maintenant: datetime | None = None,
    ) -> list[Constat]:
        """Contrôle une cotation isolée."""
        charge = dict(brut or {})
        constats: list[Constat] = []
        constats.extend(self._controler_calendrier(cotation, charge, maintenant))
        constats.extend(self._controler_variation(cotation, charge))
        constats.extend(self._controler_volume(cotation, charge))
        constats.extend(self._controler_fourchette(cotation, charge))
        constats.extend(self._controler_fraicheur(cotation, source, charge, maintenant))
        constats.extend(self._controler_referentiel(cotation, charge))
        return constats

    def _controler_calendrier(
        self, cotation: Cotation, charge: dict[str, Any], maintenant: datetime | None
    ) -> list[Constat]:
        constats: list[Constat] = []
        aujourdhui = (maintenant or datetime.now(cotation.horodatage_collecte.tzinfo)).date()

        if self.configuration.ingestion.refuser_date_future and cotation.date_seance > aujourdhui:
            constats.append(
                Constat(
                    TypeAnomalie.DATE_FUTURE,
                    GraviteAnomalie.BLOQUANTE,
                    f"Séance datée du {cotation.date_seance.isoformat()}, postérieure à "
                    f"aujourd'hui ({aujourdhui.isoformat()}). L'analyse de la source est "
                    "probablement décalée d'une ligne ou d'un format de date.",
                    cotation.ticker,
                    cotation.date_seance,
                    charge,
                )
            )

        if not self.configuration.ingestion.refuser_seance_hors_calendrier:
            return constats
        try:
            est_seance = self.calendrier.est_jour_de_seance(cotation.date_seance)
        except ErreurCalendrier as exc:
            constats.append(
                Constat(
                    TypeAnomalie.SEANCE_HORS_CALENDRIER,
                    GraviteAnomalie.AVERTISSEMENT,
                    f"Séance non vérifiable : {exc.message} Complétez le calendrier pour "
                    "que ce contrôle redevienne effectif.",
                    cotation.ticker,
                    cotation.date_seance,
                    charge,
                )
            )
            return constats
        if not est_seance:
            constats.append(
                Constat(
                    TypeAnomalie.SEANCE_HORS_CALENDRIER,
                    GraviteAnomalie.BLOQUANTE,
                    f"Cotation datée du {cotation.date_seance.isoformat()}, que le calendrier "
                    "ne reconnaît pas comme un jour de séance.",
                    cotation.ticker,
                    cotation.date_seance,
                    charge,
                )
            )
        return constats

    def _controler_variation(self, cotation: Cotation, charge: dict[str, Any]) -> list[Constat]:
        """Compare la variation à la limite réglementaire déclarée en configuration."""
        if cotation.cloture is None or not cotation.cours_precedent:
            return []
        seuil = self.configuration.marche.seuil_variation_journaliere
        variation = Decimal(cotation.cloture - cotation.cours_precedent) / Decimal(
            cotation.cours_precedent
        )
        if abs(variation) <= seuil:
            return []
        bloquante = self.configuration.ingestion.quarantaine_si_variation_hors_seuil
        return [
            Constat(
                TypeAnomalie.VARIATION_HORS_SEUIL,
                GraviteAnomalie.BLOQUANTE if bloquante else GraviteAnomalie.AVERTISSEMENT,
                f"Variation de {variation:.2%} entre {cotation.cours_precedent} et "
                f"{cotation.cloture}, au-delà du seuil réglementaire configuré "
                f"({seuil:.2%}). Un cours ne peut normalement pas franchir cette limite "
                "en une séance : la donnée est à vérifier à la source.",
                cotation.ticker,
                cotation.date_seance,
                {**charge, "variation": str(variation), "seuil": str(seuil)},
            )
        ]

    def _controler_volume(self, cotation: Cotation, charge: dict[str, Any]) -> list[Constat]:
        """Vérifie que le montant échangé annoncé est compatible avec quantité × cours.

        Lorsque la source publie un plus haut et un plus bas, l'encadrement est
        exact : le montant échangé doit tenir entre `quantité × plus_bas` et
        `quantité × plus_haut`. Sinon on se rabat sur la clôture, avec la
        tolérance configurée — une séance peut avoir traité à plusieurs cours.
        """
        if cotation.volume_xof is None or cotation.volume_titres <= 0:
            return []
        tolerance = self.configuration.ingestion.tolerance_volume_xof
        quantite = Decimal(cotation.volume_titres)
        annonce = Decimal(cotation.volume_xof)

        if cotation.plus_bas is not None and cotation.plus_haut is not None:
            minimum = quantite * Decimal(cotation.plus_bas) * (1 - tolerance)
            maximum = quantite * Decimal(cotation.plus_haut) * (1 + tolerance)
            attendu = f"entre {minimum:.0f} et {maximum:.0f}"
        elif cotation.cloture is not None:
            theorique = quantite * Decimal(cotation.cloture)
            minimum = theorique * (1 - tolerance)
            maximum = theorique * (1 + tolerance)
            attendu = f"environ {theorique:.0f}"
        else:
            return []

        if minimum <= annonce <= maximum:
            return []
        return [
            Constat(
                TypeAnomalie.VOLUME_INCOHERENT,
                GraviteAnomalie.AVERTISSEMENT,
                f"Montant échangé annoncé ({annonce:.0f} XOF) incompatible avec "
                f"{cotation.volume_titres} titres au cours de la séance : attendu {attendu}.",
                cotation.ticker,
                cotation.date_seance,
                {**charge, "volume_xof": str(annonce), "volume_titres": cotation.volume_titres},
            )
        ]

    def _controler_fourchette(self, cotation: Cotation, charge: dict[str, Any]) -> list[Constat]:
        achat, vente = cotation.meilleure_limite_achat, cotation.meilleure_limite_vente
        if achat is None or vente is None or achat <= vente:
            return []
        return [
            Constat(
                TypeAnomalie.FOURCHETTE_INVERSEE,
                GraviteAnomalie.AVERTISSEMENT,
                f"Carnet incohérent : meilleure limite d'achat ({achat}) supérieure à la "
                f"meilleure limite de vente ({vente}). Colonnes probablement interverties "
                "à l'analyse de la source.",
                cotation.ticker,
                cotation.date_seance,
                {**charge, "achat": achat, "vente": vente},
            )
        ]

    def _controler_fraicheur(
        self,
        cotation: Cotation,
        source: ConfigSource,
        charge: dict[str, Any],
        maintenant: datetime | None,
    ) -> list[Constat]:
        instant = maintenant or datetime.now(cotation.horodatage_donnee.tzinfo)
        age = cotation.age_minutes(instant)
        if age <= source.age_max_minutes:
            return []
        return [
            Constat(
                TypeAnomalie.DONNEE_PERIMEE,
                GraviteAnomalie.AVERTISSEMENT,
                f"Donnée âgée de {age:.0f} minutes, au-delà des {source.age_max_minutes} "
                f"minutes tolérées pour la source {source.nom}.",
                cotation.ticker,
                cotation.date_seance,
                {**charge, "age_minutes": str(age)},
            )
        ]

    def _controler_referentiel(self, cotation: Cotation, charge: dict[str, Any]) -> list[Constat]:
        if self.tickers_connus is None or cotation.ticker in self.tickers_connus:
            return []
        return [
            Constat(
                TypeAnomalie.TICKER_INCONNU,
                GraviteAnomalie.AVERTISSEMENT,
                f"Valeur {cotation.ticker} absente du référentiel. La cotation est conservée, "
                "mais aucun instrument n'est créé d'office : complétez l'univers suivi.",
                cotation.ticker,
                cotation.date_seance,
                charge,
            )
        ]

    # --------------------------------------------------------------------- lot

    def examiner_lot(self, cotations: Sequence[Cotation]) -> dict[int, list[Constat]]:
        """Contrôles qui n'ont de sens que sur l'ensemble d'une collecte.

        Renvoie les constats indexés par position dans la séquence, pour que
        l'appelant les rattache à la bonne cotation.
        """
        constats: dict[int, list[Constat]] = {}
        vues: dict[tuple[str, date, str], int] = {}
        for position, cotation in enumerate(cotations):
            if cotation.cle in vues:
                constats.setdefault(position, []).append(
                    Constat(
                        TypeAnomalie.DOUBLON,
                        GraviteAnomalie.BLOQUANTE,
                        f"La séance {cotation.date_seance.isoformat()} de {cotation.ticker} "
                        f"apparaît deux fois dans la même collecte de {cotation.source} "
                        f"(première occurrence en position {vues[cotation.cle]}). Les deux "
                        "versions sont conservées pour comparaison.",
                        cotation.ticker,
                        cotation.date_seance,
                        {"position": position, "premiere_occurrence": vues[cotation.cle]},
                    )
                )
            else:
                vues[cotation.cle] = position
        return constats

    def seances_manquantes(
        self, cotations: Sequence[Cotation], debut: date, fin: date, ticker: str
    ) -> list[Constat]:
        """Séances attendues au calendrier pour lesquelles aucune donnée n'est arrivée.

        Une séance manquante n'est pas une séance sans transaction : c'est un trou
        de collecte, et il est signalé comme tel plutôt que comblé.
        """
        try:
            attendues = set(self.calendrier.seances(debut, fin))
        except ErreurCalendrier as exc:
            return [
                Constat(
                    TypeAnomalie.SEANCE_MANQUANTE,
                    GraviteAnomalie.AVERTISSEMENT,
                    f"Séances manquantes non vérifiables : {exc.message}",
                    ticker,
                    None,
                    {},
                )
            ]
        recues = {cotation.date_seance for cotation in cotations if cotation.ticker == ticker}
        return [
            Constat(
                TypeAnomalie.SEANCE_MANQUANTE,
                GraviteAnomalie.AVERTISSEMENT,
                f"Aucune donnée pour {ticker} à la séance du {jour.isoformat()}, qui figure "
                "pourtant au calendrier. Trou de collecte, à ne pas confondre avec une "
                f"séance sans transaction ({StatutSeance.SANS_TRANSACTION.value}).",
                ticker,
                jour,
                {},
            )
            for jour in sorted(attendues - recues)
        ]
