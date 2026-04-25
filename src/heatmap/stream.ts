import { useEffect, useRef, useState } from 'react';
import type { FeatureCollection, Point } from 'geojson';
import { buildCentroidLookup, emptyGrid, frameToGeoJSON } from './grid.ts';
import type { GridConfig, Frame } from './grid.ts';

const STREAM_URL = 'http://localhost:8000/api/heatmap/stream';

export function useHeatmapStream(): FeatureCollection<Point> {
  const [geojson, setGeojson] = useState<FeatureCollection<Point>>(emptyGrid());
  const centroidsRef = useRef<Float64Array | null>(null);
  const configRef = useRef<GridConfig | null>(null);

  useEffect(() => {
    const source = new EventSource(STREAM_URL);

    source.addEventListener('config', (e: MessageEvent) => {
      const config: GridConfig = JSON.parse(e.data as string);
      configRef.current = config;
      centroidsRef.current = buildCentroidLookup(config);
    });

    source.addEventListener('frame', (e: MessageEvent) => {
      if (!centroidsRef.current || !configRef.current) return;
      const frame: Frame = JSON.parse(e.data as string);
      setGeojson(
        frameToGeoJSON(frame.cells, centroidsRef.current, configRef.current.cols),
      );
    });

    source.addEventListener('clear', () => {
      setGeojson(emptyGrid());
    });

    source.addEventListener('error', () => {
      console.warn('[heatmap] SSE connection error, will auto-reconnect');
    });

    return () => {
      source.close();
    };
  }, []);

  return geojson;
}
