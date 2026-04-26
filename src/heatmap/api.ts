const BASE_URL = '/api';

export type PlacedPerson = {
  id: string;
  lat: number;
  lon: number;
  count: number;
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
