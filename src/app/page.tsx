import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center px-6 py-16">
      <div className="w-full max-w-4xl">
        <div className="mb-12">
          <div className="text-xs text-zinc-500 mb-2 tracking-widest uppercase font-mono">
            Terminal Agri v0.1 · Veille & Investissement
          </div>
          <h1 className="text-3xl font-bold text-zinc-100 tracking-tight">
            Filières agricoles
          </h1>
          <p className="mt-2 text-zinc-400 text-sm">
            Sélectionnez une filière pour accéder aux prix, coûts et analyses d&apos;investissement.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link href="/referentiel/mais" className="border border-zinc-800 rounded-lg p-5 hover:border-yellow-500/50 hover:bg-zinc-900 transition-colors group block">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">ZC · CME/CBOT</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/40 text-green-400 border border-green-800/50">Cotée</span>
            </div>
            <h2 className="text-lg font-semibold text-zinc-100 group-hover:text-yellow-400 transition-colors mb-1">Maïs</h2>
            <p className="text-xs text-zinc-500 leading-relaxed">
              Commodity cotée — futures CME/CBOT (ZC), données spot mondiales, bilans USDA.
            </p>
            <div className="mt-4 text-xs text-zinc-600">
              Sources : World Bank · USDA WASDE · FAO FPMA
            </div>
          </Link>

          <Link href="/referentiel/cajou" className="border border-zinc-800 rounded-lg p-5 hover:border-amber-500/50 hover:bg-zinc-900 transition-colors group block">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">RCN · W320</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900/40 text-amber-400 border border-amber-800/50">Non coté</span>
            </div>
            <h2 className="text-lg font-semibold text-zinc-100 group-hover:text-amber-400 transition-colors mb-1">Cajou · Anacarde</h2>
            <p className="text-xs text-zinc-500 leading-relaxed">
              Marché actif non coté — prix indicatifs RCN &amp; amandes (W320/W240), CI → Vietnam/Inde.
            </p>
            <div className="mt-4 text-xs text-zinc-600">
              Sources : Conseil Anacarde CI · VINACAS · Manuel
            </div>
          </Link>

          <Link href="/referentiel/cola" className="border border-zinc-800 rounded-lg p-5 hover:border-orange-500/50 hover:bg-zinc-900 transition-colors group block">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Régional · AOF</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-orange-900/40 text-orange-400 border border-orange-800/50">Régional</span>
            </div>
            <h2 className="text-lg font-semibold text-zinc-100 group-hover:text-orange-400 transition-colors mb-1">Noix de cola</h2>
            <p className="text-xs text-zinc-500 leading-relaxed">
              Marché régional Afrique de l&apos;Ouest — pas de cotation mondiale, prix observatoires locaux.
            </p>
            <div className="mt-4 text-xs text-zinc-600">
              Sources : RESIMAO · Observatoires nationaux · Manuel
            </div>
          </Link>
        </div>

        <div className="mt-12 pt-6 border-t border-zinc-800 flex items-center justify-between text-xs text-zinc-600 font-mono">
          <span>Phase 0 ✓ · Phase 1 ✓ · Phase 2–7 en cours</span>
          <span>USD · EUR · XOF</span>
        </div>
      </div>
    </div>
  );
}
