"""Emballe la page publique en un fichier unique, pour un apercu partageable.

La page de production lit trois ressources voisines : sa feuille de style, ses
polices auto-hebergees et son instantane JSON. Un apercu partage n'a pas de
voisins : tout doit tenir dans un seul fichier.

Ce module ne redessine rien. Le systeme de design est celui du projet — voir
`.interface-design/system.md` — et il est repris tel quel. Trois substitutions,
et rien d'autre :

* la feuille de style est incorporee ;
* les polices auto-hebergees cedent la place a Google Fonts, seul hebergeur que
  la politique de contenu de l'apercu admet. C'est la SEULE difference visuelle
  avec la production, ou la page ne contacte personne ;
* l'instantane JSON est incorpore, donc fige a la date de generation.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

POLICES = (
    "https://fonts.googleapis.com/css2"
    "?family=Newsreader:opsz,wght@6..72,400..700"
    "&family=Instrument+Sans:wght@400..700"
    "&family=IBM+Plex+Mono:wght@400;500&display=swap"
)


def sans_polices_locales(css: str) -> str:
    """Retire les @font-face : les fichiers woff2 ne suivent pas la page."""
    return re.sub(r"@font-face\s*\{[^}]*\}\s*", "", css)


def batir(source: Path, sortie: Path) -> Path:
    page = (source / "index.html").read_text(encoding="utf-8")
    css = sans_polices_locales((source / "style.css").read_text(encoding="utf-8"))
    charge = json.loads((source / "marche.json").read_text(encoding="utf-8"))

    corps = page[page.index("<body>") + len("<body>") : page.index("</body>")]
    debut_script = corps.index('<script type="module">')
    script = corps[debut_script + len('<script type="module">') : corps.rindex("</script>")]
    corps = corps[:debut_script]

    # La lecture reseau devient une constante : plus rien a aller chercher.
    script = script.replace(
        '    const reponse = await fetch("marche.json", { cache: "no-store" });\n'
        "    const charge = await reponse.json();\n"
        "    if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);\n",
        "    const charge = CHARGE;\n",
    )
    # `/api/etat` subsiste dans `charger()`, qui reste DEFINIE mais n'est jamais
    # appelee : la page de production expedie le fichier de l'interface tel
    # quel, pour n'avoir qu'une source. Ce qui doit disparaitre ici, c'est la
    # lecture du JSON voisin — le seul appel reellement execute.
    if 'fetch("marche.json"' in script:
        raise AssertionError(
            "La lecture de marche.json subsiste : l'apercu n'a pas de fichier voisin."
        )

    bandeau = """
    <div class="apercu-note">
      <p><strong>Aperçu de la page de production.</strong> C'est le fichier qui
      sera servi en ligne, avec les cotations réelles de la BRVM. Une seule
      différence : les polices viennent ici de Google&nbsp;Fonts, alors qu'en
      production elles sont auto-hébergées et la page ne contacte personne.</p>
      <p>Les données sont figées à la date indiquée ci-dessous. En production,
      un travail programmé les régénère après chaque clôture.</p>
    </div>
"""
    corps = corps.replace('<div class="portee">', bandeau + '\n    <div class="portee">', 1)

    style_apercu = """
@layer composants {
  .apercu-note {
    border: 1px solid var(--indigo);
    border-inline-start-width: 3px;
    border-radius: var(--rayon);
    background: var(--indigo-voile);
    padding: var(--e4) var(--e5);
    margin-block-end: var(--e4);
  }
  .apercu-note p { margin: 0; max-width: 84ch; }
  .apercu-note p + p { margin-block-start: var(--e2); }
}
"""

    sortie.write_text(
        "<title>Criblage BRVM</title>\n"
        f'<link rel="stylesheet" href="{POLICES}">\n'
        f"<style>\n{css}\n{style_apercu}</style>\n\n"
        f"{corps}\n"
        '<script type="module">\n'
        f"const CHARGE = {json.dumps(charge, ensure_ascii=False)};\n\n"
        f"{script}\n</script>\n",
        encoding="utf-8",
    )
    return sortie


if __name__ == "__main__":
    fichier = batir(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{fichier} -- {fichier.stat().st_size / 1024:.0f} Ko")
