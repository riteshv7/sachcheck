# SachCheck 🔍
### Real-Time Hindi-English (Hinglish) Political Fact-Checking Assistant

SachCheck is a modern research and portfolio project consisting of a **Manifest V3 Chrome Extension** and a **FastAPI Backend Server**. It captures live audio from any active browser tab (such as a YouTube political debate or news segment), transcribes it in real-time using speaker-labeled Hinglish models, extracts factual assertions, and displays contextual grounding cards in a premium dark-themed browser side panel.

> [!NOTE]  
> **Context, Not Verdict**: SachCheck is built to be a *context machine, not a verdict machine*. It does not stamp claims as absolute "TRUE" or "FALSE". Instead, it acts as an objective research assistant, showing the literal claim, the implied claim, missing context, source citations, and confidence metrics.

---

## 🚀 Key Features & Architecture

```
                                  SachCheck Architecture
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
             Chrome Extension UI                           FastAPI Backend
       (Side Panel, Worker, Offscreen)                     (Uvicorn localhost)
                       │                                           │
         Sends 15s audio chunks via POST                           │
                       └───────────────────────────────────────────►
                                                                   │
                                                                   ▼
                                                          Hybrid Routing Engine
                                                                   │
                                      ┌────────────────────────────┴────────────────────────────┐
                                      ▼ (Similarity >= 0.82)                                    ▼ (Similarity < 0.82)
                                 [Fast Path]                                               [Deep Path]
                            Recycled-Claim Matcher                                     Real-Time Search & RAG
                                      │                                                         │
                        Matches against debunked_db.json                            Executes Serper Google Search
                                      │                                                         │
                         Retrieves cached vector card                              Synthesizes sources via Gemini
                                      │                                                         │
                                      └────────────────────────────┬────────────────────────────┘
                                                                   ▼
                                                     Appends turning context card
                                                                   │
                                           Polled every 2s via GET │
                                     ◄─────────────────────────────┘
```

1.  **Tab Audio Capture (No Mute)**: Uses the Chrome `tabCapture` and Web Audio APIs inside an Offscreen Document to capture tab audio and pipe it back to the user's speakers, ensuring the source audio remains audible during recording.
2.  **Hybrid Routing Engine**:
    *   **Fast Path (Recycled Matcher)**: Compares extracted claims against a local seeded vector database of known political fact-checks ([debunked_db.json](data/debunked_db.json)) using `gemini-embedding-2` and pure Python cosine similarity. Operates in **2–5 ms** on cache hits, bypassing external API calls.
    *   **Deep Path (Real-Time Search & RAG)**: For new claims, expands search queries, executes Serper Google Search APIs across restricted domains, and synthesizes source arguments into a structured context card using Gemini.
3.  **Hinglish Code-Mixed Support**: Native understanding of phonetic code-mixed statements (e.g., *"EPFO data ke mutabik pichle saal 1.3 crore jobs generate hui"*).
4.  **Evaluation Suite**: Includes simulated Word Error Rate (WER) ASR noise injection and automated source-sensitivity matrices to rigorously evaluate pipeline resilience.

---

## 📁 Repository Structure

```
sachcheck/
├── backend/                  # Python backend server and core NLP brain
│   ├── server.py             # FastAPI application and session manager
│   ├── claims.py             # Claim extraction and check-worthiness classifier
│   ├── matcher.py            # Cosine similarity matching & vector DB logic
│   ├── embeddings.py         # Text embedding generator with local cache
│   ├── search.py             # Serper Google Search API integrations
│   ├── context.py            # Gemini-based context card synthesis
│   ├── transcribe.py         # Sarvam Saaras V3 audio transcription connector
│   ├── evaluate.py           # Quantitative precision/recall evaluation suite
│   └── experiment.py         # Source-sensitivity experimental framework
├── extension/                # Chrome extension frontend
│   ├── manifest.json         # Manifest V3 configuration and permissions
│   ├── background.js         # Service worker coordinating tab capture and panel UI
│   ├── offscreen.js          # Web Audio recorder converting stream to WebM chunks
│   ├── panel.html            # Premium side panel interface
│   ├── panel.js              # Event handler, timer, and state polling coordinator
│   └── styles.css            # Dark-theme, glassmorphic UI stylesheet
├── data/                     # Local datasets and results caching
│   ├── debunked_db.json      # Seeded database of historical political fact-checks
│   ├── test_set.json         # 15 hand-labeled Hinglish political turns for evaluation
│   ├── embedding_cache.json  # Pre-computed vectors for local matching acceleration
│   └── results/              # Saved evaluation and experiment reports
└── analysis/                 # Analytical reports
    └── evaluation_report.md  # Analytical report of Phase 3 findings
```

---

## 🛠️ Setup & Installation

### 1. Backend Server Setup
Ensure you have Python 3.10+ installed.

1.  Navigate to the project root and activate the virtual environment:
    ```bash
    cd sachcheck
    source .venv/bin/activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r backend/requirements.txt
    ```
3.  Configure environment variables. Create a `.env` file in the `backend/` directory:
    ```env
    GEMINI_API_KEY=your_gemini_api_key_here
    SERPER_API_KEY=your_serper_api_key_here
    SARVAM_API_KEY=your_sarvam_api_key_here
    ```

### 2. Loading the Chrome Extension
1.  Open Google Chrome and navigate to `chrome://extensions/`.
2.  Enable **Developer mode** using the toggle in the top-right corner.
3.  Click the **Load unpacked** button in the top-left.
4.  Select the `extension/` directory inside your `sachcheck` project folder.
5.  The **SachCheck** extension icon will now appear in your toolbar. Pin it for quick access.

---

## 💻 Running & Live Testing

To test the final product and verify that the pipeline is working:

### Step 1: Start the Local Backend Server
Run the FastAPI server using Uvicorn:
```bash
.venv/bin/uvicorn backend.server:app --reload --host 127.0.0.1 --port 8000
```
Verify that the terminal indicates the server is successfully listening on `http://127.0.0.1:8000`.

### Step 2: Open and Configure the Extension
1.  Navigate to a video containing Hinglish political discussions (e.g., a debate, news segment, or speech on YouTube).
2.  Click the **SachCheck** extension icon in your Chrome toolbar. The **SachCheck Side Panel** will slide open on the right side of your browser.
3.  **Check the "Mock Mode" Box** (Recommended): 
    > [!IMPORTANT]  
    > Checking **Mock Mode** instructs the server to bypass live API calls to Serper and Gemini, using high-fidelity local simulation cards instead. This bypasses external API costs, is completely insulated from daily Gemini free-tier rate limits (`429 Resource Exhausted`), and lets you test the complete, end-to-end frontend-backend flow immediately.
4.  Click the **Start Fact-Checking** button in the side panel.

### Step 3: Run the Live Session
1.  Play the video in the active tab.
2.  Observe the side panel:
    *   The session timer will begin counting.
    *   Every 15 seconds, a new audio chunk will be sent to the server.
    *   The **Live Transcript** section will update with speaker turns.
    *   Check-worthy claims will trigger a pulsing shimmer loading card.
    *   Grounded context cards will render with literal/implied claims, citations, and confidence badges.
3.  Click **Stop Fact-Checking** when done. A final report will be written to `data/results/`.

---

## 📊 Running the Evaluation & Experiment Suites

To execute the programmatic testing frameworks in the background and review the empirical metrics:

### 1. Quantitative Evaluation (Check-Worthiness & RAG Completeness)
To run the evaluation measuring classifier precision/recall under ASR noise (0%, 10%, 20% WER) and RAG completeness:
```bash
.venv/bin/python backend/evaluate.py
```
This writes the quantitative performance matrices to `data/results/quantitative_evaluation_results.json`.

### 2. Source-Sensitivity Experiment
To run identical political claims against different restricted source boundaries (Government-only, News-only, Fact-Checkers-only, Standard/Mixed):
```bash
.venv/bin/python backend/experiment.py
```
This writes the comparative source cards to `data/results/source_sensitivity_results.json`.

---

## 📝 Research & Evaluation Highlights

### Check-Worthiness Classifier Performance (ASR Noise Impact)
Our evaluation demonstrates excellent classifier resilience under spelling variations, with a natural degradation in recall under high-noise environments:
*   **0% WER (Clean)**: 100.00% Precision, 100.00% Recall (F1: 100.00%)
*   **10% WER (Moderate Noise)**: 100.00% Precision, 100.00% Recall (F1: 100.00%)
*   **20% WER (Severe Noise)**: 100.00% Precision, 90.00% Recall (F1: 94.74%)

### Source-Sensitivity Matrix Findings
*   **Government-only Sources**: High-accuracy raw counts but high contextual omission (e.g., omitting small average loan sizes).
*   **Fact-Checking Portals**: The most effective corrective layer, exposing methodological shifts (such as the 2018 shift from linear-km to lane-km for highway speed) and structural category breakdowns.
*   **Standard/Mixed Synthesis**: The optimal configuration, successfully anchoring official statistics while incorporating investigative caveats.

For the full analytical breakdown, including the **Structured Pipeline Failure Taxonomy**, read the [evaluation_report.md](analysis/evaluation_report.md).
