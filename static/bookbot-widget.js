(() => {
    if (window.__BOOKBOT_INITED__) return;
    window.__BOOKBOT_INITED__ = true;

    const API_URL_DEFAULT = "/api/bookbot";
    const LS_KEY = "bookbot@ui-state.nomax.v3";

    function getApiUrl() {
        const scripts = document.getElementsByTagName("script");
        const me = scripts[scripts.length - 1];
        return (me && me.dataset && me.dataset.apiUrl) || API_URL_DEFAULT;
    }

    const API_URL = getApiUrl();

    const css = `
  :root{ --bb-primary:#2563eb; --bb-grad1:#2563eb; --bb-grad2:#4f46e5; --bb-green:#10b981; --bb-bg:#fff; --bb-muted:#f5f7fb; }
  .bb-fab{
    position:fixed; right:22px; bottom:22px; z-index:2147483000;
    width:56px; height:56px; border-radius:50%; background:var(--bb-primary); color:#fff;
    box-shadow:0 10px 30px rgba(0,0,0,.25); display:flex; align-items:center; justify-content:center; cursor:pointer; user-select:none;
  }
  .bb-fab:hover{ filter:brightness(.95); }
  .bb-fab svg{ width:26px; height:26px; }

  .bb-panel{
    position:fixed; z-index:2147483001; right:22px; bottom:22px;
    width:360px; height:520px; background:var(--bb-bg); border-radius:14px; overflow:hidden;
    box-shadow:0 18px 40px rgba(0,0,0,.28); display:flex; flex-direction:column;
  }
  @media (max-width:640px){
    .bb-panel{ width:100vw; height:100vh; right:0; bottom:0; left:0; top:0; border-radius:0; }
  }

  .bb-head{
    background:linear-gradient(90deg, var(--bb-grad1), var(--bb-grad2));
    color:#fff; display:flex; align-items:center; gap:8px; padding:10px 12px;
    cursor:move; user-select:none; touch-action:none;
  }
  .bb-title{ font-weight:700; flex:1; display:flex; align-items:center; gap:8px; }
  .bb-dot{ width:10px; height:10px; border-radius:50%; background:var(--bb-green); box-shadow:0 0 0 3px rgba(16,185,129,.35); }
  .bb-btn{ width:28px; height:28px; display:flex; align-items:center; justify-content:center; border-radius:8px; color:#fff; cursor:pointer; }
  .bb-btn svg{ width:16px; height:16px; }
  .bb-btn.close:hover{ background:rgba(239,68,68,.20); }

  /* Quan trọng: min-height:0 để flex child co lại -> xuất hiện thanh cuộn */
  .bb-body{ flex:1; min-height:0; display:flex; flex-direction:column; background:#fff; }
  .bb-log{
    flex:1; min-height:0; overflow-y:auto; overflow-x:hidden; padding:12px; background:#fff;
    -webkit-overflow-scrolling: touch; overscroll-behavior: contain;
  }
  .bb-row{ display:flex; gap:8px; margin:8px 0; align-items:flex-start; }
  .bb-av{ width:28px; height:28px; border-radius:50%; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; }
  .bb-av.you{ background:#2563eb; } .bb-av.bot{ background:#10b981; }
  .bb-bubble{ max-width:80%; padding:10px 12px; border-radius:12px; background:#f4f6fb; }
  .bb-row.you .bb-bubble{ background:#e8f0ff; } .bb-row.bot .bb-bubble{ background:#f6fff9; }

  .bb-foot{ display:flex; gap:8px; padding:10px; border-top:1px solid #eef2f7; background:#fafafa; }
  .bb-inp{ flex:1; padding:10px 12px; border:1px solid #e5e7eb; border-radius:10px; outline:none; }
  .bb-send{ padding:10px 14px; border:none; border-radius:10px; background:#2563eb; color:#fff; font-weight:600; cursor:pointer; }
  .bb-send:disabled{ opacity:.6; cursor:not-allowed; }
  .bb-note{ color:#666; font-size:12px; padding:4px 12px 10px; }

  .bb-resize{
    position:absolute; width:14px; height:14px; right:4px; bottom:4px; cursor:nwse-resize;
    background: linear-gradient(135deg, rgba(0,0,0,.15) 0 50%, transparent 50%);
    border-radius:2px;
  }

  /* Scrollbar nhẹ nhàng (Chrome/Edge) */
  .bb-log::-webkit-scrollbar{ width:10px; }
  .bb-log::-webkit-scrollbar-thumb{ background:#d1d5db; border-radius:8px; }
  .bb-log::-webkit-scrollbar-thumb:hover{ background:#c0c4cc; }
  `;
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const state = {open: false, x: null, y: null, w: 360, h: 520};
    try {
        Object.assign(state, JSON.parse(localStorage.getItem(LS_KEY) || "{}") || {});
    } catch {
    }

    let panel, fab, log, input, sendBtn;
    let stickBottom = true; // tự dính đáy nếu người dùng chưa kéo lên

    const saveState = () => {
        try {
            localStorage.setItem(LS_KEY, JSON.stringify(state));
        } catch {
        }
    };
    const escapeHtml = s => String(s).replace(/[&<>"']/g, m => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[m]));
    const getPoint = e => (e.touches && e.touches[0]) ? {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY
    } : {x: e.clientX, y: e.clientY};

    function makeFab() {
        if (fab) return;
        fab = document.createElement("div");
        fab.className = "bb-fab";
        fab.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H8l-5 5V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
        fab.title = "Chat tư vấn sách";
        fab.addEventListener("click", openPanel);
        document.body.appendChild(fab);
    }

    function makePanel() {
        if (panel) return;
        panel = document.createElement("div");
        panel.className = "bb-panel";
        panel.style.width = (state.w || 360) + "px";
        panel.style.height = (state.h || 520) + "px";

        if (state.x != null && state.y != null) {
            panel.style.left = state.x + "px";
            panel.style.top = state.y + "px";
            panel.style.right = "auto";
            panel.style.bottom = "auto";
        }

        panel.innerHTML = `
      <div class="bb-head" id="bb-drag">
        <div class="bb-title"><span class="bb-dot"></span> BookBot – Tư vấn sách</div>
        <div class="bb-btn close" id="bb-close" title="Đóng" aria-label="Đóng">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M6 6l12 12M6 18L18 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </div>
      </div>
      <div class="bb-body">
        <div class="bb-log" id="bb-log" aria-live="polite"></div>
        <div class="bb-foot">
          <input id="bb-input" class="bb-inp" type="text" placeholder="Nhập câu hỏi... (Enter để gửi, Shift+Enter xuống dòng)" />
          <button id="bb-send" class="bb-send">Gửi</button>
        </div>
        <div class="bb-note">Bot sẽ ưu tiên gợi ý theo kho hiện có của bạn.</div>
      </div>
      <div class="bb-resize" id="bb-resize" title="Kéo để đổi kích thước"></div>
    `;
        document.body.appendChild(panel);

        log = panel.querySelector("#bb-log");
        input = panel.querySelector("#bb-input");
        sendBtn = panel.querySelector("#bb-send");

        // auto-stick: nếu người dùng kéo lên xem lịch sử thì không tự nhảy xuống đáy nữa
        log.addEventListener("scroll", () => {
            const nearBottom = log.scrollTop >= (log.scrollHeight - log.clientHeight - 4);
            stickBottom = nearBottom;
        });

        panel.querySelector("#bb-close").onclick = closePanel;

        attachDrag(panel.querySelector("#bb-drag"));
        attachResize(panel.querySelector("#bb-resize"));

        sendBtn.onclick = onSend;
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
            }
            if (e.key === "Escape") {
                closePanel();
            }
        });

        appendBot("Chào bạn! Hãy cho mình biết thể loại yêu thích, độ dài mong muốn và tác giả/đề tài ưa thích để mình gợi ý ạ.");
        requestAnimationFrame(() => {
            log.scrollTop = log.scrollHeight;
        });
    }

    function openPanel() {
        makePanel();
        panel.style.display = "flex";
        state.open = true;
        saveState();
        if (fab) fab.style.display = "none";
        input && input.focus();
        requestAnimationFrame(() => {
            log.scrollTop = log.scrollHeight;
        });
    }

    function closePanel() {
        state.open = false;
        saveState();
        if (panel) panel.style.display = "none";
        if (fab) fab.style.display = "flex";
    }

    function clampIntoViewport() {
        if (!panel) return;
        const r = panel.getBoundingClientRect();
        const vw = window.innerWidth, vh = window.innerHeight;
        let nx = Math.min(Math.max(8, r.left), vw - r.width - 8);
        let ny = Math.min(Math.max(8, r.top), vh - r.height - 8);
        panel.style.left = nx + "px";
        panel.style.top = ny + "px";
        panel.style.right = "auto";
        panel.style.bottom = "auto";
        state.x = nx;
        state.y = ny;
        state.w = r.width;
        state.h = r.height;
        saveState();
    }

    // drag
    function attachDrag(handle) {
        let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
        const start = (e) => {
            dragging = true;
            const r = panel.getBoundingClientRect();
            ox = r.left;
            oy = r.top;
            const p = getPoint(e);
            sx = p.x;
            sy = p.y;
            document.addEventListener("mousemove", move);
            document.addEventListener("mouseup", end);
            document.addEventListener("touchmove", move, {passive: false});
            document.addEventListener("touchend", end);
            document.body.style.userSelect = "none";
        };
        const move = (e) => {
            if (!dragging) return;
            const p = getPoint(e);
            const nx = ox + (p.x - sx);
            const ny = oy + (p.y - sy);
            panel.style.left = nx + "px";
            panel.style.top = ny + "px";
            panel.style.right = "auto";
            panel.style.bottom = "auto";
            e.preventDefault();
        };
        const end = () => {
            if (!dragging) return;
            dragging = false;
            clampIntoViewport();
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", end);
            document.removeEventListener("touchmove", move);
            document.removeEventListener("touchend", end);
            document.body.style.userSelect = "";
        };
        handle.addEventListener("mousedown", start);
        handle.addEventListener("touchstart", start, {passive: false});
    }

    // resize
    function attachResize(handle) {
        let resizing = false, sw = 0, sh = 0, sx = 0, sy = 0;
        const start = (e) => {
            resizing = true;
            const r = panel.getBoundingClientRect();
            sw = r.width;
            sh = r.height;
            const p = getPoint(e);
            sx = p.x;
            sy = p.y;
            document.addEventListener("mousemove", move);
            document.addEventListener("mouseup", end);
            document.addEventListener("touchmove", move, {passive: false});
            document.addEventListener("touchend", end);
            e.preventDefault();
        };
        const move = (e) => {
            if (!resizing) return;
            const p = getPoint(e);
            const w = Math.max(300, sw + (p.x - sx));
            const h = Math.max(380, sh + (p.y - sy));
            panel.style.width = w + "px";
            panel.style.height = h + "px";
            // giữ đáy khi người dùng đang ở đáy
            if (stickBottom) requestAnimationFrame(() => {
                log.scrollTop = log.scrollHeight;
            });
            e.preventDefault();
        };
        const end = () => {
            if (!resizing) return;
            resizing = false;
            clampIntoViewport();
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", end);
            document.removeEventListener("touchmove", move);
            document.removeEventListener("touchend", end);
        };
        handle.addEventListener("mousedown", start);
        handle.addEventListener("touchstart", start, {passive: false});
    }

    function append(type, html) {
        const row = document.createElement("div");
        row.className = "bb-row " + type;
        row.innerHTML = `<div class="bb-av ${type}">${type === 'you' ? 'Y' : 'B'}</div><div class="bb-bubble">${html}</div>`;
        log.appendChild(row);
        if (stickBottom) log.scrollTop = log.scrollHeight;
    }

    const appendYou = (t) => append('you', escapeHtml(t).replace(/\n/g, "<br/>"));
    const appendBot = (t) => append('bot', t);

    function showTyping() {
        const el = document.createElement("div");
        el.className = "bb-row bot";
        el.innerHTML = `<div class="bb-av bot">B</div><div class="bb-bubble"><i>Đang soạn gợi ý…</i></div>`;
        log.appendChild(el);
        if (stickBottom) log.scrollTop = log.scrollHeight;
        return el;
    }

    function renderBot(data) {
        if (data && Array.isArray(data.recommendations)) {
            const li = data.recommendations.map(x =>
                `<li><b>${escapeHtml(x.title)}</b> — ${escapeHtml(x.author || 'N/A')}<br><i>${escapeHtml(x.reason || '')}</i>${x.in_stock === false ? ' <span style="color:#b00">(ngoài kho)</span>' : ''}</li>`
            ).join("");
            const follow = data.follow_up ? `<div style="margin-top:6px"><b>Hỏi thêm:</b> ${escapeHtml(data.follow_up)}</div>` : "";
            appendBot(`<ul>${li}</ul>${follow}`);
        } else if (data && data.summary) {
            const s = data.summary || {};
            const bullets = (s.bullets || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
            const stock = (typeof s.qty === "number") ? ` <span style="color:#555">(còn ${s.qty})</span>` : "";
            appendBot(`
      <div>
        <div><b>${escapeHtml(s.title || 'N/A')}</b> — ${escapeHtml(s.author || 'N/A')}${stock}</div>
        <ul style="margin:6px 0 0 18px">${bullets}</ul>
      </div>
    `);
        } else if (data && data.answer) {
            const books = (data.books || []).map(b => `• <b>${escapeHtml(b.title)}</b> — ${escapeHtml(b.author)} (còn ${b.qty})`).join("<br/>");
            appendBot(`${escapeHtml(data.answer)}${books ? ("<div style='margin-top:6px'>" + books + "</div>") : ""}`);
        } else {
            appendBot((data && data.raw) ? escapeHtml(data.raw) : "Mình chưa rõ nhu cầu, bạn mô tả chi tiết hơn nhé!");
        }
    }


    async function onSend() {
        const text = (input.value || "").trim();
        if (!text) return;
        appendYou(text);
        input.value = "";
        sendBtn.disabled = true;
        const typing = showTyping();
        try {
            const res = await fetch(API_URL, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({message: text})
            });
            let data;
            try {
                data = await res.json();
            } catch {
                data = null;
            }
            if (!res.ok) {
                appendBot("Máy chủ báo lỗi. Bạn thử lại sau nhé.");
            } else {
                renderBot(data || {});
            }
        } catch (e) {
            appendBot("Có lỗi mạng/API. Thử lại sau nhé.");
        } finally {
            if (typing && typing.remove) typing.remove();
            sendBtn.disabled = false;
            input.focus();
        }
    }


    function init() {
        makeFab();
        makePanel();
        if (state.open) openPanel(); else closePanel();
    }

    init();

    window.BookBotWidget = {
        open: openPanel,
        close: closePanel,
        setPosition(x, y) {
            if (!panel) return;
            panel.style.left = x + 'px';
            panel.style.top = y + 'px';
            panel.style.right = 'auto';
            panel.style.bottom = 'auto';
            state.x = x;
            state.y = y;
            saveState();
        }
    };
})();
