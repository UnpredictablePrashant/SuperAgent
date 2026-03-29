export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex min-h-screen max-w-5xl flex-col items-start justify-center gap-10 px-6 py-20">
        <div className="inline-flex items-center gap-2 rounded-full bg-emerald-500/10 px-4 py-2 text-sm text-emerald-300">
          Static Next.js Starter
        </div>
        <div className="space-y-4">
          <h1 className="text-4xl font-semibold leading-tight md:text-6xl">
            Launch a clean static site in minutes.
          </h1>
          <p className="max-w-2xl text-lg text-slate-300">
            This template ships with Tailwind, App Router, and a bold hero layout. Swap out the
            content, add sections, and deploy.
          </p>
        </div>
        <div className="flex flex-wrap gap-4">
          <button className="rounded-lg bg-emerald-500 px-6 py-3 text-sm font-semibold text-slate-900">
            Get Started
          </button>
          <button className="rounded-lg border border-slate-700 px-6 py-3 text-sm font-semibold text-slate-100">
            View Docs
          </button>
        </div>
        <div className="grid w-full gap-6 pt-10 md:grid-cols-3">
          {[
            { title: "Fast Setup", desc: "App Router + Tailwind pre-wired." },
            { title: "Responsive", desc: "Layout scales to every device." },
            { title: "Exportable", desc: "Configured for static export." },
          ].map((item) => (
            <div key={item.title} className="rounded-xl bg-slate-900/60 p-6">
              <h3 className="text-lg font-semibold">{item.title}</h3>
              <p className="mt-2 text-sm text-slate-300">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
