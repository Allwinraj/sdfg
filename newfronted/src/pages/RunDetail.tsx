import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Icon from '../components/Icon'
import IconNav from '../components/IconNav'
import RunTrace from '../components/RunTrace'
import { api } from '../lib/api'
import type { RunSnapshot } from '../types/nexus'

export default function RunDetail() {
  const { runId } = useParams()
  const [snap, setSnap] = useState<RunSnapshot | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!runId) return
    api
      .getSnapshot(runId)
      .then(setSnap)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load run'))
  }, [runId])

  const artifacts = snap?.run.artifacts ?? []
  const names = artifacts.map((path) => path.split(/[/\\]/).pop() ?? path)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-container-lowest">
      <header className="z-20 flex h-16 shrink-0 items-center justify-between border-b border-white/5 bg-surface/80 px-gutter backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <Link to="/architect/create" className="rounded-lg p-2 text-on-surface-variant hover:bg-white/5" aria-label="Back to Architect">
            <Icon name="arrow_back" />
          </Link>
          <h1 className="font-headline-md text-on-surface">Studio run</h1>
          {snap && (
            <span className="font-mono-label text-on-surface-variant">
              {snap.run.id.slice(0, 8)} · {snap.run.status}
            </span>
          )}
        </div>
        {snap?.run.extra?.source === 'library' && (
          <Link
            to={`/architect/create?pipeline=${snap.run.pipeline_id}`}
            className="font-label-md text-primary-fixed-dim hover:underline"
          >
            Open pipeline
          </Link>
        )}
      </header>
      <div className="flex flex-1 overflow-hidden">
        <IconNav />
        <main className="flex-1 overflow-y-auto p-gutter">
          {error && <p className="font-body-md text-red-300">{error}</p>}
          {!snap && !error && <p className="font-body-md text-on-surface-variant">Loading trace…</p>}
          {snap && (
            <div className="mx-auto max-w-4xl space-y-8">
              <section>
                <h2 className="mb-2 font-label-md uppercase tracking-wider text-on-surface-variant">Summary</h2>
                <p className="font-body-md text-on-surface-variant">
                  Pipeline {snap.run.pipeline_id.slice(0, 8)} · version {snap.run.pipeline_version}
                  {snap.run.started_at ? ` · started ${snap.run.started_at}` : ''}
                </p>
                {snap.run.error && <p className="mt-2 text-red-300">{snap.run.error}</p>}
              </section>
              {names.length > 0 && (
                <section>
                  <h2 className="mb-2 font-label-md uppercase tracking-wider text-on-surface-variant">Downloads</h2>
                  <div className="flex flex-wrap gap-3">
                    {names.map((name) => (
                      <a
                        key={name}
                        href={api.artifactUrl(snap.run.id, name)}
                        className="rounded-lg border border-primary-fixed-dim/30 px-4 py-2 font-label-md text-primary-fixed-dim hover:bg-white/5"
                      >
                        {name}
                      </a>
                    ))}
                  </div>
                </section>
              )}
              <section>
                <h2 className="mb-3 font-label-md uppercase tracking-wider text-on-surface-variant">Step trace</h2>
                <RunTrace steps={snap.run.steps} />
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
