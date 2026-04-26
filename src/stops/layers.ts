import type { LayerProps } from 'react-map-gl/maplibre';

// ---------------------------------------------------------------------------
// Transit line layers  (rendered BELOW stop markers)
// ---------------------------------------------------------------------------

/** White casing behind the colored line for contrast. */
export const lineCasingLayer: LayerProps = {
  id: 'transit-line-casing',
  type: 'line',
  layout: {
    'line-cap': 'round',
    'line-join': 'round',
  },
  paint: {
    'line-color': '#ffffff',
    'line-width': [
      'interpolate', ['linear'], ['zoom'],
      10, 4,
      13, 7,
      16, 10,
    ],
    'line-opacity': 0.85,
    'line-offset': [
      'interpolate', ['linear'], ['zoom'],
      10, ['*', ['get', 'offset'], 1],
      13, ['*', ['get', 'offset'], 1.5],
      16, ['*', ['get', 'offset'], 2],
    ],
  },
};

/** Colored route line — reads color from the feature's `color` property. */
export const lineRouteLayer: LayerProps = {
  id: 'transit-line-route',
  type: 'line',
  layout: {
    'line-cap': 'round',
    'line-join': 'round',
  },
  paint: {
    'line-color': ['get', 'color'],
    'line-width': [
      'interpolate', ['linear'], ['zoom'],
      10, 2,
      13, 4,
      16, 6,
    ],
    'line-opacity': 0.9,
    'line-offset': [
      'interpolate', ['linear'], ['zoom'],
      10, ['*', ['get', 'offset'], 1],
      13, ['*', ['get', 'offset'], 1.5],
      16, ['*', ['get', 'offset'], 2],
    ],
  },
};

// ---------------------------------------------------------------------------
// Stop marker layers  (rendered ABOVE transit lines)
// ---------------------------------------------------------------------------

/** Outer marker circle — visible at all zoom levels. */
export const stopCircleLayer: LayerProps = {
  id: 'transit-stops-circle',
  type: 'circle',
  paint: {
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 3,
      13, 6,
      16, 9,
    ],
    'circle-color': '#ffffff',
    'circle-opacity': 0.95,
    'circle-stroke-width': [
      'interpolate', ['linear'], ['zoom'],
      10, 1.5,
      16, 3,
    ],
    'circle-stroke-color': ['coalesce', ['get', 'markerColor'], '#1a73e8'],
    'circle-stroke-opacity': 1,
  },
};

/** Inner dot for a "bullseye" station marker look. */
export const stopDotLayer: LayerProps = {
  id: 'transit-stops-dot',
  type: 'circle',
  paint: {
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 1.5,
      13, 3,
      16, 4.5,
    ],
    'circle-color': ['coalesce', ['get', 'markerColor'], '#1a73e8'],
    'circle-opacity': 1,
  },
};

/** Station name labels — appear at zoom ≥ 13. */
export const stopLabelLayer: LayerProps = {
  id: 'transit-stops-labels',
  type: 'symbol',
  layout: {
    'text-field': ['get', 'name'],
    'text-size': [
      'interpolate', ['linear'], ['zoom'],
      13, 10,
      16, 13,
    ],
    'text-offset': [0, 1.6],
    'text-anchor': 'top',
    'text-font': ['Open Sans Semibold', 'Arial Unicode MS Bold'],
    'text-max-width': 8,
    'text-allow-overlap': false,
  },
  paint: {
    'text-color': '#1a3a5c',
    'text-halo-color': 'rgba(255, 255, 255, 0.92)',
    'text-halo-width': 1.5,
  },
  minzoom: 13,
};

// ---------------------------------------------------------------------------
// Deploy indicator layers  (pulsing ring on the trigger station)
// ---------------------------------------------------------------------------

/** Outer pulsing ring around the trigger station. */
export const deployPulseRingLayer: LayerProps = {
  id: 'deploy-pulse-ring',
  type: 'circle',
  paint: {
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 12,
      13, 20,
      16, 30,
    ],
    'circle-color': 'transparent',
    'circle-stroke-width': 3,
    'circle-stroke-color': '#facc15',
    'circle-stroke-opacity': 0.8,
  },
};

/** Inner glow dot on the trigger station. */
export const deployGlowDotLayer: LayerProps = {
  id: 'deploy-glow-dot',
  type: 'circle',
  paint: {
    'circle-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 6,
      13, 10,
      16, 15,
    ],
    'circle-color': '#facc15',
    'circle-opacity': 0.25,
  },
};
