/**
 * SachCheck Dashboard & Playground Coordinator
 * Handles tab navigation, API communication, simulated progress, and dynamic UI rendering.
 */

document.addEventListener('DOMContentLoaded', () => {
  // --- State Management ---
  const state = {
    activeTab: 'youtube',
    mockMode: true,
    isProcessing: false,
    systemOnline: false,
    results: null
  };

  // --- Sample Data ---
  const SAMPLE_TRANSCRIPT = `Anchor: Swagat hai aapka. Aaj hum baat karenge desh mein berozgari aur naukriyon ke baare mein. Hamare sath dono paksh ke pravakta hain.
Pravakta A: Dekhiye, desh ke yuva aaj pareshan hain. Government ne har saal 2 crore jobs dene ka promise kiya tha. But the truth is, pichle 45 saal mein sabse zyada unemployment rate aaj hai. PLFS data dikhata hai ki youth unemployment 15% touch kar raha hai.
Pravakta B: Yeh bilkul galat baat hai. Hamari sarkar ne EPFO data ke mutabik pichle saal hi 1.3 crore nayi jobs generate ki hain. Aur mudra loan scheme ke under humne 40 crore se zyada loans diye hain, jisse log self-employed ban rahe hain.
Pravakta A: EPFO data real jobs nahi dikhata, wo sirf formalisation of labor dikhata hai. Mudra loans se koi real long-term employment nahi create ho raha hai, average loan size bohot chota hai.`;

  // --- Element Selectors ---
  const elements = {
    // Sidebar & Navigation
    tabYoutube: document.getElementById('tab-youtube'),
    tabTranscript: document.getElementById('tab-transcript'),
    tabDiagnostics: document.getElementById('tab-diagnostics'),
    systemIndicator: document.getElementById('system-indicator'),
    systemStatusLbl: document.getElementById('system-status-lbl'),
    
    // Header & Workspace Title
    currentTabTitle: document.getElementById('current-tab-title'),
    currentTabDesc: document.getElementById('current-tab-desc'),
    mockModeToggle: document.getElementById('mock-mode-toggle'),
    
    // Panes
    paneYoutube: document.getElementById('pane-youtube'),
    paneTranscript: document.getElementById('pane-transcript'),
    paneDiagnostics: document.getElementById('pane-diagnostics'),
    
    // Inputs & Action Buttons
    ytUrlInput: document.getElementById('yt-url-input'),
    btnScanYt: document.getElementById('btn-scan-yt'),
    transcriptTextarea: document.getElementById('transcript-textarea'),
    btnClearText: document.getElementById('btn-clear-text'),
    btnLoadSample: document.getElementById('btn-load-sample'),
    btnScanText: document.getElementById('btn-scan-text'),
    
    // Diagnostics Badges & Stats
    keyGemini: document.getElementById('key-gemini'),
    keySerper: document.getElementById('key-serper'),
    keySarvam: document.getElementById('key-sarvam'),
    statDbClaims: document.getElementById('stat-db-claims'),
    statCacheEmbeddings: document.getElementById('stat-cache-embeddings'),
    
    // Loading/Processing Overlay
    processingOverlay: document.getElementById('processing-overlay'),
    processingStatus: document.getElementById('processing-status'),
    processingSubstatus: document.getElementById('processing-substatus'),
    loadingPercentage: document.getElementById('loading-percentage'),
    dot1: document.getElementById('dot-1'),
    dot2: document.getElementById('dot-2'),
    dot3: document.getElementById('dot-3'),
    
    // Results
    resultsWorkspace: document.getElementById('results-workspace'),
    badgeTurnsCount: document.getElementById('badge-turns-count'),
    badgeCardsCount: document.getElementById('badge-cards-count'),
    renderedTranscript: document.getElementById('rendered-transcript'),
    renderedCards: document.getElementById('rendered-cards'),
    renderedAudit: document.getElementById('rendered-audit'),
    badgeAuditCount: document.getElementById('badge-audit-count'),
    auditToggleBtn: document.getElementById('audit-toggle-btn')
  };

  // --- Initializer ---
  function init() {
    registerEventListeners();
    checkSystemStatus();
    // Poll system status every 10 seconds to keep diagnostics updated
    setInterval(checkSystemStatus, 10000);
  }

  // --- Event Registrations ---
  function registerEventListeners() {
    // Tab Toggles
    elements.tabYoutube.addEventListener('click', () => switchTab('youtube'));
    elements.tabTranscript.addEventListener('click', () => switchTab('transcript'));
    elements.tabDiagnostics.addEventListener('click', () => switchTab('diagnostics'));
    
    // Mock Mode Toggle Sync
    elements.mockModeToggle.addEventListener('change', (e) => {
      state.mockMode = e.target.checked;
    });

    // YouTube Examples
    document.querySelectorAll('.btn-example-url').forEach(btn => {
      btn.addEventListener('click', (e) => {
        elements.ytUrlInput.value = e.target.dataset.url;
      });
    });

    // YouTube Action
    elements.btnScanYt.addEventListener('click', handleYoutubeScan);
    
    // Transcript Actions
    elements.btnLoadSample.addEventListener('click', () => {
      elements.transcriptTextarea.value = SAMPLE_TRANSCRIPT;
    });
    elements.btnClearText.addEventListener('click', () => {
      elements.transcriptTextarea.value = '';
    });
    elements.btnScanText.addEventListener('click', handleTranscriptScan);

    // Audit Log Toggle
    elements.auditToggleBtn.addEventListener('click', () => {
      const isHidden = elements.renderedAudit.style.display === 'none';
      elements.renderedAudit.style.display = isHidden ? 'flex' : 'none';
    });
  }

  // --- Tab Switcher Logic ---
  function switchTab(tabName) {
    if (state.isProcessing) return; // Prevent navigation during active fact-check
    
    state.activeTab = tabName;
    
    // Update Sidebar Navigation buttons
    elements.tabYoutube.classList.toggle('active', tabName === 'youtube');
    elements.tabTranscript.classList.toggle('active', tabName === 'transcript');
    elements.tabDiagnostics.classList.toggle('active', tabName === 'diagnostics');
    
    // Update panes visibility
    elements.paneYoutube.classList.toggle('active', tabName === 'youtube');
    elements.paneTranscript.classList.toggle('active', tabName === 'transcript');
    elements.paneDiagnostics.classList.toggle('active', tabName === 'diagnostics');
    
    // Reset results visibility if navigating away
    elements.resultsWorkspace.style.display = 'none';
    
    // Update Title and Subtitle dynamically
    if (tabName === 'youtube') {
      elements.currentTabTitle.textContent = "YouTube Video Scanner";
      elements.currentTabDesc.textContent = "Extract, transcribe, and fact-check YouTube videos using the hybrid engine.";
    } else if (tabName === 'transcript') {
      elements.currentTabTitle.textContent = "Transcript Playground";
      elements.currentTabDesc.textContent = "Paste or write a custom dialogue to run direct fact-checking and claim auditing.";
    } else if (tabName === 'diagnostics') {
      elements.currentTabTitle.textContent = "System Diagnostics";
      elements.currentTabDesc.textContent = "Monitor active API keys, local vector database size, and server response logs.";
      // Force status update when looking at diagnostics
      checkSystemStatus();
    }
  }

  // --- System Status API Checker ---
  async function checkSystemStatus() {
    try {
      const response = await fetch('/api/system/status');
      if (!response.ok) throw new Error('Backend server returned error');
      
      const data = await response.json();
      state.systemOnline = true;
      
      // Update Sidebar Indicator
      elements.systemIndicator.className = "indicator-glow connected";
      elements.systemStatusLbl.textContent = "Server Connected";
      
      // Update Diagnostics Badges
      updateBadge(elements.keyGemini, data.api_keys.gemini);
      updateBadge(elements.keySerper, data.api_keys.serper);
      updateBadge(elements.keySarvam, data.api_keys.sarvam);
      
      // Update Database Counts
      elements.statDbClaims.textContent = data.database.seeded_claims_count;
      elements.statCacheEmbeddings.textContent = data.database.cached_embeddings_count;
      
    } catch (error) {
      state.systemOnline = false;
      elements.systemIndicator.className = "indicator-glow disconnected";
      elements.systemStatusLbl.textContent = "Server Offline";
      
      // Reset diagnostics values
      elements.keyGemini.className = "status-badge missing";
      elements.keyGemini.textContent = "Offline";
      elements.keySerper.className = "status-badge missing";
      elements.keySerper.textContent = "Offline";
      elements.keySarvam.className = "status-badge missing";
      elements.keySarvam.textContent = "Offline";
      elements.statDbClaims.textContent = "0";
      elements.statCacheEmbeddings.textContent = "0";
    }
  }

  function updateBadge(badgeElement, isConfigured) {
    if (isConfigured) {
      badgeElement.className = "status-badge active";
      badgeElement.textContent = "Configured";
    } else {
      badgeElement.className = "status-badge missing";
      badgeElement.textContent = "Missing Key";
    }
  }

  // --- YouTube Scanning Logic ---
  async function handleYoutubeScan() {
    const url = elements.ytUrlInput.value.trim();
    if (!url) {
      alert("Please enter a valid YouTube video URL.");
      return;
    }
    
    showProcessingOverlay("youtube");
    const progressInterval = simulateProgress(24000); // YouTube RAG can take ~20-25s for web searches
    
    try {
      const response = await fetch('/api/factcheck/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          mock: state.mockMode
        })
      });
      
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "URL fact-checking failed.");
      }
      
      const results = await response.json();
      clearInterval(progressInterval);
      completeProcessing(results);
      
    } catch (error) {
      clearInterval(progressInterval);
      hideProcessingOverlay();
      alert(`Error: ${error.message}`);
    }
  }

  // --- Transcript Playground Logic ---
  async function handleTranscriptScan() {
    const text = elements.transcriptTextarea.value.trim();
    if (!text) {
      alert("Please enter some transcript dialogue to analyze.");
      return;
    }
    
    showProcessingOverlay("transcript");
    const progressInterval = simulateProgress(12000); // Text RAG takes ~10-12s
    
    try {
      const response = await fetch('/api/factcheck/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: text,
          mock: state.mockMode
        })
      });
      
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Transcript analysis failed.");
      }
      
      const results = await response.json();
      clearInterval(progressInterval);
      completeProcessing(results);
      
    } catch (error) {
      clearInterval(progressInterval);
      hideProcessingOverlay();
      alert(`Error: ${error.message}`);
    }
  }

  // --- Processing Progress Simulator ---
  function simulateProgress(totalDurationMs) {
    let currentPercent = 0;
    elements.loadingPercentage.textContent = "0%";
    elements.processingOverlay.style.display = "flex";
    
    // Set initial dot active
    elements.dot1.className = "dot active";
    elements.dot2.className = "dot";
    elements.dot3.className = "dot";
    
    const intervalTime = 200;
    const increment = (100 / (totalDurationMs / intervalTime)) * 0.9; // Target max 90% until complete
    
    return setInterval(() => {
      if (currentPercent < 90) {
        currentPercent = Math.min(90, currentPercent + increment);
        elements.loadingPercentage.textContent = `${Math.round(currentPercent)}%`;
        
        // Dynamic substage labels and dot updates
        if (currentPercent < 35) {
          elements.processingStatus.textContent = "Fetching & Parsing Transcript...";
          elements.processingSubstatus.textContent = "Retrieving conversational blocks...";
          elements.dot1.className = "dot active";
        } else if (currentPercent < 70) {
          elements.processingStatus.textContent = "Extracting Political Claims...";
          elements.processingSubstatus.textContent = "Running check-worthiness classifier...";
          elements.dot1.className = "dot done";
          elements.dot2.className = "dot active";
        } else {
          elements.processingStatus.textContent = "Grounding Claims via RAG...";
          elements.processingSubstatus.textContent = "Running Fast Path matching and web retrieval...";
          elements.dot2.className = "dot done";
          elements.dot3.className = "dot active";
        }
      }
    }, intervalTime);
  }

  function showProcessingOverlay(mode) {
    state.isProcessing = true;
    elements.resultsWorkspace.style.display = 'none';
    elements.processingOverlay.style.display = 'flex';
  }

  function hideProcessingOverlay() {
    state.isProcessing = false;
    elements.processingOverlay.style.display = 'none';
  }

  function completeProcessing(results) {
    elements.loadingPercentage.textContent = "100%";
    elements.processingStatus.textContent = "Fact-check Completed!";
    elements.processingSubstatus.textContent = "Assembling interactive grounding cards...";
    elements.dot3.className = "dot done";
    
    setTimeout(() => {
      hideProcessingOverlay();
      state.results = results;
      renderResults();
    }, 800);
  }

  // --- Results Renderers ---
  function renderResults() {
    if (!state.results) return;
    
    const { transcript, context_cards, ignored_claims } = state.results;
    
    // 1. Update Header Badges
    elements.badgeTurnsCount.textContent = `${transcript.length} Turns`;
    elements.badgeCardsCount.textContent = `${context_cards.length} Grounded Cards`;
    elements.badgeAuditCount.textContent = `${ignored_claims.length} Filtered`;
    
    // 2. Render Transcript Bubbles
    elements.renderedTranscript.innerHTML = '';
    transcript.forEach(turn => {
      const bubble = document.createElement('div');
      
      // Match CSS bubble classes
      const speakerLower = turn.speaker.toLowerCase();
      let speakerClass = 'speaker-unknown';
      if (speakerLower.includes('anchor')) {
        speakerClass = 'anchor';
      } else if (speakerLower.includes('pravakta a') || speakerLower.endsWith('a')) {
        speakerClass = 'pravakta-a';
      } else if (speakerLower.includes('pravakta b') || speakerLower.endsWith('b')) {
        speakerClass = 'pravakta-b';
      }
      
      bubble.className = `speech-bubble ${speakerClass}`;
      bubble.innerHTML = `
        <span class="bubble-speaker">${turn.speaker}</span>
        <span class="bubble-text">${turn.text}</span>
      `;
      elements.renderedTranscript.appendChild(bubble);
    });
    
    // 3. Render Fact-Check Context Cards
    elements.renderedCards.innerHTML = '';
    if (context_cards.length === 0) {
      elements.renderedCards.innerHTML = `
        <div class="empty-state" style="padding: 40px; text-align: center; color: var(--text-muted);">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width: 48px; height: 48px; margin-bottom: 12px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <p>No check-worthy claims were detected in this transcript segment.</p>
        </div>
      `;
    } else {
      context_cards.forEach(card => {
        if (card.error) {
          // Render error card
          const errorCard = document.createElement('div');
          errorCard.className = 'context-card';
          errorCard.style.borderColor = 'var(--color-danger)';
          errorCard.innerHTML = `
            <div class="card-header">
              <span class="card-speaker-badge" style="background-color: rgba(239, 68, 68, 0.1); color: var(--color-danger);">${card.speaker}</span>
            </div>
            <p class="card-title">${card.claim_text}</p>
            <div class="missing-context-box" style="background-color: rgba(239, 68, 68, 0.05); border-color: rgba(239, 68, 68, 0.2);">
              <span class="missing-lbl" style="color: var(--color-danger);">Error</span>
              <p class="missing-point">${card.error}</p>
            </div>
          `;
          elements.renderedCards.appendChild(errorCard);
          return;
        }
        
        const cardEl = document.createElement('div');
        cardEl.className = 'context-card';
        
        // Fast path vs Deep path badge
        const pathBadgeHtml = card.is_recycled 
          ? '<span class="path-badge fast">Fast Path</span>' 
          : '<span class="path-badge deep">Deep Path</span>';
          
        // Confidence level color class
        const confLower = card.confidence_level.toLowerCase();
        let confClass = 'conf-medium';
        if (confLower.includes('high')) confClass = 'conf-high';
        if (confLower.includes('low')) confClass = 'conf-low';
        
        // Grounded context points
        let groundedPointsHtml = '';
        card.grounded_context.forEach(pt => {
          let pointsText = pt.point;
          
          // Inject clickable citations if available
          pt.source_citations.forEach(cIndex => {
            const matchedSrc = card.sources_used.find(s => s.index === cIndex);
            if (matchedSrc && matchedSrc.url) {
              pointsText += ` <a href="${matchedSrc.url}" target="_blank" class="cite-link" title="${matchedSrc.title}">[${cIndex}]</a>`;
            } else {
              pointsText += ` <span class="cite-link">[${cIndex}]</span>`;
            }
          });
          
          groundedPointsHtml += `<p class="grounded-point">${pointsText}</p>`;
        });
        
        // Missing context box if present
        let missingContextHtml = '';
        if (card.missing_context && card.missing_context.length > 0) {
          missingContextHtml = `
            <div class="missing-context-box">
              <span class="missing-lbl">Missing Context</span>
              ${card.missing_context.map(mc => `<p class="missing-point">• ${mc}</p>`).join('')}
            </div>
          `;
        }
        
        // Sources cited footer badges
        let sourcesBadgesHtml = '';
        if (card.sources_used && card.sources_used.length > 0) {
          sourcesBadgesHtml = `
            <div class="sources-citations-footer">
              ${card.sources_used.map(src => `
                <a href="${src.url || '#'}" target="_blank" class="footer-cite-badge" title="${src.title} (${src.source_type})">
                  [${src.index}] ${src.title.substring(0, 15)}...
                </a>
              `).join('')}
            </div>
          `;
        }
        
        cardEl.innerHTML = `
          <div class="card-header">
            <div>
              <span class="card-speaker-badge">${card.speaker}</span>
              ${pathBadgeHtml}
            </div>
            <span class="card-type-badge">${card.claim_type}</span>
          </div>
          <p class="card-title">"${card.claim_text}"</p>
          
          <div class="claim-breakdown">
            <div class="breakdown-box">
              <span class="box-label">Literal Claim</span>
              <span class="box-val">${card.literal_claim}</span>
            </div>
            <div class="breakdown-box">
              <span class="box-label">Implied Claim</span>
              <span class="box-val">${card.implied_claim}</span>
            </div>
          </div>
          
          <div class="grounded-context-list">
            ${groundedPointsHtml}
          </div>
          
          ${missingContextHtml}
          
          <div class="card-meta-footer">
            <div class="confidence-indicator">
              <span class="confidence-lbl">Confidence:</span>
              <span class="${confClass}">${card.confidence_level}</span>
            </div>
            ${sourcesBadgesHtml}
          </div>
        `;
        
        elements.renderedCards.appendChild(cardEl);
      });
    }
    
    // 4. Render Audit Log (Filtered Claims)
    elements.renderedAudit.innerHTML = '';
    if (ignored_claims.length === 0) {
      elements.renderedAudit.innerHTML = `
        <div style="padding: 12px; text-align: center; color: var(--text-muted); font-size: 11px;">
          No filtered assertions in this turn.
        </div>
      `;
    } else {
      ignored_claims.forEach(claim => {
        const item = document.createElement('div');
        item.className = 'audit-item';
        item.innerHTML = `
          <p class="audit-claim"><strong>${claim.speaker}</strong>: "${claim.text}"</p>
          <p class="audit-reason">Filtered because: ${claim.reason_check_worthy}</p>
        `;
        elements.renderedAudit.appendChild(item);
      });
    }
    
    // Make results workspace visible
    elements.resultsWorkspace.style.display = 'grid';
  }

  // --- Launch App ---
  init();
});
