import { prisma } from "@/lib/db";
import Link from "next/link";
import { notFound } from "next/navigation";

const FIABILITE_STYLE: Record<string, { label: string; cls: string }> = {
  OFFICIEL:  { label: "Officiel",  cls: "bg-green-900/40 text-green-400 border-green-800/50" },
  INDICATIF: { label: "Indicatif", cls: "bg-yellow-900/40 text-yellow-400 border-yellow-800/50" },
  ESTIME:    { label: "Estimé",    cls: "bg-orange-900/40 text-orange-400 border-orange-800/50" },
  EXEMPLE:   { label: "Exemple ⚠️", cls: "bg-zinc-800 text-zinc-500 border-zinc-700" },
};

function BadgeFiabilite({ niveau }: { niveau: string }) {
  const s = FIABILITE_STYLE[niveau] ?? { label: niveau, cls: "bg-zinc-800 text-zinc-400 border-zinc-700" };
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border font-mono ${s.cls}`}>
      {s.label}
    </span>
  );
}

function formatDate(d: Date) {
  return new Date(d).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

function formatValeur(v: unknown) {
  const n = Number(v);
  if (n >= 1000) return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 });
  if (n >= 1) return n.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 4 });
}

export default async function ProduitPage({
  params,
}: {
  params: Promise<{ code: string; produit: string }>;
}) {
  const { code, produit } = await params;

  const p = await prisma.produit.findUnique({
    where: { code: produit.toUpperCase() },
    include: {
      filiere: true,
      parent: { select: { code: true, nom: true } },
      derives: {
        orderBy: { code: "asc" },
        select: { id: true, code: true, nom: true, uniteRef: true, descriptionQualite: true },
      },
      prixReleves: {
        orderBy: { dateReleve: "desc" },
        take: 20,
        include: {
          marche: { select: { code: true, nom: true, type: true, devise: true } },
          source: { select: { code: true, nom: true } },
        },
      },
      structuresCout: {
        orderBy: [{ maillon: "asc" }, { poste: "asc" }],
        include: { source: { select: { code: true } } },
      },
    },
  });

  if (!p || p.filiere.code !== code.toUpperCase()) notFound();

  const saisonnalite = p.saisonnalite as Record<string, { debut: string; fin: string; note?: string }> | null;
  const chaine = p.chaineDValeur as { etapes?: string[]; note?: string } | null;

  return (
    <div className="flex-1 px-6 py-10 max-w-5xl mx-auto w-full">
      {/* Breadcrumb */}
      <div className="text-xs text-zinc-600 font-mono mb-6">
        <Link href="/referentiel" className="hover:text-zinc-400">Référentiel</Link>
        <span className="mx-2">›</span>
        <Link href={`/referentiel/${code.toLowerCase()}`} className="hover:text-zinc-400">{p.filiere.nom}</Link>
        <span className="mx-2">›</span>
        <span className="text-zinc-400">{p.code}</span>
      </div>

      {/* En-tête produit */}
      <div className="mb-8 pb-6 border-b border-zinc-800">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded">{p.code}</span>
              {p.estDerive && (
                <span className="text-xs text-zinc-600 font-mono">
                  dérivé de{" "}
                  <Link
                    href={`/referentiel/${code.toLowerCase()}/${p.parent?.code.toLowerCase()}`}
                    className="text-zinc-400 hover:text-zinc-200"
                  >
                    {p.parent?.code}
                  </Link>
                </span>
              )}
            </div>
            <h1 className="text-2xl font-bold text-zinc-100 mb-1">{p.nom}</h1>
            <p className="text-xs text-zinc-500 font-mono">Unité de référence : {p.uniteRef}</p>
          </div>
          <div className="text-right text-xs text-zinc-600 font-mono">
            <div>{p.prixReleves.length} relevés de prix</div>
            <div>{p.structuresCout.length} postes de coût</div>
            <div>{p.derives.length} dérivés</div>
          </div>
        </div>

        {p.descriptionQualite && (
          <div className="mt-4 text-sm text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-3">
            <span className="text-xs text-zinc-600 font-mono uppercase tracking-wider mr-2">Qualité ·</span>
            {p.descriptionQualite}
          </div>
        )}
      </div>

      <div className="space-y-10">
        {/* Saisonnalité */}
        {saisonnalite && Object.keys(saisonnalite).length > 0 && (
          <section>
            <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">Saisonnalité</h2>
            <div className="border border-zinc-800 rounded-lg overflow-hidden">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/50">
                    <th className="text-left px-4 py-2 text-zinc-500 font-normal">Zone</th>
                    <th className="text-left px-4 py-2 text-zinc-500 font-normal">Début</th>
                    <th className="text-left px-4 py-2 text-zinc-500 font-normal">Fin</th>
                    <th className="text-left px-4 py-2 text-zinc-500 font-normal">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(saisonnalite).map(([zone, s]) => (
                    <tr key={zone} className="border-b border-zinc-800/50 last:border-0">
                      <td className="px-4 py-2 text-zinc-300 font-bold">{zone}</td>
                      <td className="px-4 py-2 text-zinc-400">{s.debut}</td>
                      <td className="px-4 py-2 text-zinc-400">{s.fin}</td>
                      <td className="px-4 py-2 text-zinc-600">{s.note ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Chaîne de valeur */}
        {chaine?.etapes && chaine.etapes.length > 0 && (
          <section>
            <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">Chaîne de valeur</h2>
            <div className="flex flex-col gap-1">
              {chaine.etapes.map((etape, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="flex flex-col items-center">
                    <div className="w-5 h-5 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-xs text-zinc-500 font-mono flex-shrink-0">
                      {i + 1}
                    </div>
                    {i < chaine.etapes!.length - 1 && <div className="w-px h-3 bg-zinc-800 mt-0.5" />}
                  </div>
                  <span className="text-sm text-zinc-300">{etape}</span>
                </div>
              ))}
            </div>
            {chaine.note && (
              <p className="mt-3 text-xs text-zinc-600 italic">{chaine.note}</p>
            )}
          </section>
        )}

        {/* Cadre réglementaire & acteurs */}
        {(p.cadreReglementaire || p.acteurs) && (
          <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {p.cadreReglementaire && (
              <div>
                <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-2">Cadre réglementaire</h2>
                <p className="text-xs text-zinc-400 leading-relaxed">{p.cadreReglementaire}</p>
              </div>
            )}
            {p.acteurs && (
              <div>
                <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-2">Acteurs clés</h2>
                <p className="text-xs text-zinc-400 leading-relaxed">{p.acteurs}</p>
              </div>
            )}
          </section>
        )}

        {/* Prix relevés */}
        <section>
          <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
            Derniers relevés de prix ({p.prixReleves.length})
          </h2>
          {p.prixReleves.length === 0 ? (
            <p className="text-xs text-zinc-600">Aucun relevé de prix</p>
          ) : (
            <div className="border border-zinc-800 rounded-lg overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/50">
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Date</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Marché</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Type</th>
                    <th className="text-right px-3 py-2 text-zinc-500 font-normal">Valeur</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Devise</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Unité</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Fiabilité</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {p.prixReleves.map((pr) => (
                    <tr key={pr.id} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-900/30">
                      <td className="px-3 py-2 text-zinc-400">{formatDate(pr.dateReleve)}</td>
                      <td className="px-3 py-2 text-zinc-300" title={pr.marche.nom}>{pr.marche.code}</td>
                      <td className="px-3 py-2 text-zinc-500">{pr.typePrix}{pr.echeance ? ` ${pr.echeance}` : ""}</td>
                      <td className="px-3 py-2 text-right text-zinc-100 font-bold">{formatValeur(pr.valeur)}</td>
                      <td className="px-3 py-2 text-zinc-400">{pr.devise}</td>
                      <td className="px-3 py-2 text-zinc-500">{pr.unite}</td>
                      <td className="px-3 py-2"><BadgeFiabilite niveau={pr.fiabilite} /></td>
                      <td className="px-3 py-2 text-zinc-600" title={pr.source.nom}>{pr.source.code}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Structures de coûts */}
        {p.structuresCout.length > 0 && (
          <section>
            <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
              Structure de coûts ({p.structuresCout.length} postes)
            </h2>
            <div className="border border-zinc-800 rounded-lg overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/50">
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Maillon</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Poste</th>
                    <th className="text-right px-3 py-2 text-zinc-500 font-normal">Montant</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Devise</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Unité</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Période</th>
                    <th className="text-left px-3 py-2 text-zinc-500 font-normal">Fiabilité</th>
                  </tr>
                </thead>
                <tbody>
                  {p.structuresCout.map((c) => (
                    <tr key={c.id} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-900/30">
                      <td className="px-3 py-2 text-zinc-300 font-bold">{c.maillon}</td>
                      <td className="px-3 py-2 text-zinc-400">{c.poste.replace(/_/g, " ")}</td>
                      <td className="px-3 py-2 text-right text-zinc-100">{formatValeur(c.montant)}</td>
                      <td className="px-3 py-2 text-zinc-400">{c.devise}</td>
                      <td className="px-3 py-2 text-zinc-500">{c.unite.replace(/_/g, " ")}</td>
                      <td className="px-3 py-2 text-zinc-600">{c.periode ?? "—"}</td>
                      <td className="px-3 py-2"><BadgeFiabilite niveau={c.fiabilite} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Dérivés */}
        {p.derives.length > 0 && (
          <section>
            <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
              Produits dérivés ({p.derives.length})
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {p.derives.map((d) => (
                <Link
                  key={d.code}
                  href={`/referentiel/${code.toLowerCase()}/${d.code.toLowerCase()}`}
                  className="flex items-start justify-between border border-zinc-800/60 rounded-lg px-4 py-3 hover:border-zinc-600 hover:bg-zinc-900/50 transition-colors group"
                >
                  <div>
                    <div className="text-xs font-mono text-zinc-500 mb-0.5">{d.code}</div>
                    <div className="text-sm text-zinc-300 group-hover:text-white transition-colors">{d.nom}</div>
                    {d.descriptionQualite && (
                      <div className="text-xs text-zinc-600 mt-1 line-clamp-1">{d.descriptionQualite}</div>
                    )}
                  </div>
                  <span className="text-zinc-600 text-xs mt-0.5 flex-shrink-0 ml-2">›</span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
