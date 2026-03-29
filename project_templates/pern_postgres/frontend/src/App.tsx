import { useEffect, useState } from "react";
import { fetchHealth } from "./lib/api";

export default function App() {
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    fetchHealth()
      .then((data) => setStatus(data.status))
      .catch(() => setStatus("error"));
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="text-3xl font-semibold">PERN Template Ready</h1>
        <p className="text-slate-300">
          Frontend + API scaffold is live. Health status:{" "}
          <span className="font-semibold text-emerald-400">{status}</span>
        </p>
        <div className="rounded-xl bg-slate-900/60 px-6 py-4 text-left text-sm text-slate-200">
          <p className="font-medium text-slate-100">Next steps</p>
          <ul className="mt-2 list-disc space-y-1 pl-4">
            <li>Update Prisma schema and run migrations.</li>
            <li>Replace sample routes with real business logic.</li>
            <li>Build your product UI in React.</li>
          </ul>
        </div>
      </main>
    </div>
  );
}
