/**
 * AskforWrite AI Company OS — Embeddable 24/7 Inbound Sales Closer Widget
 * Zero-dependency, drop-in JavaScript widget for external sites (WordPress networks, landing pages)
 * 
 * Usage:
 *   <script src="https://os.askforwrite.com/dashboard/widget.js" data-company="MyBrand"></script>
 */

(function () {
  'use strict';

  // Prevent multiple initializations
  if (window.__AFW_SALES_CLOSER_INITIALIZED__) return;
  window.__AFW_SALES_CLOSER_INITIALIZED__ = true;

  // ── Configuration ──────────────────────────────────────────
  const currentScript = document.currentScript;
  const config = window.AFW_WIDGET_CONFIG || {};

  let scriptOrigin = '';
  if (currentScript && currentScript.src) {
    try {
      const parsedUrl = new URL(currentScript.src);
      scriptOrigin = parsedUrl.origin;
    } catch (e) {
      // fallback
    }
  }

  const API_BASE = config.apiBase ||
    (currentScript ? currentScript.getAttribute('data-api-base') : null) ||
    scriptOrigin ||
    (window.location.origin && window.location.origin !== 'null' ? window.location.origin : 'http://localhost:8000');

  const COMPANY_NAME = config.company ||
    (currentScript ? (currentScript.getAttribute('data-company') || currentScript.getAttribute('data-afw-tenant')) : null) ||
    'AskforWrite';

  const CURRENCY = config.currency || 'INR';

  // ── State ──────────────────────────────────────────────────
  const state = {
    isOpen: false,
    sessionId: 'session_' + Math.random().toString(36).substring(2, 12),
    prospectName: 'Guest Visitor',
    prospectContact: 'visitor@' + (window.location.hostname || 'external.site'),
    history: [],
    isSending: false,
  };

  // ── Styles Injection ───────────────────────────────────────
  const styles = `
    .afw-widget-container {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: #f3f4f6;
    }
    .afw-launcher-btn {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
      border: none;
      box-shadow: 0 8px 24px rgba(79, 70, 229, 0.45);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      position: relative;
    }
    .afw-launcher-btn:hover {
      transform: scale(1.08);
      box-shadow: 0 12px 32px rgba(79, 70, 229, 0.6);
    }
    .afw-launcher-btn svg {
      width: 28px;
      height: 28px;
      fill: #ffffff;
      transition: transform 0.2s;
    }
    .afw-online-badge {
      position: absolute;
      top: -2px;
      right: -2px;
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: #10b981;
      border: 2px solid #0b0f19;
      animation: afw-pulse 2s infinite;
    }
    @keyframes afw-pulse {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
      70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    .afw-chat-window {
      position: fixed;
      bottom: 96px;
      right: 24px;
      width: 380px;
      max-width: calc(100vw - 32px);
      height: 540px;
      max-height: calc(100vh - 120px);
      background: #0b0f19;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 20px;
      box-shadow: 0 20px 48px rgba(0, 0, 0, 0.6);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      opacity: 0;
      transform: translateY(20px) scale(0.96);
      pointer-events: none;
      z-index: 999999;
    }
    .afw-chat-window.afw-open {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }
    .afw-header {
      background: linear-gradient(135deg, rgba(79, 70, 229, 0.9) 0%, rgba(6, 182, 212, 0.9) 100%);
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    .afw-header-info {
      display: flex;
      flex-direction: column;
    }
    .afw-header-title {
      font-weight: 700;
      font-size: 15px;
      color: #ffffff;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .afw-header-sub {
      font-size: 11px;
      color: rgba(255, 255, 255, 0.85);
    }
    .afw-close-btn {
      background: rgba(0, 0, 0, 0.2);
      border: none;
      color: #ffffff;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      transition: background 0.2s;
    }
    .afw-close-btn:hover {
      background: rgba(0, 0, 0, 0.4);
    }
    .afw-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      background: #0b0f19;
    }
    .afw-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13px;
      word-wrap: break-word;
    }
    .afw-msg.afw-bot {
      align-self: flex-start;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #e5e7eb;
      border-bottom-left-radius: 4px;
    }
    .afw-msg.afw-user {
      align-self: flex-end;
      background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%);
      color: #ffffff;
      border-bottom-right-radius: 4px;
    }
    .afw-chips-container {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .afw-chip {
      background: rgba(79, 70, 229, 0.2);
      border: 1px solid rgba(79, 70, 229, 0.4);
      color: #c7d2fe;
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .afw-chip:hover {
      background: rgba(79, 70, 229, 0.4);
      color: #ffffff;
      transform: translateY(-1px);
    }
    .afw-checkout-card {
      margin-top: 10px;
      padding: 12px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.3);
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .afw-checkout-title {
      font-weight: 700;
      color: #34d399;
      font-size: 12px;
    }
    .afw-btn-checkout {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 9px 14px;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 700;
      font-size: 12px;
      transition: opacity 0.2s;
    }
    .afw-btn-checkout:hover {
      opacity: 0.9;
    }
    .afw-btn-razorpay {
      background: #4f46e5;
      color: #ffffff;
    }
    .afw-btn-paypal {
      background: #0070ba;
      color: #ffffff;
    }
    .afw-input-area {
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.02);
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .afw-input {
      flex: 1;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 10px;
      padding: 10px 14px;
      color: #ffffff;
      font-size: 13px;
      outline: none;
    }
    .afw-input:focus {
      border-color: #6366f1;
    }
    .afw-send-btn {
      background: #4f46e5;
      border: none;
      width: 38px;
      height: 38px;
      border-radius: 10px;
      color: #ffffff;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s;
    }
    .afw-send-btn:hover {
      background: #4338ca;
    }
    .afw-send-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .afw-typing-indicator {
      display: flex;
      gap: 4px;
      padding: 8px 12px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 10px;
      align-self: flex-start;
    }
    .afw-typing-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #9ca3af;
      animation: afw-bounce 1.4s infinite ease-in-out both;
    }
    .afw-typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .afw-typing-dot:nth-child(2) { animation-delay: -0.16s; }
    @keyframes afw-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1.0); }
    }
  `;

  // Inject Styles
  const styleEl = document.createElement('style');
  styleEl.textContent = styles;
  document.head.appendChild(styleEl);

  // ── Build DOM ──────────────────────────────────────────────
  const container = document.createElement('div');
  container.className = 'afw-widget-container';
  container.innerHTML = `
    <!-- Launcher Button -->
    <button class="afw-launcher-btn" id="afw-launcher" aria-label="Open AI Sales Closer">
      <span class="afw-online-badge"></span>
      <svg viewBox="0 0 24 24">
        <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
      </svg>
    </button>

    <!-- Chat Drawer -->
    <div class="afw-chat-window" id="afw-window">
      <div class="afw-header">
        <div class="afw-header-info">
          <div class="afw-header-title">
            <span>AskforWrite AI Closer</span>
            <span style="font-size: 10px; background: rgba(16, 185, 129, 0.2); color: #34d399; padding: 2px 6px; border-radius: 10px;">ACTIVE</span>
          </div>
          <span class="afw-header-sub">24/7 Autonomous Sales & Operational Advisor</span>
        </div>
        <button class="afw-close-btn" id="afw-close" aria-label="Close Chat">&times;</button>
      </div>

      <div class="afw-messages" id="afw-messages">
        <!-- Injected via JS -->
      </div>

      <div class="afw-input-area">
        <input type="text" class="afw-input" id="afw-input" placeholder="Ask about pricing, capabilities, or ROI..." />
        <button class="afw-send-btn" id="afw-send" aria-label="Send">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(container);

  const launcherBtn = document.getElementById('afw-launcher');
  const chatWindow = document.getElementById('afw-window');
  const closeBtn = document.getElementById('afw-close');
  const messagesEl = document.getElementById('afw-messages');
  const inputEl = document.getElementById('afw-input');
  const sendBtn = document.getElementById('afw-send');

  // Toggle Chat
  function toggleChat(open) {
    state.isOpen = typeof open === 'boolean' ? open : !state.isOpen;
    if (state.isOpen) {
      chatWindow.classList.add('afw-open');
      inputEl.focus();
    } else {
      chatWindow.classList.remove('afw-open');
    }
  }

  launcherBtn.addEventListener('click', () => toggleChat());
  closeBtn.addEventListener('click', () => toggleChat(false));

  // Render initial greeting
  function initGreeting() {
    appendBotMessage(
      `Hello! I'm your 24/7 autonomous sales closer for ${COMPANY_NAME}. ` +
      `We help founders and businesses automate marketing creatives, 4-site SEO publishing, produce quality CV, and warehouse operations. ` +
      `What can I help you accelerate today?`,
      [
        '🚀 What capabilities are included?',
        '💰 Pricing & ROI breakdown',
        '⚡ Instant Onboarding / Buy',
      ]
    );
  }

  // Format simple markdown into HTML
  function formatText(text) {
    if (!text) return '';
    let sanitized = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    // Bold
    sanitized = sanitized.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Bullets
    sanitized = sanitized.replace(/^\s*•\s*(.*)$/gm, '<li>$1</li>');
    sanitized = sanitized.replace(/(<li>.*<\/li>)/s, '<ul style="margin:6px 0 6px 18px;">$1</ul>');
    // Line breaks
    sanitized = sanitized.replace(/\n/g, '<br>');
    return sanitized;
  }

  function appendUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'afw-msg afw-user';
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function appendBotMessage(text, quickChips = [], paymentLinks = null) {
    const el = document.createElement('div');
    el.className = 'afw-msg afw-bot';
    el.innerHTML = formatText(text);

    // If payment links attached
    if (paymentLinks && (paymentLinks.razorpay || paymentLinks.paypal)) {
      const ctaCard = document.createElement('div');
      ctaCard.className = 'afw-checkout-card';
      ctaCard.innerHTML = `
        <div class="afw-checkout-title">⚡ 1-Click Instant Onboarding</div>
        ${paymentLinks.razorpay ? `
          <a href="${paymentLinks.razorpay}" target="_blank" rel="noopener noreferrer" class="afw-btn-checkout afw-btn-razorpay">
            Pay with Razorpay (INR)
          </a>
        ` : ''}
        ${paymentLinks.paypal ? `
          <a href="${paymentLinks.paypal}" target="_blank" rel="noopener noreferrer" class="afw-btn-checkout afw-btn-paypal">
            Pay with PayPal (USD)
          </a>
        ` : ''}
      `;
      el.appendChild(ctaCard);
    }

    // If quick chips provided
    if (quickChips && quickChips.length > 0) {
      const chipsContainer = document.createElement('div');
      chipsContainer.className = 'afw-chips-container';
      quickChips.forEach(chipText => {
        const chip = document.createElement('button');
        chip.className = 'afw-chip';
        chip.textContent = chipText;
        chip.addEventListener('click', () => {
          inputEl.value = chipText;
          sendMessage();
        });
        chipsContainer.appendChild(chip);
      });
      el.appendChild(chipsContainer);
    }

    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showTypingIndicator() {
    const el = document.createElement('div');
    el.id = 'afw-typing';
    el.className = 'afw-typing-indicator';
    el.innerHTML = `
      <div class="afw-typing-dot"></div>
      <div class="afw-typing-dot"></div>
      <div class="afw-typing-dot"></div>
    `;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideTypingIndicator() {
    const el = document.getElementById('afw-typing');
    if (el) el.remove();
  }

  // Send Message to Backend Closer API
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || state.isSending) return;

    appendUserMessage(text);
    inputEl.value = '';
    state.isSending = true;
    sendBtn.disabled = true;
    showTypingIndicator();

    state.history.push({ role: 'user', content: text });

    try {
      const res = await fetch(`${API_BASE}/v1/growth/sales-closer/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: state.sessionId,
          prospect_name: state.prospectName,
          prospect_contact: state.prospectContact,
          message: text,
          history: state.history,
          currency: CURRENCY,
          channel: 'web_closer_widget',
        }),
      });

      hideTypingIndicator();

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      state.history.push({ role: 'assistant', content: data.reply });

      const paymentLinks = data.payment_links || (data.checkout_link ? { razorpay: data.checkout_link } : null);
      appendBotMessage(data.reply, [], paymentLinks);
    } catch (err) {
      hideTypingIndicator();
      appendBotMessage(
        "I'm experiencing a momentary connection lag. Please contact us directly at info@askforwrite.in or try again in a moment.",
        ['🚀 What capabilities are included?', '⚡ Instant Onboarding / Buy']
      );
    } finally {
      state.isSending = false;
      sendBtn.disabled = false;
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      sendMessage();
    }
  });

  // Start with greeting
  initGreeting();

  // Expose Global Control API
  window.AFWSalesCloser = {
    open: () => toggleChat(true),
    close: () => toggleChat(false),
    toggle: () => toggleChat(),
    sendMessage: (msg) => {
      inputEl.value = msg;
      sendMessage();
    },
  };
})();
