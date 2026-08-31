"""Analyse de pages : extraction de tableaux HTML, pilotée par votre description.

Ce module ne connaît la mise en page d'aucun site. Il sait seulement extraire les
tableaux d'une page et appliquer une **correspondance de colonnes que vous avez
écrite après avoir regardé la page**. C'est la seule façon honnête d'analyser une
source dont personne n'a garanti la structure : le système exécute votre
description, il n'en invente aucune.

Marche à suivre pour activer une source :

1. capturer une page : ``python -m brvm.ingestion.capture --source <nom>`` ;
2. lister ses tableaux : ``python -m brvm.ingestion.capture --lister-tableaux …`` ;
3. reporter dans la configuration le rang du bon tableau et la correspondance
   entre ses en-têtes et les champs du système ;
4. relancer une collecte et vérifier les anomalies signalées.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Any, Final
from zoneinfo import ZoneInfo

from brvm.config.modeles import ConfigAnalyseur, ConfigColonneLien, Configuration
from brvm.ingestion.web import ContexteAnalyse
from brvm.utils.erreurs import ErreurSource

#: Balises ouvrant une cellule.
CELLULES: Final[frozenset[str]] = frozenset({"td", "th"})

#: Balises dont le contenu textuel n'a rien à faire dans une cellule.
IGNOREES: Final[frozenset[str]] = frozenset({"script", "style"})


@dataclass(frozen=True, slots=True)
class Cellule:
    """Contenu d'une cellule : son texte affiché et, s'il existe, son premier lien.

    Sur une page de cote, le code de la valeur n'est souvent pas affiché : il
    n'existe que dans l'adresse du lien portant son nom. Conserver les deux
    permet de le récupérer sans deviner.
    """

    texte: str
    lien: str | None = None


#: Tableau détaillé : lignes de cellules.
TableauDetaille = list[list[Cellule]]
#: Tableau réduit à son texte.
Tableau = list[list[str]]


class _ExtracteurTableaux(HTMLParser):
    """Extrait tous les tableaux d'une page sous forme de listes de cellules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tableaux: list[TableauDetaille] = []
        self._pile: list[TableauDetaille] = []
        self._ligne: list[Cellule] | None = None
        self._cellule: list[str] | None = None
        self._lien: str | None = None
        self._ignorer = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in IGNOREES:
            self._ignorer += 1
        elif tag == "table":
            self._pile.append([])
        elif tag == "tr" and self._pile:
            self._cloturer_ligne()
            self._ligne = []
        elif tag in CELLULES and self._pile:
            self._cloturer_cellule()
            self._cellule = []
            self._lien = None
        elif tag == "a" and self._cellule is not None and self._lien is None:
            # Premier lien de la cellule seulement : les suivants sont du décor.
            self._lien = next((valeur for nom, valeur in attrs if nom == "href" and valeur), None)
        elif tag == "br" and self._cellule is not None:
            self._cellule.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in IGNOREES:
            self._ignorer = max(0, self._ignorer - 1)
        elif tag in CELLULES:
            self._cloturer_cellule()
        elif tag == "tr":
            self._cloturer_ligne()
        elif tag == "table":
            self._cloturer_ligne()
            if self._pile:
                self.tableaux.append(self._pile.pop())

    def handle_data(self, data: str) -> None:
        if self._ignorer == 0 and self._cellule is not None:
            self._cellule.append(data)

    def close(self) -> None:
        super().close()
        # Page mal formée : on récupère ce qui a pu être lu plutôt que de tout perdre.
        self._cloturer_ligne()
        while self._pile:
            self.tableaux.append(self._pile.pop())

    def _cloturer_cellule(self) -> None:
        if self._cellule is None:
            return
        texte = " ".join("".join(self._cellule).split())
        if self._ligne is None:
            self._ligne = []
        self._ligne.append(Cellule(texte, self._lien))
        self._cellule = None
        self._lien = None

    def _cloturer_ligne(self) -> None:
        self._cloturer_cellule()
        if self._ligne is not None:
            if self._ligne and self._pile:
                self._pile[-1].append(self._ligne)
            self._ligne = None


def extraire_tableaux_detaille(contenu: str) -> list[TableauDetaille]:
    """Tous les tableaux de la page, cellules avec texte et lien."""
    extracteur = _ExtracteurTableaux()
    extracteur.feed(contenu)
    extracteur.close()
    return extracteur.tableaux


def extraire_tableaux(contenu: str) -> list[Tableau]:
    """Tous les tableaux de la page, réduits au texte des cellules."""
    return [
        [[cellule.texte for cellule in ligne] for ligne in tableau]
        for tableau in extraire_tableaux_detaille(contenu)
    ]


def resumer_tableaux(contenu: str, lignes_exemple: int = 3) -> str:
    """Décrit les tableaux d'une page, pour aider à remplir la configuration."""
    tableaux = extraire_tableaux(contenu)
    if not tableaux:
        return "Aucun tableau HTML trouvé dans cette page."
    morceaux: list[str] = [f"{len(tableaux)} tableau(x) trouvé(s).\n"]
    for index, tableau in enumerate(tableaux):
        entetes = tableau[0] if tableau else []
        morceaux.append(f"--- index_tableau: {index}  ({len(tableau)} ligne(s)) ---")
        morceaux.append(f"  en-têtes : {entetes}")
        for ligne in tableau[1 : 1 + lignes_exemple]:
            morceaux.append(f"  exemple  : {ligne}")
        morceaux.append("")
    return "\n".join(morceaux)


def _normaliser(entete: str) -> str:
    return " ".join(entete.split()).casefold()


class AnalyseurTableauHtml:
    """Applique une correspondance de colonnes déclarée en configuration."""

    def __init__(self, nom: str, reglage: ConfigAnalyseur, configuration: Configuration) -> None:
        self.nom = nom
        self.reglage = reglage
        self.configuration = configuration
        self._correspondance = {
            _normaliser(entete): champ for entete, champ in reglage.colonnes.items()
        }
        self._liens = {_normaliser(entete): lien for entete, lien in reglage.colonnes_lien.items()}

    def url_pour(self, url_base: str, jour: date | None) -> str:
        """L'URL configurée, telle quelle.

        Aucun paramètre de requête n'est ajouté : le système ne connaît pas la
        façon dont un site donné désigne une séance passée. Pour interroger une
        autre date, déclarez une seconde source avec l'URL correspondante.
        """
        return url_base

    def analyser(self, contenu: str, contexte: ContexteAnalyse) -> list[dict[str, Any]]:
        tableaux = extraire_tableaux_detaille(contenu)
        if self.reglage.index_tableau >= len(tableaux):
            raise ErreurSource(
                f"La page ne contient que {len(tableaux)} tableau(x), or la configuration "
                f"désigne le tableau d'index {self.reglage.index_tableau}. La structure de "
                "la page a probablement changé : recapturez-la et vérifiez l'index.",
                source=self.nom,
                url=contexte.url,
            )
        tableau = tableaux[self.reglage.index_tableau]
        if len(tableau) < 2:
            raise ErreurSource(
                "Le tableau désigné ne comporte pas de ligne de données sous son en-tête.",
                source=self.nom,
                url=contexte.url,
            )

        entetes = [_normaliser(cellule.texte) for cellule in tableau[0]]
        libelles = [cellule.texte for cellule in tableau[0]]
        positions_texte = {
            index: self._correspondance[entete]
            for index, entete in enumerate(entetes)
            if entete in self._correspondance
        }
        positions_lien = {
            index: self._liens[entete]
            for index, entete in enumerate(entetes)
            if entete in self._liens
        }
        self._verifier_entetes(positions_texte, positions_lien, libelles, contexte)

        jour_par_defaut = self._jour_par_defaut(contexte)
        lignes: list[dict[str, Any]] = []
        exemple_lien: str | None = None

        for cellules in tableau[1:]:
            if not any(cellule.texte.strip() or cellule.lien for cellule in cellules):
                continue
            brut: dict[str, Any] = {
                champ: cellules[index].texte
                for index, champ in positions_texte.items()
                if index < len(cellules)
            }
            for index, reglage in positions_lien.items():
                if index >= len(cellules):
                    continue
                lien = cellules[index].lien
                if lien is None:
                    continue
                exemple_lien = exemple_lien or lien
                trouve = re.search(reglage.motif, lien)
                if trouve:
                    brut[reglage.champ] = trouve.group(1)
            if not brut.get("ticker"):
                continue
            if self.reglage.date_seance_depuis == "jour_de_collecte":
                brut["date_seance"] = jour_par_defaut.isoformat()
            lignes.append(brut)

        if not lignes:
            self._echec_extraction(positions_lien, exemple_lien, contexte)
        return lignes

    def _verifier_entetes(
        self,
        positions_texte: dict[int, str],
        positions_lien: dict[int, ConfigColonneLien],
        libelles: list[str],
        contexte: ContexteAnalyse,
    ) -> None:
        attendus = set(self.reglage.colonnes.values()) | {
            lien.champ for lien in self.reglage.colonnes_lien.values()
        }
        trouves = set(positions_texte.values()) | {
            reglage.champ for reglage in positions_lien.values()
        }
        if manquants := attendus - trouves:
            raise ErreurSource(
                "En-têtes déclarés introuvables dans le tableau : "
                + ", ".join(sorted(manquants))
                + f". En-têtes réellement présents : {libelles}. La page a changé, ou "
                "l'index de tableau ne désigne pas le bon.",
                source=self.nom,
                url=contexte.url,
            )

    def _echec_extraction(
        self,
        positions_lien: dict[int, ConfigColonneLien],
        exemple_lien: str | None,
        contexte: ContexteAnalyse,
    ) -> None:
        """Aucune ligne exploitable : on dit pourquoi plutôt que de rendre une liste vide.

        Une liste vide passerait pour « le marché n'a rien coté aujourd'hui », ce qui
        est indiscernable d'une erreur de configuration.
        """
        if positions_lien and exemple_lien:
            motifs = ", ".join(
                f"{reglage.champ} ← {reglage.motif!r}" for reglage in positions_lien.values()
            )
            raise ErreurSource(
                "Le tableau comporte des lignes mais aucune n'a livré de code valeur. "
                f"Les motifs d'extraction ne correspondent pas aux liens de la page "
                f"({motifs}). Exemple de lien rencontré : {exemple_lien!r}.",
                source=self.nom,
                url=contexte.url,
            )
        raise ErreurSource(
            "Le tableau comporte des lignes mais aucune ne porte de code valeur "
            "exploitable. Vérifiez la colonne associée au champ `ticker`.",
            source=self.nom,
            url=contexte.url,
        )

    def _jour_par_defaut(self, contexte: ContexteAnalyse) -> date:
        """Séance retenue quand la page ne porte pas la date.

        Priorité à la séance explicitement demandée, puis à la date annoncée par
        le serveur, puis à l'instant de collecte — toutes ramenées au fuseau du
        marché, pas à UTC : une collecte à 23 h à Abidjan ne doit pas être datée
        du lendemain.
        """
        if contexte.jour is not None:
            return contexte.jour
        fuseau = ZoneInfo(self.configuration.general.fuseau_horaire)
        reference = contexte.horodatage_donnee or contexte.horodatage_collecte
        return reference.astimezone(fuseau).date()
