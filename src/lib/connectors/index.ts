// Registre des connecteurs — point d'entrée unique
// Chaque connecteur correspond à une Source en base de données

import { WorldBankConnector } from "./worldbank";
import { FaoFpmaConnector } from "./fao-fpma";
import { UsdaFasConnector } from "./usda-fas";
import { ConseilAnacardeCiConnector } from "./conseil-anacarde";
import { ResimaoConnector } from "./resimao";
import { RssNewsConnector } from "./rss-news";
import { GdeltNewsConnector } from "./gdelt-news";
import { ComtradeConnector } from "./comtrade";
// IndexMundiConnector retiré du registre : redondant (doublon du prix maïs
// World Bank, fiabilité INDICATIF) et indexmundi.com bloque les IP Vercel,
// ce qui gelait la route /api/connectors. Le fichier reste disponible.
import { TauxChangeLiveConnector } from "./taux-change";
import type { Connector } from "./base";

export const CONNECTEURS: Connector[] = [
  new TauxChangeLiveConnector(),
  new WorldBankConnector(),
  new FaoFpmaConnector(),
  new UsdaFasConnector(),
  new ConseilAnacardeCiConnector(),
  new ResimaoConnector(),
  new RssNewsConnector(),
  new GdeltNewsConnector(),
  new ComtradeConnector(),
];

export { type Connector, type ConnectorResult } from "./base";

export function getConnecteur(code: string): Connector | undefined {
  return CONNECTEURS.find((c) => c.code === code);
}
