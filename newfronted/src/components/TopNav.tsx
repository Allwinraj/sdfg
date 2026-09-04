import { Link, useLocation } from 'react-router-dom'
import Icon from './Icon'

export default function TopNav() {
  const location = useLocation()
  const isArchitect = location.pathname.startsWith('/architect')

  return (
    <header className="fixed top-0 z-50 w-full border-b border-white/10 bg-surface/80 shadow-[0_20px_40px_rgba(0,240,255,0.1)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-gutter">
        <Link
          to="/"
          className="flex items-center gap-2 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-dashed focus-visible:outline-primary-fixed-dim"
        >
          <Icon name="dataset" className="text-primary-fixed-dim" fill />
          <span className="font-headline-sm text-headline-sm font-bold tracking-tight text-primary-fixed-dim">
            Nexus 2.0
          </span>
        </Link>

        <nav className="hidden gap-8 md:flex" aria-label="Primary">
          <Link
            to="/architect"
            className={`rounded-md px-4 py-2 font-label-md text-label-md transition-all duration-300 ${
              isArchitect
                ? 'border-b-2 border-primary-fixed-dim text-primary-fixed-dim'
                : 'text-on-surface-variant hover:bg-white/5 hover:text-primary-fixed-dim'
            }`}
          >
            Architect
          </Link>
          <Link
            to="/agents"
            className={`rounded-md px-4 py-2 font-label-md text-label-md transition-all duration-300 ${
              location.pathname === '/agents'
                ? 'border-b-2 border-primary-fixed-dim text-primary-fixed-dim'
                : 'text-on-surface-variant hover:bg-white/5 hover:text-primary-fixed-dim'
            }`}
          >
            Agents
          </Link>
        </nav>

        <Link
          to="/architect"
          className="rounded-lg border border-outline-variant bg-surface-container-high px-4 py-2 font-label-md text-label-md text-on-surface transition-all duration-300 hover:border-primary-fixed-dim"
        >
          Launch Architect
        </Link>
      </div>
    </header>
  )
}
