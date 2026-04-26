import { useCallback, useEffect, useRef, useState } from 'react';
import type { FeatureCollection, Point } from 'geojson';
import { buildCentroidLookup, emptyGrid, frameToGeoJSON } from './grid.ts';
import type { GridConfig, Frame } from './grid.ts';
import {
  deleteAllPeople,
  deletePerson,
  postPeople,
  postScenario,
  type PlacedPerson,
} from './api.ts';

const STREAM_URL = 'http://localhost:8000/api/heatmap/stream';

export type HeatmapApi = {
  geojson: FeatureCollection<Point>;
  /** Last scenario_id confirmed by the server via a `scenario` event. */
  scenarioId: string | null;
  setScenario: (id: string) => Promise<void>;
  addPeople: (lat: number, lon: number, count?: number) => Promise<PlacedPerson>;
  removePeople: (id: string) => Promise<void>;
  clearPeople: () => Promise<void>;
};

export function useHeatmap(): HeatmapApi {
  const [geojson, setGeojson] = useState<FeatureCollection<Point>>(emptyGrid());
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const centroidsRef = useRef<Float64Array | null>(null);
  const configRef = useRef<GridConfig | null>(null);
  // Set when a scenario switch is in flight; frames are dropped until the
  // server's `scenario` event confirms the switch by matching this value.
  const pendingScenarioRef = useRef<string | null>(null);

  useEffect(() => {
    const source = new EventSource(STREAM_URL);

    source.addEventListener('config', (e: MessageEvent) => {
      const config: GridConfig = JSON.parse(e.data as string);
      configRef.current = config;
      centroidsRef.current = buildCentroidLookup(config);
    });

    source.addEventListener('scenario', (e: MessageEvent) => {
      const { scenario_id } = JSON.parse(e.data as string) as { scenario_id: string };
      setScenarioId(scenario_id);
      if (pendingScenarioRef.current === scenario_id) {
        pendingScenarioRef.current = null;
      }
    });

    source.addEventListener('frame', (e: MessageEvent) => {
      if (!centroidsRef.current || !configRef.current) return;
      if (pendingScenarioRef.current !== null) return;
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

  const setScenario = useCallback(async (id: string) => {
    pendingScenarioRef.current = id;
    try {
      await postScenario(id);
    } catch (err) {
      pendingScenarioRef.current = null;
      throw err;
    }
  }, []);

  const addPeople = useCallback(
    (lat: number, lon: number, count = 1) => postPeople(lat, lon, count),
    [],
  );
  const removePeople = useCallback((id: string) => deletePerson(id), []);
  const clearPeople = useCallback(() => deleteAllPeople(), []);

  return { geojson, scenarioId, setScenario, addPeople, removePeople, clearPeople };
}
