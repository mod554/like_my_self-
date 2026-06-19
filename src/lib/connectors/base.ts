// Interface commune pour tous les connecteurs de données

export interface ConnectorResult {
  source: string; // code Source
  nbImportes: number;
  nbErreurs: number;
  erreurs: string[];
  debut: Date;
  fin: Date;
}

export interface Connector {
  code: string; // doit correspondre à Source.code en BD
  nom: string;
  frequenceCron: string; // expression cron
  run(): Promise<ConnectorResult>;
}

export function creerResultatVide(source: string, debut: Date): Omit<ConnectorResult, "fin"> {
  return {
    source,
    nbImportes: 0,
    nbErreurs: 0,
    erreurs: [],
    debut,
  };
}
