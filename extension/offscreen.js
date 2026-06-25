let mediaStream = null;
let mediaRecorder = null;
let audioCtx = null;
const BACKEND_URL = "http://127.0.0.1:8000";

// Listen for control messages from the service worker
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // If background worker sends an explicit start recording (fallback)
  if (message.type === "INIT_RECORDING") {
    startRecording(message.streamId, message.sessionId, message.mock)
      .then(() => sendResponse({ status: "success" }))
      .catch((err) => {
        console.error("Offscreen recording failed to start:", err);
        sendResponse({ status: "error", error: err.message });
      });
    return true;
  }

  if (message.type === "STOP_RECORDING") {
    stopRecording();
    sendResponse({ status: "success" });
  }
});

async function startRecording(streamId, sessionId, mock) {
  if (mediaStream) {
    console.warn("Recording already in progress, stopping old one first.");
    stopRecording();
  }

  console.log(`Offscreen: Initializing getUserMedia with streamId: ${streamId}`);

  // Capture tab audio
  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId
      }
    },
    video: false
  });

  // CRITICAL: Play back the captured audio to the user's speakers
  // Otherwise, the tab will go completely silent during capture!
  audioCtx = new AudioContext();
  const source = audioCtx.createMediaStreamSource(mediaStream);
  source.connect(audioCtx.destination);
  console.log("Offscreen: Audio routed back to speakers to prevent muting.");

  // Initialize MediaRecorder
  mediaRecorder = new MediaRecorder(mediaStream, {
    mimeType: "audio/webm;codecs=opus"
  });

  mediaRecorder.ondataavailable = async (event) => {
    if (event.data && event.data.size > 0) {
      console.log(`Offscreen: Audio chunk available. Size: ${event.data.size} bytes. Uploading...`);
      await uploadAudioChunk(event.data, sessionId, mock);
    }
  };

  // Record in 15-second chunks
  const timesliceMs = 15000;
  mediaRecorder.start(timesliceMs);
  console.log(`Offscreen: MediaRecorder started with timeslice of ${timesliceMs}ms.`);
}

function stopRecording() {
  console.log("Offscreen: Stopping recording.");
  
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  if (audioCtx) {
    audioCtx.close();
    audioCtx = null;
  }
  
  mediaRecorder = null;
  console.log("Offscreen: Recording stopped, tracks and audio context released.");
}

async function uploadAudioChunk(blob, sessionId, mock) {
  const formData = new FormData();
  formData.append("file", blob, "chunk.webm");

  const url = `${BACKEND_URL}/api/session/${sessionId}/audio?mock=${mock}`;
  
  try {
    const response = await fetch(url, {
      method: "POST",
      body: formData
    });

    if (!response.ok) {
      throw new Error(`Server responded with HTTP ${response.status}`);
    }

    const data = await response.json();
    console.log("Offscreen: Chunk uploaded successfully. Server status:", data);
  } catch (error) {
    console.error("Offscreen: Failed to upload audio chunk to server:", error);
    
    chrome.runtime.sendMessage({
      type: "UPLOAD_FAILED",
      sessionId: sessionId,
      error: error.message
    });
  }
}

// CRITICAL HANDSHAKE:
// As soon as this offscreen document is loaded, tell the background service worker we are ready
// and request any pending recording configuration.
console.log("Offscreen: Script loaded. Initiating handshake with service worker...");
chrome.runtime.sendMessage({ type: "OFFSCREEN_READY" }, (response) => {
  if (chrome.runtime.lastError) {
    console.warn("Offscreen: Handshake response error (probably no pending configs):", chrome.runtime.lastError.message);
    return;
  }
  
  if (response && response.streamId) {
    console.log("Offscreen: Handshake success. Received pending recording config:", response);
    startRecording(response.streamId, response.sessionId, response.mock)
      .catch((err) => console.error("Offscreen: Failed to start recording after handshake:", err));
  } else {
    console.log("Offscreen: Handshake completed. No pending recording configs found.");
  }
});
