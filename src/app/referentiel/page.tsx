import { prisma } from "@/lib/db";
import Link from "next/link";

const FILIERE_META: Record<string, { color: string; badge: string; badgeColor: string; ticker: string }> = {
  MAIS:  { color: "yellow", badge: "Cotée CME/CBOT", badgeColor: "green",  ticker: "ZC" },
  CAJOU: { color: "amber",  badge: "Non cotée",      badgeColor: "amber",  ticker: "RCN · W320" },
  COLA:  { color: "orange", badge: "Régional AOF",   badgeColor: "orange", ticker: "Régional" },
};

export default async function ReferentielPage() {
  const filieres = await prisma.filiere.findMany({
    orderBy: { code: "asc" },
    include: {
      produits: { select: { id: true, estDerive: true } },
      _count: { select: { actualites: true } },
    },
  });

  return (
    <div className="flex-1 px-6 py-10 max-w-5xl mx-auto w-full">
      <div className="mb-8">
        <p className="text-xs text-zinc-500 font-mono tracking-widest uppercase mb-1">Référentiel</p>
        <h1 className="text-2xl font-bold text-zinc-100">Filières agricoles</h1>
        <p className="text-sm text-zinc-400 mt-1">
          3 filières couvertes · {filieres.reduce((a, f) => a + f.produits.length, 0)} produits & dérivés
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {filieres.map((f) => {
          const meta = FILIERE_META[f.code] ?? { color: "zinc", badge: "", badgeColor: "zinc", ticker: f.code };
          const principaux = f.produits.filter((p) => !p.estDerive).length;
          const derives = f.produits.filter((p) => p.estDerive).length;

          return (
            <Link
              key={f.code}
              href={`/referentiel/${f.code.toLowerCase()}`}
              className={`border border-zinc-800 rounded-lg p-5 hover:border-${meta.color}-500/50 hover:bg-zinc-900 transition-colors group block`}
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">{meta.ticker}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full bg-${meta.badgeColor}-900/40 text-${meta.badgeColor}-400 border border-${meta.badgeColor}-800/50`}>
                  {meta.badge}
                </span>
              </div>
              <h2 className={`text-lg font-semibold text-zinc-100 group-hover:text-${meta.color}-400 transition-colors mb-2`}>
                {f.nom}
              </h2>
              <p className="text-xs text-zinc-500 leading-relaxed line-clamp-3">
                {f.description}
              </p>
              <div className="mt-4 pt-3 border-t border-zinc-800 flex gap-4 text-xs text-zinc-600 font-mono">
                <span>{principaux} produit{principaux > 1 ? "s" : ""}</span>
                <span>{derives} dérivé{derives > 1 ? "s" : ""}</span>
                <span>{f._count.actualites} actu</span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
