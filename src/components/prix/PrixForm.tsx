"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Produit {
  id: string; code: string; nom: string;
  filiere: { code: string; nom: string };
}
interface Marche {
  id: string; code: string; nom: string; devise: string;
  zone: { nom: string };
}
interface Source {
  id: string; code: string; nom: string;
}

interface Props {
  produits: Produit[];
  marches: Marche[];
  sources: Source[];
}

const inputStyle = {
  width: "100%", padding: "8px 10px",
  background: "var(--bg-elevated)", border: "1px solid var(--border-default)",
  borderRadius: "6px", color: "var(--text-primary)", fontSize: 13,
  fontFamily: "var(--font-ubuntu, sans-serif)", outline: "none",
  transition: "border-color 150ms ease",
};

const labelStyle = {
  fontSize: 10, fontFamily: "monospace", letterSpacing: "0.08em",
  color: "var(--text-muted)", textTransform: "uppercase" as const,
  display: "block", marginBottom: "4px",
};

export default function PrixForm({ produits, marches, sources }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [form, setForm] = useState({
    produitId: "",
    marcheId: "",
    sourceId: sources[0]?.id ?? "",
    typePrix: "SPOT",
    valeur: "",
    devise: "XOF",
    unite: "tonne",
    dateReleve: new Date().toISOString().split("T")[0],
    fiabilite: "INDICATIF",
    notes: "",
  });

  function set(k: string, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.produitId || !form.marcheId || !form.valeur) {
      setMsg({ type: "err", text: "Produit, marché et valeur sont requis" });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await fetch("/api/prix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, valeur: parseFloat(form.valeur) }),
      });
      if (!res.ok) throw new Error(await res.text());
      setMsg({ type: "ok", text: "Relevé enregistré ✓" });
      setForm((f) => ({ ...f, valeur: "", notes: "" }));
      router.refresh();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Erreur" });
    } finally {
      setLoading(false);
    }
  }

  const DEVISES = ["XOF", "USD", "EUR", "GHS", "NGN"];
  const UNITES = ["tonne", "kg", "sac_50kg", "litre", "unité"];
  const TYPES = ["SPOT", "BORD_CHAMP", "FOB", "CIF", "GROS", "DETAIL", "FUTURE"];
  const FIABILITES = ["OFFICIEL", "INDICATIF", "ESTIME", "EXEMPLE"];

  return (
    <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>

      {/* Produit */}
      <div>
        <label style={labelStyle}>Produit *</label>
        <select style={inputStyle} value={form.produitId} onChange={(e) => set("produitId", e.target.value)} required>
          <option value="">Sélectionner…</option>
          {produits.map((p) => (
            <option key={p.id} value={p.id}>{p.filiere.code} · {p.code} — {p.nom}</option>
          ))}
        </select>
      </div>

      {/* Marché */}
      <div>
        <label style={labelStyle}>Marché *</label>
        <select
          style={inputStyle}
          value={form.marcheId}
          onChange={(e) => {
            const m = marches.find((m) => m.id === e.target.value);
            set("marcheId", e.target.value);
            if (m) set("devise", m.devise);
          }}
          required
        >
          <option value="">Sélectionner…</option>
          {marches.map((m) => (
            <option key={m.id} value={m.id}>{m.code} — {m.nom} ({m.devise})</option>
          ))}
        </select>
      </div>

      {/* Valeur + Devise */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 90px", gap: "8px" }}>
        <div>
          <label style={labelStyle}>Valeur *</label>
          <input
            type="number" step="0.01" min="0"
            style={inputStyle} value={form.valeur}
            onChange={(e) => set("valeur", e.target.value)} required
            placeholder="ex: 250000"
          />
        </div>
        <div>
          <label style={labelStyle}>Devise</label>
          <select style={inputStyle} value={form.devise} onChange={(e) => set("devise", e.target.value)}>
            {DEVISES.map((d) => <option key={d}>{d}</option>)}
          </select>
        </div>
      </div>

      {/* Unité + Type */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
        <div>
          <label style={labelStyle}>Unité</label>
          <select style={inputStyle} value={form.unite} onChange={(e) => set("unite", e.target.value)}>
            {UNITES.map((u) => <option key={u}>{u}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Type de prix</label>
          <select style={inputStyle} value={form.typePrix} onChange={(e) => set("typePrix", e.target.value)}>
            {TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {/* Date + Fiabilité */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
        <div>
          <label style={labelStyle}>Date relevé</label>
          <input type="date" style={inputStyle} value={form.dateReleve} onChange={(e) => set("dateReleve", e.target.value)} />
        </div>
        <div>
          <label style={labelStyle}>Fiabilité</label>
          <select style={inputStyle} value={form.fiabilite} onChange={(e) => set("fiabilite", e.target.value)}>
            {FIABILITES.map((f) => <option key={f}>{f}</option>)}
          </select>
        </div>
      </div>

      {/* Source */}
      <div>
        <label style={labelStyle}>Source</label>
        <select style={inputStyle} value={form.sourceId} onChange={(e) => set("sourceId", e.target.value)}>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.nom}</option>)}
        </select>
      </div>

      {/* Notes */}
      <div>
        <label style={labelStyle}>Notes (optionnel)</label>
        <input
          type="text" style={inputStyle} value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
          placeholder="Source, contexte, provenance…"
        />
      </div>

      {/* Message */}
      {msg && (
        <div style={{
          padding: "8px 12px", borderRadius: "6px", fontSize: 12, fontFamily: "monospace",
          background: msg.type === "ok" ? "rgba(74,155,111,0.12)" : "rgba(224,82,82,0.12)",
          color: msg.type === "ok" ? "#4A9B6F" : "#E05252",
          border: `1px solid ${msg.type === "ok" ? "rgba(74,155,111,0.25)" : "rgba(224,82,82,0.25)"}`,
        }}>
          {msg.text}
        </div>
      )}

      <button
        type="submit" disabled={loading}
        style={{
          padding: "10px 16px", borderRadius: "8px", fontWeight: 700, fontSize: 13,
          cursor: loading ? "not-allowed" : "pointer",
          background: loading ? "var(--bg-elevated)" : "var(--gradient-lime)",
          color: loading ? "var(--text-muted)" : "var(--text-inverse)",
          border: "none", boxShadow: loading ? "none" : "0 2px 12px rgba(146,186,89,0.3)",
          transition: "all 150ms ease",
        }}
      >
        {loading ? "Enregistrement…" : "Enregistrer le relevé"}
      </button>
    </form>
  );
}
