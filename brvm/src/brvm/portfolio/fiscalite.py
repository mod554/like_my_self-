"""Fiscalité : retenue sur dividendes et traitement des plus-values.

Aucun taux n'est écrit ici. Le module applique ce que la configuration déclare
pour votre pays de résidence fiscale, et rend le détail du calcul.

Il ne remplace pas un conseil fiscal et ne produit pas de déclaration. Il calcule
ce que vous encaissez réellement, ce qui suffit à ne pas surestimer un rendement :
un dividende de 7 % brut avec une retenue de 15 % rapporte 5,95 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from brvm.config.modeles import ConfigFiscalite, Configuration
from brvm.domain.monnaie import ModeArrondi, applique_taux, arrondi_xof
from brvm.utils.erreurs import ErreurValidation


@dataclass(frozen=True, slots=True)
class DecompteDividende:
    """Ce qui est encaissé sur un dividende, et ce qui a été prélevé avant."""

    quantite: int
    dividende_par_action: int
    montant_brut: int
    taux_retenue: Decimal
    retenue: int
    montant_net: int
    source_reference: str

    @property
    def rendement_net_sur(self) -> Decimal:
        """Fraction du brut effectivement encaissée."""
        if self.montant_brut == 0:
            return Decimal(0)
        return Decimal(self.montant_net) / Decimal(self.montant_brut)

    def detail(self) -> str:
        return (
            f"{self.quantite} × {self.dividende_par_action} XOF = "
            f"{self.montant_brut} XOF bruts\n"
            f"  retenue à la source ({self.taux_retenue:.2%}) : -{self.retenue} XOF\n"
            f"  net encaissé : {self.montant_net} XOF\n"
            f"  référence des taux : {self.source_reference}"
        )


@dataclass(frozen=True, slots=True)
class DecomptePlusValue:
    """Traitement fiscal d'une cession."""

    plus_value_brute: int
    duree_detention_mois: int | None
    imposable: bool
    taux: Decimal | None
    impot: int
    plus_value_nette: int
    motif: str

    def detail(self) -> str:
        return (
            f"plus-value brute : {self.plus_value_brute} XOF\n"
            f"  {self.motif}\n"
            f"  impôt : {self.impot} XOF\n"
            f"  plus-value nette : {self.plus_value_nette} XOF"
        )


class MoteurFiscal:
    """Applique le régime fiscal configuré."""

    def __init__(self, configuration: Configuration) -> None:
        self.configuration = configuration
        self.reglages: ConfigFiscalite = configuration.fiscalite
        self.mode_arrondi: ModeArrondi = configuration.general.mode_arrondi

    # ------------------------------------------------------------- dividendes

    def dividende(self, quantite: int, dividende_par_action: int) -> DecompteDividende:
        """Calcule le net encaissé sur un dividende.

        Raises:
            ErreurValidation: quantité ou dividende négatifs.
        """
        if quantite <= 0:
            raise ErreurValidation(
                "La quantité détenue doit être strictement positive.", quantite=quantite
            )
        if dividende_par_action < 0:
            raise ErreurValidation(
                "Un dividende par action ne peut pas être négatif.",
                dividende=dividende_par_action,
            )
        brut = quantite * dividende_par_action
        retenue = arrondi_xof(
            applique_taux(brut, self.reglages.retenue_dividendes), self.mode_arrondi
        )
        return DecompteDividende(
            quantite=quantite,
            dividende_par_action=dividende_par_action,
            montant_brut=brut,
            taux_retenue=self.reglages.retenue_dividendes,
            retenue=retenue,
            montant_net=brut - retenue,
            source_reference=self.reglages.source_reference,
        )

    def rendement_net(self, dividende_par_action: int, cours: int) -> Decimal:
        """Rendement d'une valeur **après** retenue à la source.

        C'est le seul rendement qui compte pour l'investisseur : un rendement
        brut affiché ne tient pas compte de ce qui est prélevé avant versement.
        """
        if cours <= 0:
            raise ErreurValidation("Le cours doit être strictement positif.", cours=cours)
        net = self.dividende(1, dividende_par_action).montant_net
        return Decimal(net) / Decimal(cours)

    # ------------------------------------------------------------ plus-values

    def plus_value(
        self, plus_value_brute: int, duree_detention_mois: int | None = None
    ) -> DecomptePlusValue:
        """Calcule l'impôt sur une plus-value de cession.

        Une moins-value ne génère jamais d'impôt ici : son éventuelle imputation
        sur d'autres gains relève de la déclaration, pas du calcul d'un
        portefeuille.
        """
        if not self.reglages.plus_values_imposables:
            return DecomptePlusValue(
                plus_value_brute=plus_value_brute,
                duree_detention_mois=duree_detention_mois,
                imposable=False,
                taux=None,
                impot=0,
                plus_value_nette=plus_value_brute,
                motif=(
                    "régime déclaré non imposable pour "
                    f"{self.reglages.pays_residence.value} — {self.reglages.source_reference}"
                ),
            )

        if plus_value_brute <= 0:
            return DecomptePlusValue(
                plus_value_brute=plus_value_brute,
                duree_detention_mois=duree_detention_mois,
                imposable=False,
                taux=self.reglages.plus_values_taux,
                impot=0,
                plus_value_nette=plus_value_brute,
                motif="moins-value : aucun impôt dû sur cette cession",
            )

        exoneration = self.reglages.plus_values_exoneration_mois
        if (
            exoneration is not None
            and duree_detention_mois is not None
            and duree_detention_mois >= exoneration
        ):
            return DecomptePlusValue(
                plus_value_brute=plus_value_brute,
                duree_detention_mois=duree_detention_mois,
                imposable=False,
                taux=self.reglages.plus_values_taux,
                impot=0,
                plus_value_nette=plus_value_brute,
                motif=(
                    f"détention de {duree_detention_mois} mois, au-delà des "
                    f"{exoneration} mois d'exonération configurés"
                ),
            )

        taux = self.reglages.plus_values_taux or Decimal(0)
        impot = arrondi_xof(applique_taux(plus_value_brute, taux), self.mode_arrondi)
        motif = f"imposable au taux configuré de {taux:.2%}"
        if exoneration is not None and duree_detention_mois is None:
            motif += (
                " — durée de détention inconnue, l'exonération éventuelle n'a pas pu être appliquée"
            )
        return DecomptePlusValue(
            plus_value_brute=plus_value_brute,
            duree_detention_mois=duree_detention_mois,
            imposable=True,
            taux=taux,
            impot=impot,
            plus_value_nette=plus_value_brute - impot,
            motif=motif,
        )
