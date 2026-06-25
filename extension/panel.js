const BACKEND_URL = "http://127.0.0.1:8000";
let activeSessionId = null;
let isRecording = false;
let timerInterval = null;
let pollInterval = null;
let sessionStartTime = 0;

// Remote Logger for debugging
function logToServer(level, message, context = "") {
  const logMsg = typeof context === "object" ? JSON.stringify(context) : String(context);
  console.log(`[${level.toUpperCase()}] ${message}`, context);
  
  fetch(`${BACKEND_URL}/api/log`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ 
      level: level, 
      message: message, 
      context: logMsg
    })
  }).catch(() => {});
}

// Error listeners to capture all side panel UI failures
window.addEventListener("error", (event) => {
  logToServer("error", event.message, { filename: event.filename, lineno: event.lineno });
});

window.addEventListener("unhandledrejection", (event) => {
  logToServer("error", "Unhandled Promise Rejection: " + String(event.reason), event.reason?.stack || "");
});

// DOM Elements
const actionBtn = document.getElementById("action-btn");
const mockToggle = document.getElementById("mock-toggle");
const timerEl = document.getElementById("timer");
const logoDot = document.querySelector(".logo-dot");
const connectionStatus = document.getElementById("connection-status");
const connectionDot = connectionStatus.querySelector(".status-indicator");
const connectionText = connectionStatus.querySelector(".status-text");

const transcriptContainer = document.getElementById("transcript-container");
const transcriptEmpty = document.getElementById("transcript-empty");
const transcriptCount = document.getElementById("transcript-count");

const cardsContainer = document.getElementById("cards-container");
const cardsEmpty = document.getElementById("cards-empty");
const cardsCount = document.getElementById("cards-count");

// New DOM Elements for YouTube URL scan
const tabScan = document.getElementById("tab-scan");
const tabLive = document.getElementById("tab-live");
const scanContent = document.getElementById("scan-content");
const liveContent = document.getElementById("live-content");
const scanBtn = document.getElementById("scan-btn");
const scanProgress = document.getElementById("scan-progress");
const progressPercentage = document.getElementById("progress-percentage");
const step1 = document.getElementById("step-1");
const step2 = document.getElementById("step-2");
const step3 = document.getElementById("step-3");
const videoStatusTitle = document.getElementById("video-status-title");
const videoStatusUrl = document.getElementById("video-status-url");
const manualUrlBox = document.getElementById("manual-url-box");
const manualUrlInput = document.getElementById("manual-url-input");

let renderedTurnsCount = 0;
let renderedCardsSignatures = new Set();
let currentTabUrl = "";
let currentTabId = null;

// Initialize UI and check server health
document.addEventListener("DOMContentLoaded", async () => {
  logToServer("info", "Side panel DOMContentLoaded initialized.");
  
  const storage = await chrome.storage.local.get({ mockMode: true });
  mockToggle.checked = storage.mockMode;
  
  mockToggle.addEventListener("change", () => {
    chrome.storage.local.set({ mockMode: mockToggle.checked });
    logToServer("info", `Mock mode toggled to: ${mockToggle.checked}`);
  });

  checkServerHealth();
  setInterval(checkServerHealth, 5000);
  
  actionBtn.addEventListener("click", toggleFactChecking);
  scanBtn.addEventListener("click", handleVideoScan);
  
  // Tab switching
  tabScan.addEventListener("click", () => {
    tabScan.classList.add("active");
    tabLive.classList.remove("active");
    scanContent.style.display = "flex";
    liveContent.style.display = "none";
    detectActiveTab();
  });
  
  tabLive.addEventListener("click", () => {
    tabLive.classList.add("active");
    tabScan.classList.remove("active");
    liveContent.style.display = "flex";
    scanContent.style.display = "none";
  });

  // Listen for tab activation to update active YouTube video in side panel
  chrome.tabs.onActivated.addListener(() => {
    detectActiveTab();
  });
  
  // Listen for tab updates (e.g. navigation)
  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (tabId === currentTabId && changeInfo.url) {
      detectActiveTab();
    }
  });

  // Run initial tab detection
  detectActiveTab();

  // Synchronize with any active session
  logToServer("info", "Sending PANEL_READY handshake to background service worker...");
  chrome.runtime.sendMessage({ type: "PANEL_READY" }, (response) => {
    if (chrome.runtime.lastError) {
      logToServer("warning", "PANEL_READY handshake failed (normal if first load)", chrome.runtime.lastError.message);
      return;
    }
    
    if (response && response.sessionId) {
      logToServer("info", "Synchronized successfully with active background session", response);
      
      activeSessionId = response.sessionId;
      isRecording = true;
      
      mockToggle.checked = response.mock;
      mockToggle.disabled = true;
      
      actionBtn.disabled = false;
      actionBtn.textContent = "Stop Fact-Checking";
      actionBtn.className = "btn btn-danger";
      logoDot.classList.add("active");
      
      renderedTurnsCount = 0;
      renderedCardsSignatures.clear();
      transcriptContainer.innerHTML = "";
      cardsContainer.innerHTML = "";
      transcriptEmpty.style.display = "none";
      cardsEmpty.style.display = "none";
      
      sessionStartTime = response.startTime;
      timerInterval = setInterval(updateTimer, 1000);
      pollInterval = setInterval(pollSessionStatus, 2000);
    } else {
      logToServer("info", "No active background session found on handshake.");
    }
  });
});

// Check if FastAPI server is reachable
async function checkServerHealth() {
  if (isRecording) return;
  
  try {
    const response = await fetch(`${BACKEND_URL}/`, { method: "GET" });
    if (response.ok || response.status === 200) {
      setConnectionState(true);
    } else {
      setConnectionState(false);
    }
  } catch (err) {
    setConnectionState(false);
  }
}

function setConnectionState(connected) {
  if (connected) {
    connectionDot.className = "status-indicator connected";
    connectionText.textContent = "Server Connected";
    if (!isRecording) {
      actionBtn.disabled = false;
    }
  } else {
    connectionDot.className = "status-indicator disconnected";
    connectionText.textContent = "Server Offline";
    if (!isRecording) {
      actionBtn.disabled = true;
    }
  }
}

// Toggle Start/Stop
async function toggleFactChecking() {
  if (isRecording) {
    logToServer("info", "User clicked Stop Fact-Checking button.");
    await stopFactChecking();
  } else {
    logToServer("info", "User clicked Start Fact-Checking button. Showing toolbar instruction.");
    alert(
      "To start fact-checking, please click the SachCheck 'S' icon in your Chrome toolbar.\n\n" +
      "This immediately grants the required tab capture permissions and automatically starts the fact-checking session."
    );
  }
}

// Stop Fact Checking Session
async function stopFactChecking() {
  actionBtn.disabled = true;
  actionBtn.textContent = "Saving Report...";
  
  try {
    logToServer("info", "Stopping capture session...");
    await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "STOP_CAPTURE" }, (res) => {
        resolve(res);
      });
    });
    
    if (activeSessionId) {
      const response = await fetch(`${BACKEND_URL}/api/session/${activeSessionId}/stop`, {
        method: "POST"
      });
      
      if (response.ok) {
        const data = await response.json();
        logToServer("info", `Session stopped on server. Saved: ${data.report_saved_to}`);
      }
    }
    
  } catch (err) {
    logToServer("error", "Error during stopFactChecking", err.message);
  } finally {
    resetUIState();
  }
}

function resetUIState() {
  logToServer("info", "Resetting UI state to idle.");
  isRecording = false;
  activeSessionId = null;
  mockToggle.disabled = false;
  actionBtn.disabled = false;
  actionBtn.textContent = "Start Fact-Checking";
  actionBtn.className = "btn btn-primary";
  logoDot.classList.remove("active");
  
  clearInterval(timerInterval);
  clearInterval(pollInterval);
  timerEl.textContent = "00:00";
}

function updateTimer() {
  const elapsedMs = Date.now() - sessionStartTime;
  const totalSeconds = Math.floor(elapsedMs / 1000);
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  timerEl.textContent = `${minutes}:${seconds}`;
}

// Poll Session Status from Server
async function pollSessionStatus() {
  if (!activeSessionId) return;
  
  try {
    const response = await fetch(`${BACKEND_URL}/api/session/${activeSessionId}/status`);
    if (response.status === 404) {
      logToServer("warning", "Active session expired or server restarted. Cleaning up state.");
      // Tell background script to stop recording and close offscreen document
      chrome.runtime.sendMessage({ type: "STOP_CAPTURE" }, () => {
        // Ignore errors if service worker is inactive
        if (chrome.runtime.lastError) {}
      });
      resetUIState();
      return;
    }
    
    if (!response.ok) {
      throw new Error(`Failed to fetch status: HTTP ${response.status}`);
    }
    
    const data = await response.json();
    updateUIContent(data);
  } catch (err) {
    logToServer("error", "Error polling session status", err.message);
  }
}

function updateUIContent(sessionData) {
  const { transcript, context_cards, is_processing } = sessionData;
  
  if (transcript && transcript.length > renderedTurnsCount) {
    transcriptEmpty.style.display = "none";
    
    for (let i = renderedTurnsCount; i < transcript.length; i++) {
      const turn = transcript[i];
      appendTranscriptBubble(turn);
    }
    
    renderedTurnsCount = transcript.length;
    transcriptCount.textContent = `${renderedTurnsCount} turn${renderedTurnsCount === 1 ? "" : "s"}`;
  }
  
  if (context_cards && context_cards.length > 0) {
    context_cards.forEach((card) => {
      const signature = card.claim_text;
      
      if (!renderedCardsSignatures.has(signature)) {
        cardsEmpty.style.display = "none";
        appendContextCard(card);
        renderedCardsSignatures.add(signature);
      }
    });
    
    cardsCount.textContent = `${renderedCardsSignatures.size} card${renderedCardsSignatures.size === 1 ? "" : "s"}`;
  }
  
  const existingShimmers = cardsContainer.querySelectorAll(".shimmer-card");
  existingShimmers.forEach(s => s.remove());
  
  if (is_processing) {
    appendShimmerPlaceholder();
  }
}

function formatTime(seconds) {
  if (isNaN(seconds) || seconds === null) return "00:00";
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function getSpeakerClass(speaker) {
  const name = speaker.toLowerCase();
  if (name.includes("anchor")) return "speaker-anchor";
  if (name.includes("pravakta a") || name.includes("speaker_00")) return "speaker-pravakta-a";
  if (name.includes("pravakta b") || name.includes("speaker_01")) return "speaker-pravakta-b";
  return "speaker-default";
}

function appendTranscriptBubble(turn) {
  const bubble = document.createElement("div");
  bubble.className = "transcript-bubble align-left";
  
  const speakerClass = getSpeakerClass(turn.speaker);
  const formattedTime = formatTime(turn.start_time);
  
  bubble.innerHTML = `
    <div class="bubble-header">
      <span class="speaker-badge ${speakerClass}">${turn.speaker}</span>
      <span class="bubble-time">${formattedTime}</span>
    </div>
    <div class="bubble-content">
      <p>${turn.text}</p>
    </div>
  `;
  
  transcriptContainer.appendChild(bubble);
  transcriptContainer.scrollTop = transcriptContainer.scrollHeight;
}

function appendContextCard(card) {
  const cardEl = document.createElement("article");
  cardEl.className = "context-card";
  
  const confidenceClass = (card.confidence_level || "medium").toLowerCase();
  const speakerClass = getSpeakerClass(card.speaker);
  
  let factsHtml = "";
  if (card.grounded_context && card.grounded_context.length > 0) {
    factsHtml = `
      <div class="detail-section grounded-facts">
        <h4>Grounded Facts</h4>
        <ul>
          ${card.grounded_context.map(fact => {
            const citations = fact.source_citations.map(c => `[${c}]`).join(" ");
            return `<li>${fact.point} <span class="source-index">${citations}</span></li>`;
          }).join("")}
        </ul>
      </div>
    `;
  }
  
  let missingHtml = "";
  if (card.missing_context && card.missing_context.length > 0) {
    missingHtml = `
      <div class="detail-section missing-context">
        <h4>Missing Context / Caveats</h4>
        <ul>
          ${card.missing_context.map(caveat => `<li>${caveat}</li>`).join("")}
        </ul>
      </div>
    `;
  }
  
  let sourcesHtml = "";
  if (card.sources_used && card.sources_used.length > 0) {
    sourcesHtml = `
      <div class="card-sources">
        <h4>Sources Cited</h4>
        <div class="sources-list">
          ${card.sources_used.map(src => `
            <a href="${src.url}" target="_blank" class="source-link" title="${src.title}">
              <span class="source-index">[${src.index}]</span>
              <span>${src.title.length > 25 ? src.title.substring(0, 25) + "..." : src.title}</span>
            </a>
          `).join("")}
        </div>
      </div>
    `;
  }

  if (card.error) {
    cardEl.innerHTML = `
      <div class="card-header">
        <div class="card-speaker">
          <span class="speaker-badge ${speakerClass}">${card.speaker}</span>
        </div>
        <span class="confidence-badge low">Error</span>
      </div>
      <blockquote class="card-claim">"${card.claim_text}"</blockquote>
      <div class="card-interpretations">
        <div class="interpretation-item">
          <p style="color: var(--confidence-low-text);">${card.error}</p>
        </div>
      </div>
    `;
  } else {
    cardEl.innerHTML = `
      <div class="card-header">
        <div class="card-speaker">
          <span class="speaker-badge ${speakerClass}">${card.speaker}</span>
        </div>
        <span class="confidence-badge ${confidenceClass}">${card.confidence_level} Confidence</span>
      </div>
      
      <blockquote class="card-claim">"${card.claim_text}"</blockquote>
      
      <div class="card-interpretations">
        <div class="interpretation-item">
          <strong>LITERAL CLAIM</strong>
          <p>${card.literal_claim}</p>
        </div>
        <div class="interpretation-item">
          <strong>IMPLIED FRAMING</strong>
          <p>${card.implied_claim}</p>
        </div>
      </div>
      
      <div class="card-details">
        ${factsHtml}
        ${missingHtml}
      </div>
      
      ${sourcesHtml}
    `;
  }
  
  cardsContainer.appendChild(cardEl);
  cardsContainer.scrollTop = cardsContainer.scrollHeight;
}

function appendShimmerPlaceholder() {
  const shimmer = document.createElement("div");
  shimmer.className = "shimmer-card";
  shimmer.innerHTML = `
    <div class="shimmer-line header animate-pulse"></div>
    <div class="shimmer-line claim-1"></div>
    <div class="shimmer-line claim-2"></div>
    <div class="shimmer-line body-1"></div>
    <div class="shimmer-line body-2"></div>
  `;
  cardsContainer.appendChild(shimmer);
  cardsContainer.scrollTop = cardsContainer.scrollHeight;
}

// Phase 4: YouTube URL Scanning and Caption Extraction Helper Functions

async function detectActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0]) {
      const tab = tabs[0];
      currentTabId = tab.id;
      currentTabUrl = tab.url || "";
      
      const isYouTube = currentTabUrl.includes("youtube.com/watch") || currentTabUrl.includes("youtu.be/");
      
      if (isYouTube) {
        videoStatusTitle.textContent = tab.title ? (tab.title.length > 45 ? tab.title.substring(0, 45) + "..." : tab.title) : "YouTube Video Detected";
        videoStatusUrl.textContent = currentTabUrl;
        manualUrlBox.style.display = "none";
        logToServer("info", `Detected active YouTube tab: ${currentTabUrl}`);
      } else {
        videoStatusTitle.textContent = "No YouTube Video Detected";
        videoStatusUrl.textContent = "Active tab is not a YouTube video watch page.";
        manualUrlBox.style.display = "block";
      }
    }
  } catch (err) {
    logToServer("error", "Error detecting active tab", err.message);
    videoStatusTitle.textContent = "Error detecting tab";
    videoStatusUrl.textContent = "Could not retrieve active tab URL.";
    manualUrlBox.style.display = "block";
  }
}

async function handleVideoScan() {
  let targetUrl = currentTabUrl;
  let useContentScript = false;
  
  const isYouTube = currentTabUrl.includes("youtube.com/watch") || currentTabUrl.includes("youtu.be/");
  
  // Check if we are using the manual pasted URL
  if (!isYouTube || manualUrlBox.style.display === "block") {
    const pastedUrl = manualUrlInput.value.trim();
    if (!pastedUrl) {
      alert("Please paste a valid YouTube video URL first.");
      return;
    }
    const isPastedYT = pastedUrl.includes("youtube.com/watch") || pastedUrl.includes("youtu.be/");
    if (!isPastedYT) {
      alert("Only YouTube URLs are supported for scanning.");
      return;
    }
    targetUrl = pastedUrl;
  } else {
    useContentScript = true;
  }
  
  logToServer("info", `Starting video scan for: ${targetUrl} (Use content script: ${useContentScript})`);
  
  // Disable button, show progress
  scanBtn.disabled = true;
  scanBtn.textContent = "Fact-checking...";
  scanProgress.style.display = "flex";
  
  // Reset progress steps
  step1.className = "step active";
  step2.className = "step";
  step3.className = "step";
  progressPercentage.textContent = "0%";
  
  // Start simulated progress
  let progress = 0;
  const progressInterval = setInterval(() => {
    if (progress < 90) {
      progress += Math.floor(Math.random() * 5) + 1;
      if (progress > 90) progress = 90;
      progressPercentage.textContent = `${progress}%`;
      
      // Update step active states based on percentage
      if (progress >= 30 && progress < 60) {
        step1.className = "step done";
        step2.className = "step active";
      } else if (progress >= 60) {
        step2.className = "step done";
        step3.className = "step active";
      }
    }
  }, 300);
  
  let segments = null;
  
  // 1. Browser-assisted caption extraction
  if (useContentScript && currentTabId) {
    try {
      logToServer("info", "Injecting content script to extract captions...");
      
      // Inject script to extract window.ytInitialPlayerResponse
      const injectionResults = await chrome.scripting.executeScript({
        target: { tabId: currentTabId },
        world: 'MAIN',
        func: () => {
          try {
            const response = window.ytInitialPlayerResponse || (window.yt && window.yt.config_ && window.yt.config_.PLAYER_CONFIG && window.yt.config_.PLAYER_CONFIG.args && window.yt.config_.PLAYER_CONFIG.args.raw_player_response);
            if (!response || !response.captions || !response.captions.playerCaptionsTracklistRenderer) {
              return null;
            }
            const tracks = response.captions.playerCaptionsTracklistRenderer.captionTracks;
            if (!tracks || tracks.length === 0) return null;
            
            // Prefer Hindi, then Hinglish/English, then first available
            let selectedTrack = tracks.find(t => t.languageCode === 'hi') ||
                                tracks.find(t => t.languageCode === 'en-IN') ||
                                tracks.find(t => t.languageCode === 'en') ||
                                tracks[0];
            return selectedTrack ? selectedTrack.baseUrl : null;
          } catch (e) {
            return null;
          }
        }
      });
      
      const baseUrl = injectionResults[0]?.result;
      if (baseUrl) {
        logToServer("info", `Successfully extracted caption track baseUrl: ${baseUrl}`);
        // Fetch and parse the XML track
        const xmlResponse = await fetch(baseUrl);
        const xmlText = await xmlResponse.text();
        
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(xmlText, "text/xml");
        const textNodes = xmlDoc.getElementsByTagName("text");
        
        segments = [];
        for (let i = 0; i < textNodes.length; i++) {
          const node = textNodes[i];
          const text = node.textContent || node.innerText || "";
          const start = parseFloat(node.getAttribute("start") || "0");
          const duration = parseFloat(node.getAttribute("dur") || "0");
          segments.push({ text, start, duration });
        }
        logToServer("info", `Parsed ${segments.length} caption segments from XML in the browser.`);
      } else {
        logToServer("warning", "No caption tracks found in window.ytInitialPlayerResponse on active tab.");
      }
    } catch (err) {
      logToServer("warning", "Failed to extract captions inside browser tab. Falling back to server-side retrieval.", err.message);
    }
  }
  
  // 2. Send POST request to backend
  try {
    const isMock = mockToggle.checked;
    logToServer("info", `Sending POST /api/factcheck/url (Mock: ${isMock}). Payload size: ${segments ? segments.length : 0} segments.`);
    
    const startTime = Date.now();
    const response = await fetch(`${BACKEND_URL}/api/factcheck/url`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: targetUrl,
        segments: segments,
        mock: isMock
      })
    });
    
    clearInterval(progressInterval);
    
    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}: ${await response.text()}`);
    }
    
    const data = await response.json();
    const latency = ((Date.now() - startTime) / 1000).toFixed(1);
    logToServer("info", `URL Fact-check complete in ${latency}s! Received ${data.transcript ? data.transcript.length : 0} turns and ${data.context_cards ? data.context_cards.length : 0} cards.`);
    
    // Complete progress UI
    progressPercentage.textContent = "100%";
    step1.className = "step done";
    step2.className = "step done";
    step3.className = "step done";
    
    // Render results
    renderFullReport(data);
    
    setTimeout(() => {
      scanProgress.style.display = "none";
      scanBtn.disabled = false;
      scanBtn.textContent = "Fact-Check Video";
    }, 1000);
    
  } catch (err) {
    clearInterval(progressInterval);
    logToServer("error", "Failed to complete URL fact-check", err.message);
    alert(`Fact-checking failed: ${err.message}\n\nPlease verify that the backend server is running and your API keys are configured.`);
    scanProgress.style.display = "none";
    scanBtn.disabled = false;
    scanBtn.textContent = "Fact-Check Video";
  }
}

function renderFullReport(data) {
  // Clear existing UI content
  renderedTurnsCount = 0;
  renderedCardsSignatures.clear();
  transcriptContainer.innerHTML = "";
  cardsContainer.innerHTML = "";
  transcriptEmpty.style.display = "none";
  cardsEmpty.style.display = "none";
  
  // Update UI using our existing updater logic!
  updateUIContent({
    transcript: data.transcript,
    context_cards: data.context_cards,
    is_processing: false
  });
}
