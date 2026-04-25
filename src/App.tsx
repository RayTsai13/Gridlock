import { useEffect, useRef, useState } from 'react';
import { Layer, Map, NavigationControl, Source } from 'react-map-gl/maplibre';
import type { LayerProps } from 'react-map-gl/maplibre';
import type { FeatureCollection, Geometry } from 'geojson';
import type { MapRef } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';

const BUILDING_OUTLINES_SERVICE_URL =
  'https://services.arcgis.com/ZOyb2t4B0UYuYNYH/ArcGIS/rest/services/Building_Outlines_2023/FeatureServer/0/query';

const initialViewState = {
  longitude: -122.3358,
  latitude: 47.6094,
  zoom: 15.3,
  pitch: 58,
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

const buildingFillLayer: LayerProps = {
  id: 'official-seattle-buildings-fill',
  type: 'fill-extrusion',
  paint: {
    'fill-extrusion-color': [
      'interpolate',
      ['linear'],
      ['get', 'AREA'],
      500,
      '#bcdcff',
      5000,
      '#9fcdfb',
      20000,
      '#78b6f4',
    ],
    'fill-extrusion-opacity': 1,
    'fill-extrusion-base': 0,
    'fill-extrusion-height': [
      'interpolate',
      ['linear'],
      ['get', 'AREA'],
      250,
      12,
      1500,
      24,
      5000,
      48,
      15000,
      90,
      40000,
      160,
    ],
  },
};

const buildingOutlineLayer: LayerProps = {
  id: 'official-seattle-buildings-line',
  type: 'line',
  paint: {
    'line-color': '#5b8fc6',
    'line-width': 0.9,
    'line-opacity': 1,
  },
};

function buildBuildingsUrl(
  bounds: Bounds,
  resultOffset = 0,
) {
  const params = new URLSearchParams({
    where: '1=1',
    geometry: `${bounds.west},${bounds.south},${bounds.east},${bounds.north}`,
    geometryType: 'esriGeometryEnvelope',
    inSR: '4326',
    spatialRel: 'esriSpatialRelIntersects',
    outFields: 'OBJECTID,AREA,PIN',
    returnGeometry: 'true',
    outSR: '4326',
    f: 'geojson',
    resultRecordCount: '2000',
    resultOffset: String(resultOffset),
    orderByFields: 'OBJECTID ASC',
  });

  return `${BUILDING_OUTLINES_SERVICE_URL}?${params.toString()}`;
}

async function fetchBuildingsForBounds(
  bounds: Bounds,
  signal: AbortSignal,
) {
  const features: FeatureCollection<Geometry>['features'] = [];
  let resultOffset = 0;

  while (true) {
    const response = await fetch(buildBuildingsUrl(bounds, resultOffset), { signal });
    if (!response.ok) {
      throw new Error(`Building query failed with ${response.status}`);
    }

    const payload = (await response.json()) as FeatureCollection<Geometry> & {
      properties?: { exceededTransferLimit?: boolean };
    };

    features.push(...payload.features);

    if (!payload.properties?.exceededTransferLimit || payload.features.length === 0) {
      return {
        type: 'FeatureCollection',
        features,
      } satisfies FeatureCollection<Geometry>;
    }

    resultOffset += payload.features.length;
  }
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

function boundsKey(bounds: Bounds) {
  const round = (value: number) => value.toFixed(4);
  return [bounds.west, bounds.south, bounds.east, bounds.north].map(round).join(':');
}

function containsBounds(outer: Bounds, inner: Bounds) {
  return (
    inner.west >= outer.west &&
    inner.south >= outer.south &&
    inner.east <= outer.east &&
    inner.north <= outer.north
  );
}

function App() {
  const buildingsCacheRef = useRef(
    new globalThis.Map<string, FeatureCollection<Geometry>>(),
  );
  const requestIdRef = useRef(0);
  const [buildings, setBuildings] =
    useState<FeatureCollection<Geometry>>(emptyFeatureCollection);
  const [queryBounds, setQueryBounds] = useState(initialBounds);

  useEffect(() => {
    const cacheKey = boundsKey(queryBounds);
    const cached = buildingsCacheRef.current.get(cacheKey);
    if (cached) {
      setBuildings(cached);
      return;
    }

    const controller = new AbortController();
    const requestId = ++requestIdRef.current;

    void fetchBuildingsForBounds(queryBounds, controller.signal)
      .then((featureCollection) => {
        if (requestId === requestIdRef.current) {
          buildingsCacheRef.current.set(cacheKey, featureCollection);
          setBuildings(featureCollection);
        }
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          console.error(error);
        }
      });

    return () => controller.abort();
  }, [queryBounds]);

  function updateBuildingsForViewport(map: MapRef) {
    const nextBounds = boundsFromMap(map);
    setQueryBounds((currentBounds) =>
      containsBounds(currentBounds, nextBounds) ? currentBounds : nextBounds,
    );
  }

  return (
    <div className="map-shell">
      <aside className="map-note">
        <h1>Official Seattle Buildings</h1>
        <p>
          Buildings now come from Seattle&apos;s official <code>Building_Outlines_2023</code>{' '}
          service and are queried as GeoJSON for the current map area.
        </p>
        <p>
          This service only provides footprints, so the vertical height is currently an area-based
          visual approximation.
        </p>
      </aside>

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
      </Map>
    </div>
  );
}

export default App;
