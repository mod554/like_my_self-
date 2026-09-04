"""Moteur de frais : application du barème de la SGI, ligne à ligne.

Ce module ne connaît aucun taux. Il applique celui que la configuration lui
donne, dans l'ordre qu'elle lui donne, et rend le décompte détaillé — le même
que celui qui figure sur un avis d'opéré.

Trois règles de calcul, toutes vérifiables sur un avis réel :

**Chaque ligne est arrondie, puis les lignes sont sommées.** Arrondir la somme
donnerait un total différent de celui facturé. Le choix est figé par un test.

**Une ligne assise sur le total des commissions ne taxe pas une autre taxe.**
L'assiette d'une telle ligne est la somme de toutes les lignes qui la précèdent
dans l'ordre du barème — commissions proportionnelles *et* forfaits, qui sont
également des prestations facturées — **à l'exclusion** de toute ligne
elle-même assise sur ce total. Sans cette exclusion, deux lignes de TVA se
taxeraient l'une l'autre et l'ordre du barème changerait le montant facturé.

Corollaire pratique : pour qu'un forfait échappe à la TVA, donnez-lui un ordre
**supérieur** à celle-ci. L'ordre déclaré dans la configuration décide de tout.

**Le minimum de perception s'applique à la ligne, puis au total.** Un minimum de
ligne relève cette ligne ; un minimum global ajoute une ligne de complément
nommée, pour que le décompte reste lisible et que la somme des lignes fasse
toujours le total.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from brvm.config.modeles import ConfigFrais, ConfigLigneFrais, Configuration
from brvm.domain.enums import BaseFrais, Periodicite, SensOperation
from brvm.domain.modeles import LigneFrais
from brvm.domain.monnaie import ModeArrondi, applique_taux, arrondi_xof, borne, format_xof
from brvm.utils.erreurs import ErreurValidation

#: Libellé de la ligne ajoutée quand le total n'atteint pas le minimum global.
LIBELLE_COMPLEMENT: str = "Complément minimum de perception"


@dataclass(frozen=True, slots=True)
class DecompteFrais:
    """Décompte complet d'une opération, tel qu'il devrait figurer sur l'avis d'opéré."""

    sens: SensOperation
    quantite: int
    cours_unitaire: int
    montant_brut: int
    lignes: tuple[LigneFrais, ...]
    total: int

    @property
    def montant_net(self) -> int:
        """Décaissement pour un achat, encaissement pour une vente."""
        if self.sens is SensOperation.ACHAT:
            return self.montant_brut + self.total
        return self.montant_brut - self.total

    @property
    def montant_net_unitaire(self) -> Decimal:
        """Montant net rapporté au titre.

        À l'achat, c'est le coût réel d'un titre, frais compris — toujours
        supérieur au cours affiché. À la vente, c'est le produit net encaissé par
        titre, toujours inférieur au cours affiché.
        """
        return Decimal(self.montant_net) / Decimal(self.quantite)

    @property
    def prix_revient_unitaire(self) -> Decimal:
        """Coût réel d'un titre acheté, frais compris.

        Raises:
            ErreurValidation: sur une vente, où la notion n'a pas de sens.
        """
        if self.sens is not SensOperation.ACHAT:
            raise ErreurValidation(
                "Un prix de revient ne se calcule pas sur une vente : utilisez "
                "montant_net_unitaire, qui est le produit net encaissé par titre.",
                sens=self.sens.value,
            )
        return self.montant_net_unitaire

    @property
    def taux_effectif(self) -> Decimal:
        """Part des frais dans le montant brut."""
        if self.montant_brut == 0:
            return Decimal(0)
        return Decimal(self.total) / Decimal(self.montant_brut)

    def detail(self) -> str:
        """Décompte lisible, une ligne par ligne de frais."""
        lignes = [
            f"{self.sens.value} {self.quantite} × {format_xof(self.cours_unitaire)}",
            f"  Montant brut{'':.<44}{format_xof(self.montant_brut):>20}",
        ]
        for ligne in self.lignes:
            taux = f" ({ligne.taux:.4%})" if ligne.taux is not None else ""
            lignes.append(f"  {ligne.libelle}{taux}".ljust(58) + f"{format_xof(ligne.montant):>20}")
        lignes.append(f"  Total des frais{'':.<41}{format_xof(self.total):>20}")
        lignes.append(f"  Montant net{'':.<45}{format_xof(self.montant_net):>20}")
        libelle = (
            "Prix de revient unitaire"
            if self.sens is SensOperation.ACHAT
            else "Produit net unitaire"
        )
        lignes.append(
            f"  {libelle}".ljust(58 - 4)
            + f"{self.montant_net_unitaire.quantize(Decimal('0.01'))!s:>20} XOF"
        )
        return "\n".join(lignes)


class MoteurFrais:
    """Applique le barème configuré à une opération."""

    def __init__(self, configuration: Configuration) -> None:
        self.configuration = configuration
        self.bareme: ConfigFrais = configuration.frais
        self.mode_arrondi: ModeArrondi = configuration.general.mode_arrondi

    def calculer(self, sens: SensOperation, quantite: int, cours_unitaire: int) -> DecompteFrais:
        """Calcule le décompte de frais d'une opération.

        Raises:
            ErreurValidation: quantité ou cours non strictement positifs.
        """
        if quantite <= 0:
            raise ErreurValidation(
                "La quantité d'une opération doit être strictement positive.",
                quantite=quantite,
            )
        if cours_unitaire <= 0:
            raise ErreurValidation(
                "Le cours d'une opération doit être strictement positif.",
                cours=cours_unitaire,
            )

        montant_brut = quantite * cours_unitaire
        applicables = sorted(
            (ligne for ligne in self.bareme.lignes if ligne.concerne(sens)),
            key=lambda ligne: ligne.ordre,
        )
        lignes: list[LigneFrais] = []
        commissions_cumulees = 0

        for reglage in applicables:
            calculee = self._calculer_ligne(reglage, montant_brut, commissions_cumulees)
            lignes.append(calculee)
            if reglage.base_calcul is not BaseFrais.TOTAL_COMMISSIONS:
                commissions_cumulees += calculee.montant

        total = sum(ligne.montant for ligne in lignes)
        minimum = self.bareme.minimum_perception_global
        if minimum is not None and total < minimum:
            complement = minimum - total
            lignes.append(
                LigneFrais(
                    libelle=LIBELLE_COMPLEMENT,
                    base_calcul=BaseFrais.MONTANT_FIXE,
                    assiette=0,
                    montant=complement,
                )
            )
            total = minimum

        return DecompteFrais(
            sens=sens,
            quantite=quantite,
            cours_unitaire=cours_unitaire,
            montant_brut=montant_brut,
            lignes=tuple(lignes),
            total=total,
        )

    def _calculer_ligne(
        self, reglage: ConfigLigneFrais, montant_brut: int, commissions_cumulees: int
    ) -> LigneFrais:
        if reglage.base_calcul is BaseFrais.MONTANT_FIXE:
            montant_fixe = reglage.montant_fixe or 0
            return LigneFrais(
                libelle=reglage.libelle,
                base_calcul=reglage.base_calcul,
                assiette=0,
                montant=int(
                    borne(
                        Decimal(montant_fixe),
                        reglage.minimum_perception,
                        reglage.maximum_perception,
                    )
                ),
            )

        assiette = (
            montant_brut if reglage.base_calcul is BaseFrais.MONTANT_BRUT else commissions_cumulees
        )
        brute = applique_taux(assiette, reglage.taux or Decimal(0))
        bornee = borne(brute, reglage.minimum_perception, reglage.maximum_perception)
        return LigneFrais(
            libelle=reglage.libelle,
            base_calcul=reglage.base_calcul,
            taux=reglage.taux,
            assiette=assiette,
            montant=arrondi_xof(bornee, self.mode_arrondi),
        )

    # --------------------------------------------------------------- récurrents

    def frais_periodiques_annuels(self, encours: int) -> tuple[tuple[str, int], ...]:
        """Coût annuel des frais récurrents pour un encours donné.

        Ces frais ne se déclenchent pas à l'achat : ils courent tant que la ligne
        est détenue. Les ignorer sous-estime le coût réel de détention.
        """
        resultats: list[tuple[str, int]] = []
        for frais in self.bareme.periodiques:
            if frais.base_calcul == "ENCOURS":
                montant = arrondi_xof(
                    applique_taux(encours, frais.taux or Decimal(0)), self.mode_arrondi
                )
            else:
                montant = (frais.montant_fixe or 0) * frais.periodicite.occurrences_par_an
            resultats.append((frais.libelle, montant))
        return tuple(resultats)

    def cout_annuel_detention(self, encours: int) -> int:
        return sum(montant for _, montant in self.frais_periodiques_annuels(encours))

    def periodicites_declarees(self) -> tuple[Periodicite, ...]:
        return tuple(frais.periodicite for frais in self.bareme.periodiques)


def cumuler(decomptes: Sequence[DecompteFrais]) -> int:
    """Total des frais de plusieurs opérations."""
    return sum(decompte.total for decompte in decomptes)
