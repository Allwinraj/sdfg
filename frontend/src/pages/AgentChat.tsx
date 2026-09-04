import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import TopNav from '../components/TopNav'
import Icon from '../components/Icon'
import { api } from '../lib/api'
import type { FileSlot, Pipeline, RunStreamEvent, RunView } from '../types/nexus'

interface ThinkingLine {
  node_id: string
  agent: string
  label: string
  status: 'running' | 'ok' | 'skipped' | 'error'
  message: string
}

interface Bubble {
  id: string
  role: 'assistant' | 'user'
  content: string
  files?: string[]
  thinking?: ThinkingLine[]
  run?: RunView
}

function statusIcon(status: ThinkingLine['status'] | string) {
  if (status === 'running') return 'progress_activity'
  if (status === 'ok') return 'check_circle'
  if (status === 'skipped') return 'skip_next'
  if (status === 'error') return 'error'
  return 'circle'
}

export default function AgentChat() {
  const { agentId } = useParams()
  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [slots, setSlots] = useState<FileSlot[]>([])
  const [staged, setStaged] = useState<string[]>([])
  const [missing, setMissing] = useState<string[]>([])
  const [messages, setMessages] = useState<Bubble[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [run, setRun] = useState<RunView | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const running = useRef(false)

  useEffect(() => {
    if (!agentId) return
    api
      .getPipeline(agentId)
      .then((body) => {
        setPipeline(body)
        const nextSlots = body.file_slots || []
        setSlots(nextSlots)
        setMissing(body.missing_files || nextSlots.map((s) => s.filename))
        const names = nextSlots.map((s) => s.filename).join(', ')
        setMessages([
          {
            id: 'hello',
            role: 'assistant',
            content:
              `This is ${body.name}. Attach the same file names as design time` +
              (names ? ` (${names})` : '') +
              `. The pipeline starts when every named file is attached.\n\n` +
              `After the report lands, ask how any step or calculation was done.`,
          },
        ])
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Could not load agent'))
  }, [agentId])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const startRun = async () => {
    if (!agentId || running.current) return
    running.current = true
    setBusy(true)
    setError(null)
    const thinkingId = `think-${Date.now()}`
    setMessages((prev) => [
      ...prev,
      { id: thinkingId, role: 'assistant', content: 'Running the pipeline…', thinking: [] },
    ])
    const applyEvent = (event: RunStreamEvent) => {
      setMessages((prev) =>
        prev.map((message) => {
          if (message.id !== thinkingId) return message
          const lines = [...(message.thinking || [])]
          if (event.type === 'node_start' && event.node_id) {
            const existing = lines.findIndex((line) => line.node_id === event.node_id)
            const next: ThinkingLine = {
              node_id: event.node_id,
              agent: event.agent || '',
              label: event.label || event.agent || event.node_id,
              status: 'running',
              message: event.message || `Running ${event.label || event.agent}`,
            }
            if (existing >= 0) lines[existing] = next
            else lines.push(next)
          }
          if (event.type === 'node_finish' && event.node_id) {
            const existing = lines.findIndex((line) => line.node_id === event.node_id)
            const next: ThinkingLine = {
              node_id: event.node_id,
              agent: event.agent || '',
              label: event.label || event.agent || event.node_id,
              status: (event.status as ThinkingLine['status']) || 'ok',
              message: event.summary || event.message || event.skip_reason || event.error || '',
            }
            if (existing >= 0) lines[existing] = next
            else lines.push(next)
          }
          return { ...message, thinking: lines }
        }),
      )
    }
    try {
      const next = await api.runLibraryStream(agentId, applyEvent)
      setRun(next)
      setMessages((prev) =>
        prev.map((message) =>
          message.id === thinkingId
            ? {
                ...message,
                content: next.status === 'completed' ? 'Pipeline finished.' : `Run ${next.status}.`,
                run: next,
                thinking:
                  next.steps.map((step) => ({
                    node_id: step.node_id,
                    agent: step.agent,
                    label: step.node_id,
                    status: step.status,
                    message: step.summary || step.skip_reason || step.error || step.status,
                  })) || message.thinking,
              }
            : message,
        ),
      )
    } catch (err) {
      const text = err instanceof Error ? err.message : 'Run failed'
      setError(text)
      setMessages((prev) =>
        prev.map((message) =>
          message.id === thinkingId ? { ...message, content: `Run failed. ${text}` } : message,
        ),
      )
    } finally {
      running.current = false
      setBusy(false)
    }
  }

  const onFiles = async (list: FileList | File[]) => {
    if (!agentId || !list.length) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.uploadLibraryFiles(agentId, list)
      setStaged(result.written)
      setMissing(result.missing_files)
      setSlots(result.file_slots)
      setMessages((prev) => [
        ...prev,
        {
          id: `up-${Date.now()}`,
          role: 'user',
          content: 'Attached working set',
          files: result.written,
        },
        {
          id: `up-ack-${Date.now()}`,
          role: 'assistant',
          content: result.missing_files.length
            ? `Got ${result.written.join(', ')}. Still need: ${result.missing_files.join(', ')}.`
            : `Got ${result.written.join(', ')}. Starting the pipeline.`,
        },
      ])
      if (!result.missing_files.length) {
        setBusy(false)
        await startRun()
        return
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      if (!running.current) setBusy(false)
    }
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!agentId || busy) return
    const text = draft.trim()
    setDraft('')
    if (run && text) {
      setMessages((prev) => [...prev, { id: `q-${Date.now()}`, role: 'user', content: text }])
      setBusy(true)
      setError(null)
      try {
        const body = await api.askLibrary(agentId, run.id, text)
        setMessages((prev) => [...prev, { id: `a-${Date.now()}`, role: 'assistant', content: body.answer }])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not answer')
      } finally {
        setBusy(false)
      }
      return
    }
    if (!run) {
      if (text) {
        setMessages((prev) => [...prev, { id: `q-${Date.now()}`, role: 'user', content: text }])
      }
      await startRun()
    }
  }

  const accept = slots.map((s) => s.filename.replace(/^.*(\.[^.]+)$/, '*$1')).join(',') || '.csv,.xlsx,.pdf,.txt,.md'

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopNav />
      <div className="flex min-h-0 flex-1 pt-16">
        <aside className="flex w-72 shrink-0 flex-col border-r border-white/10 bg-surface-container p-5">
          <Link to="/agents" className="mb-4 font-label-md text-primary-fixed-dim hover:underline">
            ← Library
          </Link>
          <h1 className="font-headline-md text-on-surface">{pipeline?.name || 'Agent'}</h1>
          <p className="mt-1 font-mono-label text-on-surface-variant">{pipeline?.version}</p>
          <h2 className="mt-6 font-label-md text-on-surface">Required files (same names)</h2>
          <ul className="mt-3 space-y-2">
            {slots.map((slot) => {
              const ready = staged.includes(slot.filename) || !missing.includes(slot.filename)
              return (
                <li
                  key={slot.filename}
                  className="rounded-lg border border-white/10 bg-surface-container-high px-3 py-2 font-body-md text-on-surface"
                >
                  <div className="flex items-center gap-2">
                    <Icon name={ready ? 'check_circle' : 'description'} className="text-[16px] text-primary-fixed-dim" />
                    <span>{slot.filename}</span>
                  </div>
                  <div className="pl-6 font-mono-label text-[11px] text-on-surface-variant">
                    {slot.kind === 'knowledge' ? 'Policy' : 'Input'} · {slot.label}
                  </div>
                </li>
              )
            })}
            {slots.length === 0 && (
              <li className="font-body-md text-on-surface-variant">No named files on this DAG — Send still runs it.</li>
            )}
          </ul>
          {run && (
            <div className="mt-6 space-y-2">
              {run.artifacts.map((name) => (
                <a
                  key={name}
                  href={api.artifactUrl(run.id, name)}
                  className="block font-label-md text-primary-fixed-dim hover:underline"
                >
                  Download {name}
                </a>
              ))}
              <Link to={`/runs/${run.id}`} className="block font-label-md text-on-surface hover:underline">
                Open trace
              </Link>
            </div>
          )}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col bg-surface-container-lowest">
          <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-6">
            {messages.map((message) => (
              <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[80%] whitespace-pre-wrap rounded-2xl border p-4 font-body-md ${
                    message.role === 'assistant'
                      ? 'border-white/5 bg-surface-container-high text-on-surface-variant'
                      : 'border-white/10 bg-surface-variant text-on-surface'
                  }`}
                >
                  {message.content}
                  {message.files?.length ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {message.files.map((name) => (
                        <span
                          key={name}
                          className="rounded-lg border border-white/15 px-2 py-1 font-label-md text-primary-fixed-dim"
                        >
                          {name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {message.thinking?.length ? (
                    <ol className="mt-3 space-y-2">
                      {message.thinking.map((line) => (
                        <li key={line.node_id} className="flex gap-2 rounded-lg border border-white/10 px-3 py-2">
                          <Icon
                            name={statusIcon(line.status)}
                            className={`mt-0.5 text-[18px] ${
                              line.status === 'running' ? 'animate-spin text-primary-fixed-dim' : ''
                            }`}
                          />
                          <div>
                            <div className="font-label-md text-on-surface">
                              {line.label} · {line.status}
                            </div>
                            <div className="font-body-md text-on-surface-variant">{line.message}</div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  {message.run?.artifacts?.length ? (
                    <div className="mt-3 space-y-1">
                      {message.run.artifacts.map((name) => (
                        <a
                          key={name}
                          href={api.artifactUrl(message.run!.id, name)}
                          className="block font-label-md text-primary-fixed-dim hover:underline"
                        >
                          Download {name}
                        </a>
                      ))}
                      <Link to={`/runs/${message.run.id}`} className="block font-label-md text-on-surface hover:underline">
                        Open trace
                      </Link>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
            {error && <p className="font-body-md text-red-300">{error}</p>}
          </div>
          <div className="space-y-3 border-t border-white/5 p-4">
            <button
              type="button"
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-primary-fixed-dim/30 py-2.5 font-label-md text-primary-fixed-dim"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
            >
              <Icon name="upload_file" className="text-[18px]" />
              Attach files (same names)
            </button>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              multiple
              accept={accept}
              onChange={(e) => {
                if (e.target.files?.length) void onFiles(e.target.files)
                e.target.value = ''
              }}
            />
            <form onSubmit={onSubmit} className="relative flex items-center">
              <input
                className="w-full rounded-xl border border-white/10 bg-surface py-3 pl-4 pr-12 font-body-md text-on-surface"
                placeholder={run ? 'Ask how a calculation was done…' : 'Send to run the pipeline…'}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={busy}
              />
              <button type="submit" className="absolute right-3 text-primary-fixed-dim" disabled={busy} aria-label="Send">
                <Icon name="send" />
              </button>
            </form>
            <span className="px-1 font-mono-label text-on-surface-variant/60">
              {busy ? 'Running pipeline…' : run ? 'Follow-up questions after the run' : 'Attach files to start'}
            </span>
          </div>
        </main>
      </div>
    </div>
  )
}
