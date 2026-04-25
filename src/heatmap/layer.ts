import type { LayerProps } from 'react-map-gl/maplibre';

export const heatmapLayer: LayerProps = {
  id: 'foot-traffic-heatmap',
  type: 'heatmap',
  paint: {
    'heatmap-weight': ['get', 'density'],

    'heatmap-intensity': [
      'interpolate', ['linear'], ['zoom'],
      10, 0.5,
      13, 1,
      16, 2,
    ],

    'heatmap-radius': [
      'interpolate', ['linear'], ['zoom'],
      10, 20,
      13, 40,
      15, 70,
      16, 100,
    ],

    'heatmap-color': [
      'interpolate', ['linear'], ['heatmap-density'],
      0,   'rgba(0, 0, 0, 0)',
      0.2, 'rgba(255, 255, 204, 0.6)',
      0.4, 'rgba(255, 237, 160, 0.7)',
      0.6, 'rgba(254, 178, 76, 0.8)',
      0.8, 'rgba(253, 141, 60, 0.9)',
      1.0, 'rgba(227, 26, 28, 1)',
    ],

    'heatmap-opacity': 0.7,
  },
};
