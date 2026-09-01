"""Un cycle d'exploitation complet : collecter, constater, alerter.

C'est ce que l'ordonnanceur déclenche, et ce que la ligne de commande exécute à
la main. Le cycle enchaîne toujours les mêmes étapes, dans le même ordre :

1. **collecter** — chaque source active, indépendamment des autres ;
2. **assembler** — relire la base et composer l'état du système ;
3. **constater** — en tirer les alertes prévues par la configuration ;
4. **diffuser** — sur les canaux déclarés, sans jamais interrompre le cycle.

Aucune de ces étapes ne peut faire échouer les suivantes : une source qui tombe,
un canal injoignable, une valeur sans cours produisent un constat, pas une pile
d'appels. C'est ce qui permet de le laisser tourner sans surveillance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from brvm.app.alertes import Alerte, Diffuseur, ResultatDiffusion
from brvm.app.etat import EtatSysteme, assembler
from brvm.app.surveillance import rassembler
from brvm.config.modeles import Configuration
from brvm.domain.calendrier import CalendrierSeances
from brvm.indicators.signaux import Signal
from brvm.ingestion.orchestrateur import BilanIngestion, Orchestrateur
from brvm.storage.base import BaseDonnees
from brvm.utils.journalisation import obtenir_journal

_journal = obtenir_journal("app.cycle")


@dataclass(frozen=True, slots=True)
class ResultatCycle:
    """Ce qu'a produit un cycle, de bout en bout."""

    instant: datetime
    seance: date | None
    bilans: tuple[BilanIngestion, ...] = ()
    etat: EtatSysteme | None = None
    alertes: tuple[Alerte, ...] = ()
    diffusion: ResultatDiffusion | None = None
    avertissements: tuple[str, ...] = field(default_factory=tuple)

    def resume(self) -> str:
        lignes = [f"Cycle du {self.instant.isoformat()}"]
        if self.seance:
            lignes.append(f"Séance visée : {self.seance.isoformat()}")
        lignes += [f"  {bilan.resume()}" for bilan in self.bilans]
        if self.etat is not None:
            lignes.append(f"  {self.etat.entete_fraicheur()}")
        lignes.append(f"  {len(self.alertes)} constat(s)")
        if self.diffusion is not None and self.diffusion.canaux_en_echec:
            lignes.append("  Canaux en échec : " + ", ".join(self.diffusion.canaux_en_echec))
        lignes += [f"  ⚠ {message}" for message in self.avertissements]
        return "\n".join(lignes)


class Cycle:
    """Enchaîne collecte, état et alertes, sans jamais s'interrompre en route."""

    def __init__(
        self,
        configuration: Configuration,
        base: BaseDonnees,
        calendrier: CalendrierSeances,
        diffuseur: Diffuseur,
        orchestrateur: Orchestrateur | None = None,
    ) -> None:
        self.configuration = configuration
        self.base = base
        self.calendrier = calendrier
        self.diffuseur = diffuseur
        self.orchestrateur = orchestrateur or Orchestrateur(configuration, base, calendrier)

    def executer(
        self,
        seance: date | None = None,
        instant: datetime | None = None,
        collecter: bool = True,
    ) -> ResultatCycle:
        """Exécute un cycle complet.

        Args:
            seance: séance visée. ``None`` demande la dernière disponible.
            instant: horloge de référence, injectable pour rejouer un cycle passé.
            collecter: à ``False``, l'état est recomposé et les alertes réémises
                sans toucher au réseau — utile pour produire un export sans
                solliciter les sources.
        """
        maintenant = instant or datetime.now(UTC)
        avertissements: list[str] = []
        bilans: tuple[BilanIngestion, ...] = ()

        if collecter:
            try:
                bilans = tuple(self.orchestrateur.executer(seance, maintenant))
            except Exception as exc:  # l'ingestion ne doit jamais emporter le cycle
                _journal.exception("Collecte interrompue")
                avertissements.append(
                    f"Collecte interrompue : {exc}. L'état est composé sur les "
                    "données déjà en base, qui sont donc plus anciennes que prévu."
                )

        try:
            etat: EtatSysteme | None = assembler(
                self.base, self.configuration, self.calendrier, instant=maintenant, jusqu_a=seance
            )
        except Exception as exc:
            _journal.exception("État non composable")
            avertissements.append(f"État du portefeuille non composable : {exc}")
            etat = None

        alertes = self._constater(bilans, etat, maintenant)
        diffusion = self.diffuseur.diffuser(self.diffuseur.retenir(alertes))
        self.diffuseur.oublier_absents(alertes)
        if diffusion.avertissements:
            avertissements.extend(diffusion.avertissements)

        resultat = ResultatCycle(
            instant=maintenant,
            seance=seance,
            bilans=bilans,
            etat=etat,
            alertes=tuple(alertes),
            diffusion=diffusion,
            avertissements=tuple(avertissements),
        )
        _journal.info(
            "Cycle terminé",
            extra={
                "sources": len(bilans),
                "alertes": len(alertes),
                "diffusees": len(diffusion.alertes),
            },
        )
        return resultat

    def _constater(
        self,
        bilans: tuple[BilanIngestion, ...],
        etat: EtatSysteme | None,
        maintenant: datetime,
    ) -> list[Alerte]:
        return rassembler(
            self.configuration,
            maintenant,
            bilans=bilans,
            anomalies=etat.anomalies if etat else (),
            portefeuille=etat.portefeuille if etat else None,
            rapport=etat.risque if etat else None,
            signaux=self._signaux_recents(etat),
        )

    def _signaux_recents(self, etat: EtatSysteme | None) -> tuple[Signal, ...]:
        """Signaux constatés sur la dernière séance connue, pas tout l'historique.

        Réémettre chaque jour tous les signaux jamais constatés noierait celui
        d'aujourd'hui. Le diffuseur écarte déjà les doublons ; ce filtre évite en
        plus de les fabriquer.
        """
        if etat is None:
            return ()
        signaux = etat.signaux
        if not signaux:
            return ()
        derniere = max(signal.date_constat for signal in signaux)
        return tuple(signal for signal in signaux if signal.date_constat == derniere)
