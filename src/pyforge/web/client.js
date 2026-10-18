// PyForge browser client.
// Draws what the server sends, forwards keyboard / mouse / touch input, and
// shows connection and game status. All game logic runs on the server.
(() => {
  'use strict';

  const HEARTBEAT_MS = 5000;
  const RETRY_MS = 3000;
  const BUTTONS = ['left', 'middle', 'right'];
  const NAMED_KEYS = {
    ArrowRight: 'right', ArrowLeft: 'left', ArrowUp: 'up', ArrowDown: 'down',
    Space: 'space', Enter: 'enter', NumpadEnter: 'enter', Escape: 'escape',
    Tab: 'tab', Backspace: 'backspace',
    ShiftLeft: 'shift', ShiftRight: 'shift', ControlLeft: 'ctrl', ControlRight: 'ctrl',
    AltLeft: 'alt', AltRight: 'alt',
  };
  const SCROLL_KEYS = new Set(['left', 'right', 'up', 'down', 'space']);

  const $ = (id) => document.getElementById(id);
  const canvas = $('screen');
  const ctx = canvas.getContext('2d');
  const els = {
    stage: $('stage'), title: $('title'), status: $('status'), statusText: $('status-text'),
    restart: $('restart'), overlay: $('overlay'), overlayTitle: $('overlay-title'),
    overlayBody: $('overlay-body'), overlayButton: $('overlay-button'), touch: $('touch'),
  };

  const S = {
    session: null, source: null, config: null, bg: '#000000',
    ents: new Map(), order: [], status: 'loading', error: null, notice: null,
    pending: [], mouse: null, inflight: false, dirty: true, retryTimer: null, overlayAction: null,
  };

  // ---------------------------------------------------------------- status
  function setConnection(kind, text) {
    els.status.className = 'chip chip-' + kind;
    els.statusText.textContent = text;
  }

  function showOverlay(title, body, buttonText, action) {
    els.overlayTitle.textContent = title;
    els.overlayBody.textContent = body;
    els.overlayBody.hidden = !body;
    els.overlayButton.textContent = buttonText;
    S.overlayAction = action;
    els.overlay.hidden = false;
  }

  function updateOverlay() {
    if (S.notice) {
      showOverlay(S.notice.title, S.notice.body, 'Start a new session', connect);
    } else if (S.status === 'error') {
      showOverlay('Game error', S.error || 'The game stopped because of an error.', 'Restart game', restartGame);
    } else if (S.status === 'stopped') {
      showOverlay('Game stopped', 'The game called game.stop().', 'Restart game', restartGame);
    } else {
      els.overlay.hidden = true;
    }
  }

  // ------------------------------------------------------------ connection
  async function connect() {
    clearTimeout(S.retryTimer);
    closeSource();
    S.notice = null;
    S.session = null;
    S.status = 'loading';
    updateOverlay();
    setConnection('warn', 'Connecting…');
    try {
      const response = await fetch('/api/session', { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
      S.session = data.session;
    } catch (err) {
      setConnection('bad', 'Cannot reach the server: ' + err.message);
      S.retryTimer = setTimeout(connect, RETRY_MS);
      return;
    }
    openStream();
  }

  function closeSource() {
    if (S.source) { S.source.close(); S.source = null; }
  }

  function openStream() {
    const source = new EventSource('/api/stream?session=' + encodeURIComponent(S.session));
    S.source = source;
    source.onopen = () => {
      setConnection('ok', 'Connected');
      queueEvent({ type: 'reset' });
    };
    source.onmessage = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch (err) { return; }
      handleMessage(message);
    };
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        // The server refused the stream (session unknown or expired): begin again.
        closeSource();
        setConnection('warn', 'Session ended, starting a new one…');
        S.retryTimer = setTimeout(connect, 1000);
      } else {
        setConnection('warn', 'Connection lost, reconnecting…');
      }
    };
  }

  function handleMessage(m) {
    if (m.t === 'init') {
      applyConfig(m.config);
      S.bg = m.bg;
      S.ents = new Map(Object.entries(m.ents));
      S.order = m.order.map(String);
      S.status = m.status;
      S.error = m.error;
      S.dirty = true;
      updateOverlay();
    } else if (m.t === 'state') {
      if (m.bg !== undefined) S.bg = m.bg;
      if (m.set) {
        for (const [id, props] of Object.entries(m.set)) {
          const current = S.ents.get(id);
          S.ents.set(id, current ? Object.assign(current, props) : props);
        }
      }
      if (m.del) for (const id of m.del) S.ents.delete(String(id));
      if (m.order) S.order = m.order.map(String);
      if (m.status !== undefined) { S.status = m.status; S.error = m.error; updateOverlay(); }
      S.dirty = true;
    } else if (m.t === 'closed') {
      closeSource();
      S.session = null;
      setConnection('bad', 'Session ended');
      S.notice = { title: 'Session ended', body: 'Reason: ' + (m.reason || 'unknown') + '.' };
      updateOverlay();
    }
  }

  function applyConfig(config) {
    S.config = config;
    els.title.textContent = config.title;
    document.title = config.title + ' - PyForge';
    const touch = config.touch === 'auto'
      ? ('ontouchstart' in window || (navigator.maxTouchPoints || 0) > 0)
      : !!config.touch;
    els.touch.hidden = !touch;
    layout();
  }

  async function restartGame() {
    if (!S.session) return connect();
    try {
      const response = await fetch('/api/restart?session=' + encodeURIComponent(S.session), { method: 'POST' });
      if (response.status === 404) sessionLost();
    } catch (err) { /* the status chip already shows connection problems */ }
  }

  function sessionLost() {
    closeSource();
    S.session = null;
    setConnection('warn', 'Session expired, starting a new one…');
    clearTimeout(S.retryTimer);
    S.retryTimer = setTimeout(connect, 500);
  }

  // ------------------------------------------------------------------ input
  function queueEvent(event) {
    S.pending.push(event);
    flush();
  }

  function flush() {
    if (S.inflight || !S.session) return;
    const events = S.pending;
    S.pending = [];
    if (S.mouse) { events.push(S.mouse); S.mouse = null; }
    if (events.length) send(events);
  }

  // One request at a time keeps events in order; events that arrive meanwhile
  // are sent together in the next request.
  function send(events) {
    S.inflight = true;
    sendInput(events).then(() => { S.inflight = false; flush(); });
  }

  async function sendInput(events) {
    try {
      const response = await fetch('/api/input?session=' + encodeURIComponent(S.session), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events }),
      });
      if (response.status === 404) sessionLost();
    } catch (err) { /* network hiccup: the stream status shows it */ }
  }

  function keyName(e) {
    if (NAMED_KEYS[e.code]) return NAMED_KEYS[e.code];
    let m = /^Key([A-Z])$/.exec(e.code || '');
    if (m) return m[1].toLowerCase();
    m = /^(?:Digit|Numpad)([0-9])$/.exec(e.code || '');
    if (m) return m[1];
    if (NAMED_KEYS[e.key]) return NAMED_KEYS[e.key];
    if (e.key === ' ') return 'space';
    if (e.key && e.key.length === 1) return e.key.toLowerCase();
    return null;
  }

  function onKey(down) {
    return (e) => {
      if (!S.session || (down && e.metaKey)) return;
      const name = keyName(e);
      if (!name) return;
      if (SCROLL_KEYS.has(name) && !(e.ctrlKey || e.altKey || e.metaKey)) e.preventDefault();
      if (down && e.repeat) return;
      queueEvent({ type: 'key', key: name, down });
    };
  }

  function toGame(e) {
    const rect = canvas.getBoundingClientRect();
    const c = S.config || { width: 1, height: 1 };
    return {
      x: (e.clientX - rect.left) * c.width / Math.max(rect.width, 1),
      y: (e.clientY - rect.top) * c.height / Math.max(rect.height, 1),
    };
  }

  canvas.addEventListener('pointermove', (e) => {
    const p = toGame(e);
    S.mouse = { type: 'mouse', x: p.x, y: p.y };
    flush();
  });
  canvas.addEventListener('pointerdown', (e) => {
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* not supported everywhere */ }
    const p = toGame(e);
    queueEvent({ type: 'button', button: BUTTONS[e.button] || 'left', down: true, x: p.x, y: p.y });
    e.preventDefault();
  });
  const pointerUp = (e) => {
    const p = toGame(e);
    queueEvent({ type: 'button', button: BUTTONS[e.button] || 'left', down: false, x: p.x, y: p.y });
  };
  canvas.addEventListener('pointerup', pointerUp);
  canvas.addEventListener('pointercancel', pointerUp);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());

  window.addEventListener('keydown', onKey(true));
  window.addEventListener('keyup', onKey(false));
  window.addEventListener('blur', () => queueEvent({ type: 'reset' }));
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) queueEvent({ type: 'reset' });
  });
  window.addEventListener('pagehide', (e) => {
    if (S.session && !e.persisted && navigator.sendBeacon) {
      navigator.sendBeacon('/api/close?session=' + encodeURIComponent(S.session));
    }
  });
  window.addEventListener('pageshow', (e) => { if (e.persisted) connect(); });

  // On-screen controls for touch devices send the same key events as a keyboard.
  for (const button of document.querySelectorAll('.tbtn')) {
    const key = button.dataset.key;
    const set = (down) => (e) => {
      e.preventDefault();
      button.classList.toggle('down', down);
      queueEvent({ type: 'key', key, down });
    };
    button.addEventListener('pointerdown', (e) => {
      try { button.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      set(true)(e);
    });
    button.addEventListener('pointerup', set(false));
    button.addEventListener('pointercancel', set(false));
    button.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  els.restart.addEventListener('click', restartGame);
  els.overlayButton.addEventListener('click', () => { if (S.overlayAction) S.overlayAction(); });

  // The heartbeat tells the server this player is still here.
  setInterval(() => {
    if (S.session && !S.inflight) send([]);
  }, HEARTBEAT_MS);

  // -------------------------------------------------------------- rendering
  function layout() {
    const c = S.config;
    if (!c) return;
    const rect = els.stage.getBoundingClientRect();
    const scale = Math.min(Math.max(rect.width, 1) / c.width, Math.max(rect.height, 1) / c.height);
    const cssW = Math.max(Math.floor(c.width * scale), 1);
    const cssH = Math.max(Math.floor(c.height * scale), 1);
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    canvas.width = Math.min(Math.round(cssW * dpr), 8192);
    canvas.height = Math.min(Math.round(cssH * dpr), 8192);
    S.dirty = true;
  }

  function draw() {
    const c = S.config;
    if (!c) return;
    ctx.setTransform(canvas.width / c.width, 0, 0, canvas.height / c.height, 0, 0);
    ctx.fillStyle = S.bg;
    ctx.fillRect(0, 0, c.width, c.height);
    for (const id of S.order) {
      const e = S.ents.get(id);
      if (!e || !e.v) continue;
      ctx.fillStyle = e.c;
      if (e.k === 'r') {
        ctx.fillRect(e.x, e.y, e.w, e.h);
      } else if (e.k === 't') {
        ctx.font = e.n + 'px system-ui, sans-serif';
        ctx.textBaseline = 'top';
        ctx.fillText(e.s, e.x, e.y);
      }
    }
  }

  function frameLoop() {
    if (S.dirty) { S.dirty = false; draw(); }
    requestAnimationFrame(frameLoop);
  }

  window.addEventListener('resize', layout);
  window.addEventListener('orientationchange', layout);
  if (window.ResizeObserver) new ResizeObserver(layout).observe(els.stage);

  window.__pyforge = S; // handy when debugging in the browser console
  requestAnimationFrame(frameLoop);
  connect();
})();
