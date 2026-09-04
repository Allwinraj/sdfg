import { NavLink } from 'react-router-dom'
import Icon from './Icon'

const items = [
  { to: '/architect', icon: 'dashboard', label: 'Overview' },
  { to: '/architect/skills', icon: 'account_tree', label: 'Skill Library' },
  { to: '/architect/create', icon: 'smart_toy', label: 'Create Agent' },
  { to: '/agents', icon: 'grid_view', label: 'Library' },
]

export default function IconNav() {
  return (
    <nav
      className="z-20 flex w-16 shrink-0 flex-col items-center gap-2 border-r border-white/10 bg-surface-container py-4"
      aria-label="Architect studio"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          aria-label={item.label}
          className={({ isActive }) =>
            `group relative flex h-11 w-11 items-center justify-center rounded-lg transition-colors ${
              isActive
                ? 'bg-white/5 text-primary-fixed-dim'
                : 'text-on-surface-variant hover:bg-white/5 hover:text-on-surface'
            }`
          }
        >
          <Icon name={item.icon} className="text-[22px]" />
          <span className="pointer-events-none absolute left-full z-50 ml-3 whitespace-nowrap rounded border border-white/10 bg-surface-container-highest px-2.5 py-1 font-mono-label text-on-surface opacity-0 transition-opacity group-hover:opacity-100">
            {item.label}
          </span>
        </NavLink>
      ))}
    </nav>
  )
}
