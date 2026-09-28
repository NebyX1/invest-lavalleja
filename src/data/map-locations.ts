export interface MapLocation {
  id: string;
  name: string;
  /** SVG viewBox coordinates copied from the center of each source circle. */
  x: number;
  y: number;
  zoneId: string;
}

export const mapViewBox = { width: 713, height: 779 } as const;

export const mapLocations = [
  { id: 'batlle-y-ordonez', name: 'José Batlle y Ordóñez', x: 244, y: 122, zoneId: 'batlle-zapican' },
  { id: 'jose-pedro-varela', name: 'José Pedro Varela', x: 514, y: 122, zoneId: 'jose-pedro-varela' },
  { id: 'piraraja', name: 'Pirarajá', x: 417, y: 261, zoneId: 'mariscala-piraraja' },
  { id: 'mariscala', name: 'Mariscala', x: 405, y: 421, zoneId: 'mariscala-piraraja' },
  { id: 'minas', name: 'Minas', x: 203, y: 595, zoneId: 'minas' },
  { id: 'solis-de-mataojo', name: 'Solís de Mataojo', x: 100, y: 721, zoneId: 'solis-aguas-blancas' },
] as const satisfies readonly MapLocation[];
