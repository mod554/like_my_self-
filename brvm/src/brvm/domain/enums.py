"""Énumérations du domaine.

Ne contient que des faits institutionnels stables (devise de la zone UEMOA, liste
des États membres) et des catégories internes au système. Aucune donnée de marché
— tickers, secteurs réels, barèmes — n'est codée ici : elle vient de la
configuration ou de l'ingestion.
"""

from __future__ import annotations

from enum import StrEnum


class Devise(StrEnum):
    """Seule devise acceptée. Le système ne convertit jamais implicitement."""

    XOF = "XOF"


class Pays(StrEnum):
    """États membres de l'UEMOA, plus une valeur d'échappement.

    Sert à ventiler le risque pays et à rattacher les jours fériés, qui diffèrent
    d'un État à l'autre.
    """

    BENIN = "BJ"
    BURKINA_FASO = "BF"
    COTE_DIVOIRE = "CI"
    GUINEE_BISSAU = "GW"
    MALI = "ML"
    NIGER = "NE"
    SENEGAL = "SN"
    TOGO = "TG"
    AUTRE = "XX"


class StatutFiabilite(StrEnum):
    """Confiance accordée à un enregistrement de cotation."""

    #: Donnée collectée sans anomalie détectée.
    FIABLE = "FIABLE"
    #: Anomalie non bloquante (ex. écart inhabituel) : exploitable avec prudence.
    SUSPECTE = "SUSPECTE"
    #: Anomalie bloquante : la donnée est isolée et n'alimente aucun calcul.
    QUARANTAINE = "QUARANTAINE"
    #: Saisie manuelle de secours par l'utilisateur.
    MANUELLE = "MANUELLE"


class StatutSeance(StrEnum):
    """Ce qui s'est réellement passé sur la valeur pendant la séance.

    Distinction essentielle sur un marché peu liquide : une séance sans aucune
    transaction n'est pas une séance à cours inchangé.
    """

    #: Au moins une transaction a eu lieu.
    COTEE = "COTEE"
    #: Séance ouverte, valeur présente à la cote, aucune transaction.
    SANS_TRANSACTION = "SANS_TRANSACTION"
    #: Valeur suspendue par le régulateur ou l'entreprise de marché.
    SUSPENDUE = "SUSPENDUE"
    #: Séance de bourse fermée (week-end, jour férié, fermeture exceptionnelle).
    FERMEE = "FERMEE"
    #: La source ne permet pas de trancher. Ne jamais assimiler à SANS_TRANSACTION.
    INCONNU = "INCONNU"


class SensOperation(StrEnum):
    ACHAT = "ACHAT"
    VENTE = "VENTE"


class TypeOst(StrEnum):
    """Opérations sur titres affectant la continuité de la série de cours."""

    DIVIDENDE = "DIVIDENDE"
    #: Division du nominal : 1 action devient N actions.
    DIVISION = "DIVISION"
    #: Regroupement : N actions deviennent 1 action.
    REGROUPEMENT = "REGROUPEMENT"
    #: Attribution d'actions gratuites.
    ATTRIBUTION_GRATUITE = "ATTRIBUTION_GRATUITE"
    #: Augmentation de capital avec droit préférentiel de souscription.
    AUGMENTATION_CAPITAL = "AUGMENTATION_CAPITAL"
    #: Opération connue mais dont l'effet sur le cours n'est pas modélisé ici.
    AUTRE = "AUTRE"


class MethodeValorisation(StrEnum):
    """Méthode de calcul du prix de revient d'une ligne."""

    #: Prix moyen pondéré (coût unitaire moyen recalculé à chaque achat).
    PMP = "PMP"
    #: Premier entré, premier sorti (suivi lot par lot).
    FIFO = "FIFO"


class TypeFluxEspece(StrEnum):
    """Mouvements d'espèces du portefeuille, hors achat/vente de titres."""

    APPORT = "APPORT"
    RETRAIT = "RETRAIT"
    DIVIDENDE = "DIVIDENDE"
    FRAIS_GARDE = "FRAIS_GARDE"
    AUTRE = "AUTRE"


class GraviteAnomalie(StrEnum):
    """Sévérité d'une anomalie détectée à l'ingestion."""

    #: Consigné, la donnée reste exploitable.
    INFO = "INFO"
    #: La donnée est marquée SUSPECTE mais conservée.
    AVERTISSEMENT = "AVERTISSEMENT"
    #: La donnée est mise en quarantaine et n'alimente aucun calcul.
    BLOQUANTE = "BLOQUANTE"


class BaseFrais(StrEnum):
    """Assiette sur laquelle une ligne de frais est calculée."""

    #: Quantité × cours unitaire.
    MONTANT_BRUT = "MONTANT_BRUT"
    #: Somme des commissions déjà calculées (assiette d'une TVA, par exemple).
    TOTAL_COMMISSIONS = "TOTAL_COMMISSIONS"
    #: Montant forfaitaire, indépendant de la taille de l'ordre.
    MONTANT_FIXE = "MONTANT_FIXE"


class StatutCollecte(StrEnum):
    """Issue d'un cycle d'ingestion."""

    SUCCES = "SUCCES"
    #: Une partie des valeurs attendues seulement a été récupérée.
    PARTIEL = "PARTIEL"
    ECHEC = "ECHEC"
    #: La source est tombée, le système a servi le cache local.
    DEGRADE = "DEGRADE"


class Periodicite(StrEnum):
    """Fréquence de perception d'un frais récurrent."""

    MENSUELLE = "MENSUELLE"
    TRIMESTRIELLE = "TRIMESTRIELLE"
    SEMESTRIELLE = "SEMESTRIELLE"
    ANNUELLE = "ANNUELLE"

    @property
    def occurrences_par_an(self) -> int:
        return {
            Periodicite.MENSUELLE: 12,
            Periodicite.TRIMESTRIELLE: 4,
            Periodicite.SEMESTRIELLE: 2,
            Periodicite.ANNUELLE: 1,
        }[self]
