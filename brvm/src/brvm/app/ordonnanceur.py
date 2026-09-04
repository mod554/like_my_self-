"""Quand collecter : politique de déclenchement, séparée de son exécution.

La règle est exprimée ici en fonctions pures, testables sans attendre une heure
réelle. Un moteur de planification (APScheduler ou une simple boucle) ne fait que
l'appliquer.

Deux conditions doivent être réunies pour qu'un cycle parte :

1. **l'expression cron correspond à l'instant** — minute, heure, jour du mois,
   mois, jour de la semaine ;
2. **le calendrier reconnaît une séance ce jour-là.** C'est la condition qui
   distingue ce système d'un cron ordinaire : un jour férié béninois ferme la
   bourse pour tout le monde, et lancer une collecte ce jour-là ne rapporterait
   qu'une page de la veille, prise pour celle du jour.

L'analyseur cron est volontairement minimal et local : il couvre `*`, les
valeurs, les listes, les plages et les pas. Il ne dépend d'aucune bibliothèque,
de sorte que la politique reste vérifiable même sans le moteur installé.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from brvm.config.modeles import ConfigOrdonnanceur, Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.domain.planification import Cron
from brvm.utils.erreurs import ErreurCalendrier, ErreurConfiguration
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.ordonnanceur")

#: Horizon maximal exploré pour trouver la prochaine occurrence, en minutes.
#: Deux ans : au-delà, c'est l'expression qui est fautive, pas le calendrier.
HORIZON_MINUTES: Final[int] = 366 * 2 * 24 * 60


@dataclass(frozen=True, slots=True)
class Declenchement:
    """Verdict porté sur un instant, avec son motif — toujours explicable."""

    instant: datetime
    #: Séance visée par la collecte, si elle a lieu.
    seance: date | None
    declenche: bool
    motif: str


class PolitiqueOrdonnancement:
    """Décide si un instant donné appelle une collecte, et pourquoi."""

    def __init__(self, ordonnanceur: ConfigOrdonnanceur, calendrier: CalendrierSeances) -> None:
        self.ordonnanceur = ordonnanceur
        self.calendrier = calendrier
        self.cron = Cron.analyser(ordonnanceur.cron_collecte)
        self.fuseau = self._fuseau(ordonnanceur.fuseau_horaire)

    @staticmethod
    def _fuseau(nom: str) -> ZoneInfo:
        try:
            return ZoneInfo(nom)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ErreurConfiguration(
                f"Fuseau horaire inconnu pour l'ordonnanceur : {nom!r}.", fuseau=nom
            ) from exc

    def evaluer(self, instant: datetime) -> Declenchement:
        """Dit si une collecte part à cet instant, et sinon pourquoi non.

        L'instant est ramené au fuseau déclaré : une machine réglée en UTC et un
        cron pensé en heure locale d'Abidjan ne collecteraient pas le même jour.
        """
        local = (
            instant.astimezone(self.fuseau)
            if instant.tzinfo
            else instant.replace(tzinfo=self.fuseau)
        )
        jour = local.date()

        if not self.ordonnanceur.actif:
            return Declenchement(local, None, False, "Ordonnanceur désactivé en configuration.")
        if not self.cron.correspond(local):
            return Declenchement(
                local, None, False, f"Hors des heures déclarées ({self.cron.expression})."
            )
        try:
            seance = self.calendrier.est_jour_de_seance(jour)
        except ErreurCalendrier as exc:
            # Hors période couverte : on s'abstient plutôt que de supposer une
            # séance. Un calendrier supposé est un cours daté du mauvais jour.
            return Declenchement(local, None, False, f"Calendrier indéterminé : {exc}")
        if not seance:
            return Declenchement(
                local, None, False, f"{jour.isoformat()} n'est pas un jour de séance."
            )
        return Declenchement(local, jour, True, f"Séance du {jour.isoformat()}.")

    def prochaine(
        self, depuis: datetime, horizon_minutes: int = HORIZON_MINUTES
    ) -> datetime | None:
        """Prochain instant déclenchant, ``None`` si aucun dans l'horizon.

        Recherche minute par minute : sur un cron d'une occurrence par jour de
        séance, c'est assez rapide et surtout exact — un calcul plus malin
        risquerait de rater une fermeture exceptionnelle.
        """
        local = (
            depuis.astimezone(self.fuseau) if depuis.tzinfo else depuis.replace(tzinfo=self.fuseau)
        )
        instant = local.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(horizon_minutes):
            if self.evaluer(instant).declenche:
                return instant
            instant += timedelta(minutes=1)
        return None


class Ordonnanceur:
    """Applique la politique : à chaque réveil, collecte si c'est le moment.

    L'action exécutée est injectée, ce qui permet de vérifier l'ordonnancement
    sans lancer une vraie collecte, et de réutiliser le même ordonnanceur pour
    autre chose qu'une ingestion.
    """

    def __init__(
        self,
        configuration: Configuration,
        calendrier: CalendrierSeances,
        action: Callable[[date], Any],
    ) -> None:
        self.configuration = configuration
        self.politique = PolitiqueOrdonnancement(configuration.ordonnanceur, calendrier)
        self.action = action

    def executer_si_du(self, instant: datetime) -> Declenchement:
        """Évalue l'instant et, s'il déclenche, exécute l'action pour la séance."""
        verdict = self.politique.evaluer(instant)
        if not verdict.declenche or verdict.seance is None:
            _journal.debug("Pas de collecte", extra={"motif": verdict.motif})
            return verdict
        _journal.info(
            "Déclenchement de la collecte",
            extra={"seance": verdict.seance.isoformat(), "motif": verdict.motif},
        )
        self.action(verdict.seance)
        return verdict

    def planifier(self, planificateur: Any) -> Any:
        """Enregistre la collecte sur un planificateur APScheduler fourni.

        APScheduler n'est pas une dépendance obligatoire : le paquet
        ``apscheduler`` est importé ici, et son absence donne un message qui dit
        quoi installer plutôt qu'une pile d'appels. La porte du calendrier reste
        appliquée à l'exécution — un cron ne sait pas ce qu'est un jour férié
        béninois.
        """
        try:
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as exc:  # pragma: no cover - dépend de l'installation
            raise ErreurConfiguration(
                "APScheduler n'est pas installé. Installez l'extra dédié "
                "(`pip install -e '.[ordonnanceur]'`), ou utilisez `boucle()` qui "
                "n'exige aucune dépendance.",
            ) from exc

        champs = self.politique.cron.expression.split()
        return planificateur.add_job(
            self._reveil,
            CronTrigger(
                minute=champs[0],
                hour=champs[1],
                day=champs[2],
                month=champs[3],
                # APScheduler compte 0 = lundi comme nous : la convention est la
                # même, elle est vérifiée par un test plutôt que supposée.
                day_of_week=champs[4],
                timezone=self.politique.fuseau,
            ),
            id="collecte_brvm",
            replace_existing=True,
        )

    def _reveil(self) -> None:
        self.executer_si_du(datetime.now(self.politique.fuseau))

    def boucle(
        self,
        depuis: datetime,
        occurrences: int = 1,
        dormir: Callable[[float], None] | None = None,
    ) -> list[Declenchement]:
        """Exécute les prochaines occurrences, sans dépendance extérieure.

        Le sommeil est injectable : les tests parcourent un an de calendrier sans
        attendre une seconde.
        """
        import time as _time

        attendre = dormir if dormir is not None else _time.sleep
        resultats: list[Declenchement] = []
        courant = depuis
        for _ in range(occurrences):
            prochaine = self.politique.prochaine(courant)
            if prochaine is None:
                _journal.warning(
                    "Aucune séance à venir dans l'horizon exploré",
                    extra={"depuis": courant.isoformat()},
                )
                break
            reste = (prochaine - datetime.now(self.politique.fuseau)).total_seconds()
            if reste > 0:
                attendre(reste)
            resultats.append(self.executer_si_du(prochaine))
            courant = prochaine
        return resultats


def seances_a_venir(
    politique: PolitiqueOrdonnancement, depuis: datetime, combien: int = 5
) -> list[datetime]:
    """Prochaines collectes prévues — pour l'afficher, pas pour l'exécuter."""
    prevues: list[datetime] = []
    courant = depuis
    for _ in range(combien):
        prochaine = politique.prochaine(courant)
        if prochaine is None:
            break
        prevues.append(prochaine)
        courant = prochaine
    return prevues
