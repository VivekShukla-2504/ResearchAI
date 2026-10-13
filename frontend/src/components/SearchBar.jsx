import Icon from './Icon.jsx'

export default function SearchBar({ value, onChange, onSubmit, disabled, loading, compact = false }) {
  return (
    <form className={`search-form ${compact ? 'compact' : ''}`} onSubmit={onSubmit} role="search">
      <Icon name="search" size={20} className="search-icon" />
      <label className="sr-only" htmlFor={compact ? 'header-search' : 'main-search'}>Search research papers</label>
      <input
        id={compact ? 'header-search' : 'main-search'}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Search a title, topic, or keyword..."
        maxLength={512}
        disabled={disabled || loading}
      />
      {value && <button className="search-clear" type="button" aria-label="Clear search" onClick={() => onChange('')}>×</button>}
      <button className="search-submit" type="submit" disabled={disabled || loading || !value.trim()}>
        {loading ? <span className="button-spinner" aria-label="Searching" /> : <><span>Search papers</span><Icon name="arrow" size={16} /></>}
      </button>
    </form>
  )
}
