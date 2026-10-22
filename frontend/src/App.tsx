import { useEffect, useState } from "react";
import { getHealth, type Health } from "./lib/api";

/**
 * Scaffold page. It exists to answer one question before any feature is built:
 * is the frontend talking to the API, and does the API have its keys?
 * Replaced by the Login page in M12.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="mx-auto max-w-xl p-8 font-sans">
      <h1 className="text-2xl font-bold">BeyondMarks</h1>
      <p className="mt-1 text-sm text-neutral-500">Scaffold — M0</p>

      <section className="mt-6 rounded-lg border border-neutral-200 p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
          API
        </h2>

        {error && (
          <p className="mt-2 text-sm text-red-700">
            Cannot reach the API at {import.meta.env.VITE_API_URL ?? "http://localhost:8000"} — {error}.
            Start it with <code>uvicorn app.main:app --reload</code>.
          </p>
        )}

        {!error && !health && <p className="mt-2 text-sm">Checking…</p>}

        {health && (
          <div className="mt-2 text-sm">
            <p>Reachable, service {health.service}.</p>
            {health.configured ? (
              <p className="mt-1 text-green-700">All environment keys are set.</p>
            ) : (
              <p className="mt-1 text-amber-700">
                Missing: {health.missing_env.join(", ")}
              </p>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
