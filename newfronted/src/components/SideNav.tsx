import { NavLink } from 'react-router-dom'
import Icon from './Icon'

const items = [
  { to: '/architect', icon: 'dashboard', label: 'Overview' },
  { to: '/architect/skills', icon: 'account_tree', label: 'Skill Library' },
  { to: '/architect/create', icon: 'smart_toy', label: 'Create Agent' },
  { to: '/agents', icon: 'grid_view', label: 'Library' },
]

export default function SideNav() {
  return (
    <aside className="hidden w-64 flex-shrink-0 flex-col gap-sm border-r border-white/10 bg-surface p-sm md:flex">
      <nav className="mt-lg flex flex-col gap-xs" aria-label="Architect studio">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-sm rounded border px-sm py-xs font-label-md text-label-md transition-colors ${
                isActive
                  ? 'border-white/10 bg-white/5 text-primary-fixed-dim'
                  : 'border-transparent text-on-surface-variant hover:bg-white/5 hover:text-on-surface'
              }`
            }
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
