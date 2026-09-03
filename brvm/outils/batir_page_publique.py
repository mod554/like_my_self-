"""Assemble la page publique du criblage, a partir des fichiers de l'interface.

La page servie en ligne n'est pas une seconde interface : elle EXTRAIT la seule
section publiable de l'interface locale — le marche — et n'en reecrit aucune
ligne. Deux interfaces divergeraient au premier correctif, et l'une des deux
finirait par afficher un chiffre que l'autre contredit.

Extraire une section est plus sur que d'en retirer quatre : ce qui n'est pas
explicitement extrait ne peut pas se retrouver en ligne par accident. La
difference compte, puisque ce qui reste sur la machine est le portefeuille.

Ne partent donc PAS en ligne : les lignes detenues, les montants, les
plus-values, les signaux, les stops, les anomalies, le journal de collecte, et
le champ de capital — chiffrer une repartition l'exige, et c'est une donnee
personnelle.

Partent en ligne : le classement, le detail des criteres, les valeurs ecartees
avec leur raison, et le bandeau de fraicheur. C'est ce qui rend un classement
contestable, et c'est ce qu'une page publique doit montrer plutot que masquer.
"""

from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "brvm" / "app" / "web"


def section_marche(html: str) -> str:
    """Extrait la section « marche », et elle seule."""
    debut = html.index('<section class="section" id="marche"')
    fin = html.index("</section>", debut) + len("</section>")
    section = html[debut:fin]
    # Le bloc de saisie du capital part avec le reste : la page ne chiffre
    # aucune repartition, et un champ sans effet est pire qu'un champ absent.
    # Le bloc s'ouvre sur `<div class="commande"` et se referme sur la ligne
    # `</div>` de meme indentation : on decoupe par indentation plutot que par
    # une expression rationnelle, qui compterait mal les `<div>` imbriques.
    lignes = section.split("\n")
    debut = next(i for i, ligne in enumerate(lignes) if '<div class="commande"' in ligne)
    marge = len(lignes[debut]) - len(lignes[debut].lstrip())
    fin = next(
        i
        for i in range(debut + 1, len(lignes))
        if lignes[i].strip() == "</div>" and len(lignes[i]) - len(lignes[i].lstrip()) == marge
    )
    section = "\n".join(lignes[:debut] + lignes[fin + 1 :])
    if 'id="capital"' in section:
        raise AssertionError("Le champ de capital est encore present dans la page publique.")
    return section


def script_marche(code: str) -> str:
    """Le code de l'interface, prive de tout appel reseau et de tout portefeuille."""
    # Le criblage est remis dans un fichier fige : plus rien a interroger.
    code = code.replace(
        "    const adresse = capital ? `/api/marche?capital=${encodeURIComponent(capital)}` "
        ': "/api/marche";\n'
        '    const reponse = await fetch(adresse, { headers: { Accept: "application/json" } });\n'
        "    const charge = await reponse.json();\n"
        "    if (!reponse.ok) throw new Error(charge.erreur || `HTTP ${reponse.status}`);\n",
        '    const reponse = await fetch("marche.json", { cache: "no-store" });\n'
        "    const charge = await reponse.json();\n"
        "    if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);\n",
    )
    # Le capital et son bouton n'existent plus dans le balisage.
    code = code.replace('const capital = $("capital").value.trim();', 'const capital = "";')
    code = code.replace('const bouton = $("cribler");', "const bouton = { disabled: false };")

    # Tout ce qui suppose un portefeuille est retire du demarrage. `charger()`
    # et ses rendus restent DEFINIS mais ne sont plus appeles : les supprimer
    # casserait le module, et une erreur de chargement masquerait les vraies.
    for ligne in (
        "charger();\n",
        '$("cribler").addEventListener("click", chargerMarche);\n',
        '$("capital").addEventListener("keydown", (evenement) => {\n'
        '  if (evenement.key === "Enter") chargerMarche();\n'
        "});\n",
    ):
        code = code.replace(ligne, "")
    # `charger()` et les rendus du portefeuille restent DEFINIS mais ne sont
    # plus appeles. On expedie donc le fichier de l'interface tel quel, ce qui
    # est le but : une seule source pour les deux pages. Ce qui est verifie ici
    # n'est pas l'absence du code mort, c'est qu'aucun APPEL ne subsiste : le
    # code mort ne lit rien, un appel oublie lirait.
    for appel in ("charger();", '$("capital")', '$("cribler")'):
        if appel in code:
            raise AssertionError(
                f"{appel} subsiste dans le script public : la page publique n'a "
                "ni portefeuille ni champ de capital, et cet appel echouerait."
            )
    return code


#: Icone de la page, en SVG inline : aucun fichier a servir, aucune requete.
FAVICON = (
    "data:image/svg+xml,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
    "<rect width='16' height='16' rx='2' fill='%23FBF9F6'/>"
    "<rect x='3' y='4' width='2' height='8' fill='%230F1727'/>"
    "<rect x='6.5' y='4' width='2' height='8' fill='none' stroke='%23B88923'/>"
    "<rect x='10' y='10' width='2' height='2' fill='%23969AA1'/>"
    "</svg>"
)

DESCRIPTION = (
    "Classement de la cote BRVM selon des criteres declares. Aucun conseil en investissement."
)


def batir(sortie: Path) -> Path:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    page = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Criblage de la cote BRVM</title>
<meta name="description" content="{DESCRIPTION}">
<meta name="color-scheme" content="light">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="style.css">
</head>
<body>

<a class="lien-evitement" href="#principal">Aller au contenu</a>

<div class="page">
  <aside class="rail">
    <div class="marque">
      <strong>La cote</strong>
      <span>BRVM &mdash; criblage public</span>
    </div>
    <p class="sourdine rail-mention">
      Cet ecran classe. Il ne recommande rien et ne promet aucun rendement.
    </p>
  </aside>

  <main class="contenu" id="principal">
    <h1 class="invisible">Criblage public de la cote BRVM</h1>

    <div class="portee">
      <p><strong>Criblage public de la cote BRVM.</strong> Cette page classe des
      valeurs selon des criteres declares, sur des donnees passees. Elle ne
      contient aucun portefeuille, aucun montant personnel et aucune proposition
      de repartition : celles-ci restent sur la machine de leur proprietaire.</p>
      <p>Ce n'est pas un conseil en investissement, et aucun rendement n'est
      promis. Les cours affiches sont les derniers connus, pas des cours
      actuels : verifiez l'horodatage avant d'agir.</p>
    </div>

    <div id="marche-erreur" class="erreur" hidden>
      <h2>La cote n'a pas pu etre affichee</h2>
      <p id="marche-erreur-detail"></p>
    </div>

{section_marche(index)}

    <p class="mention">
      Classement mecanique de criteres declares, sur donnees passees. Aucune
      prevision, aucune recommandation, aucune promesse de rendement. Recoupez
      avec la cote officielle de la BRVM avant toute decision.
    </p>
  </main>
</div>

<script type="module">
{script_marche((WEB / "app.js").read_text(encoding="utf-8"))}
</script>
</body>
</html>
"""
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "index.html").write_text(page, encoding="utf-8")
    (sortie / "style.css").write_text(
        (WEB / "style.css").read_text(encoding="utf-8"), encoding="utf-8"
    )
    polices = sortie / "polices"
    polices.mkdir(exist_ok=True)
    for fichier in (WEB / "polices").glob("*.woff2"):
        (polices / fichier.name).write_bytes(fichier.read_bytes())
    return sortie / "index.html"


if __name__ == "__main__":
    fichier = batir(Path(sys.argv[1]))
    print(f"{fichier} -- {fichier.stat().st_size} octets")
