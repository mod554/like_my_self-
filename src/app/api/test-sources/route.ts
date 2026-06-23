export const dynamic = "force-dynamic";
export const maxDuration = 55;

// Quick probe of each external data source — returns HTTP status and response preview
// GET /api/test-sources

const SOURCES_TO_TEST = [
  {
    code: "WORLD_BANK",
    url: "https://api.worldbank.org/v2/country/all/indicator/PMAIZMMT?format=json&mrv=3&per_page=3",
    description: "WorldBank Maize commodity price (PMAIZMMT)",
  },
  {
    code: "IMF_PMAIZE",
    url: "https://www.imf.org/external/datamapper/api/v1/PMAIZE",
    description: "IMF DataMapper — PMAIZE corn price",
  },
  {
    code: "FAOSTAT_MAIS",
    url: "https://fenixservices.fao.org/faostat/api/v1/en/data/PP?area=107&item=56&element=5532&year=2022,2023&type=datasets&output_type=json",
    description: "FAOSTAT Producer Price — Maize Côte d'Ivoire",
  },
  {
    code: "WFP_CI",
    url: "https://api.vam.wfp.org/v2/Markets/FoodPrices?CountryCode=CI&page=1&pageSize=5",
    description: "WFP VAM API — Côte d'Ivoire food prices",
  },
  {
    code: "WFP_BF",
    url: "https://api.vam.wfp.org/v2/Markets/FoodPrices?CountryCode=BF&page=1&pageSize=5",
    description: "WFP VAM API — Burkina Faso food prices",
  },
  {
    code: "INDEXMUNDI_CORN",
    url: "https://www.indexmundi.com/commodities/?commodity=corn&months=12",
    description: "IndexMundi corn price page",
  },
  {
    code: "OPENEXCHANGE_USD",
    url: "https://open.er-api.com/v6/latest/USD",
    description: "ExchangeRate-API USD rates",
  },
  {
    code: "FRANKFURTER",
    url: "https://api.frankfurter.app/latest?from=USD&to=EUR,GHS",
    description: "Frankfurter.app EUR/GHS rates",
  },
];

interface TestResult {
  code: string;
  url: string;
  description: string;
  status: number | null;
  ok: boolean;
  durationMs: number;
  preview: string;
  error?: string;
}

export async function GET() {
  const results: TestResult[] = await Promise.all(
    SOURCES_TO_TEST.map(async (src) => {
      const t0 = Date.now();
      try {
        const res = await fetch(src.url, {
          signal: AbortSignal.timeout(15_000),
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/136.0.0.0",
            "Accept": "application/json, text/html, */*",
          },
        });
        const durationMs = Date.now() - t0;
        let preview = "";
        try {
          const text = await res.text();
          preview = text.slice(0, 300).replace(/\s+/g, " ");
        } catch {
          preview = "(could not read body)";
        }
        return { ...src, status: res.status, ok: res.ok, durationMs, preview };
      } catch (err) {
        return {
          ...src,
          status: null,
          ok: false,
          durationMs: Date.now() - t0,
          preview: "",
          error: err instanceof Error ? err.message : String(err),
        };
      }
    })
  );

  const allOk = results.every((r) => r.ok);
  return Response.json({ ts: new Date().toISOString(), allOk, results }, { status: allOk ? 200 : 207 });
}
