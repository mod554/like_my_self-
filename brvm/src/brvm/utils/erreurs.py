"""Hiérarchie d'exceptions du système.

Principe : une erreur porte un message actionnable en français. Aucune couche ne
« corrige silencieusement » une donnée ; elle lève, journalise ou met en
quarantaine.
"""

from __future__ import annotations

from typing import Any


class ErreurBrvm(Exception):
    """Racine de toutes les erreurs du système."""

    def __init__(self, message: str, **contexte: Any) -> None:
        super().__init__(message)
        self.message = message
        self.contexte: dict[str, Any] = contexte

    def __str__(self) -> str:
        if not self.contexte:
            return self.message
        details = ", ".join(f"{cle}={valeur!r}" for cle, valeur in sorted(self.contexte.items()))
        return f"{self.message} ({details})"


class ErreurConfiguration(ErreurBrvm):
    """Configuration absente, incomplète ou incohérente.

    Levée notamment lorsqu'un barème de frais ou un taux de fiscalité n'a pas été
    renseigné : le système refuse de démarrer plutôt que d'inventer une valeur.
    """


class ErreurValidation(ErreurBrvm):
    """Une donnée ne respecte pas le schéma attendu à une frontière du système."""


class ErreurCalendrier(ErreurBrvm):
    """Le calendrier de séances ne couvre pas la période demandée."""


class ErreurSource(ErreurBrvm):
    """Une source de données est injoignable, incomplète ou illisible."""


class ErreurStockage(ErreurBrvm):
    """Erreur de persistance (schéma, contrainte, migration)."""


class ErreurDonneesInsuffisantes(ErreurBrvm):
    """Pas assez de séances réellement cotées pour produire un résultat honnête.

    Utilisée par la couche d'analyse technique : sur une valeur peu liquide, il
    vaut mieux ne rien afficher qu'afficher un indicateur calculé sur du vide.
    """
