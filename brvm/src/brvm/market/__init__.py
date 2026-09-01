"""Analyse de la cote entière : criblage, horizons, allocation.

Cette couche répond à trois questions, et refuse d'en traiter une quatrième.

* **Que valent les valeurs de la cote, chacune, sur des critères mesurés ?**
  → :mod:`brvm.market.criteres` et :mod:`brvm.market.analyse`.
* **Comment se classent-elles selon un horizon donné ?**
  → :mod:`brvm.market.horizons`.
* **Quelle répartition respecte mes limites déclarées ?**
  → :mod:`brvm.market.allocation`.

La quatrième question — « quelle valeur va monter ? » — n'a pas de réponse ici,
et le vocabulaire du module l'évite délibérément. On y parle de *classement*,
de *critères*, de *contraintes* ; jamais de recommandation ni d'opportunité.
Un classement par momentum et liquidité est un constat sur des données passées.
Une « meilleure opportunité » serait une prédiction, et ce système n'en produit
aucune.
"""
