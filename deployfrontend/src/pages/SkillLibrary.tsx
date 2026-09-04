import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import TopNav from '../components/TopNav'
import SideNav from '../components/SideNav'
import Icon from '../components/Icon'
import InspectionModal, { type InspectableAgent } from '../components/InspectionModal'
import { api } from '../lib/api'
import { agentIcon } from '../data/flowNodes'
import type { AgentCatalogEntry, AgentKind } from '../types/nexus'

const portTone = (port: string) => {
  if (port === 'matched' || port === 'approved' || port === 'default') return 'gold' as const
  if (port === 'residuals' || port === 'flagged') return 'cyan' as const
  if (port === 'exceptions' || port === 'escalated') return 'error' as const
  return 'muted' as const
}

function toInspectable(entry: AgentCatalogEntry): InspectableAgent {
  const outs = entry.ports?.out ?? ['default']
  return {
    name: entry.label,
    icon: agentIcon(entry.name),
    description: entry.summary,
    badge: 'Specialist',
    modeDetails: entry.modes.map((mode, i) => ({
      title: mode,
      icon: 'tune',
      description: `Mode available on the ${entry.label} agent.`,
      highlight: i === 0,
    })),
    topology: {
      inputs: [{ icon: 'input', label: 'Upstream envelopes' }],
      outputTitle: 'OUTPUT PORTS',
      outputs: outs.map((label) => ({ label, tone: portTone(label) })),
    },
  }
}

export default function SkillLibrary() {
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<AgentCatalogEntry[]>([])
  const [selected, setSelected] = useState<InspectableAgent | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listAgents()
      .then((body) => setCatalog(body.agents))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load catalog'))
  }, [])

  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <div className="flex flex-1 pt-16">
        <SideNav />
        <main className="flex-1 overflow-y-auto p-gutter md:p-margin-desktop">
          <div className="mx-auto max-w-6xl">
            <header className="mb-12">
              <h1 className="mb-2 font-display-lg text-display-lg text-on-surface">Skill Library</h1>
              <p className="max-w-2xl font-body-lg text-body-lg text-on-surface-variant">
                The five specialist agents Nexus can compose. Deploy opens an empty Architect canvas — it does not inject a hardcoded graph.
              </p>
            </header>
            {error && <p className="mb-6 font-body-md text-red-300">{error}</p>}
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-6">
              {catalog.map((agent) => (
                <div
                  key={agent.name}
                  className="glass-card group flex flex-col justify-between rounded-xl p-6 md:col-span-1 lg:col-span-2"
                >
                  <div>
                    <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-white/10 bg-surface-container-high text-primary-fixed-dim">
                      <Icon name={agentIcon(agent.name as AgentKind)} className="text-[24px]" />
                    </div>
                    <h3 className="mb-2 font-headline-md text-headline-md text-on-surface">{agent.label}</h3>
                    <p className="mb-2 font-mono-label text-on-surface-variant">{agent.modes.join(' · ')}</p>
                    <p className="mb-6 line-clamp-3 font-body-md text-body-md text-on-surface-variant">{agent.summary}</p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setSelected(toInspectable(agent))}
                      className="flex flex-1 items-center justify-center gap-2 rounded border border-white/20 py-2 font-label-md text-on-surface hover:border-primary-fixed-dim"
                    >
                      Inspect
                    </button>
                    <button
                      onClick={() => navigate('/architect/create')}
                      className="flex flex-1 items-center justify-center gap-2 rounded bg-primary-container py-2 font-label-md text-on-primary-container"
                    >
                      Deploy to Pipeline
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
      {selected && (
        <InspectionModal agent={selected} onClose={() => setSelected(null)} deployTo="/architect/create" />
      )}
    </div>
  )
}
