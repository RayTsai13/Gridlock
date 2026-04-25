import { useEffect, useState } from 'react';
import { Layer, Map, NavigationControl, Source } from 'react-map-gl/maplibre';
import type { LayerProps } from 'react-map-gl/maplibre';
import type { FeatureCollection, Geometry } from 'geojson';
import type { MapRef } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';
import { useHeatmapStream } from './heatmap/stream.ts';
import { heatmapLayer } from './heatmap/layer.ts';

const initialViewState = {
  longitude: -122.3337,
  latitude: 47.6074,
  zoom: 15.3,
  pitch: 55,
  bearing: -18,
};

const initialBounds = {
  west: -122.3525,
  south: 47.6015,
  east: -122.3245,
  north: 47.6195,
};

const emptyFeatureCollection: FeatureCollection<Geometry> = {
  type: 'FeatureCollection',
  features: [],
};

type Bounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

type BuildingRegion = {
  id: string;
  label: string;
  url: string;
  bounds: Bounds;
};

const BUILDING_REGIONS: BuildingRegion[] = [
  {
    id: 'downtown-core',
    label: 'Downtown Core',
    url: '/seattle/seattle-buildings-downtown-core.geojson',
    bounds: {
      west: -122.37,
      south: 47.585,
      east: -122.308,
      north: 47.6325,
    },
  },
  {
    id: 'east-neighborhoods',
    label: 'East Neighborhoods',
    url: '/seattle/seattle-buildings-east-neighborhoods.geojson',
    bounds: {
      west: -122.32,
      south: 47.585,
      east: -122.255,
      north: 47.676,
    },
  },
  {
    id: 'northwest-seattle',
    label: 'Northwest Seattle',
    url: '/seattle/seattle-buildings-northwest-seattle.geojson',
    bounds: {
      west: -122.43,
      south: 47.6205,
      east: -122.322,
      north: 47.69,
    },
  },
  {
    id: 'west-seattle',
    label: 'West Seattle',
    url: '/seattle/seattle-buildings-west-seattle.geojson',
    bounds: {
      west: -122.432,
      south: 47.543,
      east: -122.34,
      north: 47.604,
    },
  },
  {
    id: 'beacon-hill',
    label: 'Beacon Hill',
    url: '/seattle/seattle-buildings-beacon-hill.geojson',
    bounds: {
      west: -122.3365,
      south: 47.55,
      east: -122.284,
      north: 47.6015,
    },
  },
];

const REGION_LOAD_ORDER = [
  'downtown-core',
  'east-neighborhoods',
  'northwest-seattle',
  'beacon-hill',
  'west-seattle',
] as const;

const REGION_PRIORITY = new globalThis.Map<string, number>(
  REGION_LOAD_ORDER.map((regionId, index) => [regionId, index] as [string, number]),
);

const buildingFillLayer: LayerProps = {
  id: 'official-seattle-buildings-fill',
  type: 'fill-extrusion',
  paint: {
    'fill-extrusion-color': [
      'interpolate',
      ['linear'],
      ['get', 'height_m'],
      3,
      '#cfe6ff',
      15,
      '#b7d8fb',
      40,
      '#97c5f6',
      120,
      '#79afe6',
    ],
    'fill-extrusion-height': ['coalesce', ['get', 'height_m'], 0],
    'fill-extrusion-base': 0,
    'fill-extrusion-opacity': 1,
    'fill-extrusion-vertical-gradient': true,
  },
};

const buildingOutlineLayer: LayerProps = {
  id: 'official-seattle-buildings-line',
  type: 'line',
  paint: {
    'line-color': '#6aa6dd',
    'line-width': 1,
    'line-opacity': 1,
  },
};

async function fetchRegionBuildings(
  region: BuildingRegion,
  signal: AbortSignal,
) {
  const response = await fetch(region.url, { signal });
  if (!response.ok) {
    throw new Error(`${region.label} failed with ${response.status}`);
  }
  return response.json() as Promise<FeatureCollection<Geometry>>;
}

function expandBounds(bounds: Bounds) {
  const lonPad = (bounds.east - bounds.west) * 0.2;
  const latPad = (bounds.north - bounds.south) * 0.2;

  return {
    west: bounds.west - lonPad,
    south: bounds.south - latPad,
    east: bounds.east + lonPad,
    north: bounds.north + latPad,
  };
}

function boundsFromMap(map: MapRef) {
  const bounds = map.getBounds();
  return expandBounds({
    west: bounds.getWest(),
    south: bounds.getSouth(),
    east: bounds.getEast(),
    north: bounds.getNorth(),
  });
}

function containsBounds(outer: Bounds, inner: Bounds) {
  return (
    inner.west >= outer.west &&
    inner.south >= outer.south &&
    inner.east <= outer.east &&
    inner.north <= outer.north
  );
}

function intersectsBounds(a: Bounds, b: Bounds) {
  return !(
    a.east < b.west ||
    a.west > b.east ||
    a.north < b.south ||
    a.south > b.north
  );
}

function mergeFeatureCollections(
  collections: FeatureCollection<Geometry>[],
) {
  return {
    type: 'FeatureCollection',
    features: collections.flatMap((collection) => collection.features),
  } satisfies FeatureCollection<Geometry>;
}

function sortRegionIds(regionIds: string[]) {
  return [...new Set(regionIds)].sort(
    (left, right) =>
      (REGION_PRIORITY.get(left) ?? Number.MAX_SAFE_INTEGER)
      - (REGION_PRIORITY.get(right) ?? Number.MAX_SAFE_INTEGER),
  );
}

function App() {
  const heatmapData = useHeatmapStream();
  const [regionCollections, setRegionCollections] =
    useState<Record<string, FeatureCollection<Geometry>>>({});
  const [buildings, setBuildings] =
    useState<FeatureCollection<Geometry>>(emptyFeatureCollection);
  const [queryBounds, setQueryBounds] = useState(initialBounds);
  const [queuedRegionIds, setQueuedRegionIds] = useState<string[]>(
    REGION_LOAD_ORDER.slice(1) as unknown as string[],
  );
  const [activeRegionId, setActiveRegionId] = useState<string | null>(REGION_LOAD_ORDER[0]);
  const [buildingsError, setBuildingsError] = useState<string | null>(null);
  const [regionErrors, setRegionErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setBuildings(mergeFeatureCollections(Object.values(regionCollections)));
  }, [regionCollections]);

  useEffect(() => {
    const loadedRegionIds = Object.keys(regionCollections);
    const inViewRegionIds = BUILDING_REGIONS
      .filter((region) => intersectsBounds(region.bounds, queryBounds))
      .map((region) => region.id);
    const pendingRegionIds = sortRegionIds([
      ...inViewRegionIds,
      ...REGION_LOAD_ORDER,
    ]).filter(
      (regionId) =>
        !loadedRegionIds.includes(regionId)
        && regionId !== activeRegionId
        && !regionErrors[regionId],
    );

    setQueuedRegionIds((current) =>
      sortRegionIds([
        ...current.filter(
          (regionId) =>
            !loadedRegionIds.includes(regionId)
            && regionId !== activeRegionId
            && !regionErrors[regionId],
        ),
        ...pendingRegionIds,
      ]),
    );
  }, [activeRegionId, queryBounds, regionCollections, regionErrors]);

  useEffect(() => {
    if (activeRegionId !== null || queuedRegionIds.length === 0) {
      return;
    }

    setActiveRegionId(queuedRegionIds[0]);
    setQueuedRegionIds((current) => current.slice(1));
  }, [activeRegionId, queuedRegionIds]);

  useEffect(() => {
    if (activeRegionId === null) {
      return undefined;
    }

    const region = BUILDING_REGIONS.find((candidate) => candidate.id === activeRegionId);
    if (!region) {
      setActiveRegionId(null);
      return undefined;
    }

    const controller = new AbortController();
    setBuildingsError(null);
    setRegionErrors((current) => {
      const next = { ...current };
      delete next[activeRegionId];
      return next;
    });

    void fetchRegionBuildings(region, controller.signal)
      .then((featureCollection) => {
        setRegionCollections((current) => ({
          ...current,
          [region.id]: featureCollection,
        }));
        setRegionErrors((current) => {
          const next = { ...current };
          delete next[region.id];
          return next;
        });
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          console.error(error);
          setBuildingsError(`Could not load ${region.label}.`);
          setRegionErrors((current) => ({
            ...current,
            [region.id]: 'Error',
          }));
        }
      })
      .finally(() => {
        setActiveRegionId((current) => (current === region.id ? null : current));
      });

    return () => {
      controller.abort();
    };
  }, [activeRegionId, queryBounds]);

  function updateBuildingsForViewport(map: MapRef) {
    const nextBounds = boundsFromMap(map);
    setQueryBounds((currentBounds) =>
      containsBounds(currentBounds, nextBounds) ? currentBounds : nextBounds,
    );
  }

  const loadingLabels = activeRegionId === null
    ? []
    : [BUILDING_REGIONS.find((region) => region.id === activeRegionId)?.label ?? activeRegionId];
  const statusMessage = buildingsError
    ?? (loadingLabels.length > 0 ? `Loading ${loadingLabels.join(', ')}...` : null);
  const isStatusError = statusMessage === buildingsError;
  const regionStatuses = BUILDING_REGIONS.map((region) => {
    const isLoaded = Boolean(regionCollections[region.id]);
    const isLoading = activeRegionId === region.id;
    const isQueued = queuedRegionIds.includes(region.id);
    const hasError = Boolean(regionErrors[region.id]);
    const inView = intersectsBounds(region.bounds, queryBounds);

    let statusLabel = 'Waiting';
    if (hasError) {
      statusLabel = 'Error';
    } else if (isLoading) {
      statusLabel = 'Loading';
    } else if (isQueued) {
      statusLabel = 'Queued';
    } else if (isLoaded) {
      statusLabel = 'Loaded';
    }

    return {
      ...region,
      inView,
      statusLabel,
      statusTone: hasError
        ? 'error'
        : isLoading
          ? 'loading'
          : isLoaded
            ? 'loaded'
            : isQueued
              ? 'queued'
              : 'idle',
    };
  });

  return (
    <div className="map-shell">
      <aside className="map-note">
        <h1>Official Seattle Buildings</h1>
        <p>
          Buildings now load from local Seattle region files instead of querying the city service
          at runtime, starting with downtown core and then expanding outward.
        </p>
        <p>
          Extrusion heights come from Seattle&apos;s official 3D building shells, pre-joined to the
          2023 footprints.
        </p>

        <div className="region-status-list" aria-label="Neighborhood loading status">
          {regionStatuses.map((region) => (
            <div key={region.id} className="region-status-row">
              <span className="region-status-name">{region.label}</span>
              <span
                className={`region-status-chip is-${region.statusTone}`}
                title={region.inView ? 'Touches the current map view' : 'Outside the current map view'}
              >
                {region.statusLabel}
              </span>
            </div>
          ))}
        </div>
      </aside>

      {statusMessage ? (
        <div
          className={`map-status ${isStatusError ? 'is-error' : ''}`}
          role="status"
          aria-live="polite"
        >
          {isStatusError ? null : <span className="map-status-spinner" aria-hidden="true" />}
          <span>{statusMessage}</span>
        </div>
      ) : null}

      <Map
        initialViewState={initialViewState}
        mapStyle="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
        style={{ width: '100vw', height: '100vh' }}
        onLoad={(event) => updateBuildingsForViewport(event.target as unknown as MapRef)}
        onMoveEnd={(event) => updateBuildingsForViewport(event.target as unknown as MapRef)}
      >
        <NavigationControl position="top-right" />

        <Source id="official-seattle-buildings" type="geojson" data={buildings}>
          <Layer {...buildingFillLayer} />
          <Layer {...buildingOutlineLayer} />
        </Source>

        <Source id="heatmap-source" type="geojson" data={heatmapData}>
          <Layer {...heatmapLayer} />
        </Source>
      </Map>
    </div>
  );
}

export default App;
