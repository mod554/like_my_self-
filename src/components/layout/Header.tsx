import Link from "next/link";

export default function Header() {
  return (
    <header className="border-b border-zinc-800 bg-zinc-950 px-6 py-3 flex items-center justify-between">
      <Link href="/" className="flex items-center gap-3 group">
        <span className="text-xs text-zinc-500 font-mono tracking-widest uppercase group-hover:text-zinc-300 transition-colors">
          Terminal Agri
        </span>
        <span className="text-zinc-700 text-xs">v0.1</span>
      </Link>

      <nav className="flex items-center gap-6 text-sm font-mono">
        <Link
          href="/referentiel"
          className="text-zinc-400 hover:text-zinc-100 transition-colors text-xs tracking-wide"
        >
          Référentiel
        </Link>
        <Link
          href="/marche"
          className="text-zinc-600 hover:text-zinc-400 transition-colors text-xs tracking-wide cursor-not-allowed"
          title="Phase 4"
        >
          Marché
        </Link>
        <Link
          href="/analyse"
          className="text-zinc-600 hover:text-zinc-400 transition-colors text-xs tracking-wide cursor-not-allowed"
          title="Phase 5"
        >
          Analyse
        </Link>
      </nav>

      <div className="text-xs text-zinc-600 font-mono">
        USD · EUR · XOF
      </div>
    </header>
  );
}
