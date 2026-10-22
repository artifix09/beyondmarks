const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Health = {
  ok: boolean;
  service: string;
  configured: boolean;
  missing_env: string[];
};

export async function getHealth(): Promise<Health> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`API returned ${res.status}`);
  return res.json();
}
