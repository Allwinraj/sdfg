import TopNav from '../components/TopNav'
import SideNav from '../components/SideNav'
import Icon from '../components/Icon'
import StatusPill from '../components/StatusPill'

const stats = [
  { icon: 'smart_toy', value: '12', label: 'Total Super Agents', note: '+3 this month', accent: 'text-tertiary-fixed-dim' },
  { icon: 'rocket_launch', value: '7', label: 'Published', note: 'Live in production', accent: 'text-primary-fixed-dim' },
  { icon: 'draft', value: '4', label: 'In Draft', note: '2 pending review', accent: 'text-on-surface-variant' },
  { icon: 'bolt', value: 'Budget vs Actual', label: 'Most Active Today', note: '48 runs today', accent: 'text-primary-fixed-dim' },
]

const tableRows = [
  { icon: 'bar_chart', name: 'Budget vs Actual', category: 'FP&A', runs: 48, time: '10 min ago', status: 'published' as const },
  { icon: 'account_balance', name: 'Bank Reconciliation', category: 'R2R', runs: 31, time: '25 min ago', status: 'published' as const },
  { icon: 'receipt_long', name: 'Invoice Processing', category: 'P2P', runs: 22, time: '1 hr ago', status: 'published' as const },
]

const activity = [
  { icon: 'check', text: 'Bank-to-GL run completed — 412 matches, 3 exceptions', time: '10:32', accent: 'text-tertiary-fixed-dim' },
  { icon: 'flag', text: 'Exception exc-10045 assigned to Marcus Chen', time: '10:25', accent: 'text-primary-fixed-dim' },
]

export default function Overview() {
  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <div className="flex flex-1 pt-16">
        <SideNav />
        <main className="flex-1 overflow-y-auto p-margin-mobile md:p-margin-desktop">
          <div className="mx-auto max-w-7xl space-y-md">
            <div className="mb-lg flex flex-col justify-between gap-sm md:flex-row md:items-center">
              <div>
                <h1 className="flex items-center gap-xs font-headline-lg text-headline-lg text-on-surface">
                  Welcome back, Elena <span className="text-2xl">👋</span>
                </h1>
                <p className="mt-base font-body-md text-on-surface-variant">
                  Here's your super agent workspace at a glance.
                </p>
              </div>
              <div className="flex items-center gap-xs rounded-full border border-primary-fixed-dim/20 bg-primary-fixed-dim/10 px-sm py-xs">
                <div className="h-2 w-2 animate-pulse rounded-full bg-primary-container" />
                <span className="font-mono-label text-mono-label uppercase tracking-wider text-primary-fixed-dim">
                  All Systems Operational
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-md md:grid-cols-2 lg:grid-cols-4">
              {stats.map((stat) => (
                <div
                  key={stat.label}
                  className="card-elevated group relative flex h-32 flex-col justify-between overflow-hidden rounded-xl p-md"
                >
                  <div className="absolute inset-0 bg-gradient-to-br from-white/5 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
                  <div className="relative z-10 flex items-start justify-between">
                    <div className="flex h-8 w-8 items-center justify-center rounded border border-white/5 bg-surface-container">
                      <Icon name={stat.icon} className={`text-sm ${stat.accent}`} />
                    </div>
                    <span className="font-mono-label text-mono-label text-tertiary-fixed-dim">
                      {stat.note}
                    </span>
                  </div>
                  <div className="relative z-10 mt-auto">
                    <div className="font-headline-md text-headline-md text-on-surface">
                      {stat.value}
                    </div>
                    <div className="mt-base font-mono-label text-mono-label uppercase tracking-wider text-on-surface-variant">
                      {stat.label}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="card-elevated mt-lg flex flex-col overflow-hidden rounded-xl">
              <div className="flex items-center justify-between border-b border-white/5 p-md">
                <h2 className="flex items-center gap-sm font-headline-md text-headline-md text-on-surface">
                  <Icon name="smart_toy" className="text-primary-fixed-dim" />
                  Super Agents
                </h2>
                <button className="rounded border border-white/20 px-sm py-xs font-label-md text-label-md text-on-surface transition-colors hover:bg-white/5">
                  Use-Case Agents
                </button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <tbody>
                    {tableRows.map((row) => (
                      <tr key={row.name} className="table-row-hover border-b border-white/5">
                        <td className="p-sm py-md">
                          <div className="flex items-center gap-sm">
                            <div className="flex h-10 w-10 items-center justify-center rounded bg-surface-container">
                              <Icon name={row.icon} className="text-secondary" />
                            </div>
                            <div>
                              <div className="font-label-md text-label-md text-on-surface">
                                {row.name}
                              </div>
                              <div className="mt-1 font-mono-label text-mono-label text-on-surface-variant">
                                {row.category}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="p-sm py-md text-right">
                          <div className="font-headline-md leading-none text-on-surface">
                            {row.runs}
                          </div>
                          <div className="mt-1 font-mono-label text-mono-label text-on-surface-variant">
                            RUNS
                          </div>
                        </td>
                        <td className="p-sm py-md text-right font-label-md text-label-md text-on-surface-variant">
                          {row.time}
                        </td>
                        <td className="p-sm py-md text-right">
                          <StatusPill status={row.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="mt-lg grid grid-cols-1 gap-md lg:grid-cols-2">
              <div className="card-elevated flex h-full flex-col rounded-xl p-md">
                <div className="mb-lg flex items-center justify-between">
                  <h3 className="font-headline-md text-headline-md text-on-surface">
                    Agent Status Breakdown
                  </h3>
                  <button className="rounded border border-white/20 px-sm py-xs font-mono-label text-mono-label uppercase tracking-wide text-on-surface transition-colors hover:bg-white/5">
                    This Month
                  </button>
                </div>
                <div className="flex flex-1 items-center justify-center gap-xl">
                  <div className="relative flex h-40 w-40 items-center justify-center rounded-full border-[12px] border-tertiary-fixed-dim">
                    <div className="text-center">
                      <div className="font-headline-lg text-headline-lg text-on-surface">
                        92%
                      </div>
                      <div className="mt-1 font-mono-label text-mono-label uppercase text-on-surface-variant">
                        Auto-Matched
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-sm">
                    {[
                      { label: 'Auto-matched', value: '92%', color: 'bg-tertiary-fixed-dim' },
                      { label: 'Needs review', value: '6%', color: 'bg-primary-fixed-dim' },
                      { label: 'Exceptions', value: '2%', color: 'bg-error' },
                    ].map((item) => (
                      <div key={item.label} className="flex items-center justify-between gap-xl">
                        <div className="flex items-center gap-xs font-label-md text-label-md text-on-surface-variant">
                          <div className={`h-2.5 w-2.5 rounded-sm ${item.color}`} />
                          {item.label}
                        </div>
                        <span className="font-headline-md text-headline-md text-on-surface">
                          {item.value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="card-elevated flex h-full flex-col rounded-xl p-md">
                <div className="mb-lg flex items-center justify-between">
                  <h3 className="font-headline-md text-headline-md text-on-surface">
                    Recent activity
                  </h3>
                  <button className="rounded border border-white/20 px-sm py-xs font-mono-label text-mono-label uppercase tracking-wide text-on-surface transition-colors hover:bg-white/5">
                    Today
                  </button>
                </div>
                <div className="flex flex-col gap-sm">
                  {activity.map((item) => (
                    <div key={item.text} className="flex items-center gap-md border-b border-white/5 py-sm">
                      <div className="flex h-6 w-6 items-center justify-center rounded bg-surface-container">
                        <Icon name={item.icon} className={`text-[16px] ${item.accent}`} />
                      </div>
                      <div className="flex-1 font-label-md text-label-md text-on-surface">
                        {item.text}
                      </div>
                      <div className="font-mono-label text-mono-label text-on-surface-variant">
                        {item.time}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
