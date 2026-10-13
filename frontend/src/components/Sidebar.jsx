import Icon from './Icon.jsx'

const links = [
  { id: 'discover', label: 'Discover', icon: 'compass' },
  { id: 'saved', label: 'Saved papers', icon: 'bookmark' },
  { id: 'history', label: 'Search history', icon: 'clock' },
  { id: 'interests', label: 'Research interests', icon: 'spark' },
]

export default function Sidebar({ activeView, onNavigate, mongoAvailable }) {
  return (
    <aside className="sidebar">
      <a className="brand" href="#discover" onClick={(event) => { event.preventDefault(); onNavigate('discover') }}>
        <span className="brand-mark"><Icon name="orbit" size={22} /></span>
        <span className="brand-copy"><strong>ResearchPaper</strong><small>AI discovery workspace</small></span>
      </a>

      <div className="sidebar-label">WORKSPACE</div>
      <nav className="side-nav" aria-label="Main navigation">
        {links.map((link) => (
          <button
            className={`nav-link ${activeView === link.id ? 'active' : ''}`}
            key={link.id}
            onClick={() => onNavigate(link.id)}
            aria-current={activeView === link.id ? 'page' : undefined}
          >
            <Icon name={link.icon} size={18} />
            <span>{link.label}</span>
            {link.id !== 'discover' && !mongoAvailable && <span className="nav-lock" aria-label="Activity storage unavailable">·</span>}
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />
      <div className="sidebar-note">
        <span className="sidebar-note-icon"><Icon name="spark" size={16} /></span>
        <strong>Find your next idea</strong>
        <p>Search a title, method, or research question to explore related work.</p>
        <button onClick={() => onNavigate('discover')}>Start exploring <Icon name="arrow" size={14} /></button>
      </div>
      <div className="sidebar-footer"><span className="status-dot" />{mongoAvailable ? 'Activity storage connected' : 'Local research workspace'}</div>
    </aside>
  )
}
