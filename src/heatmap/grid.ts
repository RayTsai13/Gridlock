import type { FeatureCollection, Point } from 'geojson';

export type Bounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type GridConfig = {
  bounds: Bounds;
  rows: number;
  cols: number;
};

export type HeatmapRaster = {
  url: string;
  coordinates: [
    [number, number],
    [number, number],
    [number, number],
    [number, number],
  ];
};

/** [row, col, density] tuple from the SSE frame */
export type CellTuple = [row: number, col: number, density: number];

type SampleOffset = {
  x: number;
  y: number;
  weight: number;
};

const CELL_SAMPLE_OFFSETS: SampleOffset[] = [
  { x: 0, y: 0, weight: 0.35 },
  { x: -0.34, y: -0.34, weight: 0.2 },
  { x: 0.34, y: -0.34, weight: 0.2 },
  { x: -0.34, y: 0.34, weight: 0.2 },
  { x: 0.34, y: 0.34, weight: 0.2 },
];

const RASTER_PIXELS_PER_CELL = 16;
const RASTER_MAX_DIMENSION = 1200;
const SHORE_FADE_METERS = 180;
const GAP_FILL_RADIUS_CELLS = 2;

type LonLat = [lon: number, lat: number];

type ColorStop = {
  value: number;
  color: [number, number, number];
  alpha: number;
};

const RASTER_COLOR_STOPS: ColorStop[] = [
  { value: 0, color: [35, 128, 188], alpha: 0 },
  { value: 0.08, color: [35, 128, 188], alpha: 0.22 },
  { value: 0.18, color: [67, 182, 198], alpha: 0.38 },
  { value: 0.32, color: [151, 213, 164], alpha: 0.54 },
  { value: 0.48, color: [255, 223, 122], alpha: 0.68 },
  { value: 0.64, color: [246, 156, 80], alpha: 0.8 },
  { value: 0.8, color: [219, 74, 74], alpha: 0.9 },
  { value: 1, color: [125, 32, 85], alpha: 0.96 },
];

const PUGET_COAST: LonLat[] = [
  [-122.42, 47.74],
  [-122.41, 47.69],
  [-122.40, 47.67],
  [-122.41, 47.645],
  [-122.39, 47.635],
  [-122.37, 47.625],
  [-122.355, 47.615],
  [-122.347, 47.605],
  [-122.347, 47.595],
  [-122.36, 47.58],
  [-122.375, 47.565],
  [-122.39, 47.55],
  [-122.40, 47.50],
];

const LAKE_WASHINGTON_COAST: LonLat[] = [
  [-122.255, 47.70],
  [-122.260, 47.68],
  [-122.262, 47.66],
  [-122.270, 47.645],
  [-122.275, 47.635],
  [-122.272, 47.62],
  [-122.270, 47.60],
  [-122.268, 47.58],
  [-122.262, 47.56],
  [-122.255, 47.50],
];

const WATER_POLYGONS: LonLat[][] = [
  [
    [-122.348, 47.646],
    [-122.343, 47.649],
    [-122.334, 47.650],
    [-122.324, 47.647],
    [-122.320, 47.641],
    [-122.321, 47.632],
    [-122.326, 47.627],
    [-122.334, 47.625],
    [-122.342, 47.627],
    [-122.347, 47.634],
    [-122.349, 47.641],
    [-122.348, 47.646],
  ],
  [
    [-122.359, 47.653],
    [-122.349, 47.652],
    [-122.340, 47.651],
    [-122.337, 47.648],
    [-122.343, 47.647],
    [-122.352, 47.648],
    [-122.361, 47.650],
    [-122.359, 47.653],
  ],
  [
    [-122.326, 47.649],
    [-122.317, 47.650],
    [-122.307, 47.650],
    [-122.302, 47.647],
    [-122.306, 47.644],
    [-122.318, 47.644],
    [-122.325, 47.646],
    [-122.326, 47.649],
  ],
];

const landAlphaCache = new Map<string, Uint8ClampedArray>();

export type Frame = {
  timestamp: number;
  state_version?: string;
  sim_time?: SimTime;
  cells: CellTuple[];
};

export type SimTime = {
  day_of_week: number;
  time_bin: number;
  minute_of_week: number;
};

/**
 * Precompute a flat array of [lon, lat] pairs for every (row, col).
 * Index formula: (row * cols + col) * 2 → lon, +1 → lat.
 */
export function buildCentroidLookup(config: GridConfig): Float64Array {
  const { bounds, rows, cols } = config;
  const cellWidth = (bounds.east - bounds.west) / cols;
  const cellHeight = (bounds.north - bounds.south) / rows;
  const lookup = new Float64Array(rows * cols * 2);

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const idx = (r * cols + c) * 2;
      lookup[idx] = bounds.west + (c + 0.5) * cellWidth;
      lookup[idx + 1] = bounds.north - (r + 0.5) * cellHeight;
    }
  }
  return lookup;
}

export function frameToGeoJSON(
  cells: CellTuple[],
  centroids: Float64Array,
  config: GridConfig,
): FeatureCollection<Point> {
  const { bounds, rows, cols } = config;
  const cellWidth = (bounds.east - bounds.west) / cols;
  const cellHeight = (bounds.north - bounds.south) / rows;

  return {
    type: 'FeatureCollection',
    features: cells.flatMap(([row, col, density]) => {
      const idx = (row * cols + col) * 2;
      const lon = centroids[idx];
      const lat = centroids[idx + 1];

      return CELL_SAMPLE_OFFSETS.map((offset) => ({
        type: 'Feature' as const,
        geometry: {
          type: 'Point' as const,
          coordinates: [
            lon + offset.x * cellWidth,
            lat + offset.y * cellHeight,
          ],
        },
        properties: { density, sampleWeight: offset.weight },
      }));
    }),
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function lerp(left: number, right: number, amount: number) {
  return left + (right - left) * amount;
}

function smoothstep(edge0: number, edge1: number, value: number) {
  const amount = clamp((value - edge0) / (edge1 - edge0), 0, 1);
  return amount * amount * (3 - 2 * amount);
}

function metersPerLonDegree(lat: number) {
  return 111_320 * Math.cos((lat * Math.PI) / 180);
}

function distanceToSegmentMeters(point: LonLat, start: LonLat, end: LonLat) {
  const midLat = point[1];
  const lonScale = metersPerLonDegree(midLat);
  const pointX = point[0] * lonScale;
  const pointY = point[1] * 111_320;
  const startX = start[0] * lonScale;
  const startY = start[1] * 111_320;
  const endX = end[0] * lonScale;
  const endY = end[1] * 111_320;
  const segmentX = endX - startX;
  const segmentY = endY - startY;
  const segmentLengthSq = segmentX * segmentX + segmentY * segmentY;
  const amount =
    segmentLengthSq === 0
      ? 0
      : clamp(
          ((pointX - startX) * segmentX + (pointY - startY) * segmentY) /
            segmentLengthSq,
          0,
          1,
        );
  const projectedX = startX + amount * segmentX;
  const projectedY = startY + amount * segmentY;
  return Math.hypot(pointX - projectedX, pointY - projectedY);
}

function distanceToPolylineMeters(point: LonLat, line: LonLat[]) {
  let minDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < line.length - 1; index += 1) {
    minDistance = Math.min(
      minDistance,
      distanceToSegmentMeters(point, line[index], line[index + 1]),
    );
  }
  return minDistance;
}

function distanceToPolygonMeters(point: LonLat, polygon: LonLat[]) {
  let minDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polygon.length - 1; index += 1) {
    minDistance = Math.min(
      minDistance,
      distanceToSegmentMeters(point, polygon[index], polygon[index + 1]),
    );
  }
  return minDistance;
}

function interpolatedCoastLon(lat: number, waypoints: LonLat[]) {
  if (lat >= waypoints[0][1]) {
    return waypoints[0][0];
  }
  if (lat <= waypoints[waypoints.length - 1][1]) {
    return waypoints[waypoints.length - 1][0];
  }

  for (let index = 0; index < waypoints.length - 1; index += 1) {
    const [lonA, latA] = waypoints[index];
    const [lonB, latB] = waypoints[index + 1];
    if (latB <= lat && lat <= latA) {
      const amount = (lat - latB) / (latA - latB);
      return lonB + amount * (lonA - lonB);
    }
  }

  return waypoints[waypoints.length - 1][0];
}

function pointInPolygon(point: LonLat, polygon: LonLat[]) {
  const [lon, lat] = point;
  let inside = false;

  for (
    let index = 0, previousIndex = polygon.length - 1;
    index < polygon.length;
    previousIndex = index, index += 1
  ) {
    const [lonI, latI] = polygon[index];
    const [lonJ, latJ] = polygon[previousIndex];
    const intersects =
      latI > lat !== latJ > lat &&
      lon < ((lonJ - lonI) * (lat - latI)) / (latJ - latI) + lonI;

    if (intersects) {
      inside = !inside;
    }
  }

  return inside;
}

function landAlphaForPoint(point: LonLat) {
  const [lon, lat] = point;
  let alpha = 1;
  const pugetCoastLon = interpolatedCoastLon(lat, PUGET_COAST);

  if (lon < pugetCoastLon) {
    return 0;
  }
  alpha = Math.min(
    alpha,
    smoothstep(
      0,
      SHORE_FADE_METERS,
      distanceToPolylineMeters(point, PUGET_COAST),
    ),
  );

  const lakeWashingtonCoastLon = interpolatedCoastLon(
    lat,
    LAKE_WASHINGTON_COAST,
  );
  if (47.52 < lat && lat < 47.70 && lon > lakeWashingtonCoastLon) {
    return 0;
  }
  if (47.52 < lat && lat < 47.70) {
    alpha = Math.min(
      alpha,
      smoothstep(
        0,
        SHORE_FADE_METERS,
        distanceToPolylineMeters(point, LAKE_WASHINGTON_COAST),
      ),
    );
  }

  for (const polygon of WATER_POLYGONS) {
    if (pointInPolygon(point, polygon)) {
      return 0;
    }
    alpha = Math.min(
      alpha,
      smoothstep(
        0,
        SHORE_FADE_METERS,
        distanceToPolygonMeters(point, polygon),
      ),
    );
  }

  return alpha;
}

function landAlphaMaskKey(config: GridConfig, width: number, height: number) {
  const { bounds } = config;
  return [
    bounds.west,
    bounds.south,
    bounds.east,
    bounds.north,
    width,
    height,
  ].join(':');
}

function getLandAlphaMask(config: GridConfig, width: number, height: number) {
  const cacheKey = landAlphaMaskKey(config, width, height);
  const cached = landAlphaCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const { bounds } = config;
  const mask = new Uint8ClampedArray(width * height);

  for (let y = 0; y < height; y += 1) {
    const lat = lerp(bounds.north, bounds.south, (y + 0.5) / height);
    for (let x = 0; x < width; x += 1) {
      const lon = lerp(bounds.west, bounds.east, (x + 0.5) / width);
      mask[y * width + x] = Math.round(
        landAlphaForPoint([lon, lat]) * 255,
      );
    }
  }

  landAlphaCache.set(cacheKey, mask);
  return mask;
}

function sampleBilinear(
  grid: Float32Array,
  rows: number,
  cols: number,
  row: number,
  col: number,
) {
  const row0 = clamp(Math.floor(row), 0, rows - 1);
  const col0 = clamp(Math.floor(col), 0, cols - 1);
  const row1 = clamp(row0 + 1, 0, rows - 1);
  const col1 = clamp(col0 + 1, 0, cols - 1);
  const rowAmount = clamp(row - row0, 0, 1);
  const colAmount = clamp(col - col0, 0, 1);

  const top = lerp(
    grid[row0 * cols + col0],
    grid[row0 * cols + col1],
    colAmount,
  );
  const bottom = lerp(
    grid[row1 * cols + col0],
    grid[row1 * cols + col1],
    colAmount,
  );

  return lerp(top, bottom, rowAmount);
}

function colorForDensity(density: number): [number, number, number, number] {
  const adjustedDensity = Math.pow(clamp(density, 0, 1), 0.72);

  for (let index = 1; index < RASTER_COLOR_STOPS.length; index += 1) {
    const right = RASTER_COLOR_STOPS[index];
    if (adjustedDensity > right.value) {
      continue;
    }

    const left = RASTER_COLOR_STOPS[index - 1];
    const amount =
      right.value === left.value
        ? 0
        : (adjustedDensity - left.value) / (right.value - left.value);

    return [
      Math.round(lerp(left.color[0], right.color[0], amount)),
      Math.round(lerp(left.color[1], right.color[1], amount)),
      Math.round(lerp(left.color[2], right.color[2], amount)),
      Math.round(lerp(left.alpha, right.alpha, amount) * 255),
    ];
  }

  const finalStop = RASTER_COLOR_STOPS[RASTER_COLOR_STOPS.length - 1];
  return [
    finalStop.color[0],
    finalStop.color[1],
    finalStop.color[2],
    Math.round(finalStop.alpha * 255),
  ];
}

function fillDensityGaps(
  densityGrid: Float32Array,
  knownCells: Uint8Array,
  config: GridConfig,
) {
  const { bounds, rows, cols } = config;
  const cellWidth = (bounds.east - bounds.west) / cols;
  const cellHeight = (bounds.north - bounds.south) / rows;
  const filledGrid = new Float32Array(densityGrid);

  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const index = row * cols + col;
      if (knownCells[index]) {
        continue;
      }

      const lon = bounds.west + (col + 0.5) * cellWidth;
      const lat = bounds.north - (row + 0.5) * cellHeight;
      if (landAlphaForPoint([lon, lat]) < 0.2) {
        continue;
      }

      let weightedDensity = 0;
      let weightTotal = 0;
      for (
        let neighborRow = Math.max(0, row - GAP_FILL_RADIUS_CELLS);
        neighborRow <= Math.min(rows - 1, row + GAP_FILL_RADIUS_CELLS);
        neighborRow += 1
      ) {
        for (
          let neighborCol = Math.max(0, col - GAP_FILL_RADIUS_CELLS);
          neighborCol <= Math.min(cols - 1, col + GAP_FILL_RADIUS_CELLS);
          neighborCol += 1
        ) {
          const neighborIndex = neighborRow * cols + neighborCol;
          if (!knownCells[neighborIndex]) {
            continue;
          }

          const rowDelta = neighborRow - row;
          const colDelta = neighborCol - col;
          const distanceSq = rowDelta * rowDelta + colDelta * colDelta;
          const weight = Math.exp(-distanceSq / 3);
          weightedDensity += densityGrid[neighborIndex] * weight;
          weightTotal += weight;
        }
      }

      if (weightTotal > 0) {
        const density = weightedDensity / weightTotal;
        filledGrid[index] = density > 0.04 ? density * 0.82 : 0;
      }
    }
  }

  return filledGrid;
}

export function frameToHeatmapRaster(
  cells: CellTuple[],
  config: GridConfig,
): HeatmapRaster | null {
  const { bounds, rows, cols } = config;
  const scale = Math.min(
    RASTER_PIXELS_PER_CELL,
    RASTER_MAX_DIMENSION / Math.max(rows, cols),
  );
  const width = Math.max(1, Math.round(cols * scale));
  const height = Math.max(1, Math.round(rows * scale));
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');

  if (!context) {
    return null;
  }

  canvas.width = width;
  canvas.height = height;

  const densityGrid = new Float32Array(rows * cols);
  const knownCells = new Uint8Array(rows * cols);
  for (const [row, col, density] of cells) {
    if (row >= 0 && row < rows && col >= 0 && col < cols) {
      const index = row * cols + col;
      densityGrid[index] = clamp(density, 0, 1);
      knownCells[index] = 1;
    }
  }
  const displayGrid = fillDensityGaps(densityGrid, knownCells, config);
  const landAlphaMask = getLandAlphaMask(config, width, height);

  const imageData = context.createImageData(width, height);
  const data = imageData.data;

  for (let y = 0; y < height; y += 1) {
    const gridRow = ((y + 0.5) / height) * rows - 0.5;
    for (let x = 0; x < width; x += 1) {
      const gridCol = ((x + 0.5) / width) * cols - 0.5;
      const density = sampleBilinear(displayGrid, rows, cols, gridRow, gridCol);
      const [red, green, blue, alpha] = colorForDensity(density);
      const index = (y * width + x) * 4;
      data[index] = red;
      data[index + 1] = green;
      data[index + 2] = blue;
      data[index + 3] = Math.round((alpha * landAlphaMask[y * width + x]) / 255);
    }
  }

  context.putImageData(imageData, 0, 0);

  return {
    url: canvas.toDataURL('image/png'),
    coordinates: [
      [bounds.west, bounds.north],
      [bounds.east, bounds.north],
      [bounds.east, bounds.south],
      [bounds.west, bounds.south],
    ],
  };
}

export function emptyGrid(): FeatureCollection<Point> {
  return { type: 'FeatureCollection', features: [] };
}
