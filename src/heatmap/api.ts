const BASE_URL = '';

export type PlacedPerson = {
  id: string;
  lat: number;
  lon: number;
  count: number;
};

export type SimTime = {
  day_of_week: number;
  time_bin: number;
  minute_of_week: number;
};

export type PlaybackState = {
  is_playing: boolean;
  current_tick: number;
  sim_step_seconds: number;
  sim_minutes_per_second: number;
  frame_interval_seconds: number;
  time_bin_minutes: number;
  sim_time: SimTime;
};

export async function postScenario(scenarioId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/scenario failed: ${res.status}`);
  }
}

export async function postPeople(
  lat: number,
  lon: number,
  count = 1,
): Promise<PlacedPerson> {
  const res = await fetch(`${BASE_URL}/api/people`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lat, lon, count }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/people failed: ${res.status}`);
  }
  return res.json();
}

export async function postPlayback(
  updates: Partial<Pick<PlaybackState, 'is_playing' | 'sim_minutes_per_second'>>,
): Promise<PlaybackState> {
  const res = await fetch(`${BASE_URL}/api/playback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    throw new Error(`POST /api/playback failed: ${res.status}`);
  }
  return res.json();
}

export async function seekPlayback(dayOfWeek: number, timeBin: number): Promise<PlaybackState> {
  const res = await fetch(`${BASE_URL}/api/playback/seek`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ day_of_week: dayOfWeek, time_bin: timeBin }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/playback/seek failed: ${res.status}`);
  }
  return res.json();
}

export async function deletePerson(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/people/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`DELETE /api/people/${id} failed: ${res.status}`);
  }
}

export async function deleteAllPeople(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/people`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`DELETE /api/people failed: ${res.status}`);
  }
}

export type DemoStop = {
  id: string;
  lat: number;
  lon: number;
  peak: number;
  decay_m: number;
  max_m: number;
};

export type DemoState = {
  scenario_id: string;
  relief_strength: number;
  demo_corridor_boost: boolean;
  demo_corridor_replaces_scenarios: boolean;
  extra_stops: DemoStop[];
};

/**
 * World Cup demo "more train cars" lever. 1.0 is default (lines fully drain
 * their catchment); 0.0 disables relief; 1.5+ over-drains so even a 30k crowd
 * vanishes from the heatmap. Backend clamps to [0, 4].
 */
export async function postReliefStrength(strength: number): Promise<{ strength: number }> {
  const res = await fetch(`${BASE_URL}/api/demo/relief`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ strength }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/demo/relief failed: ${res.status}`);
  }
  return res.json();
}

export async function getDemoState(): Promise<DemoState> {
  const res = await fetch(`${BASE_URL}/api/demo/state`);
  if (!res.ok) {
    throw new Error(`GET /api/demo/state failed: ${res.status}`);
  }
  return res.json();
}

/**
 * Drag-and-drop a "demo stop" onto the map. Each stop acts like a mini-station
 * that absorbs nearby crowd / corridor heat. Useful for the World Cup demo
 * where the user adds extra stops to relieve congestion.
 */
export async function addDemoStop(
  lat: number,
  lon: number,
  options: { peak?: number; decayM?: number; maxM?: number } = {},
): Promise<DemoStop> {
  const res = await fetch(`${BASE_URL}/api/demo/stops`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lat,
      lon,
      peak: options.peak ?? 0.45,
      decay_m: options.decayM ?? 700,
      max_m: options.maxM ?? 2200,
    }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/demo/stops failed: ${res.status}`);
  }
  return res.json();
}

export async function listDemoStops(): Promise<{ stops: DemoStop[] }> {
  const res = await fetch(`${BASE_URL}/api/demo/stops`);
  if (!res.ok) {
    throw new Error(`GET /api/demo/stops failed: ${res.status}`);
  }
  return res.json();
}

export async function removeDemoStop(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/demo/stops/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`DELETE /api/demo/stops/${id} failed: ${res.status}`);
  }
}

export async function clearDemoStops(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/demo/stops`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`DELETE /api/demo/stops failed: ${res.status}`);
  }
}
