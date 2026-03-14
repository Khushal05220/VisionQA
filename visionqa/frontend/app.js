/**
 * VisionQA — Production Frontend
 * Clean, fast, voice-first QA agent interface
 */

// ============ Config ============

const CONFIG = {
    API_BASE: window.location.origin,
    WS_URL: `ws://${window.location.host}/ws`,
    SESSION_ID: 'session_' + Math.random().toString(36).substr(2, 9),
    RECONNECT_INTERVAL: 3000,
    HEARTBEAT_INTERVAL: 25000,
};

// ============ State ============

const state = {
    ws: null,
    isConnected: false,
    isVoiceActive: false,
    isTTSEnabled: false,
    recognition: null,
    heartbeatTimer: null,
    reconnectTimer: null,
    sessionActions: [],
    sessionBugs: [],
    lastReportData: null,
    isResizing: false,
};

// ============ WebSocket ============

function connectWebSocket() {
    const wsUrl = `${CONFIG.WS_URL}/${CONFIG.SESSION_ID}`;
    try {
        state.ws = new WebSocket(wsUrl);
    } catch (e) {
        scheduleReconnect();
        return;
    }

    state.ws.onopen = () => {
        state.isConnected = true;
        setStatus('connected', 'Connected');
        startHeartbeat();
    };

    state.ws.onmessage = (event) => {
        try { handleWSMessage(JSON.parse(event.data)); }
        catch (e) { console.error('WS parse error:', e); }
    };

    state.ws.onclose = () => {
        state.isConnected = false;
        setStatus('', 'Disconnected');
        stopHeartbeat();
        scheduleReconnect();
    };

    state.ws.onerror = () => {};
}

function scheduleReconnect() {
    if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(() => {
        if (!state.isConnected) connectWebSocket();
    }, CONFIG.RECONNECT_INTERVAL);
}

function startHeartbeat() {
    state.heartbeatTimer = setInterval(() => {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send(JSON.stringify({ type: 'heartbeat', data: {} }));
        }
    }, CONFIG.HEARTBEAT_INTERVAL);
}

function stopHeartbeat() {
    if (state.heartbeatTimer) {
        clearInterval(state.heartbeatTimer);
        state.heartbeatTimer = null;
    }
}

function wsSend(type, data) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type, data }));
    }
}

// ============ Message Handlers ============

function handleWSMessage(msg) {
    const { type, data } = msg;

    switch (type) {
        case 'log':
            addLiveLog(data.message, data.level);
            if (data.level === 'success' || data.level === 'warning') {
                addMsg('thought', data.message);
            }
            break;

        case 'screenshot':
            updateLiveView(data.image_url, data.description);
            break;

        case 'action':
            handleActionMsg(data);
            break;

        case 'status':
            handleStatusMsg(data);
            break;

        case 'test_result':
            handleTestResult(data);
            break;

        case 'plan':
            addMsg('agent', '📋 Test plan ready: ' + (data.plan_name || 'Plan') + ' — ' + (data.total_test_cases || 0) + ' test cases');
            break;

        case 'error':
            addMsg('agent', '❌ ' + data.error);
            setStatus('error', 'Error');
            break;

        case 'agent_thought':
            if (data.thought && !data.thought.includes('🔧 Calling:')) {
                addMsg('thought', data.thought);
            }
            break;

        case 'report_ready':
            showTestResults(data);
            break;

        case 'heartbeat':
        case 'voice_transcript':
            break;

        default:
            break;
    }
}

function handleActionMsg(data) {
    if (data.action && data.target) {
        const entry = {
            action: data.action,
            target: data.target,
            status: data.status || 'info',
            time: new Date().toLocaleTimeString(),
        };
        state.sessionActions.push(entry);
        if (data.status === 'failed') {
            state.sessionBugs.push(entry);
        }
        addLiveLog(`${data.action}: ${data.target}`, data.status === 'failed' ? 'error' : 'info');
    }
}

function handleStatusMsg(data) {
    if (data.status === 'running' || data.status === 'processing') {
        setStatus('running', 'Working...');
    } else if (data.status === 'error') {
        setStatus('error', 'Error');
    } else if (data.status === 'pdf_ready') {
        // Ignored — PDF removed
        return;
    } else {
        setStatus('connected', 'Ready');
    }

    if (data.status === 'completed' && data.response) {
        addMsg('agent', data.response);
        speakText(data.response);
    }
}

function handleTestResult(data) {
    state.sessionActions.push({
        action: 'test',
        target: data.test_case_id || 'Test case',
        status: data.status === 'passed' ? 'pass' : 'fail',
        time: new Date().toLocaleTimeString(),
    });
}

// ============ Test Results Card ============

let _resultsCardEl = null;
let _reportCardCount = 0;

function showTestResults(data) {
    state.lastReportData = data;
    _reportCardCount++;

    const total = data.total || 0;
    const passed = data.passed || 0;
    const failed = data.failed || 0;
    const testItems = data.test_items || [];
    const bugs = data.bugs || [];
    const title = data.title || 'Test Results';
    const summaryText = data.summary || '';
    const url = data.url || '';
    const cardId = 'results-card-' + _reportCardCount;

    const passRate = total > 0 ? Math.round((passed / total) * 100) : 0;

    // Build test items table rows
    let itemsHtml = '';
    if (testItems.length > 0) {
        itemsHtml = '<div class="rc-table-wrap"><table class="rc-table"><thead><tr><th>#</th><th>Test / Action</th><th>Status</th><th>Time</th></tr></thead><tbody>';
        testItems.slice(0, 50).forEach((item, idx) => {
            const isPass = item.status === 'passed' || item.status === 'pass';
            const isInfo = item.status === 'info';
            const statusIcon = isPass ? '✅' : isInfo ? '🔵' : '❌';
            const rowClass = isPass ? 'row-pass' : isInfo ? '' : 'row-fail';
            const name = (item.name || '').substring(0, 80);
            const time = item.timestamp || '';
            itemsHtml += `<tr class="${rowClass}"><td style="color:var(--gray-400)">${idx + 1}</td><td>${name}</td><td>${statusIcon}</td><td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--gray-400)">${time}</td></tr>`;
        });
        if (testItems.length > 50) {
            itemsHtml += `<tr><td colspan="4" style="text-align:center;color:var(--gray-400);font-style:italic;">... and ${testItems.length - 50} more</td></tr>`;
        }
        itemsHtml += '</tbody></table></div>';
    }

    // Build bugs section
    let bugsHtml = '';
    if (bugs.length > 0) {
        bugsHtml = '<div class="rc-bugs"><div class="rc-bugs-title">🐛 Bugs Found (' + bugs.length + ')</div>';
        bugs.forEach(bug => {
            bugsHtml += `<div class="rc-bug-item"><span class="bug-sev ${(bug.severity||'major').toLowerCase()}">${bug.severity||'Major'}</span><span class="bug-name">${(bug.name||bug.description||'').substring(0,100)}</span></div>`;
        });
        bugsHtml += '</div>';
    }

    const summaryHtml = summaryText ? `<p class="rc-summary">${summaryText}</p>` : '';
    const urlHtml = url ? `<div class="rc-url">🌐 ${url}</div>` : '';
    const progressHtml = `<div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${passRate}%"></div></div>`;

    const cardHtml =
        `<div class="result-card" id="${cardId}">` +
        '<div class="rc-header">' +
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M9 12l2 2 4-4"/></svg>' +
        title +
        '</div>' +
        urlHtml +
        summaryHtml +
        '<div class="rc-stats">' +
        '<div class="rc-stat total"><div class="rc-num">' + total + '</div><div class="rc-label">Total</div></div>' +
        '<div class="rc-stat pass"><div class="rc-num">' + passed + '</div><div class="rc-label">Passed</div></div>' +
        '<div class="rc-stat fail"><div class="rc-num">' + failed + '</div><div class="rc-label">Failed</div></div>' +
        '<div class="rc-stat"><div class="rc-num" style="color:var(--cyan-600,#0891b2)">' + passRate + '%</div><div class="rc-label">Pass Rate</div>' + progressHtml + '</div>' +
        '</div>' +
        itemsHtml +
        bugsHtml +
        '<div class="rc-actions">' +
        '<button class="dl-btn csv" onclick="downloadCSV()" style="width:100%">📄 Export Detailed CSV Report</button>' +
        '</div>' +
        '</div>';

    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg system';
    div.innerHTML = '<div class="msg-body" style="width:100%">' + cardHtml + '</div>';
    _resultsCardEl = div;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;

    speakText(`Testing complete. ${total} tests: ${passed} passed, ${failed} failed.`);
    setStatus('connected', 'Ready');
    showToast(`✅ Testing complete — ${passed}/${total} passed`);
}

// ============ Downloads ============

function downloadCSV() {
    const data = state.lastReportData;
    const rows = [];
    const items = (data && data.test_items) ? data.test_items : state.sessionActions;
    const bugs = (data && data.bugs) ? data.bugs : state.sessionBugs;
    const actions = (data && data.actions) ? data.actions : [];
    const total = (data && data.total) || items.length;
    const passed = (data && data.passed) || 0;
    const failed = (data && data.failed) || 0;
    const passRate = total > 0 ? Math.round((passed / total) * 100) + '%' : 'N/A';
    const testedUrl = (data && data.url) || '';
    const reportTitle = (data && data.title) || 'VisionQA Test Report';

    // --- Summary Section ---
    rows.push(['=== VISIONQA TEST REPORT ===']);
    rows.push(['Report Title', reportTitle]);
    rows.push(['URL Tested', testedUrl]);
    rows.push(['Generated', new Date().toLocaleString()]);
    rows.push(['Total Tests', total]);
    rows.push(['Passed', passed]);
    rows.push(['Failed', failed]);
    rows.push(['Pass Rate', passRate]);
    rows.push(['Bugs Found', bugs.length]);
    if (data && data.summary) {
        rows.push(['Summary', data.summary]);
    }
    rows.push([]);

    // --- Test Cases Section ---
    rows.push(['=== TEST CASES ===']);
    rows.push(['#', 'Test Case', 'Status', 'Steps Passed', 'Steps Failed', 'URL', 'Time', 'Detail']);
    items.forEach((item, i) => {
        rows.push([
            i + 1,
            (item.name || '').substring(0, 200),
            item.status || '',
            item.steps_passed || 0,
            item.steps_failed || 0,
            item.url || testedUrl,
            item.timestamp || item.time || '',
            item.detail || '',
        ]);
    });
    rows.push([]);

    // --- Bugs Section ---
    if (bugs.length > 0) {
        rows.push(['=== BUGS FOUND ===']);
        rows.push(['#', 'Bug Description', 'Severity', 'URL', 'Detail']);
        bugs.forEach((b, i) => {
            rows.push([
                i + 1,
                (b.name || b.description || '').substring(0, 200),
                b.severity || 'Major',
                b.url || testedUrl,
                b.detail || '',
            ]);
        });
        rows.push([]);
    }

    // --- Detailed Action Log ---
    if (actions.length > 0) {
        rows.push(['=== DETAILED ACTION LOG ===']);
        rows.push(['#', 'Action', 'Target/Element', 'Result', 'Detail', 'Timestamp']);
        actions.forEach((act, i) => {
            rows.push([
                i + 1,
                act.action || '',
                (act.target || '').substring(0, 200),
                act.status || '',
                act.detail || '',
                act.timestamp || '',
            ]);
        });
    }

    const csv = rows.map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const dlUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = dlUrl;
    a.download = 'VisionQA_Report_' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(dlUrl);

    addMsg('agent', '✅ CSV exported successfully.');
    showToast('📄 CSV downloaded!');
}

// ============ API ============

function sendCommand(command) {
    addMsg('user', command);
    setStatus('running', 'Processing...');
    showTypingIndicator();

    if (state.isConnected) {
        wsSend('command', { command });
    } else {
        fetch(CONFIG.API_BASE + '/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command, session_id: CONFIG.SESSION_ID }),
        })
        .then(r => r.json())
        .then(result => {
            hideTypingIndicator();
            addMsg('agent', result.response || 'Done.');
            setStatus('connected', 'Ready');
        })
        .catch(e => {
            hideTypingIndicator();
            addMsg('agent', '❌ ' + e.message);
            setStatus('error', 'Error');
        });
    }
}

function sendVoiceCommand(transcript) {
    addMsg('user', '🎤 ' + transcript);
    setStatus('running', 'Processing...');
    showTypingIndicator();

    if (state.isConnected) {
        wsSend('voice', { transcript });
    } else {
        fetch(CONFIG.API_BASE + '/api/voice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transcript, session_id: CONFIG.SESSION_ID }),
        })
        .then(r => r.json())
        .then(result => {
            hideTypingIndicator();
            addMsg('agent', result.response || 'Done.');
            setStatus('connected', 'Ready');
        })
        .catch(e => {
            hideTypingIndicator();
            addMsg('agent', '❌ ' + e.message);
            setStatus('error', 'Error');
        });
    }
}

async function resetSession() {
    try {
        await fetch(CONFIG.API_BASE + '/api/agent/reset', { method: 'POST' });
    } catch (_) {}
    state.sessionActions = [];
    state.sessionBugs = [];
    state.lastReportData = null;
    _resultsCardEl = null;
    _reportCardCount = 0;
    const container = document.getElementById('chat-messages');
    container.innerHTML = '';
    addMsg('system', '🔄 Session reset. Ready for new testing!');
    setStatus('connected', 'Ready');

    const viewport = document.getElementById('live-viewport');
    viewport.innerHTML =
        '<div class="live-empty"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.2"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21,15 16,10 5,21"/></svg><p>Screenshots appear here as the agent browses</p></div>';
    document.getElementById('live-badge').textContent = 'No page open';
    document.getElementById('live-badge').classList.remove('active');
    document.getElementById('live-activity').innerHTML = '';
}

// ============ Voice / Speech ============

function initVoiceRecognition() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
        const micBtn = document.getElementById('btn-mic');
        if (micBtn) { micBtn.style.opacity = '0.3'; micBtn.title = 'Voice not supported in this browser'; }
        return;
    }

    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    recognition.maxAlternatives = 1;

    // Debounce timer: wait for the user to finish speaking before sending
    let voiceDebounceTimer = null;
    let accumulatedFinal = '';

    recognition.onstart = () => {
        state.isVoiceActive = true;
        accumulatedFinal = '';
        document.getElementById('btn-mic').classList.add('active');
        document.getElementById('voice-bar').classList.add('active');
    };

    recognition.onend = () => {
        // If there's accumulated text that hasn't been sent yet, send it now
        if (accumulatedFinal.trim()) {
            if (voiceDebounceTimer) clearTimeout(voiceDebounceTimer);
            const finalText = accumulatedFinal.trim();
            accumulatedFinal = '';
            document.getElementById('input-cmd').value = '';
            sendVoiceCommand(finalText);
        }
        state.isVoiceActive = false;
        document.getElementById('btn-mic').classList.remove('active');
        document.getElementById('voice-bar').classList.remove('active');
        document.getElementById('input-cmd').value = '';
    };

    recognition.onresult = (event) => {
        let finalThisEvent = '';
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                finalThisEvent += event.results[i][0].transcript;
            } else {
                interim += event.results[i][0].transcript;
            }
        }

        // Show interim text in the input box as the user speaks
        if (interim) {
            document.getElementById('input-cmd').value = accumulatedFinal + interim;
        }

        if (finalThisEvent) {
            accumulatedFinal += finalThisEvent;
            document.getElementById('input-cmd').value = accumulatedFinal;

            // Reset the debounce timer — wait 1.5s of silence before sending
            if (voiceDebounceTimer) clearTimeout(voiceDebounceTimer);
            voiceDebounceTimer = setTimeout(() => {
                if (accumulatedFinal.trim()) {
                    const finalText = accumulatedFinal.trim();
                    accumulatedFinal = '';
                    document.getElementById('input-cmd').value = '';
                    // Stop recognition after sending
                    try { recognition.stop(); } catch (_) {}
                    sendVoiceCommand(finalText);
                }
            }, 1500);
        }
    };

    recognition.onerror = (event) => {
        if (event.error !== 'no-speech' && event.error !== 'aborted') {
            addMsg('thought', '⚠️ Voice error: ' + event.error);
        }
        accumulatedFinal = '';
        if (voiceDebounceTimer) clearTimeout(voiceDebounceTimer);
        state.isVoiceActive = false;
        document.getElementById('btn-mic').classList.remove('active');
        document.getElementById('voice-bar').classList.remove('active');
        document.getElementById('input-cmd').value = '';
    };

    state.recognition = recognition;
}

function toggleVoice() {
    if (!state.recognition) { addMsg('thought', '⚠️ Voice not supported in this browser. Try Chrome.'); return; }
    if (state.isVoiceActive) {
        state.recognition.stop();
    } else {
        try {
            state.recognition.start();
        } catch (e) {
            addMsg('thought', '⚠️ Could not start voice: ' + e.message);
        }
    }
}

function speakText(text) {
    if (!state.isTTSEnabled || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    let clean = text
        .replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '')
        .replace(/https?:\/\/[^\s]+/g, 'link')
        .replace(/[*_`#]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    if (clean.length > 200) clean = clean.substring(0, 197) + '...';
    if (!clean) return;

    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.rate = 1.05;
    utterance.lang = 'en-US';
    const voices = window.speechSynthesis.getVoices();
    const natural = voices.find(v => v.name.includes('Google') || v.name.includes('Natural'));
    if (natural) utterance.voice = natural;
    window.speechSynthesis.speak(utterance);
}

function toggleTTS() {
    state.isTTSEnabled = !state.isTTSEnabled;
    document.getElementById('btn-tts').classList.toggle('active', state.isTTSEnabled);
    if (!state.isTTSEnabled && window.speechSynthesis) window.speechSynthesis.cancel();
}

// ============ UI Helpers ============

function setStatus(cls, label) {
    const pill = document.getElementById('status-pill');
    pill.className = 'status-pill' + (cls ? ' ' + cls : '');
    document.getElementById('status-label').textContent = label;
}

function addMsg(role, text) {
    hideTypingIndicator();
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    const body = document.createElement('div');
    body.className = 'msg-body';
    body.textContent = text;
    div.appendChild(body);
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    while (container.children.length > 300) container.removeChild(container.firstChild);
}

function showTypingIndicator() {
    hideTypingIndicator();
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'msg agent';
    div.id = 'typing-indicator';
    div.innerHTML = '<div class="msg-body"><div class="typing-indicator"><span></span><span></span><span></span></div></div>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function hideTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

function updateLiveView(imageUrl, description) {
    if (!imageUrl) return;
    const viewport = document.getElementById('live-viewport');
    const badge = document.getElementById('live-badge');
    let src;
    if (imageUrl.startsWith('data:') || imageUrl.startsWith('http')) {
        src = imageUrl;
    } else {
        const filename = imageUrl.split(/[\\/]/).pop();
        src = CONFIG.API_BASE + '/screenshots/' + filename + '?t=' + Date.now();
    }
    const img = new Image();
    img.onload = () => {
        viewport.innerHTML = '';
        img.alt = description || 'Screenshot';
        img.style.cursor = 'zoom-in';
        img.onclick = () => window.open(src, '_blank');
        viewport.appendChild(img);
    };
    img.src = src;
    badge.textContent = description || 'Live';
    badge.classList.add('active');
}

function addLiveLog(message, level) {
    const logContainer = document.getElementById('live-activity');
    if (!logContainer) return;
    const entry = document.createElement('div');
    entry.className = 'live-log-entry ' + (level || 'info');
    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    entry.innerHTML = `<span class="log-time">${time}</span><span>${message}</span>`;
    logContainer.appendChild(entry);
    logContainer.scrollTop = logContainer.scrollHeight;
    while (logContainer.children.length > 100) logContainer.removeChild(logContainer.firstChild);
}

function showToast(message) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

// ============ Resizable Panels ============

function initResizeHandle() {
    const handle = document.getElementById('resize-handle');
    const chatPanel = document.querySelector('.chat-panel');
    const livePanel = document.querySelector('.live-panel');
    if (!handle || !chatPanel || !livePanel) return;

    let startX, chatWidth, liveWidth;

    handle.addEventListener('mousedown', (e) => {
        state.isResizing = true;
        handle.classList.add('active');
        startX = e.clientX;
        chatWidth = chatPanel.offsetWidth;
        liveWidth = livePanel.offsetWidth;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!state.isResizing) return;
        const dx = e.clientX - startX;
        const newChatWidth = Math.max(360, chatWidth + dx);
        const newLiveWidth = Math.max(260, liveWidth - dx);
        const totalWidth = chatPanel.parentElement.offsetWidth - 4;

        if (newChatWidth + newLiveWidth <= totalWidth + 10) {
            chatPanel.style.flex = 'none';
            chatPanel.style.width = newChatWidth + 'px';
            livePanel.style.flex = 'none';
            livePanel.style.width = newLiveWidth + 'px';
        }
    });

    document.addEventListener('mouseup', () => {
        if (state.isResizing) {
            state.isResizing = false;
            handle.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// ============ Init ============

document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('input-cmd');
    const sendBtn = document.getElementById('btn-send');

    function submit() {
        const cmd = input.value.trim();
        if (!cmd) return;
        sendCommand(cmd);
        input.value = '';
    }

    sendBtn.addEventListener('click', submit);
    input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });

    document.getElementById('btn-mic').addEventListener('click', toggleVoice);
    document.getElementById('btn-tts').addEventListener('click', toggleTTS);
    document.getElementById('btn-reset').addEventListener('click', resetSession);

    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); input.focus(); }
    });

    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
    }

    initVoiceRecognition();
    initResizeHandle();
    connectWebSocket();
});
