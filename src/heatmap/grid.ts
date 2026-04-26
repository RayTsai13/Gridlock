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

/** [row, col, density] tuple from the SSE frame */
export type CellTuple = [row: number, col: number, density: number];

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

const HEATMAP_SUBDIVISIONS = 3;
const MIN_RENDER_DENSITY = 0.006;

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
  config: GridConfig,
): FeatureCollection<Point> {
  const { bounds, rows, cols } = config;
  const cellWidth = (bounds.east - bounds.west) / cols;
  const cellHeight = (bounds.north - bounds.south) / rows;
  const values = new Float32Array(rows * cols);

  for (const [row, col, density] of cells) {
    if (row < 0 || row >= rows || col < 0 || col >= cols) continue;
    values[row * cols + col] = density;
  }

  const features: FeatureCollection<Point>['features'] = [];

  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      for (let sampleY = 0; sampleY < HEATMAP_SUBDIVISIONS; sampleY++) {
        const y = (sampleY + 0.5) / HEATMAP_SUBDIVISIONS;
        const rowCoord = row + y - 0.5;

        for (let sampleX = 0; sampleX < HEATMAP_SUBDIVISIONS; sampleX++) {
          const x = (sampleX + 0.5) / HEATMAP_SUBDIVISIONS;
          const colCoord = col + x - 0.5;
          const density = sampleGrid(values, rows, cols, rowCoord, colCoord);

          if (density <= MIN_RENDER_DENSITY) continue;

          features.push({
            type: 'Feature' as const,
            geometry: {
              type: 'Point' as const,
              coordinates: [
                bounds.west + (col + x) * cellWidth,
                bounds.north - (row + y) * cellHeight,
              ],
            },
            properties: { density },
          });
        }
      }
    }
  }

  return {
    type: 'FeatureCollection',
    features,
  };
}

export function emptyGrid(): FeatureCollection<Point> {
  return { type: 'FeatureCollection', features: [] };
}

function sampleGrid(
  values: Float32Array,
  rows: number,
  cols: number,
  rowCoord: number,
  colCoord: number,
): number {
  const row0 = clampIndex(Math.floor(rowCoord), rows);
  const col0 = clampIndex(Math.floor(colCoord), cols);
  const row1 = clampIndex(row0 + 1, rows);
  const col1 = clampIndex(col0 + 1, cols);
  const rowT = clamp01(rowCoord - Math.floor(rowCoord));
  const colT = clamp01(colCoord - Math.floor(colCoord));

  const topLeft = values[row0 * cols + col0];
  const topRight = values[row0 * cols + col1];
  const bottomLeft = values[row1 * cols + col0];
  const bottomRight = values[row1 * cols + col1];
  const top = topLeft * (1 - colT) + topRight * colT;
  const bottom = bottomLeft * (1 - colT) + bottomRight * colT;
  return top * (1 - rowT) + bottom * rowT;
}

function clampIndex(value: number, length: number): number {
  return Math.max(0, Math.min(length - 1, value));
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}
