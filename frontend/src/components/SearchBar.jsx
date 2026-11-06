import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../lib/api.js'

export default function SearchBar({ value, onChange, onSubmit, onSelectSuggestion, disabled, loading, compact = false }) {
  const [suggestions, setSuggestions] = useState([])
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const containerRef = useRef(null)

  useEffect(() => {
    const trimmed = (value || '').trim()
    if (trimmed.length < 2) {
      setSuggestions([])
      setOpen(false)
      return undefined
    }

    let active = true
    const timer = setTimeout(() => {
      api.suggest(trimmed, 6)
        .then((res) => {
          if (active && res.suggestions && res.suggestions.length > 0) {
            setSuggestions(res.suggestions)
            setOpen(true)
          } else if (active) {
            setSuggestions([])
            setOpen(false)
          }
        })
        .catch(() => {
          if (active) setSuggestions([])
        })
    }, 150)

    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [value])

  useEffect(() => {
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function handleKeyDown(event) {
    if (!open || suggestions.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((prev) => (prev + 1) % suggestions.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((prev) => (prev <= 0 ? suggestions.length - 1 : prev - 1))
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault()
      const selected = suggestions[activeIndex]
      setOpen(false)
      setActiveIndex(-1)
      if (onSelectSuggestion) onSelectSuggestion(selected)
      else {
        onChange(selected)
        onSubmit(event)
      }
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  function handlePick(item) {
    setOpen(false)
    setActiveIndex(-1)
    if (onSelectSuggestion) onSelectSuggestion(item)
    else {
      onChange(item)
    }
  }

  return (
    <div className="search-bar-wrapper" ref={containerRef}>
      <form className={`search-form ${compact ? 'compact' : ''}`} onSubmit={onSubmit} role="search">
        <Icon name="search" size={20} className="search-icon" />
        <label className="sr-only" htmlFor={compact ? 'header-search' : 'main-search'}>Search research papers</label>
        <input
          id={compact ? 'header-search' : 'main-search'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onFocus={() => { if (suggestions.length > 0) setOpen(true) }}
          onKeyDown={handleKeyDown}
          placeholder="Search a title, topic, or keyword..."
          maxLength={512}
          disabled={disabled || loading}
          autoComplete="off"
        />
        {value && <button className="search-clear" type="button" aria-label="Clear search" onClick={() => { onChange(''); setSuggestions([]); setOpen(false) }}>×</button>}
        <button className="search-submit" type="submit" disabled={disabled || loading || !value.trim()}>
          {loading ? <span className="button-spinner" aria-label="Searching" /> : <><span>Search papers</span><Icon name="arrow" size={16} /></>}
        </button>
      </form>

      {open && suggestions.length > 0 && (
        <ul className="search-suggestions-dropdown" role="listbox" aria-label="Search query suggestions">
          {suggestions.map((item, idx) => (
            <li
              key={item}
              role="option"
              aria-selected={idx === activeIndex}
              className={`suggestion-item ${idx === activeIndex ? 'is-active' : ''}`}
              onMouseDown={(e) => { e.preventDefault(); handlePick(item) }}
            >
              <Icon name="search" size={14} className="suggestion-icon" />
              <span className="suggestion-text">{item}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
