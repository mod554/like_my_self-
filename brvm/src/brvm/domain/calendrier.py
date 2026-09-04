"""Calendrier des séances de bourse.

Le calendrier est une **donnée de configuration**, jamais une constante du code :
les jours fériés de l'UEMOA varient d'un État à l'autre et, pour certains, d'une
année à l'autre (fêtes mobiles). Le système refuse de raisonner sur une période
qu'il ne couvre pas explicitement, plutôt que de supposer un calendrier.

Deux notions distinctes cohabitent :

* la **place de cotation** (un seul pays) : ses jours fériés ferment la bourse ;
* les **pays des émetteurs** : leurs jours fériés ne ferment pas la bourse, mais
  expliquent souvent une absence de transaction sur les valeurs concernées. Cette
  information sert à qualifier un trou de série, pas à le combler.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from brvm.domain.enums import Pays
from brvm.utils.erreurs import ErreurCalendrier, ErreurConfiguration

#: Lundi=0 … Dimanche=6, convention ``date.weekday()``.
LUNDI: Final[int] = 0
VENDREDI: Final[int] = 4

#: Jours ouvrés retenus par défaut si la configuration n'en impose pas d'autres.
JOURS_OUVRES_DEFAUT: Final[frozenset[int]] = frozenset({LUNDI, 1, 2, 3, VENDREDI})

#: Garde-fou : au-delà, une recherche de séance suivante est considérée comme le
#: signe d'un calendrier mal renseigné plutôt que d'une longue fermeture.
MAX_JOURS_RECHERCHE: Final[int] = 60


@dataclass(frozen=True, slots=True)
class CalendrierSeances:
    """Calendrier immuable, valable sur une période de couverture déclarée."""

    pays_place: Pays
    couverture_debut: date
    couverture_fin: date
    jours_ouvres: frozenset[int] = JOURS_OUVRES_DEFAUT
    feries_par_pays: Mapping[Pays, frozenset[date]] = None  # type: ignore[assignment]
    fermetures_exceptionnelles: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        if self.feries_par_pays is None:
            object.__setattr__(self, "feries_par_pays", {})
        if self.couverture_debut > self.couverture_fin:
            raise ErreurConfiguration(
                "Période de couverture du calendrier inversée : le début est postérieur à la fin.",
                debut=self.couverture_debut.isoformat(),
                fin=self.couverture_fin.isoformat(),
            )
        if not self.jours_ouvres:
            raise ErreurConfiguration(
                "Aucun jour ouvré déclaré : le calendrier ne comporterait aucune séance possible."
            )
        if any(jour not in range(7) for jour in self.jours_ouvres):
            raise ErreurConfiguration(
                "Jours ouvrés hors intervalle : attendu 0 (lundi) à 6 (dimanche).",
                jours_ouvres=sorted(self.jours_ouvres),
            )

    # ------------------------------------------------------------------ couverture

    def est_couverte(self, jour: date) -> bool:
        return self.couverture_debut <= jour <= self.couverture_fin

    def exiger_couverture(self, jour: date) -> None:
        """Lève si la date sort de la période explicitement renseignée."""
        if not self.est_couverte(jour):
            raise ErreurCalendrier(
                "Le calendrier de séances ne couvre pas cette date. Complétez le fichier de "
                "jours fériés (jours fériés UEMOA de l'année concernée) puis étendez la "
                "période de couverture. Le système refuse de supposer un calendrier.",
                date_demandee=jour.isoformat(),
                couverture_debut=self.couverture_debut.isoformat(),
                couverture_fin=self.couverture_fin.isoformat(),
            )

    # -------------------------------------------------------------------- séances

    def est_ferie(self, jour: date, pays: Pays | None = None) -> bool:
        """Indique si ``jour`` est férié dans ``pays`` (par défaut la place de cotation)."""
        cible = pays if pays is not None else self.pays_place
        return jour in self.feries_par_pays.get(cible, frozenset())

    def est_jour_de_seance(self, jour: date) -> bool:
        """Vrai si la bourse est ouverte ce jour-là.

        Lève :class:`ErreurCalendrier` si la date sort de la couverture : une
        réponse ``False`` non fondée serait indiscernable d'un vrai jour fermé.
        """
        self.exiger_couverture(jour)
        if jour.weekday() not in self.jours_ouvres:
            return False
        if jour in self.fermetures_exceptionnelles:
            return False
        return not self.est_ferie(jour, self.pays_place)

    def seances(self, debut: date, fin: date) -> list[date]:
        """Liste ordonnée des jours de séance dans ``[debut, fin]`` inclus."""
        if debut > fin:
            return []
        self.exiger_couverture(debut)
        self.exiger_couverture(fin)
        resultat: list[date] = []
        jour = debut
        while jour <= fin:
            if self.est_jour_de_seance(jour):
                resultat.append(jour)
            jour += timedelta(days=1)
        return resultat

    def nb_seances(self, debut: date, fin: date) -> int:
        return len(self.seances(debut, fin))

    def prochaine_seance(self, jour: date, inclusif: bool = False) -> date:
        """Première séance à partir de ``jour`` (incluse si ``inclusif``)."""
        return self._chercher(jour, pas=1, inclusif=inclusif)

    def seance_precedente(self, jour: date, inclusif: bool = False) -> date:
        """Dernière séance avant ``jour`` (incluse si ``inclusif``)."""
        return self._chercher(jour, pas=-1, inclusif=inclusif)

    def _chercher(self, jour: date, pas: int, inclusif: bool) -> date:
        candidat = jour if inclusif else jour + timedelta(days=pas)
        for _ in range(MAX_JOURS_RECHERCHE):
            self.exiger_couverture(candidat)
            if self.est_jour_de_seance(candidat):
                return candidat
            candidat += timedelta(days=pas)
        raise ErreurCalendrier(
            f"Aucune séance trouvée en {MAX_JOURS_RECHERCHE} jours : le calendrier est "
            "probablement mal renseigné (jours fériés trop nombreux ou jours ouvrés absents).",
            depart=jour.isoformat(),
            sens="avant" if pas > 0 else "arrière",
        )

    # --------------------------------------------------------------- diagnostics

    def annees_couvertes(self) -> list[int]:
        return list(range(self.couverture_debut.year, self.couverture_fin.year + 1))

    def avertissements(self) -> list[str]:
        """Signale les années de couverture sans aucun jour férié déclaré.

        Un calendrier annuel sans férié est possible en théorie mais, en pratique,
        signale un fichier non rempli. Le système le dit au lieu de le corriger.
        """
        feries_place = self.feries_par_pays.get(self.pays_place, frozenset())
        annees_avec_feries = {jour.year for jour in feries_place}
        messages: list[str] = []
        for annee in self.annees_couvertes():
            if annee not in annees_avec_feries:
                messages.append(
                    f"Aucun jour férié déclaré pour {self.pays_place.value} en {annee} : "
                    "vérifiez le fichier de calendrier, les séances de cette année seront "
                    "comptées comme ouvertes du lundi au vendredi."
                )
        return messages


def construire_calendrier(
    pays_place: Pays,
    couverture_debut: date,
    couverture_fin: date,
    jours_ouvres: Iterable[int] | None = None,
    feries_par_pays: Mapping[Pays, Iterable[date]] | None = None,
    fermetures_exceptionnelles: Iterable[date] | None = None,
) -> CalendrierSeances:
    """Fabrique un calendrier à partir de données brutes de configuration."""
    return CalendrierSeances(
        pays_place=pays_place,
        couverture_debut=couverture_debut,
        couverture_fin=couverture_fin,
        # `None` signifie « non précisé » et retombe sur le défaut ; une liste
        # explicitement vide est une erreur de configuration, pas une omission.
        jours_ouvres=(frozenset(jours_ouvres) if jours_ouvres is not None else JOURS_OUVRES_DEFAUT),
        feries_par_pays={pays: frozenset(jours) for pays, jours in (feries_par_pays or {}).items()},
        fermetures_exceptionnelles=frozenset(fermetures_exceptionnelles or ()),
    )
