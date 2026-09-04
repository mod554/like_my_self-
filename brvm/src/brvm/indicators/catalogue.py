"""Indicateurs exposés au reste du système, avec leurs garde-fous.

Le module :mod:`brvm.indicators.calculs` sait faire de l'arithmétique. Celui-ci
sait **quand refuser de le faire**.

Deux règles s'appliquent à chaque sortie.

**Le seuil de séances cotées.** Une moyenne mobile sur vingt séances dont trois
seulement ont donné lieu à un échange décrit le report de cours, pas le marché.
En deçà de ``indicateurs.ratio_minimum_seances_cotees``, la valeur est remplacée
par un refus motivé — pas par une approximation.

**La séparation des familles.** Les indicateurs de prix consomment la série
complète, report borné compris. Les indicateurs d'amplitude et de volume ne
consomment que les séances réellement cotées, puis leur résultat est reporté sur
les séances suivantes avec son ancienneté : une séance sans transaction n'a pas
une amplitude nulle ni un volume nul, elle n'en a pas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from brvm.config.modeles import Configuration
from brvm.indicators import calculs
from brvm.indicators.confiance import ScoreConfiance, evaluer_confiance
from brvm.indicators.resultats import (
    PointIndicateur,
    ResultatBollinger,
    ResultatExtremes,
    ResultatIndicateur,
    ResultatMacd,
)
from brvm.indicators.serie import OrigineValeur, SerieTechnique

Parametres = Mapping[str, int | Decimal | str]


class Indicateurs:
    """Calcule les indicateurs d'une valeur en appliquant la politique d'illiquidité."""

    def __init__(self, serie: SerieTechnique, configuration: Configuration) -> None:
        self.serie = serie
        self.configuration = configuration
        self.reglages = configuration.indicateurs
        self.confiance: ScoreConfiance = evaluer_confiance(serie, configuration)

    # ------------------------------------------------------------ assemblage

    def _qualite(self, position: int, fenetre: int) -> tuple[int, int, Decimal]:
        """Séances cotées, taille réelle de la fenêtre et taux de report."""
        debut = max(0, position - fenetre + 1)
        barres = self.serie.barres[debut : position + 1]
        if not barres:
            return 0, 0, Decimal(0)
        cotees = sum(1 for barre in barres if barre.cotee)
        reportees = sum(1 for barre in barres if barre.origine is OrigineValeur.REPORTEE)
        return cotees, len(barres), Decimal(reportees) / Decimal(len(barres))

    def _assembler(
        self,
        nom: str,
        valeurs: Sequence[Decimal | None],
        fenetre: int,
        parametres: Parametres,
    ) -> ResultatIndicateur:
        """Applique le seuil de séances cotées à une série calculée sur les prix."""
        seuil = self.reglages.ratio_minimum_seances_cotees
        points: list[PointIndicateur] = []

        for position, barre in enumerate(self.serie.barres):
            cotees, taille, remplissage = self._qualite(position, fenetre)
            valeur = valeurs[position]
            motif: str | None = None

            if valeur is None:
                motif = (
                    "fenêtre incomplète : historique trop court, ou trou de cotation "
                    "non comblé dans la fenêtre"
                )
            elif taille and Decimal(cotees) / Decimal(taille) < seuil:
                motif = (
                    f"seulement {cotees} séance(s) réellement cotée(s) sur {taille} "
                    f"dans la fenêtre, sous le seuil configuré de {seuil:.0%}"
                )
                valeur = None

            points.append(
                PointIndicateur(
                    date_seance=barre.date_seance,
                    valeur=valeur,
                    seances_cotees=cotees,
                    seances_fenetre=taille,
                    taux_remplissage=remplissage,
                    anciennete=barre.anciennete,
                    motif_refus=motif,
                )
            )

        return ResultatIndicateur(
            nom=nom,
            ticker=self.serie.ticker,
            parametres=parametres,
            points=tuple(points),
            confiance=self.confiance,
            avertissements=self.serie.avertissements,
        )

    def _assembler_sur_cotees(
        self,
        nom: str,
        valeurs_cotees: Sequence[Decimal | None],
        fenetre: int,
        parametres: Parametres,
    ) -> ResultatIndicateur:
        """Reporte sur le calendrier un indicateur calculé sur les seules séances cotées.

        La valeur d'une séance sans transaction est celle de la dernière séance
        cotée, accompagnée du nombre de séances écoulées depuis : le lecteur voit
        immédiatement s'il regarde une mesure d'hier ou d'il y a trois semaines.
        """
        index_cotees = self.serie.index_cotees()
        valeur_courante: Decimal | None = None
        derniere_position: int | None = None
        prochaine = 0
        points: list[PointIndicateur] = []

        for position, barre in enumerate(self.serie.barres):
            if prochaine < len(index_cotees) and index_cotees[prochaine] == position:
                valeur_courante = valeurs_cotees[prochaine]
                derniere_position = position
                prochaine += 1

            anciennete = 0 if derniere_position is None else position - derniere_position
            cotees, taille, remplissage = self._qualite(position, max(fenetre, anciennete + 1))
            motif = (
                None
                if valeur_courante is not None
                else f"moins de {fenetre} séances réellement cotées disponibles"
            )
            points.append(
                PointIndicateur(
                    date_seance=barre.date_seance,
                    valeur=valeur_courante,
                    seances_cotees=cotees,
                    seances_fenetre=taille,
                    taux_remplissage=remplissage,
                    anciennete=anciennete,
                    motif_refus=motif,
                )
            )

        return ResultatIndicateur(
            nom=nom,
            ticker=self.serie.ticker,
            parametres=parametres,
            points=tuple(points),
            confiance=self.confiance,
            avertissements=self.serie.avertissements,
        )

    # ------------------------------------------------------- indicateurs de prix

    def moyenne_simple(self, fenetre: int | None = None) -> ResultatIndicateur:
        taille = fenetre or self.reglages.fenetre_mm_courte
        return self._assembler(
            f"MM{taille}",
            calculs.moyenne_mobile_simple(self.serie.clotures(), taille),
            taille,
            {"fenetre": taille, "type": "simple"},
        )

    def moyenne_exponentielle(self, fenetre: int | None = None) -> ResultatIndicateur:
        taille = fenetre or self.reglages.fenetre_mm_courte
        return self._assembler(
            f"MME{taille}",
            calculs.moyenne_mobile_exponentielle(self.serie.clotures(), taille),
            taille,
            {"fenetre": taille, "type": "exponentielle"},
        )

    def rsi(self, fenetre: int | None = None) -> ResultatIndicateur:
        taille = fenetre or self.reglages.fenetre_rsi
        return self._assembler(
            f"RSI{taille}",
            calculs.rsi(self.serie.clotures(), taille),
            taille + 1,
            {
                "fenetre": taille,
                "survente": self.reglages.rsi_survente,
                "surachat": self.reglages.rsi_surachat,
            },
        )

    def macd(self) -> ResultatMacd:
        rapide = self.reglages.macd_rapide
        lente = self.reglages.macd_lente
        signal = self.reglages.macd_signal
        ligne, ligne_signal, histogramme = calculs.macd(
            self.serie.clotures(), rapide, lente, signal
        )
        parametres: Parametres = {"rapide": rapide, "lente": lente, "signal": signal}
        return ResultatMacd(
            ligne=self._assembler("MACD", ligne, lente, parametres),
            signal=self._assembler("MACD signal", ligne_signal, lente + signal, parametres),
            histogramme=self._assembler(
                "MACD histogramme", histogramme, lente + signal, parametres
            ),
        )

    def bollinger(self, fenetre: int | None = None) -> ResultatBollinger:
        taille = fenetre or self.reglages.fenetre_bollinger
        ecarts = self.reglages.ecarts_bollinger
        basse, moyenne, haute = calculs.bandes_bollinger(self.serie.clotures(), taille, ecarts)
        parametres: Parametres = {"fenetre": taille, "ecarts": ecarts}
        return ResultatBollinger(
            basse=self._assembler("Bollinger basse", basse, taille, parametres),
            moyenne=self._assembler("Bollinger moyenne", moyenne, taille, parametres),
            haute=self._assembler("Bollinger haute", haute, taille, parametres),
        )

    def momentum(self, decalage: int | None = None) -> ResultatIndicateur:
        taille = decalage or self.reglages.fenetre_momentum
        return self._assembler(
            f"Momentum {taille}",
            calculs.momentum(self.serie.clotures(), taille),
            taille + 1,
            {"decalage": taille},
        )

    def extremes(self, fenetre: int | None = None) -> ResultatExtremes:
        taille = fenetre or self.reglages.fenetre_extremes
        plus_bas, plus_haut = calculs.extremes_glissants(self.serie.clotures(), taille)
        parametres: Parametres = {"fenetre": taille}
        return ResultatExtremes(
            plus_bas=self._assembler(f"Plus bas {taille}", plus_bas, taille, parametres),
            plus_haut=self._assembler(f"Plus haut {taille}", plus_haut, taille, parametres),
        )

    # ------------------------------------- indicateurs d'amplitude et de volume

    def atr(self, fenetre: int | None = None) -> ResultatIndicateur:
        """Amplitude moyenne vraie, calculée sur les seules séances cotées.

        Alimenter l'ATR avec des séances sans transaction ferait tendre la
        volatilité mesurée vers zéro, et donc placer des stops d'autant plus
        serrés que la valeur est illiquide — exactement l'inverse du bon sens.
        """
        taille = fenetre or self.reglages.fenetre_atr
        cotees = self.serie.barres_cotees()
        valeurs = calculs.atr(
            [barre.haut for barre in cotees],
            [barre.bas for barre in cotees],
            [barre.cloture for barre in cotees],
            taille,
        )
        return self._assembler_sur_cotees(
            f"ATR{taille}", valeurs, taille, {"fenetre": taille, "assiette": "séances cotées"}
        )

    def obv(self) -> ResultatIndicateur:
        """Volume cumulé signé, sur les seules séances cotées."""
        cotees = self.serie.barres_cotees()
        valeurs = calculs.obv(
            [barre.cloture for barre in cotees], [barre.volume for barre in cotees]
        )
        return self._assembler_sur_cotees("OBV", valeurs, 1, {"assiette": "séances cotées"})

    # ------------------------------------------------------------------ synthèse

    def tous(self) -> dict[str, ResultatIndicateur]:
        """Jeu complet, dans un dictionnaire indexé par nom d'indicateur."""
        macd = self.macd()
        bollinger = self.bollinger()
        extremes = self.extremes()
        resultats = [
            self.moyenne_simple(self.reglages.fenetre_mm_courte),
            self.moyenne_simple(self.reglages.fenetre_mm_longue),
            self.moyenne_simple(self.reglages.fenetre_mm_fond),
            self.moyenne_exponentielle(),
            self.rsi(),
            macd.ligne,
            macd.signal,
            macd.histogramme,
            bollinger.basse,
            bollinger.moyenne,
            bollinger.haute,
            self.atr(),
            self.obv(),
            self.momentum(),
            extremes.plus_bas,
            extremes.plus_haut,
        ]
        return {resultat.nom: resultat for resultat in resultats}
