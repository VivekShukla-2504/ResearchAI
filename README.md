# ResearchPaper AI

ResearchPaper AI includes the Phase 2 reproducible data pipeline and sparse
TF-IDF recommendation engine, a Phase 3 FastAPI service with optional MongoDB
activity storage, and a Phase 4 React/Vite/Tailwind frontend.

## Setup

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

## Prepare the selected dataset

The original `data/arxiv_data_210930-054931.csv` is read only. Preprocessing
uses `ast.literal_eval` with type validation for the list-like `terms` field;
it never uses `eval()`.

```powershell
python -m researchpaper_ai.preprocess
```

This reproducibly writes `data/processed/papers_clean.csv`. Exact source rows
are deduplicated. Rows with the same normalized title and abstract are merged
with a sorted union of their terms. Rows with a repeated title and a different
normalized abstract remain separate. Missing text in one field is allowed if
the other field has usable content; records with neither are removed. IDs are
`paper_` plus the SHA-256 of normalized title and abstract, so IDs do not
depend on input row order or tag ordering.

## Use the recommendation interface

```python
from researchpaper_ai.data import load_clean_csv
from researchpaper_ai.engine import ResearchPaperRecommender

papers = load_clean_csv("data/processed/papers_clean.csv")
recommender = ResearchPaperRecommender(papers)

# Query by paper ID (the source paper is excluded from results):
results = recommender.recommend(paper_id=papers[0].paper_id, top_k=10)

# Or by free text:
results = recommender.recommend(query="graph neural network representations", top_k=10)
```

The fitted `TfidfVectorizer` uses English stop words, unigrams and bigrams,
`min_df=2`, `max_features=150000`, sublinear term frequency, and float32
values. Titles are repeated twice in the input text, giving them more weight
than abstracts. The feature matrix remains sparse. Each query computes one
similarity score per paper; the implementation never creates a dense
all-pairs similarity matrix. Blank or out-of-vocabulary queries return an
empty list; unknown paper IDs raise `KeyError`. If `min_df=2` would eliminate
the entire vocabulary in a very small catalog, fitting retries once with
`min_df=1`; stopword-only text fails with a clear `ValueError`.

## Evaluate recommendations and clusters

```powershell
python scripts/evaluate_recommender.py
pytest -q
```

The evaluation defaults to 500 fixed-seed paper queries and reports
Precision@10 and Recall@10 using overlap in the dataset's `terms` as a
**proxy relevance signal**, plus intra-list diversity. It compares ordinary
cosine ranking with a cluster-aware reranking experiment. This is not human
feedback or recommendation accuracy: broad shared tags can mark unrelated
papers as relevant, and the random query sample is not a temporal holdout.

The exploratory model is `MiniBatchKMeans` with 30 clusters, batch size 1,024,
100 maximum iterations, three initializations, and random seed 42. A
2,000-paper sample is used for cosine silhouette because full silhouette is
quadratic. Cluster top terms, representative papers, cluster sizes, and
metrics are written to `reports/phase2_evaluation.json`. Clustering is kept
only as an experimental topic grouping/diversification path, not as the
default recommender. In the measured run, cosine silhouette was 0.005541.
Some clusters had descriptive top terms, but the partition was imbalanced
(including two singleton clusters), and cluster-aware reranking traded lower
category-overlap relevance for higher list diversity. It is not treated as
an improvement to recommendations.

### Measured run (seed 42)

The selected source produced 41,120 cleaned papers and a sparse TF-IDF matrix
with 41,120 rows, 150,000 features, and 5,454,716 non-zero values. On 500
sampled queries at K=10, the baseline measured Precision@10 **0.933400**,
Recall@10 **0.000373**, and diversity **0.898795**. Cluster-aware reranking
measured Precision@10 **0.871600**, Recall@10 **0.000346**, and diversity
**0.936327**. These precision/recall values use category overlap as the
proxy; the high precision and very low recall reflect the very large set of
papers sharing at least one broad category, not human relevance. The generated
report contains the full per-cluster term and representative-paper inspection.

## Phase 2 limitations

- The source has no paper IDs; IDs here are deterministic content-derived
  internal identifiers.
- The `terms` values parse, but contain a long tail and mixed/composite
  conventions. They are not a clean single-label taxonomy.
- Repeated titles with different abstracts are retained as separate records;
  the dataset does not establish whether these are revisions or distinct
  works.
- Category overlap is only an offline proxy for relevance. Human or user
  evaluation is still needed before claiming recommendation quality.
- The K-Means silhouette is close to zero and its clusters are uneven. The
  cluster-aware experiment reduced the category-overlap proxy scores, so the
  default product recommendation remains sparse TF-IDF cosine ranking.

## Phase 3: FastAPI and MongoDB

### Build and run

The API does not train the model on requests or at each startup. Build the
compressed fitted artifact once after preprocessing, then launch the service:

```powershell
python scripts/build_model_artifact.py
uvicorn researchpaper_ai.api:app --reload
```

The default artifact is `artifacts/recommender.joblib` (about 54 MB in the
current workspace). It contains the already fitted vectorizer, sparse feature
matrix, and paper lookup data. Startup loads it once. If it is missing, startup
reports the build command and fails rather than fitting silently. This local
artifact is ignored by Git; recreate it from the available cleaned CSV with
the build command. Only load artifacts generated from this project's trusted
local data; joblib files are Python pickle data and should not be accepted from
untrusted sources.

Copy `.env.example` to `.env` and configure:

| Variable | Purpose | Default |
|---|---|---|
| `MONGODB_URI` | Mongo connection URI | `mongodb://localhost:27017` |
| `MONGODB_DATABASE` | Activity database name | `researchpaper_ai` |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS` | Startup/connect timeout | `1500` |
| `CLEANED_DATA_PATH` | Input CSV for one-time artifact build | `data/processed/papers_clean.csv` |
| `MODEL_ARTIFACT_PATH` | Artifact path used by builder and API | `artifacts/recommender.joblib` |
| `CORS_ORIGINS` | Comma-separated browser origins | localhost Vite ports 5173 |

`.env.example` contains no credentials. For a protected Mongo deployment, put
the URI with credentials in the ignored local `.env` or another secret store;
never put it in source control. MongoDB is optional for read/search operation:
if its connection fails, `/health` reports `degraded`, search still works,
search history reports `history_saved: false`, and session persistence routes
return HTTP 503.

### HTTP endpoints

FastAPI publishes interactive OpenAPI documentation at `/docs`.

| Method and path | Behavior |
|---|---|
| `GET /health` | Model paper count and MongoDB availability |
| `GET /papers/search?q=...&limit=...` | Search with the fitted TF-IDF model; records search history when MongoDB is available |
| `GET /papers/{paper_id}` | Paper details |
| `GET /papers/{paper_id}/recommendations?k=10` | Top recommendations; unknown paper IDs return 404 |
| `POST /session/bookmarks` | Add a bookmark using JSON `{"paper_id":"..."}` |
| `GET /session/bookmarks?limit=50` | List this session's bookmarks with paper titles |
| `DELETE /session/bookmarks/{paper_id}` | Remove a bookmark |
| `GET /session/search-history?limit=50` | List recent searches for a session |
| `GET /session/interests` | Read session research interests |
| `PUT /session/interests` | Replace interests with JSON `{"terms":["cs.AI"]}` |

Search limits and recommendation K are 1–50; activity list limits are 1–100;
queries are 1–512 characters. Empty/whitespace-only queries and malformed
session IDs receive HTTP 422; unknown papers receive 404. The default CORS
allowlist is `http://localhost:5173` and `http://127.0.0.1:5173`, with no
credentialed browser requests.

### MongoDB data and local session model

MongoDB stores only user activity in three collections: `bookmarks`,
`search_history`, and `interests`. The paper corpus stays in the cleaned CSV
and fitted artifact; details are looked up from the model's paper index, so
the 41,120 paper records are not copied into MongoDB.

There is no authentication or secure account system. The API accepts an
`X-Session-ID` label, defaulting to `local-anonymous` for simple local use.
Anyone who can call the service can choose or spoof another session ID, and
the default session is shared by clients that omit the header. Do not expose
this local-development service as a multi-user authenticated application.
Search queries and activity are persisted without a configured retention
period, so clear the local collections when they are no longer needed.

No `/clusters` endpoint is exposed: Phase 2's K-Means partition had near-zero
sampled cosine silhouette and did not improve the category-overlap relevance
proxy, so cluster metadata is not treated as useful serving data.

### Phase 3 tests and limits

Run the complete Phase 2 and Phase 3 suite with:

```powershell
python -m pytest -q
```

Verified in this workspace: **15 passed**, including all 7 Phase 2 tests and
8 Phase 3 tests. Pytest reports one non-failing Starlette deprecation warning
about its HTTPX-backed test client. The persistence tests use mocks; no live MongoDB server is bundled. Verify
the configured URI and database permissions against a local MongoDB instance
before relying on saved activity. The anonymous session label is for local
development only, not account security or privacy isolation.

## Phase 4 frontend

The React/Vite frontend is in `frontend/`. It calls the existing FastAPI routes and does not bundle or duplicate the paper corpus. Copy `frontend/.env.example` to `frontend/.env` and set `VITE_API_BASE_URL` to the API origin if it differs from `http://127.0.0.1:8000`.

Start the backend in one terminal from the project root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn researchpaper_ai.api:app --reload
```

Start the frontend in another PowerShell terminal:

```powershell
cd frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm.cmd install
npm.cmd run dev
```

Open the Vite URL (normally `http://localhost:5173`). FastAPI CORS already includes localhost and 127.0.0.1 Vite origins. The UI supports search, paper details, similar-paper recommendations, session bookmarks, search history, and editable research interests. MongoDB-backed activity controls become unavailable when the API reports MongoDB offline; paper search and recommendations remain usable. A browser session ID is an untrusted local activity label, not login or secure authentication.

The interface supports light, dark, and system themes. It follows the operating-system preference by default, cycles modes from the top-bar theme button, and remembers the selected mode in browser local storage when available. The Discover screen uses a restrained cosmic research-lab visual theme; layouts adapt for desktop, tablet, and mobile widths. In Research Interests, use **Add topic** to append to the existing draft without replacing earlier lines, then save the list to the current anonymous session.

Build the production frontend bundle with `cd frontend; npm.cmd run build`. There is no dedicated frontend automated test suite yet. The latest UI refresh build succeeded with Vite 7.3.7: JavaScript 246.17 kB (76.48 kB gzip), CSS 47.73 kB (10.93 kB gzip). No browser automation or accessibility test coverage is available here, so theme appearance and responsive layouts still need visual review in a browser.

## Phase 5 end-to-end verification

### Commands and checks run

The documented backend command `python -m uvicorn researchpaper_ai.api:app --host 127.0.0.1 --port 8000` started successfully and loaded the existing artifact. The documented Vite command `npm.cmd run dev -- --host 127.0.0.1` served the frontend with HTTP 200. The configured frontend URL (`http://127.0.0.1:8000`) matches the backend URL; CORS returned `http://127.0.0.1:5173` for the Vite origin. No `.env` or `frontend/.env` existed, and none was created or overwritten during verification. Existing dependencies were used; no browser tools were installed.

`python -m pytest -q`: **15 passed**, 1 non-failing Starlette/HTTPX deprecation warning. `npm.cmd run build`: succeeded (Vite 7.3.7; JS 243.38 kB / 75.65 kB gzip; CSS 21.97 kB / 5.97 kB gzip). `npm.cmd ls --depth=0` in `frontend/` found all declared frontend packages installed.

The live local FastAPI process returned HTTP 200 for health (41,120 papers), search (5 real results), paper details, and recommendations (5 results); the selected paper was absent from its recommendations. Whitespace query returned 422; unknown paper ID returned 404. Search still worked with `history_saved: false` while health reported `degraded` and MongoDB `unavailable`. Bookmark, history, and interest routes returned 503 as designed. The server was then stopped; a subsequent health request returned curl status `000` (connection unavailable). The Vite page returned HTTP 200. The automated Python tests exercise bookmark add/list/remove, history, and interest save/read using an in-memory mock store; these are not live MongoDB checks.

### Not verified / remaining limitations

No `MONGODB_URI` environment variable or local `.env` was configured, and no MongoDB service/tools were available. Therefore real MongoDB persistence for bookmarks, search history, and interests remains **unverified**. Playwright, Puppeteer, and Selenium are not installed, and no browser automation tool is available in this workspace; frontend interaction states (including its rendered backend-unavailable UI) were not browser-tested. There is no frontend automated test suite. Python regression tests and the frontend production build passed. No reproducible functional bug was found; setup `.env` copy commands were guarded so rerunning documented setup does not overwrite existing local configuration.

### Follow-up audit (2026-10-13)

This follow-up supersedes the earlier Phase 5 availability note above. The existing API on `http://127.0.0.1:8000` returned healthy status, model loaded, 41,120 papers, and MongoDB available. The root `.env` now exists; it was not displayed or changed. No `frontend/.env` exists. The configured frontend base URL in `frontend/.env.example` matches the backend URL. CORS returned `http://127.0.0.1:5173` for the Vite origin.

The existing API performed live MongoDB bookmark add (201), list (200), and delete (200) using a fresh unique session. Listing in a second unique session returned no bookmark; the test bookmark was deleted and verified absent. A fresh session's search-history and interests GET returned empty values. No history or interests were written, to avoid leaving test records: the API has no delete-history/delete-interest route, and a separate audit process could not connect directly to the configured MongoDB host for cleanup.

A second, temporary API process on port 8001 loaded the same artifact and dataset but could not resolve its MongoDB host from this environment. In that process, health was degraded; valid search returned five results with `history_saved: false`; details and recommendations returned 200; selected paper was excluded; and activity routes returned 503. This verifies degraded behavior. The temporary process was stopped; the existing port-8000 process was not restarted or interrupted.

Additional actual API validation results: missing/blank search query 422, unknown details and recommendation IDs 404, invalid K 422, bookmark body missing `paper_id` 422, bookmark unknown ID 404, malformed interests payload 422, and malformed session header 422. The real artifact returned ten query recommendations; empty, all-stopword, and out-of-vocabulary queries returned no results; scores were finite, between 0 and 1, and descending. Unknown model paper ID raised `KeyError` as documented.

Latest regression checks: `python -m pytest -q` **15 passed**, one non-failing Starlette/HTTPX deprecation warning; `npm.cmd run build` succeeded with Vite 7.3.7. `frontend/` has no test script and Playwright/Puppeteer/Selenium are unavailable, so browser interactions and responsive rendering were not tested. Actual persistence of search history and interests, persistence across an API restart, and direct MongoDB access from a new process remain unverified. No reproducible code bug was found; only this verification record changed.

## Phase 3 frontend bug fixes (2026-10-13)

Fixed stale-response races so an older search or recommendation request cannot replace the current view. Paper-detail failures now offer a retry. Activity-load failures now show an error and retry control instead of looking like a successful empty saved/history/interests result. Theme preference persistence now runs when the selected mode changes even if the effective colors stay the same (for example, selecting System while the OS is in Light mode). If browser session storage is blocked, API calls continue with one stable in-memory session ID for the page lifetime; it cannot persist across refresh in that browser configuration.

Added dependency-free API/session regression tests using Node's built-in test runner. From `frontend/`, run `npm.cmd test` and `npm.cmd run build`. Verified on 2026-10-13: `npm.cmd test` **2 passed**; `npm.cmd run build` succeeded with Vite 7.3.7 (JS 247.18 kB / 76.80 kB gzip; CSS 47.73 kB / 10.93 kB gzip). The tests cover stable session headers for interest GET/PUT and the blocked-storage fallback. No browser automation/browser binary is available, so rendered UI interactions, theme switching, race behavior, and responsive layouts still need manual browser verification. No frontend test existed before this phase; no backend, ML, dataset, or model artifact was changed.
