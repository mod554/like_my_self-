// Registre des connecteurs — point d'entrée unique
// Chaque connecteur correspond à une Source en base de données

import { WorldBankConnector } from "./worldbank";
// FaoFpmaConnector retiré du registre : FAOSTAT exige une authentification
// (HTTP 401) depuis 2026 — la source FAO_FPMA est désormais alimentée par le
// runner GitHub via l'API GIEWS FPMA (fpma.fao.org) → POST /api/import/fpma.
import { UsdaFasConnector } from "./usda-fas";
import { ConseilAnacardeCiConnector } from "./conseil-anacarde";
import { ResimaoConnector } from "./resimao";
import { RssNewsConnector } from "./rss-news";
// GdeltNewsConnector retiré du registre : GDELT rate-limite les IP partagées
// Vercel — la collecte GDELT se fait désormais côté runner GitHub (IP propre)
// via /api/import/news. Le fichier reste disponible.
import { ComtradeConnector } from "./comtrade";
// IndexMundiConnector retiré du registre : redondant (doublon du prix maïs
// World Bank, fiabilité INDICATIF) et indexmundi.com bloque les IP Vercel,
// ce qui gelait la route /api/connectors. Le fichier reste disponible.
import { TauxChangeLiveConnector } from "./taux-change";
import { IceSoftsConnector } from "./ice-softs";
import { AgmarknetConnector } from "./agmarknet";
import type { Connector } from "./base";

export const CONNECTEURS: Connector[] = [
  new TauxChangeLiveConnector(),
  new IceSoftsConnector(),
  new AgmarknetConnector(),
  new WorldBankConnector(),
  new UsdaFasConnector(),
  new ConseilAnacardeCiConnector(),
  new ResimaoConnector(),
  new RssNewsConnector(),
  new ComtradeConnector(),
];

export { type Connector, type ConnectorResult } from "./base";

export function getConnecteur(code: string): Connector | undefined {
  return CONNECTEURS.find((c) => c.code === code);
}
