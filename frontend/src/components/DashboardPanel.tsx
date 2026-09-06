import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useThemeVar } from '../lib/useThemeVar'
import type { DashboardView, DashboardWidget } from '../types/nexus'

const COLORS = ['#FCA311', '#14213D', '#E5E5E5', '#000000', '#FCA311']

function useCountUp(value: number | undefined) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (value == null || Number.isNaN(value)) {
      setShown(0)
      return
    }
    const start = performance.now()
    const from = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 600)
      setShown(from + (value - from) * t)
      if (t < 1) requestAnimationFrame(tick)
    }
    const id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [value])
  return shown
}

function Kpi({ widget }: { widget: DashboardWidget }) {
  const shown = useCountUp(typeof widget.value === 'number' ? widget.value : undefined)
  const display =
    typeof widget.value === 'number'
      ? widget.unit === '%'
        ? shown.toFixed(1)
        : Number.isInteger(widget.value)
          ? Math.round(shown)
          : shown.toFixed(1)
      : widget.value ?? '—'
  return (
    <div className="neu-raised lift rail rounded-2xl p-5 pl-6" title={widget.explain?.why}>
      <div className="font-mono-label uppercase tracking-wider text-on-surface-variant">{widget.title}</div>
      <div className="mt-2 font-headline-lg text-headline-lg text-accent-grad">
        {display}
        {widget.unit ? <span className="ml-1 text-base text-on-surface-variant">{widget.unit}</span> : null}
      </div>
      {widget.subtitle ? <div className="mt-1 font-body-md text-sm text-on-surface-variant">{widget.subtitle}</div> : null}
      {widget.delta != null ? (
        <span className="chip chip-accent mt-2 font-mono-label">Δ {widget.delta}</span>
      ) : null}
      {widget.trend?.length ? (
        <div className="mt-2 h-8">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={widget.trend.map((value, index) => ({ name: index, value }))}>
              <Line type="monotone" dataKey="value" stroke="#FCA311" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </div>
  )
}

function ChartFrame({ widget, children }: { widget: DashboardWidget; children: ReactNode }) {
  return (
    <div className="neu-raised lift flex h-80 flex-col rounded-2xl p-4" title={widget.explain?.why}>
      <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
        <div className="font-label-md text-on-surface">{widget.title}</div>
        {widget.source_port ? <span className="chip font-mono-label">{widget.source_port}</span> : null}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  )
}

function useTooltipStyle() {
  const card = useThemeVar('--ey-card', '#ffffff')
  const line = useThemeVar('--ey-line', '#e5e5e5')
  const ink = useThemeVar('--ey-ink', '#14213d')
  return useMemo(
    () => ({
      contentStyle: {
        background: card,
        border: `1px solid ${line}`,
        borderRadius: 12,
        color: ink,
        fontSize: 12,
      },
      labelStyle: { color: ink },
      itemStyle: { color: ink },
    }),
    [card, line, ink],
  )
}

export default function DashboardPanel({ dashboard }: { dashboard: DashboardView | null }) {
  const widgets = dashboard?.widgets || []
  const grid = useThemeVar('--ey-grid', '#E5E5E5')
  const ink = useThemeVar('--ey-ink', '#14213D')
  const tip = useTooltipStyle()
  const kpis = useMemo(() => widgets.filter((w) => w.catalog_id === 'kpi_card' || w.catalog_id === 'rate_gauge'), [widgets])
  const narratives = useMemo(() => widgets.filter((w) => w.catalog_id === 'narrative_card'), [widgets])
  const charts = useMemo(
    () =>
      widgets.filter((w) =>
        ['bar_chart', 'pie_chart', 'donut_chart', 'line_chart', 'area_chart', 'grouped_bar_chart', 'stacked_bar_chart', 'variance_chart'].includes(
          w.catalog_id,
        ),
      ),
    [widgets],
  )
  const tables = useMemo(
    () => widgets.filter((w) => ['insight_table', 'breakdown_table', 'exception_table', 'action_list'].includes(w.catalog_id)),
    [widgets],
  )

  if (!dashboard) {
    return (
      <div className="space-y-4 p-6">
        <p className="font-body-md text-on-surface-variant">Run the pipeline to build this dashboard.</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton h-28" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="skeleton h-64" />
          <div className="skeleton h-64" />
        </div>
      </div>
    )
  }

  const profile = dashboard.profile

  return (
    <div className="h-full min-h-0 space-y-4 overflow-y-auto overflow-x-hidden p-4">
      <div className="neu-inset rail rounded-2xl px-5 py-3">
        <div className="font-headline-sm text-accent-grad">{profile?.name || 'Run dashboard'}</div>
        <p className="mt-1 font-body-md text-sm text-on-surface-variant">
          {profile?.purpose || 'Charts follow this use case and the columns in the run.'}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {profile?.status ? <span className="chip chip-accent font-mono-label">{profile.status}</span> : null}
          {profile?.totals != null ? <span className="chip font-mono-label">{profile.totals} rows</span> : null}
          <span className="chip font-mono-label">{widgets.length} widgets</span>
        </div>
      </div>
      <div className="stagger grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((widget) => (
          <Kpi key={`${widget.title}-${widget.source_port}`} widget={widget} />
        ))}
      </div>
      {narratives.map((widget) => (
        <div
          key={widget.title}
          className="neu-raised rail rounded-2xl p-5 pl-6 font-body-md text-on-surface"
        >
          {widget.text || widget.title}
        </div>
      ))}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {charts.map((widget) => {
          const data = (widget.data || []) as Record<string, unknown>[]
          if (widget.catalog_id === 'bar_chart' || widget.catalog_id === 'variance_chart') {
            return (
              <ChartFrame key={widget.title} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    <Bar dataKey="value" fill="#FCA311" radius={[8, 8, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'grouped_bar_chart') {
            return (
              <ChartFrame key={widget.title} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    <Bar dataKey="actual" fill="#FCA311" />
                    <Bar dataKey="expected" fill="#14213D" />
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'stacked_bar_chart') {
            const series = widget.series || ['value']
            return (
              <ChartFrame key={widget.title} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                    <YAxis tick={{ fill: ink, fontSize: 11 }} />
                    <Tooltip {...tip} />
                    {series.map((key, index) => (
                      <Bar key={key} dataKey={key} stackId="a" fill={COLORS[index % COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          if (widget.catalog_id === 'line_chart' || widget.catalog_id === 'area_chart') {
            return (
              <ChartFrame key={widget.title} widget={widget}>
                <ResponsiveContainer width="100%" height="100%">
                  {widget.catalog_id === 'area_chart' ? (
                    <AreaChart data={data}>
                      <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                      <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                      <YAxis tick={{ fill: ink, fontSize: 11 }} />
                      <Tooltip {...tip} />
                      <Area type="monotone" dataKey="value" stroke="#FCA311" fill="#FCA311" fillOpacity={0.25} />
                    </AreaChart>
                  ) : (
                    <LineChart data={data}>
                      <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                      <XAxis dataKey="name" tick={{ fill: ink, fontSize: 11 }} />
                      <YAxis tick={{ fill: ink, fontSize: 11 }} />
                      <Tooltip {...tip} />
                      <Line type="monotone" dataKey="value" stroke="#FCA311" strokeWidth={2} dot={false} />
                    </LineChart>
                  )}
                </ResponsiveContainer>
              </ChartFrame>
            )
          }
          const donut = widget.catalog_id === 'donut_chart'
          return (
            <ChartFrame key={widget.title} widget={widget}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data} dataKey="value" nameKey="name" innerRadius={donut ? 48 : 0} outerRadius={80}>
                    {data.map((_, index) => (
                      <Cell key={index} fill={COLORS[index % COLORS.length]} stroke={ink} />
                    ))}
                  </Pie>
                  <Tooltip {...tip} />
                </PieChart>
              </ResponsiveContainer>
            </ChartFrame>
          )
        })}
        {tables.map((widget) => {
          if (widget.catalog_id === 'action_list') {
            return (
              <div key={widget.title} className="neu-raised lift rounded-2xl p-4">
                <div className="mb-3 font-label-md text-on-surface">{widget.title}</div>
                <ul className="stagger space-y-2">
                  {(widget.actions || []).map((item) => (
                    <li key={item} className="neu-inset rail rounded-xl px-4 py-2 font-body-md text-on-surface">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )
          }
          return (
            <div key={widget.title} className="neu-raised lift flex max-h-80 min-h-0 flex-col overflow-hidden rounded-2xl p-4">
              <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
                <div className="font-label-md text-on-surface">{widget.title}</div>
                <span className="chip font-mono-label">{(widget.rows || []).length} rows</span>
              </div>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="data-table w-full text-left font-body-md text-sm">
                  <thead className="sticky top-0 z-10 bg-surface">
                    <tr>
                      {(widget.columns || []).map((col) => (
                        <th
                          key={col}
                          className="border-b border-[var(--ey-line)] bg-surface pb-2 pr-3 font-mono-label uppercase tracking-wider text-on-surface-variant"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(widget.rows || []).map((row, index) => (
                      <tr key={index} className="border-t border-[var(--ey-line)] transition-colors">
                        {(widget.columns || []).map((col) => (
                          <td key={col} className="py-2 pr-3 text-on-surface">
                            {String(row[col] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
