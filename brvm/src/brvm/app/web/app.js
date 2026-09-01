// Rendu de l'interface. Cette couche n'effectue AUCUN calcul : elle affiche ce
// que /api/etat lui remet. Un écran qui recalculerait pour son compte finirait
// par montrer un total qui ne correspond ni à l'export, ni aux alertes.

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- formatage

const FR = new Intl.NumberFormat("fr-FR");

/** Un entier de XOF. Le franc ne circule pas en centimes : aucune décimale. */
const xof = (v) => (v === null || v === undefined ? "—" : FR.format(v));

/** Un montant signé. Le signe précède toujours : la couleur ne suffit jamais. */
const signe = (v) =>
  v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + FR.format(v);

const pourcent = (v, decimales = 2) =>
  v === null || v === undefined ? "—" : (v * 100).toFixed(decimales) + " %";

const jour = (iso) => (iso ? iso.slice(0, 10) : "—");

/** Un âge en minutes, dit en heures ou en jours dès que c'est plus lisible. */
function age(minutes) {
  if (minutes === null || minutes === undefined) return "—";
  if (minutes < 90) return `${Math.round(minutes)} min`;
  if (minutes < 60 * 36) return `${Math.round(minutes / 60)} h`;
  return `${Math.round(minutes / 1440)} j`;
}

const classeSigne = (v) => (v > 0 ? "gain" : v < 0 ? "perte" : "");

function vider(noeud) {
  while (noeud.firstChild) noeud.removeChild(noeud.firstChild);
}

/**
 * Crée un élément.
 *
 * Deux règles tenues partout dans ce fichier :
 *
 * - **aucun innerHTML avec des données.** Tout passe par `textContent` et le
 *   DOM : un message d'anomalie contenant `<` ne peut rien exécuter ;
 * - **aucun attribut `style`.** La politique de sécurité de contenu du serveur
 *   interdit les styles en ligne, et c'est voulu. Les valeurs continues (largeur
 *   d'une jauge, position d'une limite) passent par `style.setProperty`, qui
 *   emprunte le CSSOM et non l'attribut — la feuille de style garde la main sur
 *   la mise en forme, le script ne fournit que la mesure.
 */
function el(balise, attributs = {}, enfants = []) {
  const noeud = document.createElement(balise);
  for (const [cle, valeur] of Object.entries(attributs)) {
    if (valeur === null || valeur === undefined) continue;
    if (cle === "class") noeud.className = valeur;
    else if (cle === "text") noeud.textContent = valeur;
    else if (cle === "vars") {
      for (const [propriete, mesure] of Object.entries(valeur)) {
        noeud.style.setProperty(propriete, mesure);
      }
    } else noeud.setAttribute(cle, valeur);
  }
  for (const enfant of [].concat(enfants)) {
    if (enfant) noeud.appendChild(enfant);
  }
  return noeud;
}

// ------------------------------------------------------ SIGNATURE : la trame

/**
 * Une marque par séance attendue : pleine si la valeur a réellement coté,
 * creuse sinon. C'est le qualificatif le plus important de l'écran — un cours
 * vu douze fois sur vingt séances ne vaut pas le même cours vu deux fois.
 *
 * La forme porte le sens ; la couleur ne fait que l'appuyer. La trame reste
 * donc lisible sans distinction des couleurs, et en contrastes forcés.
 */
function trame(donnees, nu = false) {
  if (!donnees) return el("span", { class: "sourdine", text: "aucune séance en base" });

  const bande = el("div", {
    class: nu ? "trame" : "trame trame--compacte",
    role: "img",
    "aria-label":
      `${donnees.cotees} séances cotées sur ${donnees.attendues} attendues` +
      (donnees.derniere_cotee ? `, dernière le ${donnees.derniere_cotee}` : ""),
  });
  for (const seance of donnees.seances) {
    bande.appendChild(
      el("span", {
        class: "seance",
        "data-origine": seance.origine,
        title: `${seance.date} — ${libelleOrigine(seance.origine)}`,
      }),
    );
  }

  if (nu) return bande;

  return el("div", { class: "rangee" }, [
    bande,
    el("span", {
      class: "trame-compte",
      text: `${donnees.cotees}/${donnees.attendues}`,
    }),
  ]);
}

/** Accord en nombre. « 1 ligne valorisée » plutôt que « 1 ligne(s) ». */
const pluriel = (n, singulier, plural) => (Math.abs(n) < 2 ? singulier : plural);

const libelleOrigine = (o) =>
  ({ COTEE: "séance cotée", REPORTEE: "cours reporté", ABSENTE: "séance absente" })[o] ||
  o;

// --------------------------------------------------------------- courbe SVG

const SVG = "http://www.w3.org/2000/svg";

/**
 * Courbe des cours. Les segments qui reposent sur un cours reporté sont tracés
 * en trait interrompu : les lisser dessinerait une tendance qui n'a pas eu lieu.
 */
function courbe(points) {
  const largeur = 560;
  const hauteur = 132;
  const marge = { haut: 10, bas: 16, gauche: 4, droite: 4 };

  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "courbe");
  svg.setAttribute("viewBox", `0 0 ${largeur} ${hauteur}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("role", "img");

  if (!points || points.length < 2) {
    svg.setAttribute("aria-label", "Pas assez de séances pour tracer une courbe");
    return svg;
  }

  const valeurs = points.map((p) => p.cloture);
  const min = Math.min(...valeurs);
  const max = Math.max(...valeurs);
  const etendue = max - min || 1;
  const utileX = largeur - marge.gauche - marge.droite;
  const utileY = hauteur - marge.haut - marge.bas;

  const x = (i) => marge.gauche + (i / (points.length - 1)) * utileX;
  const y = (v) => marge.haut + (1 - (v - min) / etendue) * utileY;

  svg.setAttribute(
    "aria-label",
    `Cours de ${points[0].date} à ${points[points.length - 1].date}, ` +
      `de ${FR.format(min)} à ${FR.format(max)} XOF`,
  );

  // Ligne de base discrète, pour donner une assise au tracé.
  const base = document.createElementNS(SVG, "line");
  base.setAttribute("class", "grille");
  base.setAttribute("x1", "0");
  base.setAttribute("x2", String(largeur));
  base.setAttribute("y1", String(hauteur - marge.bas));
  base.setAttribute("y2", String(hauteur - marge.bas));
  svg.appendChild(base);

  // Un segment par intervalle : son style dépend de la nature des deux bouts.
  for (let i = 1; i < points.length; i += 1) {
    const segment = document.createElementNS(SVG, "line");
    const reporte = !points[i].cotee || !points[i - 1].cotee;
    segment.setAttribute("class", `trace${reporte ? " trace--reporte" : ""}`);
    segment.setAttribute("x1", String(x(i - 1)));
    segment.setAttribute("y1", String(y(points[i - 1].cloture)));
    segment.setAttribute("x2", String(x(i)));
    segment.setAttribute("y2", String(y(points[i].cloture)));
    svg.appendChild(segment);
  }

  // Dernier point coté, marqué : c'est le cours qui sert à la valorisation.
  for (let i = points.length - 1; i >= 0; i -= 1) {
    if (!points[i].cotee) continue;
    const point = document.createElementNS(SVG, "circle");
    point.setAttribute("class", "point");
    point.setAttribute("cx", String(x(i)));
    point.setAttribute("cy", String(y(points[i].cloture)));
    point.setAttribute("r", "2.5");
    svg.appendChild(point);
    break;
  }

  return svg;
}

// -------------------------------------------------------------- fraîcheur

function rendreFraicheur(f) {
  const bloc = $("fraicheur");
  bloc.dataset.perimee = String(f.perimee);
  const horodatage = $("fraicheur-horodatage");
  horodatage.textContent = f.horodatage ? f.horodatage.replace("T", " ").slice(0, 19) : "aucune";
  horodatage.setAttribute("datetime", f.horodatage || "");
  $("fraicheur-age").textContent = f.horodatage ? `il y a ${age(f.age_minutes)}` : "";
  $("fraicheur-note").textContent = f.perimee
    ? `Au-delà des ${f.seuil_minutes} minutes que vous tolérez. Les chiffres ci-dessous décrivent cette date, pas aujourd'hui.`
    : "Les chiffres ci-dessous reposent sur cette date.";
}

// ------------------------------------------------------------ portefeuille

function rendrePortefeuille(donnees) {
  const p = donnees.portefeuille;

  $("portefeuille-methode").textContent =
    `Valorisation ${donnees.methode}. Les lignes sans cours ne sont pas comptées pour zéro.`;

  const valeur = $("c-valeur");
  valeur.className = "";
  valeur.textContent = xof(p.valeur_totale);
  $("c-cout").textContent = xof(p.cout_total);

  const brute = $("c-pv-brute");
  brute.textContent = signe(p.plus_value_brute);
  brute.className = classeSigne(p.plus_value_brute);

  const nette = $("c-pv-nette");
  nette.textContent = signe(p.plus_value_nette);
  nette.className = classeSigne(p.plus_value_nette);

  $("c-dividendes").textContent = xof(p.dividendes_nets);

  const valorisees = p.lignes.filter((l) => l.valorisee).length;
  $("c-valeur-note").textContent = p.non_valorisees.length
    ? `Total incomplet : ${p.non_valorisees.join(", ")} ${pluriel(p.non_valorisees.length, "est", "sont")} sans cours.`
    : `${valorisees} ${pluriel(valorisees, "ligne valorisée", "lignes valorisées")}`;

  // Assiduité de chaque valeur détenue, dans le bloc héros : la texture du
  // silence, avant même le détail des lignes.
  const global = $("trame-globale");
  vider(global);
  for (const ligne of p.lignes) {
    if (!ligne.trame) continue;
    global.appendChild(
      el("div", { class: "assiduite" }, [
        el("span", { class: "valeur-titre", text: ligne.ticker }),
        trame(ligne.trame, true),
        el("span", {
          class: "trame-compte",
          text: `${Math.round((ligne.trame.cotees / ligne.trame.attendues) * 100)} %`,
        }),
      ]),
    );
  }

  const note = $("note-performance");
  note.textContent = donnees.performance.motif;
  note.className = "note";

  const corps = $("lignes");
  vider(corps);

  if (!p.lignes.length) {
    corps.appendChild(
      el("tr", {}, [
        el("td", { colspan: "9", class: "vide" }, [
          el("strong", { text: "Aucune position" }),
          document.createTextNode(
            "Enregistrez une transaction, puis lancez une collecte.",
          ),
        ]),
      ]),
    );
    return;
  }

  for (const ligne of p.lignes) {
    corps.appendChild(rangeeLigne(ligne));
  }
}

function rangeeLigne(ligne) {
  const rangee = el("tr");
  rangee.appendChild(el("th", { scope: "row", class: "valeur-titre", text: ligne.ticker }));
  rangee.appendChild(el("td", {}, [trame(ligne.trame)]));
  rangee.appendChild(el("td", { class: "num", text: FR.format(ligne.quantite) }));
  rangee.appendChild(el("td", { class: "num", text: xof(Math.round(ligne.prix_revient_unitaire)) }));

  if (!ligne.valorisee) {
    const cellule = el("td", { class: "num", colspan: "5" }, [
      el("span", {
        class: "etiq etiq--attention",
        text: "non valorisée",
      }),
      el("span", {
        class: "sourdine motif-ligne",
        text: ligne.motif_indisponible || "aucun cours disponible",
      }),
    ]);
    cellule.className = "cellule-indisponible";
    rangee.appendChild(cellule);
    return rangee;
  }

  rangee.appendChild(el("td", { class: "num", text: xof(ligne.cours) }));

  // L'âge du cours porte la séance dont il provient : « 1 j » ne dit pas de
  // quelle séance, et sur ce marché c'est justement la question.
  rangee.appendChild(
    el("td", { class: "num", title: `séance du ${jour(ligne.date_cours)}` }, [
      document.createTextNode(age(ligne.age_minutes)),
    ]),
  );

  rangee.appendChild(el("td", { class: "num", text: xof(ligne.valeur) }));
  rangee.appendChild(el("td", { class: "num", text: pourcent(ligne.poids, 1) }));

  const pv = el("td", { class: `num ${classeSigne(ligne.plus_value_nette)}` });
  pv.textContent = signe(ligne.plus_value_nette);
  rangee.appendChild(pv);

  return rangee;
}

// ----------------------------------------------------------------- signaux

function rendreSignaux(donnees) {
  const bloc = $("liste-signaux");
  vider(bloc);

  if (!donnees.signaux.length) {
    bloc.appendChild(
      el("div", { class: "cadre" }, [
        el("div", { class: "vide" }, [
          el("strong", { text: "Aucun signal constaté" }),
          document.createTextNode(
            "Sur l'historique disponible, aucune règle mécanique n'a été franchie.",
          ),
        ]),
      ]),
    );
    return;
  }

  for (const signal of donnees.signaux.slice(0, 12)) {
    const achat = signal.sens === "ACHAT";
    const carte = el("article", { class: "signal" });

    carte.appendChild(
      el("div", { class: "signal-tete" }, [
        // Glyphe + texte : jamais la couleur seule pour porter le sens.
        el("span", {
          class: `etiq ${achat ? "etiq--achat" : "etiq--vente"}`,
          text: (achat ? "▲ " : "▼ ") + signal.sens,
        }),
        el("span", { class: "signal-regle valeur-titre", text: signal.ticker }),
        el("span", { class: "sourdine", text: signal.regle }),
        el("span", {
          class: "etiq etiq--neutre",
          text: `confiance ${signal.niveau_confiance}`,
        }),
      ]),
    );

    carte.appendChild(el("p", { text: signal.explication }));

    carte.appendChild(
      el("dl", { class: "signal-dates" }, [
        el("div", {}, [
          el("dt", { text: "Constaté sur la séance du" }),
          el("dd", { text: signal.date_constat }),
        ]),
        el("div", { class: "execution" }, [
          el("dt", { text: "Exécutable au plus tôt le" }),
          el("dd", { text: signal.date_execution }),
        ]),
      ]),
    );

    for (const avertissement of signal.avertissements) {
      carte.appendChild(el("p", { class: "note note--attention", text: avertissement }));
    }

    const points = donnees.courbes[signal.ticker];
    if (points && points.length > 1) carte.appendChild(courbe(points));

    bloc.appendChild(carte);
  }
}

// ------------------------------------------------------------------ risque

/** Un ratio contre une limite : une jauge, pas un camembert. */
function jauge(constat) {
  const echelle = Math.max(constat.poids, constat.limite, 0.0001) * 1.15;
  const bloc = el("div", { class: "jauge", "data-depasse": String(!constat.respecte) });

  // Le poids se lit contre son propre libellé, pas contre celui d'en dessous.
  // Et seul un dépassement porte un badge : sept étiquettes « dans la limite »
  // identiques ne disent rien et masquent celle qui compterait.
  bloc.appendChild(
    el("div", { class: "jauge-tete" }, [
      el("span", { class: "cle" }, [
        el("span", { class: "sourdine", text: constat.dimension + " " }),
        document.createTextNode(constat.cle),
      ]),
      el("span", { class: "rangee" }, [
        el("span", { class: "jauge-poids", text: pourcent(constat.poids) }),
        el("span", { class: "jauge-limite-texte", text: `limite ${pourcent(constat.limite)}` }),
        constat.respecte
          ? null
          : el("span", { class: "etiq etiq--vente", text: "✕ dépassé" }),
      ]),
    ]),
  );

  const piste = el("div", { class: "jauge-piste" });
  piste.appendChild(
    el("div", {
      class: "jauge-remplissage",
      vars: { "--part": `${Math.min(100, (constat.poids / echelle) * 100).toFixed(2)}%` },
    }),
  );
  piste.appendChild(
    el("div", {
      class: "jauge-limite",
      vars: { "--part": `${((constat.limite / echelle) * 100).toFixed(2)}%` },
      title: `limite ${pourcent(constat.limite)}`,
    }),
  );
  bloc.appendChild(piste);

  return bloc;
}

/** Avertissements portés par TOUS les stops : ils se disent une fois. */
function avertissementsCommuns(stops) {
  if (stops.length < 2) return [];
  const [premier, ...reste] = stops;
  return premier.avertissements.filter((message) =>
    reste.every((stop) => stop.avertissements.includes(message)),
  );
}

function rendreRisque(donnees) {
  const r = donnees.risque;

  const bloc = $("concentrations");
  vider(bloc);
  if (!r.concentrations.length) {
    bloc.appendChild(el("p", { class: "vide", text: "Aucune concentration à mesurer." }));
  } else {
    for (const constat of r.concentrations) bloc.appendChild(jauge(constat));
  }

  const corps = $("liquidites");
  vider(corps);
  if (!r.liquidites.length) {
    corps.appendChild(
      el("tr", {}, [el("td", { colspan: "5", class: "vide", text: "Aucune ligne à mesurer." })]),
    );
  }
  for (const constat of r.liquidites) {
    const rangee = el("tr");
    rangee.appendChild(el("th", { scope: "row", class: "valeur-titre", text: constat.ticker }));
    rangee.appendChild(el("td", { class: "num", text: FR.format(constat.quantite) }));
    rangee.appendChild(el("td", { class: "num", text: FR.format(constat.volume_moyen) }));
    rangee.appendChild(
      el("td", { class: "num", text: `${constat.seances_cotees}/${constat.seances_observees}` }),
    );
    rangee.appendChild(
      constat.mesurable
        ? el("td", { class: "num", text: constat.seances_pour_deboucler.toFixed(1) })
        : el("td", {}, [
            el("span", { class: "etiq etiq--attention", text: "non mesurable" }),
          ]),
    );
    corps.appendChild(rangee);
  }

  const stops = $("stops");
  vider(stops);
  if (r.stops.length) {
    // Les avertissements communs à tous les stops sont dits une fois. Répétés
    // sous chaque ligne, ils deviennent un décor que plus personne ne lit.
    const communs = avertissementsCommuns(r.stops);
    for (const message of communs) {
      stops.appendChild(el("p", { class: "note note--attention", text: message }));
    }
    const liste = el("div", { class: "cadre cadre--rembourre pile" });
    for (const stop of r.stops) {
      const texte = stop.niveau
        ? `${stop.ticker} — stop à ${xof(stop.niveau)} XOF, ${pourcent(stop.distance)} sous ${xof(stop.cours_reference)}`
        : `${stop.ticker} — stop non calculable : ${stop.motif_indisponible}`;
      liste.appendChild(el("p", { class: "ligne-stop", text: texte }));
      for (const message of stop.avertissements) {
        if (communs.includes(message)) continue;
        liste.appendChild(
          el("p", { class: "note note--attention", text: `${stop.ticker} — ${message}` }),
        );
      }
    }
    stops.appendChild(liste);
  }
  for (const avertissement of r.avertissements) {
    stops.appendChild(el("p", { class: "note", text: avertissement }));
  }
}

// ----------------------------------------------------------------- données

function rendreDonnees(donnees) {
  const corps = $("anomalies");
  vider(corps);
  if (!donnees.anomalies.length) {
    corps.appendChild(
      el("tr", {}, [
        el("td", { colspan: "5", class: "vide" }, [
          el("strong", { text: "Aucune anomalie ouverte" }),
          document.createTextNode("Rien n'attend d'investigation."),
        ]),
      ]),
    );
  }
  for (const anomalie of donnees.anomalies.slice(0, 60)) {
    const rangee = el("tr");
    rangee.appendChild(
      el("td", { class: "num", text: anomalie.detectee_le.replace("T", " ").slice(0, 16) }),
    );
    rangee.appendChild(
      el("td", {}, [
        el("span", {
          class: `etiq ${anomalie.gravite === "BLOQUANTE" ? "etiq--vente" : "etiq--attention"}`,
          text: anomalie.gravite,
        }),
      ]),
    );
    rangee.appendChild(el("td", { text: anomalie.source }));
    rangee.appendChild(el("td", { class: "valeur-titre", text: anomalie.ticker || "—" }));
    rangee.appendChild(el("td", { text: anomalie.message }));
    corps.appendChild(rangee);
  }

  const bloc = $("avertissements");
  vider(bloc);
  for (const message of donnees.avertissements) {
    bloc.appendChild(el("p", { class: "note note--attention", text: message }));
  }

  const liste = $("collectes");
  vider(liste);
  if (!donnees.collectes.length) {
    liste.appendChild(el("li", { class: "sourdine", text: "Aucune collecte enregistrée." }));
  }
  for (const entree of donnees.collectes) {
    liste.appendChild(el("li", { text: entree }));
  }
}

// ------------------------------------------------------------- navigation

/** Marque la section visible dans le rail. Recognition over recall. */
function suivreSections() {
  const liens = [...document.querySelectorAll(".rail a")];
  const sections = liens
    .map((lien) => document.querySelector(lien.getAttribute("href")))
    .filter(Boolean);

  const observateur = new IntersectionObserver(
    (entrees) => {
      for (const entree of entrees) {
        if (!entree.isIntersecting) continue;
        for (const lien of liens) {
          lien.setAttribute(
            "aria-current",
            String(lien.getAttribute("href") === `#${entree.target.id}`),
          );
        }
      }
    },
    { rootMargin: "-20% 0px -70% 0px" },
  );
  for (const section of sections) observateur.observe(section);
}

// ------------------------------------------------------------------ départ

async function charger() {
  try {
    const reponse = await fetch("/api/etat", { headers: { Accept: "application/json" } });
    const charge = await reponse.json();
    if (!reponse.ok) throw new Error(charge.erreur || `HTTP ${reponse.status}`);

    rendreFraicheur(charge.fraicheur);
    rendrePortefeuille(charge);
    rendreSignaux(charge);
    rendreRisque(charge);
    rendreDonnees(charge);
    $("erreur").hidden = true;
  } catch (exception) {
    // Une erreur ne laisse jamais l'écran sur des chiffres périmés sans le dire.
    $("erreur").hidden = false;
    $("erreur-detail").textContent = String(exception.message || exception);
  }
}

charger();
suivreSections();
