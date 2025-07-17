let currentUser = 1; // Temporary user ID
let isProcessing = false;

const API_CONFIG = {
    baseUrl: 'http://localhost:8000',
    rateLimit: {
        maxRequests: 5,
        timeWindow: 60000, // 1 minute
        requests: [],
    }
};

function checkRateLimit() {
    const now = Date.now();
    API_CONFIG.rateLimit.requests = API_CONFIG.rateLimit.requests.filter(
        time => now - time < API_CONFIG.rateLimit.timeWindow
    );
    
    if (API_CONFIG.rateLimit.requests.length >= API_CONFIG.rateLimit.maxRequests) {
        const oldestRequest = Math.min(...API_CONFIG.rateLimit.requests);
        const waitTime = Math.ceil((API_CONFIG.rateLimit.timeWindow - (now - oldestRequest)) / 1000);
        throw new Error(`Rate limit exceeded. Please wait ${waitTime} seconds.`);
    }
    
    API_CONFIG.rateLimit.requests.push(now);
}

// Configure Markdown parser
marked.setOptions({
    highlight: (code, lang) => {
        const language = hljs.getLanguage(lang) ? lang : 'plaintext';
        return hljs.highlight(code, { language }).value;
    },
    breaks: true,
    gfm: true
});

// DOM Elements
const domElements = {
    promptInput: document.getElementById('promptInput'),
    submitBtn: document.getElementById('submitBtn'),
    loading: document.getElementById('loading'),
    responseContainer: document.getElementById('responseContainer'),
    synthesisBox: document.getElementById('synthesisBox'),
    synthesisContent: document.getElementById('synthesisContent'),
    historyList: document.getElementById('historyList'),
    refreshHistory: document.getElementById('refreshHistory')
};

// Event Listeners
domElements.refreshHistory.addEventListener('click', loadHistory);
window.addEventListener('load', () => {
    loadHistory();
    MathJax.typesetPromise();
});

async function processPrompt() {
    const prompt = domElements.promptInput.value.trim();
    
    if (isProcessing) {
        showError('A request is already in progress');
        return;
    }
    
    if (!prompt) {
        showError('Please enter a valid prompt');
        return;
    }
    
    try {
        checkRateLimit();
        isProcessing = true;
        showLoading(true);
        clearResults();
        
        const response = await fetch(`${API_CONFIG.baseUrl}/process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                user_id: currentUser
            })
        });
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(
                data.detail || 
                `Request failed with status ${response.status}`
            );
        }
        
        const data = await response.json();
        displayResults(data);
        domElements.promptInput.value = '';
        await loadHistory();
        showSuccess('Response generated successfully!');
        
    } catch (error) {
        console.error('Error processing prompt:', error);
        showError(error.message);
        
    } finally {
        isProcessing = false;
        showLoading(false);
    }
}

async function loadHistory() {
    try {
        const response = await fetch(`http://localhost:8000/conversations?user_id=${currentUser}`);
        const conversations = await response.json();
        renderHistory(conversations);
    } catch (error) {
        showError('Failed to load history');
    }
}

function renderHistory(conversations) {
    domElements.historyList.innerHTML = conversations.map(conv => `
        <div class="conversation-item" data-id="${conv.id}">
            <div class="conversation-content" onclick="loadConversation(${conv.id})">
                <div class="conversation-preview">
                    ${conv.prompt.substring(0, 80)}${conv.prompt.length > 80 ? '...' : ''}
                </div>
                <div class="timestamp">
                    ${new Date(conv.created_at).toLocaleDateString()}
                    ${new Date(conv.created_at).toLocaleTimeString()}
                </div>
                ${conv.context?.personal_info?.job_role ? `
                    <div class="context-indicator">
                        👤 ${conv.context.personal_info.job_role}
                    </div>
                ` : ''}
            </div>
            <button class="delete-btn" onclick="deleteConversation(${conv.id}, event)">🗑️</button>
        </div>
    `).join('');
}

async function loadConversation(conversationId) {
    try {
        const response = await fetch(`http://localhost:8000/conversations/${conversationId}`);
        const conversation = await response.json();
        
        clearResults();
        displayResults({
            responses: conversation.responses,
            synthesis: { content: conversation.synthesis }
        });
        
        // Highlight selected conversation
        document.querySelectorAll('.conversation-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelector(`[data-id="${conversationId}"]`).classList.add('active');
    } catch (error) {
        showError('Failed to load conversation');
    }
}

function displayResults(data) {
    // Display individual responses
    domElements.responseContainer.innerHTML = data.responses.map(response => `
        <div class="response-card ${!response.success ? 'error-card' : ''}">
            <div class="response-header">
                <span class="provider-name">${response.provider}</span>
                <span class="latency">${response.latency}ms</span>
            </div>
            <div class="response-content">
                ${response.success ? 
                    DOMPurify.sanitize(marked.parse(response.content)) : 
                    `<div class="error-message">${response.error}</div>`
                }
            </div>
        </div>
    `).join('');

    // Display synthesis
    if (data.synthesis?.content) {
        domElements.synthesisBox.classList.remove('hidden');
        domElements.synthesisContent.innerHTML = DOMPurify.sanitize(marked.parse(data.synthesis.content));
        MathJax.typesetPromise();
    }
}

function createResponseCard(response) {
    const card = document.createElement('div');
    card.className = `response-card ${response.error ? 'error' : ''}`;
    
    // Clean and parse content
    let content = '';
    if (response.error) {
        content = `⚠️ Error: ${response.error.replace('⚠️', '').trim()}`;
    } else {
        content = response.content || 'No response received';
    }

    // Sanitize and parse markdown
    const cleanContent = DOMPurify.sanitize(marked.parse(content));
    
    card.innerHTML = `
        <div class="response-header">
            <div class="provider-name">${response.provider}</div>
            <div class="latency">${response.latency}ms</div>
        </div>
        <div class="response-content">
            ${cleanContent}
        </div>
    `;

    // Render MathJax after content is inserted
    MathJax.typesetPromise([card]).catch(err => {
        console.error('MathJax rendering error:', err);
    });

    return card;
}

function copySynthesis() {
    navigator.clipboard.writeText(domElements.synthesisContent.textContent)
        .then(() => alert('Copied to clipboard!'))
        .catch(err => showError('Failed to copy'));
}

// Helper functions
function showLoading(show) {
    domElements.loading.classList.toggle('hidden', !show);
    domElements.submitBtn.disabled = show;
}

function clearResults() {
    domElements.responseContainer.innerHTML = '';
    domElements.synthesisBox.classList.add('hidden');
}

function showSuccess(message) {
    const alert = document.createElement('div');
    alert.className = 'alert-success';
    alert.textContent = message;
    document.body.appendChild(alert);
    setTimeout(() => alert.remove(), 3000);
}

function showError(message, type = 'error') {
    const alert = document.createElement('div');
    alert.className = `alert-${type}`;
    alert.innerHTML = `
        <div class="alert-content">
            <span class="alert-icon">${type === 'error' ? '⚠️' : '✓'}</span>
            <span class="alert-message">${message}</span>
        </div>
        <button class="alert-close">×</button>
    `;
    
    alert.querySelector('.alert-close').addEventListener('click', () => alert.remove());
    document.body.appendChild(alert);
    
    if (type === 'error') {
        alert.style.backgroundColor = '#fee';
        alert.style.color = '#e74c3c';
    } else {
        alert.style.backgroundColor = '#e8f8f5';
        alert.style.color = '#27ae60';
    }
    
    setTimeout(() => alert.remove(), type === 'error' ? 5000 : 3000);
}

function showSuccess(message) {
    showError(message, 'success');
}

function checkRateLimit() {
    const now = Date.now();
    const { rateLimit } = API_CONFIG;
    
    // Clean up old requests
    rateLimit.requests = rateLimit.requests.filter(
        time => now - time < rateLimit.timeWindow
    );
    
    if (rateLimit.requests.length >= rateLimit.maxRequests) {
        const oldestRequest = Math.min(...rateLimit.requests);
        const waitTime = Math.ceil((rateLimit.timeWindow - (now - oldestRequest)) / 1000);
        const retryAfter = new Date(oldestRequest + rateLimit.timeWindow);
        
        throw new Error(
            `Rate limit exceeded. Please wait ${waitTime} seconds.\n` +
            `You can try again at ${retryAfter.toLocaleTimeString()}.`
        );
    }
    
    rateLimit.requests.push(now);
    
    // Update UI with remaining requests
    const remainingRequests = rateLimit.maxRequests - rateLimit.requests.length;
    domElements.submitBtn.title = `${remainingRequests} requests remaining`;
}

async function processPrompt() {
    const prompt = domElements.promptInput.value.trim();
    
    if (isProcessing) {
        showError('A request is already in progress');
        return;
    }
    
    if (!prompt) {
        showError('Please enter a valid prompt');
        return;
    }
    
    try {
        checkRateLimit();
        isProcessing = true;
        showLoading(true);
        clearResults();
        
        const response = await fetch(`${API_CONFIG.baseUrl}/process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                user_id: currentUser
            })
        });
        
        if (!response.ok) {
            const data = await response.json();
            throw new Error(
                data.detail || 
                `Request failed with status ${response.status}`
            );
        }
        
        const data = await response.json();
        displayResults(data);
        domElements.promptInput.value = '';
        await loadHistory();
        showSuccess('Response generated successfully!');
        
    } catch (error) {
        console.error('Error processing prompt:', error);
        showError(error.message);
        
    } finally {
        isProcessing = false;
        showLoading(false);
    }
}

// Add new delete function
async function deleteConversation(conversationId, event) {
    event.stopPropagation();
    
    if (!confirm('Are you sure you want to delete this conversation?')) {
        return;
    }

    try {
        const response = await fetch(`http://localhost:8000/conversations/${conversationId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error('Delete failed');
        
        // Remove from UI
        document.querySelector(`[data-id="${conversationId}"]`).remove();
        showError('Conversation deleted', 'success');
    } catch (error) {
        showError('Failed to delete conversation');
    }
}