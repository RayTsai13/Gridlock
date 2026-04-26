import type { Feature, FeatureCollection, LineString, Point } from 'geojson';

export type TransitStop = {
  id: string;
  name: string;
  coordinates: [longitude: number, latitude: number];
};

export type TransitLine = {
  id: string;
  name: string;
  color: string;
  /** Perpendicular pixel offset for parallel-line rendering. */
  offset: number;
  /** Ordered stop IDs that define the route path. */
  stopIds: string[];
};

export type ExpansionMode = {
  id: string;
  name: string;
  description: string;
  stops: TransitStop[];
  lines: TransitLine[];
};

// ---------------------------------------------------------------------------
// Stops
// ---------------------------------------------------------------------------

/** Existing Link 1 Line stations, ordered north → south. */
export const LINE_1_STOPS: TransitStop[] = [
  { id: 'northgate',      name: 'Northgate',                 coordinates: [-122.3272, 47.6992] },
  { id: 'roosevelt',      name: 'Roosevelt',                 coordinates: [-122.3167, 47.6768] },
  { id: 'u-district',     name: 'U District',                coordinates: [-122.3155, 47.6614] },
  { id: 'uw',             name: 'UW',                        coordinates: [-122.3037, 47.6498] },
  { id: 'capitol-hill',   name: 'Capitol Hill',              coordinates: [-122.3209, 47.6190] },
  { id: 'westlake',       name: 'Westlake',                  coordinates: [-122.3371, 47.6113] },
  { id: 'symphony',       name: 'Symphony',                  coordinates: [-122.3361, 47.6074] },
  { id: 'pioneer-square', name: 'Pioneer Square',            coordinates: [-122.3314, 47.6021] },
  { id: 'id-chinatown',   name: 'Intl District / Chinatown', coordinates: [-122.3278, 47.5983] },
  { id: 'stadium',        name: 'Stadium',                   coordinates: [-122.3275, 47.5911] },
  { id: 'sodo',           name: 'SODO',                      coordinates: [-122.3271, 47.5807] },
  { id: 'beacon-hill',    name: 'Beacon Hill',               coordinates: [-122.3118, 47.5684] },
  { id: 'mount-baker',    name: 'Mount Baker',               coordinates: [-122.2975, 47.5764] },
  { id: 'columbia-city',  name: 'Columbia City',             coordinates: [-122.2922, 47.5599] },
  { id: 'othello',        name: 'Othello',                   coordinates: [-122.2812, 47.5383] },
  { id: 'rainier-beach',  name: 'Rainier Beach',             coordinates: [-122.2688, 47.5222] },
];

/** 2 Line — branches east from ID/Chinatown, across Lake Washington. */
export const LINE_2_STOPS: TransitStop[] = [
  { id: 'judkins-park',      name: 'Judkins Park',      coordinates: [-122.3043, 47.5907] },
  { id: 'mercer-island',     name: 'Mercer Island',     coordinates: [-122.2350, 47.5871] },
  { id: 'bellevue-downtown', name: 'Bellevue Downtown', coordinates: [-122.1960, 47.6155] },
];

/** Ballard extension — unique stations not on the 1 or 2 Line. */
export const BALLARD_STOPS: TransitStop[] = [
  { id: 'denny',            name: 'Denny',            coordinates: [-122.3405, 47.6188] },
  { id: 'south-lake-union', name: 'South Lake Union',  coordinates: [-122.3377, 47.6258] },
  { id: 'seattle-center',   name: 'Seattle Center',    coordinates: [-122.3520, 47.6243] },
  { id: 'smith-cove',       name: 'Smith Cove',        coordinates: [-122.3635, 47.6378] },
  { id: 'interbay',         name: 'Interbay',          coordinates: [-122.3765, 47.6478] },
  { id: 'ballard',          name: 'Ballard',           coordinates: [-122.3765, 47.6677] },
];

// ---------------------------------------------------------------------------
// Lines
// ---------------------------------------------------------------------------

export const LINK_1_LINE: TransitLine = {
  id: 'link-1-line',
  name: '1 Line',
  color: '#0063c6',
  offset: -4,
  stopIds: [
    'northgate', 'roosevelt', 'u-district', 'uw', 'capitol-hill',
    'westlake', 'symphony', 'pioneer-square', 'id-chinatown',
    'stadium', 'sodo', 'beacon-hill', 'mount-baker',
    'columbia-city', 'othello', 'rainier-beach',
  ],
};

/**
 * 2 Line — runs from Northgate through the shared downtown tunnel,
 * then branches east from ID/Chinatown across Lake Washington.
 * Overlaps with the 1 Line from Northgate to ID/Chinatown.
 */
export const LINK_2_LINE: TransitLine = {
  id: 'link-2-line',
  name: '2 Line',
  color: '#d63e2a',
  offset: 4,
  stopIds: [
    'northgate', 'roosevelt', 'u-district', 'uw', 'capitol-hill',
    'westlake', 'symphony', 'pioneer-square', 'id-chinatown',
    'judkins-park', 'mercer-island', 'bellevue-downtown',
  ],
};

/**
 * Ballard Line — runs from Ballard south through downtown to SODO.
 * Shares Westlake → SODO with the 1 Line.
 * All three lines overlap from Westlake → ID/Chinatown.
 */
export const BALLARD_LINE: TransitLine = {
  id: 'ballard-line',
  name: 'Ballard Line',
  color: '#00875a',
  offset: 0,
  stopIds: [
    'ballard', 'interbay', 'smith-cove', 'seattle-center',
    'south-lake-union', 'denny', 'westlake', 'symphony',
    'pioneer-square', 'id-chinatown', 'stadium', 'sodo',
  ],
};

// ---------------------------------------------------------------------------
// Expansion modes (cumulative)
// ---------------------------------------------------------------------------

export const EXPANSION_MODES: ExpansionMode[] = [
  {
    id: 'line-1',
    name: '1 Line Only',
    description: "Today's Link 1 Line — Northgate to Rainier Beach",
    stops: [...LINE_1_STOPS],
    lines: [LINK_1_LINE],
  },
  {
    id: 'line-1-2',
    name: '+ 2 Line',
    description: 'Adds the 2 Line east branch — ID/Chinatown to Judkins Park and beyond',
    stops: [...LINE_1_STOPS, ...LINE_2_STOPS],
    lines: [LINK_1_LINE, LINK_2_LINE],
  },
  {
    id: 'line-1-2-ballard',
    name: '+ Ballard Extension',
    description: 'Adds the Ballard line — Westlake northwest to Ballard',
    stops: [...LINE_1_STOPS, ...LINE_2_STOPS, ...BALLARD_STOPS],
    lines: [LINK_1_LINE, LINK_2_LINE, BALLARD_LINE],
  },
];

// ---------------------------------------------------------------------------
// GeoJSON helpers
// ---------------------------------------------------------------------------

export function stopsToGeoJSON(stops: TransitStop[]): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: stops.map((stop) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: stop.coordinates },
      properties: { id: stop.id, name: stop.name },
    })),
  };
}

export function linesToGeoJSON(
  lines: TransitLine[],
  stops: TransitStop[],
): FeatureCollection<LineString> {
  const stopMap = new Map(stops.map((s) => [s.id, s]));

  const features: Feature<LineString>[] = lines.map((line) => {
    const coordinates = line.stopIds
      .map((sid) => stopMap.get(sid)?.coordinates)
      .filter((c): c is [number, number] => c !== undefined);

    return {
      type: 'Feature' as const,
      geometry: { type: 'LineString' as const, coordinates },
      properties: { id: line.id, name: line.name, color: line.color, offset: line.offset },
    };
  });

  return { type: 'FeatureCollection', features };
}

// ---------------------------------------------------------------------------
// Deploy steps — progressive unlock sequence
// ---------------------------------------------------------------------------

export type DeployStep = {
  id: string;
  /** The stop ID the user must click to deploy this line. null = auto-deployed on load. */
  triggerStopId: string | null;
  /** Custom coordinates for the deploy node (overrides triggerStopId position). */
  triggerCoordinates?: [longitude: number, latitude: number];
  line: TransitLine;
  newStops: TransitStop[];
  /** Label shown on the deploy tooltip. */
  label?: string;
};

export const DEPLOY_STEPS: DeployStep[] = [
  { id: 'line-1', triggerStopId: null, line: LINK_1_LINE, newStops: LINE_1_STOPS },
  { id: 'line-2', triggerStopId: 'id-chinatown', triggerCoordinates: [-122.285, 47.589], line: LINK_2_LINE, newStops: LINE_2_STOPS, label: 'Deploy 2 Line' },
  { id: 'ballard', triggerStopId: 'westlake', line: BALLARD_LINE, newStops: BALLARD_STOPS, label: 'Deploy Ballard Extension' },
];
