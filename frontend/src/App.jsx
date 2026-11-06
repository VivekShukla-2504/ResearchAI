import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './lib/api.js'
import AuthModal from './components/AuthModal.jsx'
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

const CATEGORY_FILTERS = [
  { id: '', label: 'All Fields' },
  { id: 'cs.CV', label: 'Computer Vision' },
  { id: 'cs.LG', label: 'Machine Learning' },
  { id: 'cs.AI', label: 'Artificial Intelligence' },
  { id: 'cs.CL', label: 'NLP & Language' },
  { id: 'stat.ML', label: 'Stat ML' },
  { id: 'cs.RO', label: 'Robotics' },
]

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
  const [selectedCategory, setSelectedCategory] = useState('')
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
  const [personalizedPapers, setPersonalizedPapers] = useState([])
  const [personalizedLoading, setPersonalizedLoading] = useState(false)
  const [currentUser, setCurrentUser] = useState(() => api.getStoredUser())
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [authModalMode, setAuthModalMode] = useState('login')

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
      if (api.getStoredToken()) {
        try {
          const me = await api.me()
          setCurrentUser(me)
        } catch {
          api.clearAuth()
          setCurrentUser(null)
        }
      }
      if (available) await loadActivity()
    } catch (error) {
      setBackendAvailable(false)
      setHealth(null)
      setActivityAvailable(false)
      setNotice(error.message)
    }
  }

  function handleAuthSuccess(user, message) {
    setCurrentUser(user)
    showBookmarkToast('success', message)
    loadActivity()
  }

  function handleLogout() {
    api.clearAuth()
    setCurrentUser(null)
    showBookmarkToast('success', 'Signed out successfully.')
    loadActivity()
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
    if ((bookmarkResult.value.bookmarks?.length || 0) > 0 || savedInterests.length > 0) {
      loadPersonalized()
    }
  }

  async function loadPersonalized(cat = selectedCategory) {
    setPersonalizedLoading(true)
    try {
      const response = await api.personalizedRecommendations(6, cat)
      setPersonalizedPapers(response.recommendations || [])
    } catch {
      setPersonalizedPapers([])
    } finally {
      setPersonalizedLoading(false)
    }
  }

  useEffect(() => { checkBackend() }, [])

  async function runSearch(searchTerm = query, categoryFilter = selectedCategory) {
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
      const response = await api.search(cleanQuery, 10, categoryFilter)
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

  function handleCategorySelect(catId) {
    setSelectedCategory(catId)
    if (query.trim()) {
      runSearch(query, catId)
    } else {
      loadPersonalized(catId)
    }
  }

  function downloadFile(filename, content, mimeType) {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  function exportMarkdownDossier() {
    if (!bookmarks.length) return
    let content = `# Research Paper Reading Dossier\n*Generated by ResearchPaper AI on ${new Date().toLocaleDateString()}*\n\n`
    content += `**Total Bookmarked Papers:** ${bookmarks.length}\n\n---\n\n`
    bookmarks.forEach((item, index) => {
      content += `### ${index + 1}. ${item.title}\n`
      content += `- **Paper ID:** \`${item.paper_id}\`\n`
      content += `- **Google Scholar:** [Search Paper](https://scholar.google.com/scholar?q=${encodeURIComponent(item.title)})\n`
      content += `- **arXiv Search:** [Search on arXiv](https://arxiv.org/search/?query=${encodeURIComponent(item.title)}&searchtype=title)\n\n`
    })
    downloadFile('research_dossier.md', content, 'text/markdown;charset=utf-8')
    showBookmarkToast('success', 'Exported reading dossier as Markdown.')
  }

  function exportBibtexDossier() {
    if (!bookmarks.length) return
    let content = `% BibTeX Citations exported from ResearchPaper AI\n\n`
    bookmarks.forEach((item) => {
      const firstWord = (item.title.split(' ')[0] || 'paper').replace(/[^a-zA-Z0-9]/g, '').toLowerCase()
      content += `@article{${firstWord}_arxiv,\n`
      content += `  title = {${item.title.replace(/[{}]/g, '')}},\n`
      content += `  year = {2021}\n}\n\n`
    })
    downloadFile('citations.bib', content, 'text/plain;charset=utf-8')
    showBookmarkToast('success', 'Exported citations as BibTeX.')
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
        loadPersonalized()
      } else {
        setBookmarks((current) => [outcome.bookmark, ...current.filter((entry) => entry.paper_id !== paperId)])
        showBookmarkToast('success', outcome.message)
        loadPersonalized()
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
      loadPersonalized()
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
            {currentUser ? (
              <div className="user-profile-badge">
                <div className="user-avatar-circle" title={currentUser.email}>
                  {currentUser.picture ? (
                    <img src={currentUser.picture} alt={currentUser.name} />
                  ) : (
                    (currentUser.name || currentUser.email)[0].toUpperCase()
                  )}
                </div>
                <span className="user-display-name">{currentUser.name || currentUser.email}</span>
                <button className="sign-out-btn" type="button" onClick={handleLogout} title="Sign Out">
                  Sign Out
                </button>
              </div>
            ) : (
              <button
                className="auth-open-btn"
                type="button"
                onClick={() => { setAuthModalMode('login'); setAuthModalOpen(true); }}
              >
                <Icon name="spark" size={14} /> Sign In
              </button>
            )}
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
                  <SearchBar
                    value={query}
                    onChange={setQuery}
                    onSubmit={(event) => { event.preventDefault(); runSearch() }}
                    onSelectSuggestion={(selected) => { setQuery(selected); runSearch(selected) }}
                    loading={searchLoading}
                    disabled={backendAvailable === false}
                  />
                  <div className="category-filter-row" role="tablist" aria-label="Filter by research domain">
                    {CATEGORY_FILTERS.map((cat) => (
                      <button
                        key={cat.id}
                        className={`category-filter-pill ${selectedCategory === cat.id ? 'is-active' : ''}`}
                        type="button"
                        onClick={() => handleCategorySelect(cat.id)}
                      >
                        {cat.label}
                      </button>
                    ))}
                  </div>
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
                <>
                  {personalizedPapers.length > 0 && (
                    <section className="personalized-section" aria-label="Personalized Recommendations" style={{ marginTop: '24px' }}>
                      <div className="results-heading">
                        <div>
                          <span className="eyebrow" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                            <Icon name="spark" size={13} /> FOR YOU · AI RECOMMENDATIONS
                          </span>
                          <h2>Recommended for Your Research Profile</h2>
                          <p style={{ margin: '4px 0 0', fontSize: '11px', color: 'var(--muted)' }}>
                            Based on your bookmarked papers and saved research interests.
                          </p>
                        </div>
                        <button
                          className="secondary-action"
                          type="button"
                          onClick={() => loadPersonalized()}
                          disabled={personalizedLoading}
                          title="Refresh personalized recommendations"
                        >
                          <Icon name="spark" size={13} /> {personalizedLoading ? 'Updating…' : 'Refresh Feed'}
                        </button>
                      </div>
                      <div className="paper-list">
                        {personalizedPapers.map((paper) => (
                          <PaperCard
                            key={paper.paper_id}
                            paper={paper}
                            onOpen={openPaper}
                            bookmarked={bookmarkIds.has(paper.paper_id)}
                            onBookmark={toggleBookmark}
                            bookmarkDisabled={activityAvailable !== true}
                            bookmarkPending={pendingBookmarkIds.has(paper.paper_id)}
                          />
                        ))}
                      </div>
                    </section>
                  )}
                  {selectedPaperId && (
                    <DetailPanel
                      paperId={selectedPaperId}
                      onClose={() => setSelectedPaperId(null)}
                      onOpenPaper={openPaper}
                      bookmarked={bookmarkIds.has(selectedPaperId)}
                      onBookmark={toggleBookmark}
                      activityDisabled={!activityAvailable}
                    />
                  )}
                  <section className="welcome-grid" style={personalizedPapers.length > 0 ? { marginTop: '32px' } : undefined}>
                    <div className="welcome-card welcome-card-primary">
                      <div className="welcome-card-icon"><Icon name="search" size={19} /></div>
                      <div><span className="eyebrow">START WITH A QUESTION</span><h2>Turn a topic into a reading list</h2><p>Search a phrase from your research question, a paper title, or a method you want to understand.</p></div>
                    </div>
                    <div className="welcome-card">
                      <div className="welcome-card-icon mint"><Icon name="spark" size={19} /></div>
                      <div><span className="eyebrow">FOLLOW THE CONNECTIONS</span><h2>Find similar papers</h2><p>Open a result to see papers with similar title and abstract text.</p></div>
                    </div>
                  </section>
                </>
              )}
            </>
          )}

          {view === 'saved' && (
            <section className="content-page">
              <PageHeading
                eyebrow="YOUR LIBRARY"
                title="Saved papers"
                description="Keep a session-based reading list of papers you want to revisit."
                trailing={
                  bookmarks.length > 0 ? (
                    <div className="dossier-export-actions">
                      <button className="secondary-action" type="button" onClick={exportMarkdownDossier} title="Export all saved papers as a Markdown summary">
                        <Icon name="spark" size={14} /> Export Dossier (.md)
                      </button>
                      <button className="secondary-action" type="button" onClick={exportBibtexDossier} title="Export BibTeX citations for all saved papers">
                        Export BibTeX (.bib)
                      </button>
                    </div>
                  ) : null
                }
              />
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
                  <p>Enter one topic or category per line. The AI recommendation engine uses these along with your bookmarks to personalize your Discover feed.</p>
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
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onAuthSuccess={handleAuthSuccess}
        initialMode={authModalMode}
        theme={theme}
      />
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
