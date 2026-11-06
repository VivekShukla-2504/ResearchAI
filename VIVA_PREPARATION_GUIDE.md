# 🎓 ResearchPaper AI: Complete Viva Preparation & Project Guide

> **Project Title:** ResearchPaper AI – Intelligent Research Paper Discovery & Recommendation System  
> **Author / Developer:** Vivek Shukla  
> **Tech Stack:** Python, FastAPI, Scikit-Learn, NumPy, React 19, Vite, MongoDB Atlas, JWT, Google OAuth 2.0, SMTP  
> **Deployment:** Backend on Render, Frontend on Vercel, Database on MongoDB Atlas  

---

## 📌 Table of Contents
1. [30-Second Elevator Pitch (Opening Statement)](#1-30-second-elevator-pitch-opening-statement)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Complete System Architecture](#3-complete-system-architecture)
4. [Machine Learning & Recommendation Engine (Deep Dive)](#4-machine-learning--recommendation-engine-deep-dive)
5. [Backend Engineering & API Design (FastAPI)](#5-backend-engineering--api-design-fastapi)
6. [Authentication & Security Architecture](#6-authentication--security-architecture)
7. [Frontend Architecture & UI/UX (React + Vite)](#7-frontend-architecture--uiux-react--vite)
8. [Database Schema & Persistence Strategy](#8-database-schema--persistence-strategy)
9. [Deployment & DevOps Pipeline](#9-deployment--devops-pipeline)
10. [Top 25 Viva Questions & Model Answers](#10-top-25-viva-questions--model-answers)
11. [Slide-by-Slide Presentation Structure (For Claude PPT Generation)](#11-slide-by-slide-presentation-structure-for-claude-ppt-generation)

---

## 1. 30-Second Elevator Pitch (Opening Statement)

> *"Good morning, esteemed examiners. My project is **ResearchPaper AI**, an intelligent, full-stack research paper recommendation and discovery platform. When researchers search across academic databases like arXiv, keyword matching often fails to capture contextual relevance and inter-paper relationships. 
> 
> Our system ingests tens of thousands of scientific publications, normalizes the text, and maps them into a high-dimensional vector space using an optimized sublinear **TF-IDF with unigram and bigram representation**. Recommendations are calculated in sub-10 milliseconds using **L2-normalized Cosine Similarity**, with an **explainable AI feature** that surfaces exact matching terms. 
> 
> On the software engineering side, it features an asynchronous **FastAPI backend** with multi-factor authentication (Google OAuth, JWT token-versioning, and SMTP OTP verification), a responsive **React 19 single-page application**, and a fault-tolerant cloud architecture deployed across **Render, Vercel, and MongoDB Atlas**."*

---

## 2. Problem Statement & Motivation

### The Problem
* **Information Overload:** Over 2 million scientific papers are published annually. Finding prior work in a specific niche is like finding a needle in a haystack.
* **Flaws of Plain Keyword Search:** If a researcher searches for *"Graph Neural Networks for Drug Discovery"*, traditional Boolean search misses papers titled *"Molecular Property Prediction via Relational Message Passing"* simply because different vocabulary was used.
* **Lack of Explainability:** Many black-box deep learning systems output a list of papers without explaining *why* they were recommended.
* **Fragmented Researcher Experience:** Researchers have to switch between search engines, citation generators, and bookmarking tools.

### Our Solution
1. **Contextual Recommendation:** Uses scientific abstract and title representations to find mathematically similar papers.
2. **Transparent Recommendations:** Shows the exact top 5 overlapping scientific terms (`matching_terms`) that caused two papers to be linked.
3. **Personalized Profiles:** Automatically aggregates a researcher's saved papers and custom research interests to compute a personalized recommendation feed.
4. **All-in-One Workspace:** Integrated citation generator (BibTeX / APA), interactive similarity graphs, and multi-device authentication.

---

## 3. Complete System Architecture

```
[ User Browser / Client ]
           │
           ▼
[ React 19 + Vite Frontend ] (Hosted on Vercel)
     │                     │
     │ REST API (JSON)     │ Google Identity Services
     │ Bearer JWT          ▼
     │            [ Google OAuth 2.0 ]
     ▼
[ FastAPI Backend Application ] (Hosted on Render Web Service)
  ├── 1. Auth & Security Module (JWT Validation, Token Versioning, Passwords)
  ├── 2. SMTP Mailer (6-digit OTP verification via Gmail TLS)
  ├── 3. Recommendation Engine (In-Memory Fitted Model Artifact)
  │      ├── Sublinear TF-IDF Sparse Matrix (150,000 features, float32)
  │      ├── Cosine Similarity Matrix Calculator
  │      └── Lexicographical Prefix Suggester (O(log N) bisect)
  └── 4. MongoStore Adapter (Graceful degradation connection manager)
           │
           ▼
[ MongoDB Atlas Cloud Cluster ]
  ├── users (Unique emails, token versions, password hashes)
  ├── bookmarks (User saved papers)
  ├── interests (User research interest keywords)
  ├── search_history (Audit log of recent user queries)
  └── otps (TTL self-expiring 10-minute verification codes)
```

---

## 4. Machine Learning & Recommendation Engine (Deep Dive)

### A. Dataset Cleaning & Ingestion (`researchpaper_ai/data.py`)
* **Source:** ArXiv Computer Science dataset containing titles, abstracts, and category terms.
* **Cleaning Steps:**
  1. **Unicode Normalization:** NFKC normalization removes non-standard whitespace and special characters.
  2. **Safe Term Parsing:** Evaluates list strings safely without using dangerous `eval()`.
  3. **Deterministic Deduplication:** Generates a deterministic SHA-256 fingerprint for `(normalized_title, normalized_abstract)` to eliminate duplicates while merging overlapping category tags.
  4. **Title Weighting:** When constructing the textual representation of each paper, the title is repeated twice:
     $$\text{Document Text} = \text{Title} + \text{" "} + \text{Title} + \text{" "} + \text{Abstract}$$
     *Why?* Words in the paper title carry significantly higher semantic intent than words appearing once in a long abstract.

### B. Vectorization: Sublinear TF-IDF (`researchpaper_ai/engine.py`)
* **Parameters Configured:**
  * `stop_words='english'`: Eliminates non-informative words (*the, is, at, which*).
  * `ngram_range=(1, 2)`: Captures both individual terms (*"neural"*, *"network"*) and scientific phrases (*"neural network"*, *"attention mechanism"*, *"image segmentation"*).
  * `min_df=2`: Excludes typos and single-occurrence tokens (hapax legomena) to reduce noise.
  * `max_features=150,000`: Bounded vocabulary prevents memory explosion while keeping domain-specific terms.
  * `sublinear_tf=True`: Instead of raw term frequency $\text{tf}$, it uses:
    $$\text{sublinear\_tf} = 1 + \log(\text{tf}) \quad \text{for } \text{tf} > 0$$
    *Why?* A word appearing 20 times in an abstract is not 20 times more important than a word appearing once. Logarithmic scaling dampens the effect of repetitive keywords.
  * `dtype=np.float32`: Halves the RAM footprint compared to standard 64-bit float without any precision loss.
  * `L2 Normalization`: Every document vector is scaled so its Euclidean length is $1.0$:
    $$\|v\|_2 = \sqrt{\sum v_i^2} = 1$$

### C. Similarity Metric: Cosine Similarity
$$\text{Cosine Similarity}(q, d) = \frac{q \cdot d}{\|q\|_2 \|d\|_2}$$
Because both the query vector $q$ and document vector $d$ are pre-normalized to unit length ($\|q\| = 1, \|d\| = 1$), the formula simplifies to the simple dot product:
$$\text{Cosine Similarity}(q, d) = q \cdot d = \sum_{i=1}^{V} q_i \cdot d_i$$
* **Why Cosine over Euclidean Distance?**  
  Euclidean distance penalizes documents of different lengths. A 50-word short abstract and a 300-word comprehensive abstract discussing the exact same topic would have a large Euclidean distance. Cosine similarity measures the **angle** between the vectors, making it completely invariant to document length!
* **Computation Speed:** Generating recommendations over 40,000+ papers takes **under 8 milliseconds** because it leverages sparse matrix-vector multiplication in SciPy/NumPy.

### D. Explainable AI: Overlapping Scientific Terms
Unlike standard search engines that just give a score, our engine calculates the Hadamard (element-wise) product between the query vector and candidate paper vector:
$$\text{Product}_i = q_i \times d_i$$
It sorts the indices with the highest product values and maps them back to the vocabulary feature names. This extracts the **exact top 5 scientific terms** that contributed most to the match (e.g., `["graph neural", "attention", "node", "embeddings"]`).

### E. Fast Prefix Autocomplete (Bisection Algorithm)
When the user types into the search bar, the system provides live autocomplete suggestions. Instead of scanning all papers with regex (which is $O(N)$), it uses **Binary Search (`bisect.bisect_left`)** on the pre-sorted vocabulary array in **$O(\log V)$ time** (where $V = 150,000$ features), returning instant typeahead suggestions in less than 1 millisecond.

### F. Profile-Based Recommendations
When an authenticated user requests recommendations:
1. The engine retrieves all paper vectors saved in the user's bookmarks.
2. It vectorizes the user's custom research interest keywords.
3. It computes the **Centroid (mean composite vector)** of these representations and normalizes it.
4. It performs Cosine Similarity against the entire dataset, excluding papers the user has already bookmarked, returning a fresh, personalized feed.

---

## 5. Backend Engineering & API Design (FastAPI)

### Why FastAPI?
1. **Asynchronous Throughput:** Built on Starlette and ASGI (`uvicorn`), capable of handling thousands of concurrent requests.
2. **Automatic Data Validation:** Pydantic v2 schemas enforce strict type safety, input bounds (`min_length`, `max_length`), and payload sanitization before reaching business logic.
3. **Automated Documentation:** Generates interactive OpenAPI Swagger docs (`/docs`) and ReDoc (`/redoc`) out of the box.
4. **Lightweight & Modular:** Unlike Django, it does not bring an unneeded heavy ORM when working with scientific in-memory arrays and NoSQL.

### Key API Endpoints

| Method | Endpoint | Description | Access |
| :--- | :--- | :--- | :--- |
| `GET / HEAD` | `/` & `/health` | Service health status, paper count, Mongo connectivity | Public |
| `GET` | `/papers/suggest` | Prefix autocomplete suggestions ($O(\log N)$) | Public |
| `GET` | `/papers/search` | Search papers by free text query with similarity score | Public |
| `GET` | `/papers/{id}` | Detailed metadata, abstract, and terms for a paper | Public |
| `GET` | `/papers/{id}/recommendations` | Top-K most similar papers to a given paper | Public |
| `GET` | `/papers/recommendations/profile` | Personalized feed based on user bookmarks & interests | Protected (JWT) |
| `POST` | `/auth/send-otp` | Sends 6-digit OTP via SMTP (Signup, Login, Reset) | Public |
| `POST` | `/auth/signup` | Creates user account after OTP verification | Public |
| `POST` | `/auth/login` | Email + password authentication | Public |
| `POST` | `/auth/google` | Verifies Google OAuth 2.0 credential token | Public |
| `GET` | `/auth/me` | Fetches signed-in user profile details | Protected (JWT) |
| `POST` | `/auth/logout` | Revokes active user tokens server-side | Protected (JWT) |
| `GET / POST` | `/session/bookmarks` | Manage user saved paper library | Protected (JWT) |
| `GET / PUT` | `/session/interests` | Get / update user research interest keywords | Protected (JWT) |

### Fault Tolerance & Graceful Degradation
* In `mongo_store.py`, all database calls are wrapped in a resilient manager. If MongoDB Atlas experiences a network timeout or temporary outage:
  1. The API **does not crash**.
  2. Health endpoint reports status: `"degraded"`.
  3. ML Paper Search, Autocomplete, and Paper Recommendations **remain 100% operational** directly from the in-memory fitted model artifact.
  4. Only user persistence (saving new bookmarks) returns a gentle error instead of a 500 internal server error.

---

## 6. Authentication & Security Architecture

### A. Multi-Provider Authentication
1. **Local Password Flow:**
   * Passwords are never stored in plaintext. They are salted and hashed using PBKDF2-HMAC-SHA256 with 100,000 iterations.
2. **Google OAuth 2.0 (Google Identity Services):**
   * The client renders the official Google GIS button.
   * On sign-in, Google returns a cryptographically signed JWT `credential`.
   * The backend validates this token against Google's public keys via `google-auth` / tokeninfo verification, checking expiration, issuer (`accounts.google.com`), and our authorized `client_id`.
3. **Passwordless Email OTP Flow:**
   * Generates a secure, random 6-digit integer via Python's cryptographically secure `secrets.randbelow()`.
   * Dispatched to the user's real email via Gmail SMTP over TLS (Port 587).
   * Stored in MongoDB with a 10-minute TTL (Time-To-Live) index that auto-purges expired codes.

### B. Stateful Token Revocation via Token Versioning
* *The Problem with standard JWTs:* Standard JWTs are stateless. If a user logs out or resets their password, a stolen token remains valid until it expires.
* *Our Solution:* Every user document in MongoDB has an integer field: `token_version: int`.
  * When a JWT is minted, `token_version` is embedded in the token payload.
  * When the user clicks **Logout** or **Resets Password**, the server atomically increments `token_version += 1`.
  * On every protected request, the backend compares the token's version with the database's version. If they don't match, the request is immediately rejected with `401 Unauthorized`.
  * This provides **instant server-side token revocation** with zero external Redis dependencies!

### C. Duplicate Registration & Edge-Case Protection
* **Early OTP Gate:** If a user tries to create an account with an email that is already registered, `/auth/send-otp` rejects the request early with `400 Bad Request` (*"An account with this email already exists. Please sign in instead."*). No unnecessary emails are sent.
* **Database Constraint Safety:** The `email` field in MongoDB has a unique index. In `mongo_store.py`, `DuplicateKeyError` is handled cleanly so connection pools never close on user conflict.
* **Google Account Guard:** If a user originally registered with Google and later attempts to log in using a random password, the API detects `auth_provider == "google"` and `password_hash is None`, returning helpful guidance: *"This account was created with Google. Please use Google Sign-In or reset your password."*

---

## 7. Frontend Architecture & UI/UX (React + Vite)

### Modern Frontend Principles
* **React 19 & Vite:** Fast build tooling with Instant Hot Module Replacement (HMR) and optimized rollup production bundles.
* **Design Aesthetic:** "Cosmic Research Laboratory" theme featuring high-contrast scientific typography, crisp line borders, responsive grid layouts, and smooth transition animations.
* **Custom SVG Icon Library:** Hand-crafted lightweight SVG icons (`Icon.jsx`) without heavy third-party icon bundle bloat.
* **Interactive Network Similarity Graph:** Renders a 2D canvas visualization showing the central paper connected to its top similar papers with visual edge lines representing cosine similarity strength.
* **Instant Academic Citations:** Built-in modal generates formatted **BibTeX (`@misc`)** and **APA** citation strings with one-click copy to clipboard.
* **Responsive Mobile Drawer:** Smooth slide-out paper detail panel with Esc-key listener and backdrop blur.
* **Single-Page Application (SPA) Routing:** `vercel.json` rewrite configuration ensures all route requests fallback cleanly to `index.html` without 404 errors on browser refresh.

---

## 8. Database Schema & Persistence Strategy

### Collections in MongoDB Atlas

1. **`users`**
   ```json
   {
     "user_id": "user_a1b2c3d4e5f6",
     "email": "researcher@university.edu",
     "name": "Dr. Vivek Shukla",
     "password_hash": "pbkdf2:sha256:100000$...",
     "token_version": 1,
     "auth_provider": "local",
     "is_verified": true,
     "picture": "https://...",
     "created_at": "ISODate(...)",
     "updated_at": "ISODate(...)"
   }
   ```
   *Indexes:* `email` (Unique), `user_id` (Unique).

2. **`bookmarks`**
   ```json
   {
     "session_id": "user_a1b2c3d4e5f6",
     "paper_id": "paper_9f83b2...",
     "created_at": "ISODate(...)"
   }
   ```
   *Indexes:* Compound Unique `[("session_id", 1), ("paper_id", 1)]`.

3. **`interests`**
   ```json
   {
     "session_id": "user_a1b2c3d4e5f6",
     "terms": ["graph neural networks", "drug discovery", "bioinformatics"],
     "updated_at": "ISODate(...)"
   }
   ```
   *Indexes:* `session_id` (Unique).

4. **`otps`**
   ```json
   {
     "email": "researcher@university.edu",
     "purpose": "signup",
     "otp": "839201",
     "created_at": "ISODate(...)",
     "expires_at": "ISODate(...)"
   }
   ```
   *Indexes:* `[("email", 1), ("purpose", 1)]`, TTL index on `expires_at` (`expireAfterSeconds=0`).

---

## 9. Deployment & DevOps Pipeline

1. **Backend Service (Render):**
   * Automatically triggered on push to branch `main`.
   * Environment runs Python with `pip install -r requirements.txt`.
   * Start command: `uvicorn researchpaper_ai.api:create_app --factory --host 0.0.0.0 --port $PORT`.
   * Render health check probes (`HEAD /` and `GET /health`) verify application readiness.
2. **Frontend Service (Vercel):**
   * Automatically triggered on push to branch `main`.
   * Builds using `npm run build` (`vite build`) producing minified production assets.
   * `vercel.json` provides URL rewrite rules for SPA client routing.
3. **Database (MongoDB Atlas):**
   * Multi-region serverless cloud cluster with IP access whitelist and SSL/TLS encryption in transit and at rest.

---

## 10. Top 25 Viva Questions & Model Answers

### General & Conceptual Questions

#### Q1: What is ResearchPaper AI in simple terms?
**Answer:** It is a machine learning-powered web platform that helps researchers quickly discover relevant academic papers by analyzing the textual and conceptual similarity of paper titles and abstracts, rather than relying solely on exact keyword matches.

#### Q2: What type of Recommendation System is this (Collaborative vs Content-Based)?
**Answer:** This is a **Content-Based Filtering System**. It recommends items based purely on the features of the items themselves (the words and semantic n-grams in the title and abstract) and the user's declared profile/bookmarks, without requiring community rating matrices.

#### Q3: Why didn't you use Collaborative Filtering?
**Answer:** Academic research papers suffer heavily from the **"Cold-Start Problem"** and extreme sparsity. Thousands of papers have very few or zero user clicks/ratings initially. Content-based filtering allows us to recommend newly published papers immediately based on their text alone.

#### Q4: Why did you choose TF-IDF over deep learning models like BERT or SciBERT?
**Answer:** There are four key engineering reasons:
1. **Inference Latency:** TF-IDF with sparse dot products computes recommendations over 40,000 papers in under 10 milliseconds, whereas running BERT transformers over 40,000 papers without specialized multi-GPU infrastructure takes seconds per query.
2. **RAM & Hosting Constraints:** Free and standard cloud tiers (such as Render) provide 512 MB of RAM. A compressed float32 sparse matrix takes ~70 MB, whereas deep transformer models exceed 1.5 GB.
3. **Explainability:** TF-IDF gives transparent feature weights, allowing us to display the exact top 5 scientific terms responsible for the recommendation (`matching_terms`).
4. **Deterministic Accuracy:** For academic title and abstract search, domain-specific unigrams and bigrams provide high precision without hallucination.

#### Q5: What is the difference between Term Frequency (TF) and Inverse Document Frequency (IDF)?
**Answer:**
* **Term Frequency (TF):** Measures how frequently a word appears in a specific document.
* **Inverse Document Frequency (IDF):** Measures how rare or common a word is across the entire corpus:
  $$\text{IDF}(t) = \log\left(\frac{1 + N}{1 + \text{df}(t)}\right) + 1$$
* Common words like *"experiment"* or *"result"* receive a very low IDF score, while specific scientific terms like *"CRISPR"* or *"eigenvalue"* receive a high IDF score.

#### Q6: What does `sublinear_tf=True` do and why did you use it?
**Answer:** Normally, TF is linear. But if an abstract mentions the word *"quantum"* 10 times, it is not 10 times more relevant than an abstract that mentions it 3 times. `sublinear_tf=True` replaces raw count with $1 + \log(\text{tf})$, preventing repetitive text from disproportionately dominating the ranking.

#### Q7: Why did you use `ngram_range=(1, 2)` instead of just unigrams?
**Answer:** In scientific literature, pairs of words have completely different meanings than individual words. For example, *"neural"* and *"network"* alone are generic, but the bigram *"neural network"* represents a specific concept. Similarly, *"random"* and *"forest"* vs *"random forest"*. Bigrams capture contextual phrases.

#### Q8: Why did you duplicate the title in `paper.text` (`f"{title} {title} {abstract}"`)?
**Answer:** It is a technique called **feature weighting**. The title represents the core contribution of the paper. Doubling the title gives its terms twice the frequency count, ensuring title matches have higher priority in cosine similarity rankings.

#### Q9: What is the time complexity of generating recommendations?
**Answer:** For a query vector with $K$ non-zero terms against $N$ pre-normalized document vectors, calculating cosine similarity is $O(K \times \text{average non-zero entries})$. In practice, with $N = 40,000$, this matrix-vector dot product executes in **~5 to 8 milliseconds**.

#### Q10: How does the search autocomplete / suggest feature work?
**Answer:** The vocabulary of 150,000 features is kept lexicographically sorted. When the user types a prefix, the system runs a **Binary Search (`bisect_left`)** in **$O(\log V)$** time to locate the prefix range immediately, returning instant typeahead suggestions with zero full-dataset scans.

---

### Backend & Database Architecture

#### Q11: Why did you choose FastAPI over Flask or Django?
**Answer:**
1. **Asynchronous Architecture:** FastAPI runs on `asyncio` and ASGI (`uvicorn`), handling concurrent I/O operations efficiently.
2. **Built-in Pydantic v2:** Automatic request parsing, validation, and serialization with descriptive error messages.
3. **Auto-Documentation:** Automatic OpenAPI/Swagger generation at `/docs`.
4. **Minimalism:** Unlike Django, which imposes a heavyweight SQL ORM, FastAPI integrates natively with custom NumPy/Scikit-Learn in-memory models and NoSQL MongoDB.

#### Q12: Why MongoDB instead of PostgreSQL or MySQL?
**Answer:** The primary entities in this application are user bookmarks, recent searches, and research interest arrays. These are document-oriented and session-scoped. MongoDB's JSON/BSON document model matches our data schemas directly, and features like TTL (Time-To-Live) indexes allow automatic purging of expired verification codes without needing a background cron job.

#### Q13: What happens if MongoDB goes down while the server is running?
**Answer:** The application implements **Graceful Degradation**. All ML search, recommendation, and autocomplete operations run entirely in-memory from the fitted Python model artifact. If MongoDB becomes unreachable, the health check switches to `"degraded"`, but search and recommendations continue serving users without crashing.

#### Q14: How does your OTP verification work?
**Answer:** When requested, the server generates a cryptographically secure 6-digit code using `secrets.randbelow()`. It hashes/stores it in MongoDB with a 10-minute expiry timestamp and dispatches an HTML email via Gmail SMTP over TLS (port 587). The OTP is consumed (deleted) immediately upon single successful verification to prevent replay attacks.

#### Q15: How do you prevent duplicate user registrations?
**Answer:** We protect against duplicate registrations at two distinct layers:
1. **Application Layer:** When `/auth/send-otp` is called with purpose `"signup"`, it checks if the email already exists in MongoDB. If it does, it immediately throws `400 Bad Request` (*"An account with this email already exists"*), preventing spamming of OTP emails.
2. **Database Layer:** The `email` field has a MongoDB Unique Index constraint. If a race condition occurs, `mongo_store.py` catches `DuplicateKeyError` and raises a clean `DuplicateUserError` without closing the connection.

---

### Security & Authentication

#### Q16: How do JWT tokens work in your system?
**Answer:** When a user logs in, the server generates an HMAC-SHA256 signed JSON Web Token containing claims: `user_id`, `email`, `name`, `token_version`, and an expiration timestamp (`exp`). The client sends this token in the HTTP `Authorization: Bearer <token>` header for protected endpoints.

#### Q17: If JWTs are stateless, how do you handle Logout or Password Reset?
**Answer:** We implemented **Token Versioning**. Each user in MongoDB has an integer `token_version`. When a user logs out or resets their password, the database field `token_version` is atomically incremented by 1. Whenever an API request arrives, the token's version is compared with the database. If the user logged out, their old token's version will not match, immediately invalidating all previous sessions.

#### Q18: How does Google OAuth 2.0 work in your project?
**Answer:** The frontend integrates Google Identity Services (GIS). Upon successful user consent, Google issues a signed ID token credential. The frontend sends this to `/auth/google`. The backend verifies the signature, issuer, and `audience` using Google's public keys. If valid, it extracts the verified email, name, and profile picture, creates or updates the user record, and issues our internal JWT.

#### Q19: What was the "Error 400: origin_mismatch" and how did you resolve it?
**Answer:** Google OAuth requires all client application URLs to be explicitly whitelisted under **"Authorized JavaScript origins"** in the Google Cloud Console. When our frontend was deployed to Vercel (`https://research-ai-opal-two.vercel.app`), Google blocked sign-in because that domain was not registered. Adding the Vercel URL and local development origins resolved the mismatch.

#### Q20: What is CORS and why is it important in this project?
**Answer:** Cross-Origin Resource Sharing (CORS) is a browser security mechanism that blocks web pages from making AJAX requests to a different domain. Because our frontend is on Vercel (`*.vercel.app`) and our backend is on Render (`*.onrender.com`), the backend must explicitly declare `CORSMiddleware` with allowed origins, methods, and headers.

---

### Frontend & UI/UX

#### Q21: What is the "Cosmic" UI theme?
**Answer:** It is a custom design system tailored for academic and deep-tech platforms. It uses a high-contrast palette, deep slate/indigo backgrounds in dark mode, crisp borders, subtle glassmorphism card surfaces, and clear visual hierarchy for paper titles, tags, and similarity percentages.

#### Q22: How does the Interactive Similarity Graph work?
**Answer:** It uses an HTML5 Canvas component that renders a node-link diagram. The queried or selected paper is placed at the center, and recommended papers are arrayed around it as orbital nodes. The distance and opacity of the connecting lines visually represent their Cosine Similarity score.

#### Q23: Why do you need `vercel.json` for deployment?
**Answer:** In a Single Page Application (SPA) using client-side routing, navigating directly to a deep URL or refreshing the page causes the web server to look for a physical file at that path. `vercel.json` specifies a rewrite rule (`"source": "/(.*)", "destination": "/index.html"`) so all routes are served by React.

---

### Limitations & Future Scope

#### Q24: What are the current limitations of this project?
**Answer:**
1. **Vocabulary Ceiling:** While 150,000 features cover most computer science terminology, new slang or completely novel buzzwords outside the corpus require periodic refitting.
2. **Text-Only Modality:** It analyzes textual metadata (title and abstract) but does not inspect mathematical equations, embedded charts, or paper figures.

#### Q25: How would you scale this system in the future?
**Answer:**
1. **Hybrid Retrieval (Dense + Sparse):** Combine BM25/TF-IDF for high-precision keyword recall with dense neural embeddings (e.g., Specter or SciBERT) indexed in a vector database like Pinecone, Milvus, or Qdrant for semantic nuances.
2. **Automated ArXiv Ingestion Pipeline:** Connect a daily cron job that streams new preprint papers from the ArXiv API into MongoDB.
3. **LLM Synthesis:** Integrate Gemini or Claude to generate 3-bullet executive takeaways or comparative synthesis between two papers.

---

## 11. Slide-by-Slide Presentation Structure (For Claude PPT Generation)

> **Tip:** You can paste the following slide outline into Claude or ChatGPT to generate your PowerPoint presentation slides!

### Slide 1: Title Slide
* **Title:** ResearchPaper AI: Intelligent Research Paper Discovery & Recommendation Platform
* **Subtitle:** Machine Learning-Driven Academic Discovery with Explainable AI & Secure Full-Stack Architecture
* **Presenter:** Vivek Shukla
* **Key Tech:** FastAPI, Scikit-Learn, React 19, MongoDB Atlas, Google OAuth

### Slide 2: Problem Statement & Motivation
* Academic publishing explosion: 2M+ papers annually.
* Keyword search limitations: Misses conceptual matches with different vocabulary.
* Black-box recommendation tools: No transparency on *why* papers are linked.
* Objective: Build a fast (<10ms), explainable, and personalized recommendation engine.

### Slide 3: System Architecture Overview
* Clean client-server separation:
  * **Frontend:** React 19 + Vite SPA (Vercel)
  * **Backend:** FastAPI ASGI Application (Render)
  * **ML Engine:** In-memory Sublinear TF-IDF + Cosine Similarity Matrix
  * **Database:** MongoDB Atlas Cloud Cluster
  * **External Services:** Google Identity Services, Gmail SMTP

### Slide 4: Data Engineering & Cleaning Pipeline
* Ingestion of arXiv Computer Science dataset.
* Deterministic SHA-256 deduplication for title-abstract pairs.
* Safe ast parsing of multi-label taxonomy terms.
* Feature weighting: Doubled title string (`Title + Title + Abstract`) for higher semantic relevance.

### Slide 5: Core Machine Learning Engine
* Sublinear TF-IDF: $1 + \log(\text{tf})$ dampens term frequency inflation.
* Unigrams & Bigrams (`ngram_range=(1, 2)`) capture academic phrases.
* L2 Normalization creates unit vectors ($\|v\|_2 = 1$).
* Cosine Similarity simplified to high-speed dot products.
* Sub-10 millisecond latency over 40,000+ papers.

### Slide 6: Explainable AI & Fast Search
* **Explainable Matching:** Hadamard product highlights the top 5 overlapping scientific terms (`matching_terms`).
* **Instant Typeahead:** $O(\log N)$ binary search (`bisect`) on 150,000 sorted features provides sub-millisecond autocomplete.
* **Profile Personalization:** Generates composite user vector from saved bookmarks and interest tags.

### Slide 7: Backend Engineering & API Design
* FastAPI framework with asynchronous uvicorn server.
* Pydantic v2 strict input validation and auto OpenAPI Swagger documentation.
* Fault-tolerant architecture: Graceful degradation keeps search operational even if MongoDB disconnects.
* Comprehensive test suite: 51 automated unit/integration tests (pytest).

### Slide 8: Security & Authentication Architecture
* Three authentication options:
  1. Local email + salted PBKDF2 password hashing.
  2. Google OAuth 2.0 (Google Identity Services).
  3. Passwordless 6-digit OTP verification via Gmail SMTP TLS.
* **Token Versioning:** Instant server-side JWT revocation on logout and password reset.
* Early duplicate registration validation.

### Slide 9: Frontend Design & User Experience
* Responsive Cosmic Theme with Light/Dark mode toggling.
* Interactive HTML5 Canvas network similarity graph.
* One-click academic citation generator (BibTeX & APA).
* Responsive slide-out paper details drawer with keyboard navigation.

### Slide 10: Database Schema & Cloud Storage
* MongoDB Atlas collections: `users`, `bookmarks`, `interests`, `otps`.
* Compound unique indexes prevent duplicate bookmarks and registrations.
* Automatic self-expiring TTL index on OTP verification codes.

### Slide 11: Deployment & DevOps
* Continuous Deployment via Git:
  * Backend on Render Web Service with health probes (`HEAD` / `GET`).
  * Frontend on Vercel with SPA routing rewrites (`vercel.json`).
  * Database on MongoDB Atlas serverless cluster.

### Slide 12: Summary & Future Enhancements
* **Key Achievements:** Sub-10ms search, explainable AI, multi-auth security, 100% test pass rate.
* **Future Roadmap:**
  * Hybrid retrieval with Dense Embeddings (SciBERT) + Vector DB (Pinecone).
  * Automated daily arXiv RSS ingestion pipeline.
  * LLM-powered multi-paper comparative synthesis.
* **Q&A:** Open for questions.
