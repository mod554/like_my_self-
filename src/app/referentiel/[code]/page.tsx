import { prisma } from "@/lib/db";
import Link from "next/link";
import { notFound } from "next/navigation";

export default async function FilierePage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;

  const filiere = await prisma.filiere.findUnique({
    where: { code: code.toUpperCase() },
    include: {
      produits: {
        orderBy: [{ estDerive: "asc" }, { code: "asc" }],
        include: {
          _count: { select: { prixReleves: true } },
          derives: { select: { id: true } },
        },
      },
      actualites: {
        orderBy: { datePublication: "desc" },
        take: 5,
      },
    },
  });

  if (!filiere) notFound();

  const principaux = filiere.produits.filter((p) => !p.estDerive);
  const derives = filiere.produits.filter((p) => p.estDerive);

  return (
    <div className="flex-1 px-6 py-10 max-w-5xl mx-auto w-full">
      {/* Breadcrumb */}
      <div className="text-xs text-zinc-600 font-mono mb-6">
        <Link href="/referentiel" className="hover:text-zinc-400 transition-colors">Référentiel</Link>
        <span className="mx-2">›</span>
        <span className="text-zinc-400">{filiere.nom}</span>
      </div>

      {/* En-tête filière */}
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xs font-mono text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded">{filiere.code}</span>
        </div>
        <h1 className="text-2xl font-bold text-zinc-100 mb-3">{filiere.nom}</h1>
        <p className="text-sm text-zinc-400 leading-relaxed max-w-2xl">{filiere.description}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Produits principaux */}
        <div className="lg:col-span-2 space-y-6">
          <div>
            <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
              Produits principaux ({principaux.length})
            </h2>
            <div className="space-y-2">
              {principaux.map((p) => (
                <Link
                  key={p.code}
                  href={`/referentiel/${code.toLowerCase()}/${p.code.toLowerCase()}`}
                  className="flex items-center justify-between border border-zinc-800 rounded-lg px-4 py-3 hover:border-zinc-600 hover:bg-zinc-900 transition-colors group"
                >
                  <div>
                    <span className="text-xs font-mono text-zinc-500 mr-3">{p.code}</span>
                    <span className="text-sm text-zinc-200 group-hover:text-white transition-colors">{p.nom}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-zinc-600 font-mono">
                    <span>{p._count.prixReleves} prix</span>
                    <span>{p.derives.length} dérivés</span>
                    <span className="text-zinc-700">›</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>

          {/* Dérivés */}
          {derives.length > 0 && (
            <div>
              <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
                Dérivés & transformés ({derives.length})
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {derives.map((p) => (
                  <Link
                    key={p.code}
                    href={`/referentiel/${code.toLowerCase()}/${p.code.toLowerCase()}`}
                    className="flex items-center justify-between border border-zinc-800/60 rounded-lg px-4 py-2.5 hover:border-zinc-700 hover:bg-zinc-900/50 transition-colors group"
                  >
                    <div>
                      <span className="text-xs font-mono text-zinc-600 mr-2">{p.code}</span>
                      <span className="text-xs text-zinc-300 group-hover:text-white transition-colors">{p.nom}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-zinc-600 font-mono">
                      <span>{p._count.prixReleves}</span>
                      <span className="text-zinc-700">›</span>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Actualités */}
        <div>
          <h2 className="text-xs font-mono text-zinc-500 uppercase tracking-widest mb-3">
            Actualités récentes
          </h2>
          {filiere.actualites.length === 0 ? (
            <p className="text-xs text-zinc-600">Aucune actualité</p>
          ) : (
            <div className="space-y-3">
              {filiere.actualites.map((a) => (
                <div key={a.id} className="border border-zinc-800/60 rounded-lg p-3">
                  <div className="text-xs text-zinc-600 font-mono mb-1">
                    {new Date(a.datePublication).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}
                  </div>
                  <p className="text-xs text-zinc-300 leading-relaxed line-clamp-3">{a.titre}</p>
                  <div className="mt-1 text-xs text-zinc-600 truncate">{a.source}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
