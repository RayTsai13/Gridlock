import type { LayerProps } from 'react-map-gl/maplibre';

export const heatmapLayer: LayerProps = {
  id: 'foot-traffic-heatmap',
  type: 'heatmap',
  paint: {
    'heatmap-weight': ['get', 'density'],

    'heatmap-intensity': [
      'interpolate', ['linear'], ['zoom'],
      10, 0.4,
      13, 0.8,
      15, 1.6,
      16, 2.0,
    ],

    'heatmap-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 8,
      13, 24,
      15, 60,
      16, 90,
      18, 140,
    ],

    'heatmap-color': [
      'interpolate', ['linear'], ['heatmap-density'],
      0,    'rgba(0, 0, 0, 0)',
      0.05, 'rgba(49, 54, 149, 0.25)',
      0.1,  'rgba(69, 117, 180, 0.45)',
      0.2,  'rgba(116, 173, 209, 0.65)',
      0.3,  'rgba(171, 217, 233, 0.75)',
      0.4,  'rgba(224, 243, 248, 0.8)',
      0.5,  'rgba(255, 255, 191, 0.85)',
      0.6,  'rgba(254, 224, 144, 0.85)',
      0.7,  'rgba(253, 174, 97, 0.9)',
      0.8,  'rgba(244, 109, 67, 0.92)',
      0.9,  'rgba(215, 48, 39, 0.95)',
      1.0,  'rgba(165, 0, 38, 1)',
    ],

    'heatmap-opacity': 0.7,
  },
};
