(function () {
    const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';

    // Helpers -----------------------------------------------------------
    function formatTime(iso) {
        if (!iso) return '';
        const d = new Date(iso);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    async function fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const result = reader.result;
                const commaIdx = result.indexOf(',');
                resolve(result.slice(commaIdx + 1)); // pure base64
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    // Guest widget -------------------------------------------------------
    class GuestWidget {
        constructor(root) {
            this.root = root;
            this.slug = root.dataset.slug;
            this.ws = null;
            this.messagesEl = root.querySelector('[data-messages]');
            this.inputEl = root.querySelector('[data-chat-input]');
            this.sendBtn = root.querySelector('[data-send]');
            this.fileInput = root.querySelector('[data-attachment-input]');
            this.attachBtn = root.querySelector('[data-attachment-trigger]');

            this.bindEvents();
            this.connect();
        }

        bindEvents() {
            this.sendBtn?.addEventListener('click', () => this.send());
            this.inputEl?.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.send();
                }
            });
            this.attachBtn?.addEventListener('click', () => this.fileInput?.click());
            this.fileInput?.addEventListener('change', (e) => this.handleFile(e));
        }

        connect() {
            const url = `${WS_PROTOCOL}://${window.location.host}/ws/chat/${this.slug}/`;
            this.ws = new WebSocket(url);

            this.ws.addEventListener('open', () => {
                // No special init needed for guest
            });

            this.ws.addEventListener('message', (event) => {
                const payload = JSON.parse(event.data);
                if (payload.event === 'bootstrap') {
                    payload.messages.forEach(msg => this.appendMessage(msg));
                } else if (payload.event === 'message') {
                    this.appendMessage(payload.message);
                } else if (payload.event === 'read') {
                    // CS read the thread – no UI change needed for guest
                } else if (payload.event === 'typing') {
                    // Optional: show CS typing indicator
                } else if (payload.event === 'error') {
                    console.error('Chat error:', payload.detail);
                }
            });

            this.ws.addEventListener('close', () => {
                // Reconnect after 2 seconds
                setTimeout(() => this.connect(), 2000);
            });
        }

        async send() {
            const text = this.inputEl?.value.trim();
            if (!text || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ action: 'message', message: text }));
            this.inputEl.value = '';
        }

        async handleFile(event) {
            const file = event.target.files[0];
            if (!file) return;
            if (file.size > 2 * 1024 * 1024) {
                alert('File must be ≤ 2 MB');
                return;
            }
            const allowedMimes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf', 'text/plain', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
            if (!allowedMimes.includes(file.type)) {
                alert('File type not allowed');
                return;
            }
            const base64 = await fileToBase64(file);
            this.ws.send(JSON.stringify({
                action: 'file',
                file_name: file.name,
                mime_type: file.type,
                file_data: base64,
            }));
            // Reset file input
            this.fileInput.value = '';
        }

        appendMessage(msg) {
            const div = document.createElement('div');
            div.className = 'chat-message';
            if (msg.sender_role === 'guest') div.classList.add('is-self');

            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble';

            if (msg.attachment && msg.attachment.url) {
                const a = document.createElement('a');
                a.href = msg.attachment.url;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = `📎 ${msg.attachment.name || 'Attachment'}`;
                bubble.appendChild(a);
            }
            if (msg.content) {
                const txt = document.createElement('div');
                txt.textContent = msg.content;
                bubble.appendChild(txt);
            }

            const time = document.createElement('div');
            time.style.fontSize = '0.75em';
            time.style.color = '#666';
            time.style.marginTop = '4px';
            time.textContent = formatTime(msg.created_at);

            div.appendChild(bubble);
            div.appendChild(time);
            this.messagesEl.appendChild(div);
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }
    }

    // CS dashboard -------------------------------------------------------
    class CsDashboard {
        constructor(root) {
            this.root = root;
            this.ws = null;
            this.currentThread = null;
            this.threadListEl = root.querySelector('[data-thread-list]');
            this.messagesEl = root.querySelector('[data-messages]');
            this.convHeaderEl = root.querySelector('[data-conv-header]');
            this.inputEl = root.querySelector('[data-chat-input]');
            this.sendBtn = root.querySelector('[data-send]');
            this.fileInput = root.querySelector('[data-attachment-input]');
            this.attachBtn = root.querySelector('[data-attachment-trigger]');

            this.bindEvents();
            this.fetchThreads();
            // Auto-refresh every 10 seconds
            setInterval(() => this.fetchThreads(), 10000);
        }

        bindEvents() {
            this.sendBtn?.addEventListener('click', () => this.send());
            this.inputEl?.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.send();
                }
            });
            this.attachBtn?.addEventListener('click', () => this.fileInput?.click());
            this.fileInput?.addEventListener('change', (e) => this.handleFile(e));
            this.root.querySelector('[data-refresh-threads]')?.addEventListener('click', () => this.fetchThreads());
        }

        async fetchThreads() {
            try {
                const resp = await fetch('/chat/cs/threads/');
                const data = await resp.json();
                this.renderThreadList(data.threads || []);
            } catch (e) {
                console.error('Failed to load threads', e);
            }
        }

        renderThreadList(threads) {
            if (!threads.length) {
                this.threadListEl.innerHTML = '<div class="empty-state">No active chats</div>';
                return;
            }
            const html = threads.map(t => `
                <div class="thread-item" data-slug="${t.slug}">
                    <div class="thread-info">
                        <div class="slug">${t.slug}</div>
                        <div class="time">${formatTime(t.last_activity)}</div>
                    </div>
                    <span class="unread-badge ${t.unread_for_cs ? 'visible' : ''}">${t.unread_for_cs || ''}</span>
                </div>
            `).join('');
            this.threadListEl.innerHTML = html;

            // Attach click listeners
            this.threadListEl.querySelectorAll('.thread-item').forEach(item => {
                item.addEventListener('click', () => {
                    const slug = item.dataset.slug;
                    this.openThread(slug);
                });
            });
        }

        openThread(slug) {
            // Update UI
            this.threadListEl.querySelectorAll('.thread-item').forEach(el => el.classList.remove('active'));
            this.threadListEl.querySelector(`[data-slug="${slug}"]`)?.classList.add('active');
            this.convHeaderEl.textContent = `Chat with ${slug}`;
            this.messagesEl.innerHTML = '';

            // Enable input
            this.inputEl.disabled = false;
            this.sendBtn.disabled = false;

            // Close previous WebSocket
            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }

            // Open new WebSocket
            const url = `${WS_PROTOCOL}://${window.location.host}/ws/chat/${slug}/`;
            this.ws = new WebSocket(url);
            this.currentThread = slug;

            this.ws.addEventListener('open', () => {
                // Mark as read immediately
                this.ws.send(JSON.stringify({ action: 'read' }));
                // Clear badge locally
                const badge = this.threadListEl.querySelector(`[data-slug="${slug}"] .unread-badge`);
                if (badge) badge.classList.remove('visible');
            });

            this.ws.addEventListener('message', (event) => {
                const payload = JSON.parse(event.data);
                if (payload.event === 'bootstrap') {
                    payload.messages.forEach(msg => this.appendMessage(msg));
                } else if (payload.event === 'message') {
                    this.appendMessage(payload.message);
                } else if (payload.event === 'read') {
                    // CS read event – not needed here
                } else if (payload.event === 'typing') {
                    // Optional: show guest typing
                } else if (payload.event === 'error') {
                    console.error('Chat error:', payload.detail);
                }
            });

            this.ws.addEventListener('close', () => {
                // Optionally indicate disconnected
            });
        }

        async send() {
            const text = this.inputEl?.value.trim();
            if (!text || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            this.ws.send(JSON.stringify({ action: 'message', message: text }));
            this.inputEl.value = '';
        }

        async handleFile(event) {
            const file = event.target.files[0];
            if (!file) return;
            if (file.size > 2 * 1024 * 1024) {
                alert('File must be ≤ 2 MB');
                return;
            }
            const allowedMimes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf', 'text/plain', 'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
            if (!allowedMimes.includes(file.type)) {
                alert('File type not allowed');
                return;
            }
            const base64 = await fileToBase64(file);
            this.ws.send(JSON.stringify({
                action: 'file',
                file_name: file.name,
                mime_type: file.type,
                file_data: base64,
            }));
            this.fileInput.value = '';
        }

        appendMessage(msg) {
            const div = document.createElement('div');
            div.className = 'chat-message';
            if (msg.sender_role === 'guest') div.classList.add('is-self');

            const bubble = document.createElement('div');
            bubble.className = 'chat-bubble';

            if (msg.attachment && msg.attachment.url) {
                const a = document.createElement('a');
                a.href = msg.attachment.url;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = `📎 ${msg.attachment.name || 'Attachment'}`;
                bubble.appendChild(a);
            }
            if (msg.content) {
                const txt = document.createElement('div');
                txt.textContent = msg.content;
                bubble.appendChild(txt);
            }

            const time = document.createElement('div');
            time.style.fontSize = '0.75em';
            time.style.color = '#666';
            time.style.marginTop = '4px';
            time.textContent = formatTime(msg.created_at);

            div.appendChild(bubble);
            div.appendChild(time);
            this.messagesEl.appendChild(div);
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }
    }

    // Init ---------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        const root = document.querySelector('[data-role]');
        if (!root) return;
        const role = root.dataset.role;
        if (role === 'guest') {
            new GuestWidget(root);
        } else if (role === 'cs') {
            new CsDashboard(root);
        } else {
            console.warn('Unknown chat role:', role);
        }
    });
})();