import type { LayerProps } from "react-map-gl/maplibre";

export const heatmapRasterLayer: LayerProps = {
  id: "foot-traffic-demand-drape",
  type: "raster",
  paint: {
    "raster-opacity": 0.88,
    "raster-fade-duration": 0,
    "raster-resampling": "linear",
  },
};

export const heatmapLayer: LayerProps = {
  id: "foot-traffic-heatmap",
  type: "heatmap",
  paint: {
    "heatmap-weight": [
      "*",
      [
        "interpolate",
        ["linear"],
        ["get", "density"],
        0,
        0,
        0.02,
        0.14,
        0.12,
        0.42,
        0.28,
        0.72,
        0.55,
        0.95,
        1,
        1,
      ],
      ["coalesce", ["get", "sampleWeight"], 1],
    ],

    "heatmap-intensity": [
      "interpolate",
      ["linear"],
      ["zoom"],
      10,
      0.52,
      13,
      0.72,
      15,
      0.92,
      16,
      1.08,
    ],

    "heatmap-radius": [
      "interpolate",
      ["linear"],
      ["zoom"],
      10,
      34,
      13,
      68,
      15,
      118,
      16,
      160,
    ],

    "heatmap-color": [
      "interpolate",
      ["linear"],
      ["heatmap-density"],
      0,
      "rgba(0, 0, 0, 0)",
      0.03,
      "rgba(62, 146, 204, 0.22)",
      0.12,
      "rgba(103, 196, 220, 0.42)",
      0.24,
      "rgba(176, 227, 209, 0.58)",
      0.38,
      "rgba(255, 235, 157, 0.72)",
      0.55,
      "rgba(253, 181, 91, 0.84)",
      0.72,
      "rgba(237, 104, 71, 0.92)",
      0.88,
      "rgba(190, 54, 76, 0.96)",
      1,
      "rgba(116, 28, 78, 1)",
    ],

    "heatmap-opacity": 0.18,
  },
};
