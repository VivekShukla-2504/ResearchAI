# ResearchPaper AI — Project Context

## Project goal

Build an MCA-level research paper recommendation system using paper text and
metadata. The planned stack is Python, pandas, scikit-learn, TF-IDF,
cosine similarity, FastAPI, MongoDB, React, Vite, and Tailwind CSS.

## Phase 1: dataset audit (2026-10-13)

The workspace has the following source files under `data/`; neither file was
modified during the audit:

| File | Size | Rows | Columns and observed types | Missing fields | Exact duplicate rows |
|---|---:|---:|---|---:|---:|
| `data/arxiv_data.csv` | 67,411,252 bytes | 51,774 | `titles` (text/object), `summaries` (text/object), `terms` (text/object) | 0 | 12,783 |
| `data/arxiv_data_210930-054931.csv` | 73,029,841 bytes | 56,181 | `terms` (text/object), `titles` (text/object), `abstracts` (text/object) | 0 | 15,054 |

Each file has three columns. Both have zero empty fields, zero malformed-width
records, and text-valued columns throughout (pandas was not installed in the
workspace, so the audit used Python's CSV reader and reports pandas-style
`object` as the expected dtype for these mixed-length text fields). Duplicate
row counts were calculated over complete parsed CSV records. Title repeats
are also substantial: 12,802 repeated rows in `arxiv_data.csv` and 15,076 in
the dated file. These two counts differ from exact duplicate counts because
some repeated titles have differing metadata or text.

### Field mapping

| Purpose | `arxiv_data.csv` | `arxiv_data_210930-054931.csv` |
|---|---|---|
| Paper title | `titles` | `titles` |
| Abstract/text | `summaries` | `abstracts` |
| Category/tags | `terms` | `terms` |
| Paper ID | Not present | Not present |

`terms` values are string representations of category lists, for example
`['cs.CV', 'cs.LG']`. A later data-preparation phase should parse/normalize
these safely and create an internal stable key if needed; do not treat the
current row number as a durable paper ID.

### Comparison and selection

The files share 38,865 distinct titles. `arxiv_data.csv` has 38,972 distinct
titles and the dated file has 41,105. The dated file contains 2,240 distinct
titles not found in the other file, while the other file contains 107 titles
not found in the dated file. Therefore select **`data/arxiv_data_210930-054931.csv`**
for the initial project dataset: it has 4,407 more rows, more distinct titles,
and an `abstracts` field that directly matches the project's paper-abstract
use case. This is a project-fit choice based on the observed files; the filename
alone is not evidence that all records are newer.

### Scale and implementation note

At 56,181 records and about 73 MB on disk, TF-IDF on title plus abstract text
is practical on a typical student laptop if represented as a sparse matrix.
Avoid materializing a full dense pairwise cosine matrix: 56,181 × 56,181
float32 scores alone would take about 12.6 GB (float64 about 25.2 GB), before
runtime overhead. Use sparse TF-IDF, optionally `float32` and a vocabulary cap,
then compute only top-k recommendations or process query/batch similarities.
Deduplicate records before vectorization and retain a source-to-internal-ID
mapping. This keeps both quality and memory manageable.

### Data-quality observations and decisions

- No missing/empty title, text, or terms values were found by the audit.
- Exact duplicate rows and repeated titles are numerous, so deduplication or
  a documented duplicate policy is needed before indexing.
- No paper ID column exists in either file. Establish an internal ID and keep
  the original title and source row provenance.
- No explicit train/test split or evaluation labels were identified in the
  inspected schema; recommendation quality will need a planned evaluation
  approach.
- Source CSVs must remain unchanged; preprocessing should write derived data
  separately.

The next planned phase after this Phase 1 audit was reproducible preprocessing
and an explicit duplicate/ID policy. That plan was completed in Phase 2 below.

## Additional ML algorithm assessment (2026-10-13; no model trained)

The selected file's `terms` values parse as Python-literal lists for all 56,181
rows. They are multi-label: 21,862 rows have one term and 34,319 (61.1%) have
more than one. The parsed values contain 1,177 distinct term strings, with a
strong long tail: 991 occur on fewer than five papers and only 93 occur on at
least 20. Common terms include `cs.CV` (33,433 papers), `cs.LG` (30,939),
`stat.ML` (16,570), and `cs.AI` (8,390). Some values are composite or use
mixed category conventions, so these strings should not yet be treated as a
clean single-label taxonomy.

**Recommendation: consider sparse-text K-Means as the additional algorithm**
for exploratory topic grouping and recommendation diversity. It fits the
available unlabeled text objective without pretending the existing noisy,
long-tail tags form a clean classification target. Fit on normalized sparse
TF-IDF vectors (or MiniBatchKMeans if memory/runtime warrants it); do not form
a dense pairwise similarity matrix. Assess cluster separation with cosine
silhouette on a representative sample, inspect cluster top terms and
representative papers, and compare tag composition for interpretability.
Keep clustering only if the groups support useful topic navigation or
diversified recommendations. Silhouette alone does not prove recommendation
quality; a small human relevance/diversity review against the TF-IDF baseline
would be the practical product evaluation.

Logistic Regression is technically possible as multi-label text
classification, but it should not be added merely to claim another algorithm:
the 1,177-term space, sparse rare labels, multi-label records, and inconsistent
term conventions make a defensible target require significant cleanup and a
careful label-frequency policy. If later choosing that route, first define a
clean taxonomy and evaluate on a deduplicated, title-grouped holdout using
micro/macro F1 and per-label support; macro metrics must disclose the rare
label policy. XGBoost/regression has no clear advantage for the current
recommendation objective or target schema and is not recommended.

## Phase 2: recommendation engine (2026-10-13)

### Files added

- `researchpaper_ai/data.py`: safe `ast.literal_eval` category parsing,
  deterministic preprocessing, CSV input/output, stable paper IDs.
- `researchpaper_ai/engine.py`: sparse TF-IDF recommendations and optional
  MiniBatchKMeans topic/diversification experiment.
- `researchpaper_ai/preprocess.py`: preprocessing CLI.
- `scripts/evaluate_recommender.py`: reproducible category-overlap proxy,
  diversity, and sampled silhouette evaluation.
- `tests/test_recommender.py`: focused data and recommendation tests.
- `requirements.txt`, `README.md`: environment setup and usage.
- `data/processed/papers_clean.csv`: generated cleaned dataset; original CSV
  remains unchanged.
- `reports/phase2_evaluation.json`: measured metrics and per-cluster report.

### Preprocessing policy and results

- Parse `terms` with `ast.literal_eval`; validate list/tuple and string items,
  deduplicate and sort tag strings. No `eval()` is used.
- Normalize title/abstract with Unicode NFKC and whitespace collapse. Exact
  parsed source rows are counted once. Rows with the same normalized title and
  abstract are merged and their terms unioned, even if the tag field differs.
- Same title with a different normalized abstract is kept as a separate item.
  This makes no unsupported assertion about whether records are revisions.
- Rows with neither usable title nor abstract are removed; one usable field is
  sufficient. Source row ordinals are retained for provenance.
- IDs are `paper_` plus the SHA-256 digest of compact JSON containing the
  case-folded, normalized title and abstract. Thus IDs are independent of CSV
  row order and tags. Output rows sort by ID for deterministic serialization.
- Observed clean result: 56,181 input rows; 15,054 exact duplicate rows
  removed; 7 same-title/same-abstract rows merged after tag union; 16 repeated
  title groups with differing abstracts retained; 0 unusable-text rows
  removed; 41,120 cleaned papers.

### Recommendation model

`TfidfVectorizer` settings: English stop words, (1, 2) n-grams, `min_df=2`,
`max_features=150000`, sublinear TF, float32. The title is included twice and
the abstract once to give title terms greater weight. L2-normalized features
remain sparse. For each request, one query-to-corpus cosine score vector is
computed; no corpus-wide dense pairwise matrix is materialized. An all-stopword
paper or query returns no recommendations; an empty query returns none; an
unknown paper ID raises `KeyError`; selected source ID is excluded.

### K-Means assessment and evaluation

MiniBatchKMeans was fit on the 41,120 by 150,000 sparse TF-IDF matrix with 30
clusters, batch size 1,024, 100 max iterations, 3 initializations, and seed 42.
The matrix has 5,454,716 non-zero entries. Cosine silhouette on a reproducible
2,000-paper sample was **0.005541**, near zero. Cluster top terms show several
recognizable topic groups, but sizes are uneven (including two singleton
clusters). An optional top-100 candidate reranking that penalizes repeated
clusters was compared with baseline on 500 seed-42 queries at K=10:

| Method | Precision@10 | Recall@10 | Intra-list diversity |
|---|---:|---:|---:|
| TF-IDF cosine baseline | 0.933400 | 0.000373 | 0.898795 |
| Cluster-aware rerank | 0.871600 | 0.000346 | 0.936327 |

Precision/recall use any shared `terms` value as a **proxy relevant** signal.
All 500 queries had at least one such candidate. Because categories are broad,
multi-label, and noisy, this is not human relevance or model accuracy; low
Recall@10 comes from many eligible same-category papers. Diversity is one minus
the mean pairwise cosine similarity within each returned list. Cluster-aware
reranking increased this diversity measure but lowered both proxy relevance
metrics, so K-Means is retained only for reproducible exploratory diagnostics,
not as a default recommendation improvement. The report includes each
cluster's size, top terms, and representative paper.

### Verification and limitations

- `python -m pytest -q`: **7 passed** (stable IDs, exact and logical duplicate
  handling, repeated titles with distinct abstracts, safe term parsing,
  missing/unusable text, empty/unknown queries, self-exclusion, and output shape).
- Preprocessing and evaluation completed with the actual selected CSV.
- `requirements.txt` declares NumPy, scikit-learn, and pytest; no pandas,
  database, or web framework is needed for this phase.
- The evaluation is a random query sample, not a temporal holdout or user
  study. Term overlap may reward broad labels. Repeated-title records with
  distinct abstracts cannot be resolved as revisions from available fields.
- The environment used Python 3.14.6, scikit-learn 1.9.1, NumPy 2.5.4, and
  SciPy 1.18.1 for the measured run.

## Phase 3: FastAPI and MongoDB (2026-10-13)

### Files added or updated

- `researchpaper_ai/api.py`: FastAPI endpoints, request/response validation,
  CORS, startup artifact load, and anonymous session activity routes.
- `researchpaper_ai/mongo_store.py`: optional MongoDB persistence with a
  bounded connection timeout and clear unavailable behavior.
- `researchpaper_ai/model_artifact.py`: serialize/load the fitted Phase 2
  recommender without changing its algorithm.
- `scripts/build_model_artifact.py`: one-time fitted artifact builder.
- `tests/test_api.py`, `tests/test_mongo_store.py`: API and mocked persistence
  tests. Existing Phase 2 tests remain unchanged.
- `.env.example`, `.gitignore`, `requirements.txt`, `README.md`: local
  configuration, credentials/artifact exclusions, dependencies, and setup.
- `artifacts/recommender.joblib`: generated fitted artifact (54,369,625 bytes);
  excluded from Git and recreatable with the builder command.

### Model lifecycle and API behavior

The Phase 2 engine was preserved. The artifact builder loads
`data/processed/papers_clean.csv`, fits the existing `ResearchPaperRecommender`
once, and serializes its vectorizer, sparse matrix, and paper index with
joblib compression level 3. The FastAPI lifespan loads this artifact once;
requests never call fit, and a missing artifact causes a clear startup error
with the builder command. A smoke request against the actual artifact returned
HTTP 200 for health with 41,120 papers and HTTP 200 with three results for a
graph query.

Implemented routes:

- `GET /health`
- `GET /papers/search?q=...&limit=...`
- `GET /papers/{paper_id}`
- `GET /papers/{paper_id}/recommendations?k=10`
- `POST`, `GET`, and `DELETE /session/bookmarks`
- `GET /session/search-history`
- `GET` and `PUT /session/interests`
- Interactive OpenAPI docs at `/docs`

Search and K are constrained to 1–50; session list limits to 1–100; query text
is limited to 512 characters. Invalid requests return 422 and unknown paper
IDs return 404. Local frontend CORS defaults to ports 5173, configurable via
`CORS_ORIGINS`, and browser credentials are disabled. `/clusters` is omitted:
Phase 2 cluster metadata was weak (sampled silhouette 0.005541 and uneven
clusters), so it is not considered useful for API consumers.

### MongoDB design and limitations

`MONGODB_URI`, `MONGODB_DATABASE`, and
`MONGODB_SERVER_SELECTION_TIMEOUT_MS` configure the database. The default URI
is local and contains no credentials. Mongo stores only bookmark, search
history, and interest documents in separate collections; paper abstracts and
the paper corpus remain in the cleaned CSV and fitted model artifact. Indexes
are created for session lookups. If MongoDB is unavailable at startup, health
reports `degraded`, search/recommendations continue, search returns
`history_saved: false`, and activity endpoints return HTTP 503. A Mongo error
during operation similarly disables persistence without taking down core
recommendations.

Authentication is not implemented. `X-Session-ID` is an untrusted local label
with default `local-anonymous`; callers can spoof any session, and callers
omitting the header share the default bucket. This is not secure account
separation. Search queries/activity have no configured retention period. Do
not expose this local-development session scheme as authenticated service.

### Verification

- `python -m pytest -q`: **15 passed** (7 existing Phase 2 tests and 8 Phase 3
  API/Mongo mock tests). One non-failing Starlette deprecation warning notes
  its current TestClient use of HTTPX; no test failed.
- Artifact builder completed and wrote the actual full-corpus artifact.
- Smoke-tested app startup loading that artifact plus health and search.
- Mongo behavior was tested with mocks; no live MongoDB integration was run.
- No React frontend or deployment work was performed.

## Phase 3 next step (historical)

The frontend work described as the next phase below has since been completed
in Phase 4. The local anonymous session limitations remain in effect.

## Phase 4: React/Vite/Tailwind frontend (2026-10-13)

### Implementation

Added `frontend/` with React 19, Vite 7, and Tailwind CSS 4 through its Vite plugin. API origin is configured by `VITE_API_BASE_URL` in `frontend/.env.example` (default `http://127.0.0.1:8000`). The frontend calls existing FastAPI schemas and does not bundle the paper dataset.

The responsive dashboard supports title/topic/keyword search, actual paper results with tags and abstract previews, detail views, explicit “Find similar papers” recommendations, labeled similarity scores, bookmarks, search history, and editing session interests. It shows loading, empty, error, backend-offline, and MongoDB activity-unavailable states. It does not expose filters the API does not support. Recommendation scores are text similarity scores, not probabilities or model accuracy.

The frontend stores its generated session label in browser `sessionStorage` and sends it as `X-Session-ID`; this is untrusted session/activity grouping, not authentication. MongoDB-dependent UI features explain when persistence is unavailable. Search and recommendations continue to call the API independently.

### Run and verification

Start the backend from the repository root with the Phase 3 setup (activate `.venv`, then `uvicorn researchpaper_ai.api:app --reload`). In another PowerShell terminal run:

```powershell
cd frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm.cmd install
npm.cmd run dev
```

The Vite server uses port 5173, included in the backend's default CORS origins. `npm.cmd run build` completed successfully using Node v24.18.0 and Vite 7.3.7. Output: `dist/index.html` 0.56 kB, CSS 21.97 kB (5.97 kB gzip), JavaScript 243.38 kB (75.65 kB gzip). No automated frontend test suite or browser/e2e verification exists yet. Python API/model behavior remains covered by the Phase 2/3 suite; rerun `python -m pytest -q` to verify it after this phase.

### Files and limitations

Added frontend source/components, Vite/Tailwind configuration, `frontend/.env.example`, and `frontend/package-lock.json`; updated `.gitignore` to exclude frontend `node_modules` and build output. Updated this context and README with run/build steps. No backend, ML, data, or model artifact changes were made. The interface has no browser automation or dedicated accessibility test coverage. Authentication remains out of scope; activity is session-labeled and insecure by design for local use.

## Next planned step

## Phase 5: end-to-end verification and bug fixing (2026-10-13)

### Verification results

- Read this context and README before checking the code. No root `.env` or
  `frontend/.env` existed; no environment file was created or overwritten.
- The existing fitted model artifact and cleaned CSV were present. The
  documented local Uvicorn command started successfully with the actual
  artifact; Vite served the frontend at `http://127.0.0.1:5173/` with HTTP 200.
- Frontend API default `http://127.0.0.1:8000` matches the backend bind URL.
  CORS allowed `http://127.0.0.1:5173`.
- Live API checks against the real corpus: health HTTP 200 (`degraded`, 41,120
  papers), search HTTP 200 (5 results), details HTTP 200 and matched the
  selected result, recommendations HTTP 200 (5 results), and source paper
  excluded. Whitespace-only query returned 422; invalid paper ID returned 404.
- With MongoDB unavailable, search still returned results and
  `history_saved: false`; health reported MongoDB unavailable. Bookmark,
  history, and interest endpoints returned HTTP 503. Existing tests exercise
  bookmark add/list/remove, search history, and interest save/read with an
  in-memory mock, not a live Mongo server.
- After stopping Uvicorn, a health request returned curl status `000`,
  confirming the backend was unreachable. The frontend offline screen was
  not verified in a browser.
- `python -m pytest -q`: **15 passed**, with one non-failing
  Starlette/HTTPX deprecation warning. `npm.cmd run build`: succeeded with
  Vite 7.3.7 (JavaScript 243.38 kB / 75.65 kB gzip; CSS 21.97 kB / 5.97 kB
  gzip). Declared frontend dependencies were present.

### Limits and fixes

No `MONGODB_URI` environment variable or local `.env` was configured, and no
MongoDB service/tools were available; real persistence remains unverified.
Playwright, Puppeteer, Selenium, and browser automation are unavailable, and
there is no frontend test suite, so interactions and rendered unavailable
states were not browser-tested. No reproducible functional bug was found.
Changed setup instructions to guard `.env` copies with `Test-Path`, avoiding
overwrite of an existing local configuration. No model, backend, dataset,
artifact, or frontend feature implementation was changed in Phase 5.

## Next step

Review Phase 5 limits and provide a MongoDB instance or browser-testing setup
if live persistence and browser-level verification are required.

### Follow-up audit (2026-10-13)

This follow-up supersedes the earlier Phase 5 MongoDB availability note. The pre-existing API at `127.0.0.1:8000` reported `status=ok`, `model_loaded=true`, `paper_count=41120`, and `mongodb=available`. Root `.env` exists and was not read to output or modified; no `frontend/.env` exists. The frontend example API URL is `http://127.0.0.1:8000`, and backend CORS returned the Vite origin `http://127.0.0.1:5173`.

Against that existing API, Mongo-backed bookmark add (201), list (200), and delete (200) succeeded for a fresh unique session; a second fresh session did not see the bookmark. The test bookmark was deleted and verified absent. For fresh sessions, history GET and interests GET returned empty values. No history or interests were written because the API has no delete routes for these records and direct audit-process Mongo connection could not reach the configured host for cleanup.

A separate temporary Uvicorn process on port 8001 loaded the artifact and corpus, but its Mongo connection failed DNS resolution. It reported degraded health; actual search returned five records and `history_saved=false`; details and recommendations returned 200, source self-exclusion held, and Mongo-only routes returned 503. The process was stopped. The existing port-8000 server was not restarted or disturbed, so persistence across a backend restart remains unverified.

Live API validation responses: absent/blank query 422; unknown details/recommendations IDs 404; invalid K 422; malformed bookmark body 422; unknown bookmark paper 404; malformed interests body 422; malformed session header 422. The actual artifact returned ten results for a graph query; empty, stopword-only, and OOV model queries returned zero; scores were finite, bounded [0,1], and descending; unknown model IDs raised `KeyError`.

Latest checks: `python -m pytest -q` **15 passed**, one non-failing Starlette/HTTPX deprecation warning; `npm.cmd run build` succeeded (Vite 7.3.7, JS 243.38 kB / 75.65 kB gzip, CSS 21.97 kB / 5.97 kB gzip). Frontend has no test script. Playwright, Puppeteer, Selenium, and browser automation were unavailable, so UI behavior/responsive rendering was not browser-tested. Real search-history persistence, interest save/update, and restart persistence remain unverified. No reproducible code bug was found; no source implementation was changed.

### Remaining-items follow-up (2026-10-13)

- Inspected `MongoStore`: `search_history` documents include `session_id`, `query`, `result_count`, and `created_at`; `interests` documents include `session_id`, `terms`, and `updated_at`. API deletion exists for bookmarks only. There is no API cleanup for history or interests. The audit process could not establish a direct MongoDB connection, so it did not perform history/interest writes that could leave test records behind.
- Read-only GETs for search history and interests using two distinct fresh session IDs returned empty values for both sessions. This checks fresh-session isolation only; it does not verify history insertion or interest save/update persistence.
- Against the existing server, GET details and GET recommendations for an unknown model ID both returned HTTP 404. `python -m pytest -q tests/test_api.py -k missing_paper` passed: **1 passed, 4 deselected**, with one non-failing Starlette/HTTPX deprecation warning. The API translates the engine's `KeyError` into 404, so no fix or recommendation behavior change was needed.
- No restart was performed to avoid interrupting the user's existing server. Restart persistence still requires manual verification with a fresh session: create a bookmark, list it, restart FastAPI in the user's terminal, list it again using the same `X-Session-ID`, then delete it and verify it is absent.
- No source implementation changed. The previous full suite and frontend build results remain recorded above; this follow-up reran the focused unknown-ID regression test.

## Research interests persistence investigation (2026-10-13)

### Code path inspected

- The interests form submits through `saveInterests` on form submit; the handler trims nonempty lines and calls `api.saveInterests(terms)`.
- `api.saveInterests` sends `PUT /session/interests`. The common `apiRequest` adds `X-Session-ID` for both GET and PUT. The ID is generated once and stored under `researchpaper-ai.local-session` in browser `sessionStorage`, which survives a refresh in the same tab/origin.
- On initialization, the frontend calls `/health`; when Mongo reports available it runs `loadActivity`, which requests bookmarks, search history, and `GET /session/interests`, then copies returned terms into the UI state/draft.
- FastAPI binds the same `X-Session-ID` header on both interests routes. `MongoStore.set_interests` upserts by `session_id` and `get_interests` reads by that same key. The observed API implementation has no apparent GET/PUT session mismatch.

### Results and limits

- Existing API at `127.0.0.1:8000` reported MongoDB available. Fresh-session read-only GET requests returned empty interests. A Vite SSR smoke check of the actual client module showed GET, PUT, and a subsequent GET all carried the same stored session UUID; this used a mocked fetch and does not prove browser rendering or MongoDB persistence.
- The relevant existing API test passed: `python -m pytest -q tests/test_api.py -k session_bookmarks_interests_and_search_history` => **1 passed, 4 deselected**. It verifies mocked PUT normalization and GET readback. `npm.cmd run build` succeeded (Vite 7.3.7).
- A direct MongoStore connection from this audit process returned unavailable, despite the pre-existing API's health result. Since interests has no delete route (and search history likewise has no cleanup route), a live test PUT could leave a permanent test document. No interests or search-history writes were made; no test data was created.
- No actual root cause for the reported disappearance was reproduced, so no application code was changed. To diagnose the user's specific browser session, inspect its Network requests for PUT response status/body and confirm the PUT and post-refresh GET have the same `X-Session-ID`; browser automation/sessionStorage was not accessible in this audit.

## Cosmic UI refresh (2026-10-13)

- Reworked the existing shell and screens with a restrained cosmic observatory palette, CSS star field/nebula atmosphere, glass surfaces, constellation-style identity, refined paper cards and interaction states, and responsive navigation/content layouts. Motion respects `prefers-reduced-motion`; no external imagery or dependencies were added.
- Theme supports `system`, `dark`, and `light`; it follows the operating-system setting by default, reacts to OS preference changes while in system mode, cycles from the top-bar control, and persists mode in `localStorage`. Storage access remains guarded.
- Added an explicit research-topic append control with duplicate protection, preserving the other draft lines; existing PUT save and GET load API flow remains in use. Saved topics display as chips after loading/saving.
- Changed `frontend/src/App.jsx`, `frontend/src/components/Icon.jsx`, `frontend/src/components/Sidebar.jsx`, `frontend/src/main.jsx`; added `frontend/src/cosmic.css`. README setup/UI notes and current build result updated. No backend, API, ML, data, or model artifacts changed.
- Verification: `npm.cmd run build` in `frontend/` succeeded with Vite 7.3.7 (38 modules; JS 246.17 kB / 76.48 kB gzip; CSS 47.73 kB / 10.93 kB gzip). `npm.cmd run` confirms there is no frontend test script. No browser automation was available, so visual rendering at target viewports, actual keyboard interaction, and live UI/API interaction still require browser review.

## Frontend bug fixes (2026-10-13)

- Fixed theme preference persistence when the mode changes but the effective color scheme does not (such as Light to System while the OS is Light).
- Added latest-request guards to search and recommendation requests so out-of-order responses cannot overwrite the currently selected query or paper. Detail fetch failures can be retried.
- Activity initialization failures now have a visible retry state rather than showing empty saved/history/interests content as if the request succeeded. Existing MongoDB unavailable handling remains in place.
- The session ID remains stored in `sessionStorage` normally. If access is blocked, requests use one in-memory session label per page load and no longer fail before reaching the API; cross-refresh session continuity cannot be guaranteed in this case.
- Added `frontend/tests/api.test.js` and the `npm test` script. The two tests verify consistent session headers across interest GET/PUT and requests when browser storage throws.
- Verification: in `frontend/`, `npm.cmd test` reported **2 passed, 0 failed**; `npm.cmd run build` succeeded using Vite 7.3.7 (38 modules; JS 247.18 kB / 76.80 kB gzip; CSS 47.73 kB / 10.93 kB gzip). No browser automation package or browser executable was available, so visual layouts, theme interaction, API-connected UI behavior, and race handling have not been verified in a browser. No backend, ML, data, or model artifacts changed.

## ML/API pipeline hardening (2026-10-13)

- The production artifact was loaded and inspected: 41,120 papers, a sparse 41,120 × 150,000 matrix with 5,454,716 nonzero values, unique paper IDs, and an ID-to-row map matching the artifact order. A live-in-process API smoke check returned valid details, search, and recommendations; the selected paper was excluded and returned scores were finite, bounded, and descending. OOV search returned no matches; whitespace search returned 422 and an unknown ID returned 404.
- Reproduced an edge case: the default `min_df=2` made a one-paper catalog fail before recommendation. The engine now retries that empty-vocabulary fit once at `min_df=1`; catalogs containing only stopwords fail with a clear error.
- Recommendation retrieval now omits non-finite similarities, bounds cosine outputs to [0, 1], and breaks score ties by stable paper row index. Artifact loading checks sparse feature shape, vocabulary width, finite feature values, and exact paper-ID mapping before serving.
- API lifespan already loads the artifact once; a regression test now verifies that multiple requests do not reload it. No full-corpus artifacts were rebuilt or modified, and the recommendation algorithm for the production corpus remains TF-IDF cosine similarity.
- `python -m pytest -q`: 25 passed with one non-failing Starlette TestClient deprecation warning. The exact saved artifact also passed a smoke test through the API boundary. Live MongoDB persistence was not exercised in this ML phase.
