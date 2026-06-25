let offscreenCreated = false;
let pendingRecording = null;
let activeSession = null;
const BACKEND_URL = "https://sachcheck-one.vercel.app";

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

// Error listeners to capture all service worker failures
self.addEventListener("error", (event) => {
  logToServer("error", event.message, { filename: event.filename, lineno: event.lineno });
});

self.addEventListener("unhandledrejection", (event) => {
  logToServer("error", "Unhandled Promise Rejection: " + String(event.reason), event.reason?.stack || "");
});

// When the user clicks the extension action icon in the toolbar
chrome.action.onClicked.addListener((tab) => {
  logToServer("info", `Action clicked on tab ${tab.id}. Triggering capture and side panel opening synchronously...`);

  if (activeSession && activeSession.tabId === tab.id) {
    logToServer("info", "Session already active. Reopening side panel.");
    chrome.sidePanel.open({ tabId: tab.id }).catch(err => logToServer("error", "Failed to reopen side panel", err));
    return;
  }

  // 1. Enable and open the side panel SYNCHRONOUSLY!
  // Doing this synchronously in the click handler preserves the user gesture.
  chrome.sidePanel.setOptions({
    tabId: tab.id,
    path: "panel.html",
    enabled: true
  }).catch(err => logToServer("error", "Failed to set side panel options", err.message));

  chrome.sidePanel.open({ tabId: tab.id })
    .then(() => logToServer("info", "Side panel opened programmatically."))
    .catch(err => logToServer("error", "Failed to open side panel programmatically", err.message));

  // 2. Capture tab audio stream ID SYNCHRONOUSLY!
  // Calling this in the same click handler body preserves the user gesture.
  chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id }, async (streamId) => {
    if (chrome.runtime.lastError) {
      logToServer("error", "Failed to get tab capture stream ID inside click handler", chrome.runtime.lastError.message);
      return;
    }

    if (!streamId) {
      logToServer("error", "Acquired empty stream ID from tabCapture.");
      return;
    }

    logToServer("info", `Successfully captured stream ID synchronously: ${streamId}`);

    try {
      // Read preference
      const storage = await chrome.storage.local.get({ mockMode: true });
      const isMock = storage.mockMode;

      // Start session on server
      logToServer("info", "Starting session on backend server...");
      const response = await fetch(`${BACKEND_URL}/api/session/start`, {
        method: "POST"
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const data = await response.json();
      const sessionId = data.session_id;
      logToServer("info", `Session started on backend: ${sessionId}`);

      // Set active session
      activeSession = {
        sessionId: sessionId,
        tabId: tab.id,
        mock: isMock,
        startTime: Date.now()
      };

      pendingRecording = {
        streamId: streamId,
        sessionId: sessionId,
        mock: isMock
      };

      // Create offscreen doc
      await createOffscreenDocument();

    } catch (err) {
      logToServer("error", "Failed to initialize session after capture", err.message);
    }
  });
});

// Listen for messages from the side panel or offscreen document
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "PANEL_READY") {
    if (activeSession) {
      logToServer("info", "Side panel loaded. Synchronizing active session state", activeSession);
      sendResponse(activeSession);
    } else {
      logToServer("info", "Side panel loaded. No active session to synchronize.");
      sendResponse(null);
    }
    return false;
  }

  if (message.type === "STOP_CAPTURE") {
    logToServer("info", "Received STOP_CAPTURE request from side panel.");
    handleStopCapture()
      .then(() => {
        activeSession = null;
        sendResponse({ status: "success" });
      })
      .catch((err) => {
        logToServer("error", "Failed to stop capture", err.message);
        sendResponse({ status: "error", error: err.message });
      });
    return true;
  }

  if (message.type === "OFFSCREEN_READY") {
    if (pendingRecording) {
      logToServer("info", "Offscreen ready. Sending pending recording config", pendingRecording);
      sendResponse(pendingRecording);
      pendingRecording = null;
    } else {
      logToServer("warning", "Offscreen reported ready, but no pending recording config found.");
      sendResponse(null);
    }
    return false;
  }
});

async function handleStopCapture() {
  logToServer("info", "Stopping capture and closing offscreen document.");
  if (offscreenCreated) {
    try {
      await chrome.runtime.sendMessage({ type: "STOP_RECORDING" });
    } catch (e) {
      logToServer("warning", "Could not send stop message to offscreen", e.message);
    }
    try {
      await chrome.offscreen.closeDocument();
    } catch (e) {
      logToServer("warning", "Error closing offscreen document", e.message);
    }
    offscreenCreated = false;
  }
}

async function createOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL("offscreen.html");
  
  try {
    await chrome.offscreen.createDocument({
      url: offscreenUrl,
      reasons: ["USER_MEDIA"],
      justification: "Capture tab audio stream for real-time speech transcription."
    });
    offscreenCreated = true;
    logToServer("info", "Offscreen document created successfully.");
  } catch (err) {
    if (err.message.includes("Only one offscreen document is allowed") || err.message.includes("already exists")) {
      logToServer("info", "Offscreen document already exists (caught exception).");
      offscreenCreated = true;
    } else {
      logToServer("error", "Failed to create offscreen document", err.message);
      throw err;
    }
  }
}
