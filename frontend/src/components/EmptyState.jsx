import Icon from './Icon.jsx'

export default function EmptyState({ icon = 'search', title, children, action }) {
  return (
    <div className="empty-state">
      <div className="empty-icon"><Icon name={icon} size={23} /></div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}
