import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './lib/api.js'
import DetailPanel from './components/DetailPanel.jsx'
import EmptyState from './components/EmptyState.jsx'
import Icon from './components/Icon.jsx'
import PaperCard from './components/PaperCard.jsx'
import SearchBar from './components/SearchBar.jsx'
import Sidebar from './components/Sidebar.jsx'
import { requestBookmarkChange } from './lib/bookmarks.js'

const viewNames = {
  discover: 'Discover research',
  saved: 'Saved papers',
  history: 'Search history',
  interests: 'Research interests',
}

function InlineNotice({ kind = 'info', children, action }) {
  return <div className={`notice notice-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}{action}</div>
}

function ActivityGate({ available, loading, error, onRetry, children }) {
  if (available === false) return <UnavailableActivity />
  if (available === null || loading) return <LoadingList />
  if (error) return <EmptyState icon="clock" title="Could not load saved activity">
    {error}<button className="secondary-action" type="button" onClick={onRetry}>Retry</button>
  </EmptyState>
  return children
}

function PageHeading({ eyebrow, title, description, trailing }) {
  return (
    <div className="page-heading">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description && <p>{description}</p>}</div>
      {trailing}
    </div>
  )
}

function initialTheme() {
  try {
    const saved = window.localStorage.getItem('researchpaper-ai.theme')
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  } catch {
    // Theme still follows the operating system when browser storage is blocked.
  }
  return 'system'
}

function App() {
  const [themeMode, setThemeMode] = useState(initialTheme)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  const [view, setView] = useState('discover')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [hasSearched, setHasSearched] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [backendAvailable, setBackendAvailable] = useState(null)
  const [health, setHealth] = useState(null)
  const [activityAvailable, setActivityAvailable] = useState(null)
  const [activityError, setActivityError] = useState('')
  const [selectedPaperId, setSelectedPaperId] = useState(null)
  const [bookmarks, setBookmarks] = useState([])
  const [history, setHistory] = useState([])
  const [interests, setInterests] = useState([])
  const [interestDraft, setInterestDraft] = useState('')
  const [interestInput, setInterestInput] = useState('')
  const [savingInterests, setSavingInterests] = useState(false)
  const [notice, setNotice] = useState('')
  const [activityLoading, setActivityLoading] = useState(false)
  const searchRequestId = useRef(0)
  const bookmarkRequestIds = useRef(new Set())
  const bookmarkToastTimer = useRef(null)
  const nextToastId = useRef(0)
  const [pendingBookmarkIds, setPendingBookmarkIds] = useState(() => new Set())
  const [bookmarkToast, setBookmarkToast] = useState(null)

  const bookmarkIds = useMemo(() => new Set(bookmarks.map((item) => item.paper_id)), [bookmarks])

  const theme = themeMode === 'system' ? (systemDark ? 'dark' : 'light') : themeMode

  useEffect(() => {
    const preference = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!preference) return undefined
    const update = (event) => setSystemDark(event.matches)
    preference.addEventListener?.('change', update)
    return () => preference.removeEventListener?.('change', update)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#080d1b' : '#f5f6fc')
    try {
      window.localStorage.setItem('researchpaper-ai.theme', themeMode)
    } catch {
      // Keep the selected theme for this page even when it cannot be persisted.
    }
  }, [theme, themeMode])

  useEffect(() => () => window.clearTimeout(bookmarkToastTimer.current), [])

  function showBookmarkToast(type, message) {
    const id = ++nextToastId.current
    window.clearTimeout(bookmarkToastTimer.current)
    setBookmarkToast({ id, type, message })
    bookmarkToastTimer.current = window.setTimeout(() => {
      setBookmarkToast((current) => current?.id === id ? null : current)
    }, 4500)
  }

  async function checkBackend() {
    try {
      const response = await api.health()
      setHealth(response)
      setBackendAvailable(true)
      const available = response.mongodb === 'available'
      setActivityAvailable(available)
      if (available) await loadActivity()
    } catch (error) {
      setBackendAvailable(false)
      setHealth(null)
      setActivityAvailable(false)
      setNotice(error.message)
    }
  }

  async function loadActivity() {
    setActivityLoading(true)
    setActivityError('')
    const [bookmarkResult, historyResult, interestResult] = await Promise.allSettled([
      api.bookmarks(), api.history(), api.interests(),
    ])
    setActivityLoading(false)
    const failed = [bookmarkResult, historyResult, interestResult].find((item) => item.status === 'rejected')
    if (failed) {
      if (failed.reason instanceof ApiError && failed.reason.status === 503) {
        setActivityAvailable(false)
        setNotice('MongoDB activity storage became unavailable. Search and recommendations still work.')
      } else {
        setActivityError(failed.reason?.message || 'Could not load saved activity.')
      }
      return
    }
    setBookmarks(bookmarkResult.value.bookmarks || [])
    setHistory(historyResult.value.history || [])
    const savedInterests = interestResult.value.terms || []
    setInterests(savedInterests)
    setInterestDraft(savedInterests.join('\n'))
  }

  useEffect(() => { checkBackend() }, [])

  async function runSearch(searchTerm = query) {
    const cleanQuery = searchTerm.trim()
    if (!cleanQuery) {
      setNotice('Enter a paper title, topic, or keyword to search.')
      return
    }
    setQuery(cleanQuery)
    setView('discover')
    setHasSearched(true)
    const requestId = ++searchRequestId.current
    setSearchLoading(true)
    setNotice('')
    setSelectedPaperId(null)
    try {
      const response = await api.search(cleanQuery, 10)
      if (requestId !== searchRequestId.current) return
      setResults(response.results || [])
      if (response.history_saved) {
        try {
          const updated = await api.history()
          if (requestId === searchRequestId.current) setHistory(updated.history || [])
        } catch (error) {
          if (requestId === searchRequestId.current && error instanceof ApiError && error.status === 503) setActivityAvailable(false)
        }
      } else if (requestId === searchRequestId.current) {
        setActivityAvailable(false)
      }
    } catch (error) {
      if (requestId !== searchRequestId.current) return
      setNotice(error.message)
      if (error instanceof ApiError && error.status === 0) setBackendAvailable(false)
    } finally {
      if (requestId === searchRequestId.current) setSearchLoading(false)
    }
  }

  async function openPaper(paperId) {
    setSelectedPaperId(paperId)
  }

  async function toggleBookmark(paper) {
    const paperId = paper.paper_id
    if (activityAvailable !== true || bookmarkRequestIds.current.has(paperId)) return
    bookmarkRequestIds.current.add(paperId)
    setPendingBookmarkIds((current) => new Set(current).add(paperId))
    try {
      const outcome = await requestBookmarkChange({
        paper,
        isSaved: bookmarkIds.has(paperId),
        client: api,
      })
      if (outcome.status === 'error') {
        if (outcome.error instanceof ApiError && outcome.error.status === 503) setActivityAvailable(false)
        showBookmarkToast('error', outcome.message)
      } else if (outcome.action === 'remove') {
        setBookmarks((current) => current.filter((entry) => entry.paper_id !== paperId))
        showBookmarkToast('success', outcome.message)
      } else {
        setBookmarks((current) => [outcome.bookmark, ...current.filter((entry) => entry.paper_id !== paperId)])
        showBookmarkToast('success', outcome.message)
      }
    } finally {
      bookmarkRequestIds.current.delete(paperId)
      setPendingBookmarkIds((current) => {
        const next = new Set(current)
        next.delete(paperId)
        return next
      })
    }
  }

  async function saveInterests(event) {
    event.preventDefault()
    if (!activityAvailable) return
    const terms = interestDraft.split('\n').map((term) => term.trim()).filter(Boolean)
    setSavingInterests(true)
    setNotice('')
    try {
      const response = await api.saveInterests(terms)
      setInterests(response.terms || [])
      setInterestDraft((response.terms || []).join('\n'))
      setActivityError('')
      setNotice('Research interests saved for this local session.')
    } catch (error) {
      if (error instanceof ApiError && error.status === 503) setActivityAvailable(false)
      setNotice(error.message)
    } finally {
      setSavingInterests(false)
    }
  }

  function addInterest() {
    const nextInterest = interestInput.trim()
    if (!nextInterest) return
    const current = interestDraft.split('\n').map((term) => term.trim()).filter(Boolean)
    if (current.some((term) => term.toLocaleLowerCase() === nextInterest.toLocaleLowerCase())) {
      setNotice('That topic is already in your list.')
      return
    }
    setInterestDraft([...current, nextInterest].join('\n'))
    setInterestInput('')
    setNotice('')
  }

  const pageTitle = viewNames[view]

  return (
    <div className="app-shell">
      <Sidebar activeView={view} onNavigate={(next) => { setView(next); setNotice('') }} mongoAvailable={activityAvailable === true} />
      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><Icon name="chevron" size={14} /><strong>{pageTitle}</strong></div>
          <div className="topbar-actions">
            <button
              className="theme-toggle"
              type="button"
              onClick={() => setThemeMode((current) => current === 'system' ? 'dark' : current === 'dark' ? 'light' : 'system')}
              aria-label={`Theme: ${themeMode}. Switch to ${themeMode === 'system' ? 'dark' : themeMode === 'dark' ? 'light' : 'system'} theme`}
              title={`Theme: ${themeMode} · click to change`}
            ><Icon name={themeMode === 'system' ? 'monitor' : themeMode === 'dark' ? 'moon' : 'sun'} size={17} /></button>
            <div className={`connection-pill ${backendAvailable === false ? 'offline' : activityAvailable === false ? 'degraded' : ''}`}>
              <span className="connection-dot" />
              {backendAvailable === false ? 'Backend unavailable' : activityAvailable === false ? 'Activity storage offline' : 'API connected'}
            </div>
          </div>
        </header>

        <main className="main-content">
          {backendAvailable === false && (
            <InlineNotice kind="error" action={<button className="notice-action" onClick={checkBackend}>Retry connection</button>}>
              ResearchPaper AI could not reach the backend. Start FastAPI, then try again.
            </InlineNotice>
          )}
          {backendAvailable && activityAvailable === false && (
            <InlineNotice kind="warning">
              MongoDB-backed bookmarks, search history, and research interests are unavailable. Search and paper recommendations remain available.
            </InlineNotice>
          )}
          {notice && <InlineNotice kind={backendAvailable === false ? 'error' : 'info'}>{notice}</InlineNotice>}

          {view === 'discover' && (
            <>
              <section className={`hero ${hasSearched ? 'hero-compact' : ''}`}>
                <div className="hero-orb hero-orb-one" /><div className="hero-orb hero-orb-two" />
                <div className="hero-content">
                  <div className="hero-eyebrow"><span className="eyebrow-star"><Icon name="spark" size={13} /></span> RESEARCH, CONNECTED</div>
                  <h1>{hasSearched ? 'Explore the literature' : <>Explore the universe<br />of <em>research.</em></>}</h1>
                  <p>Follow ideas across the literature. Search papers by topic, title, or the question you are trying to answer.</p>
                  <SearchBar value={query} onChange={setQuery} onSubmit={(event) => { event.preventDefault(); runSearch() }} loading={searchLoading} disabled={backendAvailable === false} />
                  <div className="search-hint"><span className="keycap">↵</span> Press Enter to search the paper collection</div>
                </div>
                <div className="hero-decoration" aria-hidden="true"><span className="orbit orbit-a" /><span className="orbit orbit-b" /><span className="orbit-center"><Icon name="book" size={28} /></span><i className="orbit-dot dot-a" /><i className="orbit-dot dot-b" /><i className="orbit-dot dot-c" /></div>
              </section>

              {hasSearched ? (
                <section className="discovery-layout" aria-live="polite">
                  <div className="results-column">
                    <div className="results-heading">
                      <div><span className="eyebrow">SEARCH RESULTS</span><h2>{searchLoading ? 'Searching papers…' : results.length ? 'Papers to explore' : 'No matching papers'}</h2></div>
                      {!searchLoading && results.length > 0 && <span className="result-count">{results.length} returned</span>}
                    </div>
                    {searchLoading ? <LoadingList /> : results.length ? (
                      <div className="paper-list">
                        {results.map((paper) => <PaperCard key={paper.paper_id} paper={paper} onOpen={openPaper} bookmarked={bookmarkIds.has(paper.paper_id)} onBookmark={toggleBookmark} bookmarkDisabled={activityAvailable !== true} bookmarkPending={pendingBookmarkIds.has(paper.paper_id)} />)}
                      </div>
                    ) : <EmptyState icon="search" title="Try a broader search" >No papers were returned for “{query}”. Try another title, method, or keyword.</EmptyState>}
                  </div>
                  {selectedPaperId && <DetailPanel paperId={selectedPaperId} onClose={() => setSelectedPaperId(null)} onOpenPaper={openPaper} bookmarked={bookmarkIds.has(selectedPaperId)} onBookmark={toggleBookmark} activityDisabled={!activityAvailable} />}
                  {!selectedPaperId && results.length > 0 && <aside className="discover-aside"><EmptyState icon="book" title="Curious about a paper?">Open any result to read its abstract and find related research.</EmptyState></aside>}
                </section>
              ) : (
                <section className="welcome-grid">
                  <div className="welcome-card welcome-card-primary">
                    <div className="welcome-card-icon"><Icon name="search" size={19} /></div>
                    <div><span className="eyebrow">START WITH A QUESTION</span><h2>Turn a topic into a reading list</h2><p>Search a phrase from your research question, a paper title, or a method you want to understand.</p></div>
                  </div>
                  <div className="welcome-card">
                    <div className="welcome-card-icon mint"><Icon name="spark" size={19} /></div>
                    <div><span className="eyebrow">FOLLOW THE CONNECTIONS</span><h2>Find similar papers</h2><p>Open a result to see papers with similar title and abstract text.</p></div>
                  </div>
                </section>
              )}
            </>
          )}

          {view === 'saved' && (
            <section className="content-page">
              <PageHeading eyebrow="YOUR LIBRARY" title="Saved papers" description="Keep a session-based reading list of papers you want to revisit." />
              <ActivityGate available={activityAvailable} loading={activityLoading} error={activityError} onRetry={loadActivity}>{bookmarks.length ? (
                <div className="paper-list">{bookmarks.map((entry) => <PaperCard key={entry.paper_id} paper={{ ...entry, terms: [], abstract: '' }} onOpen={openPaper} bookmarked onBookmark={toggleBookmark} bookmarkDisabled={activityAvailable !== true} bookmarkPending={pendingBookmarkIds.has(entry.paper_id)} compact />)}</div>
              ) : <EmptyState icon="bookmark" title="No saved papers yet">Use the bookmark control on a paper to keep it here for this session.</EmptyState>}</ActivityGate>
            </section>
          )}

          {view === 'history' && (
            <section className="content-page">
              <PageHeading eyebrow="YOUR ACTIVITY" title="Search history" description="Revisit recent searches from this browser session." />
              <ActivityGate available={activityAvailable} loading={activityLoading} error={activityError} onRetry={loadActivity}>{history.length ? (
                <div className="history-list">{history.map((item, index) => (
                  <button className="history-row" key={`${item.created_at}-${index}`} onClick={() => runSearch(item.query)}>
                    <span className="history-icon"><Icon name="clock" size={18} /></span><span className="history-query">{item.query}<small>{new Date(item.created_at).toLocaleString()}</small></span><span className="history-count">{item.result_count} returned</span><Icon name="arrow" size={16} />
                  </button>
                ))}</div>
              ) : <EmptyState icon="clock" title="Your search history is empty">Searches are saved here when MongoDB activity storage is available.</EmptyState>}</ActivityGate>
            </section>
          )}

          {view === 'interests' && (
            <section className="content-page">
              <PageHeading eyebrow="PERSONALIZE YOUR SPACE" title="Research interests" description="Save topics you are exploring for this local browser session." />
              <ActivityGate available={activityAvailable} loading={activityLoading} error={activityError} onRetry={loadActivity}>
                <form className="interests-card" onSubmit={saveInterests}>
                  <label htmlFor="interest-list">Your topics</label>
                  <p>Enter one topic or category per line. These are saved as session preferences; they do not filter search results.</p>
                  <div className="interest-add-row">
                    <label className="sr-only" htmlFor="new-interest">Add a research topic</label>
                    <input id="new-interest" value={interestInput} maxLength="200" onChange={(event) => setInterestInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addInterest() } }} placeholder="Add a topic, e.g. graph neural networks" />
                    <button className="secondary-action" type="button" onClick={addInterest} disabled={!interestInput.trim()}><Icon name="plus" size={15} />Add topic</button>
                  </div>
                  <textarea id="interest-list" rows="7" maxLength="5000" value={interestDraft} onChange={(event) => setInterestDraft(event.target.value)} placeholder={'Example: graph neural networks\ncs.AI'} />
                  {interests.length > 0 && <div className="interest-chips" aria-label="Currently saved interests">{interests.map((interest) => <span className="interest-chip" key={interest}><Icon name="spark" size={13} />{interest}</span>)}</div>}
                  <div className="interests-footer"><span>{interests.length} saved {interests.length === 1 ? 'interest' : 'interests'}</span><button className="primary-action" type="submit" disabled={savingInterests}>{savingInterests ? <span className="button-spinner" /> : <Icon name="check" size={16} />}{savingInterests ? 'Saving…' : 'Save interests'}</button></div>
                </form>
              </ActivityGate>
            </section>
          )}
        </main>
        <footer className="app-footer"><span>ResearchPaper AI</span><span>Similarity scores describe text similarity; they are not probabilities or accuracy.</span></footer>
      </div>

      {selectedPaperId && view !== 'discover' && <DetailPanel paperId={selectedPaperId} onClose={() => setSelectedPaperId(null)} onOpenPaper={openPaper} bookmarked={bookmarkIds.has(selectedPaperId)} onBookmark={toggleBookmark} activityDisabled={!activityAvailable} />}
      {bookmarkToast && <div className={`bookmark-toast bookmark-toast-${bookmarkToast.type}`} role={bookmarkToast.type === 'error' ? 'alert' : 'status'} aria-live={bookmarkToast.type === 'error' ? 'assertive' : 'polite'} aria-atomic="true">
        <span className="bookmark-toast-icon"><Icon name={bookmarkToast.type === 'success' ? 'check' : 'close'} size={17} /></span>
        <span className="bookmark-toast-message">{bookmarkToast.message}</span>
        <button className="bookmark-toast-dismiss" type="button" aria-label="Dismiss notification" onClick={() => {
          window.clearTimeout(bookmarkToastTimer.current)
          setBookmarkToast(null)
        }}><Icon name="close" size={15} /></button>
      </div>}
    </div>
  )
}

function LoadingList() {
  return <div className="loading-list" role="status"><span className="spinner" />Loading from the research collection…</div>
}

function UnavailableActivity() {
  return <EmptyState icon="clock" title="Activity storage unavailable">The FastAPI backend is running, but its MongoDB activity store is unavailable. Search papers and recommendations continue to work.</EmptyState>
}

export default App
