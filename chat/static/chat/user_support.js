(() => {
    const WS_PROTOCOL = window.location.protocol === "https:" ? "wss" : "ws";

    const formatTime = (iso) => {
        if (!iso) return "";
        const d = new Date(iso);
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    };

    const buildUrl = (template, threadId, messageId) => {
        if (!template) return "";
        let url = template;
        if (threadId) {
            url = url.replace("/0/", `/${threadId}/`);
        }
        if (typeof messageId !== "undefined") {
            url = url.replace("/0/", `/${messageId}/`);
        }
        return url;
    };

    class SupportPortal {
        constructor(root) {
            this.root = root;
            this.role = root.dataset.role;
            this.threadId = root.dataset.threadId || null;
            this.wsBase = root.dataset.wsBase || "/ws/support/";
            this.bootstrapUrl = root.dataset.bootstrapUrl || "";
            this.threadUrlTemplate = root.dataset.threadUrlTemplate || "";
            this.sendUrlTemplate = root.dataset.sendUrlTemplate || "";
            this.readUrlTemplate = root.dataset.readUrlTemplate || "";
            this.csThreadListUrl = root.dataset.csThreadListUrl || "";
        this.uploadUrlTemplate = root.dataset.uploadUrlTemplate || "";
        this.deleteUrlTemplate = root.dataset.deleteUrlTemplate || "";

            this.messagesEl = root.querySelector("[data-messages]");
            this.inputEl = root.querySelector("[data-chat-input]");
            this.sendBtn = root.querySelector("[data-send-button]");
            this.participantNameEl = root.querySelector("[data-participant-name]");
            this.participantStatusEl = root.querySelector("[data-participant-status]");
            this.avatarEl = root.querySelector("[data-avatar]");
            this.unreadPillEl = root.querySelector("[data-unread-pill]");
            this.threadListEl = root.querySelector("[data-thread-list]");
            this.refreshBtn = root.querySelector("[data-refresh-threads]");

            this.ws = null;
            this.currentThread = null;
            this.isAutoScroll = true;

            this.bindEvents();
            this.init();
        }

        canDeleteMessages() {
            return this.role === "customerservice";
        }

        getMaxUploadBytes() {
            return 3 * 1024 * 1024;
        }

        bindEvents() {
            this.sendBtn?.addEventListener("click", () => this.sendMessage());
            this.inputEl?.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
            this.inputEl?.addEventListener("input", () => {
                this.sendBtn.disabled = !this.inputEl.value.trim() || !this.threadId;
            });
            this.messagesEl?.addEventListener("scroll", () => {
                const nearBottom =
                    this.messagesEl.scrollHeight - this.messagesEl.scrollTop - this.messagesEl.clientHeight < 40;
                this.isAutoScroll = nearBottom;
                if (nearBottom && this.threadId) {
                    this.markRead();
                }
            });
            this.refreshBtn?.addEventListener("click", () => this.fetchThreadList());
            this.attachBtn = this.root.querySelector("[data-attachment-trigger]");
            this.attachmentInput = this.root.querySelector("[data-attachment-input]");
            this.attachBtn?.addEventListener("click", () => this.attachmentInput?.click());
            this.attachmentInput?.addEventListener("change", (event) => this.handleAttachmentUpload(event));
        }

        init() {
            if (this.role === "user") {
                this.bootstrapUser();
            } else if (this.role === "customerservice") {
                this.fetchThreadList();
                this.setComposerEnabled(false);
            }
        }

        setComposerEnabled(enabled) {
            if (this.inputEl) {
                this.inputEl.disabled = !enabled;
                if (!enabled) {
                    this.inputEl.value = "";
                }
            }
            if (this.sendBtn) {
                this.sendBtn.disabled = !enabled;
            }
        }

        async bootstrapUser() {
            if (!this.bootstrapUrl) return;
            try {
                const resp = await fetch(this.bootstrapUrl, { credentials: "same-origin" });
                if (!resp.ok) throw new Error("Bootstrap failed");
                const data = await resp.json();
                this.threadId = data.thread?.id;
                this.currentThread = data.thread;
                this.renderParticipant(data.thread);
                this.renderMessages(data.messages || []);
                this.openWebSocket();
                this.markRead();
                this.setComposerEnabled(true);
            } catch (err) {
                console.error("Bootstrap error:", err);
            }
        }

        async fetchThreadList() {
            if (!this.csThreadListUrl) return;
            try {
                const resp = await fetch(this.csThreadListUrl, { credentials: "same-origin" });
                if (!resp.ok) throw new Error("Thread list failed");
                const data = await resp.json();
                this.renderThreadList(data.threads || []);
            } catch (err) {
                console.error("Thread list error:", err);
            }
        }

        renderThreadList(threads) {
            if (!this.threadListEl) return;
            if (!threads.length) {
                this.threadListEl.innerHTML = `<div class="p-4 text-center text-muted small">No active chats</div>`;
                this.threadId = null;
                this.renderMessages([]);
                this.setComposerEnabled(false);
                this.closeWebSocket();
                return;
            }
            this.threadListEl.innerHTML = threads
                .map(
                    (thread) => `
                <div class="support-thread" data-thread-id="${thread.id}">
                    <div>
                        <h4>${thread.user?.display_name || "User #" + thread.user_id}</h4>
                        <small>${thread.last_activity ? formatTime(thread.last_activity) : "—"}</small>
                    </div>
                    ${
                        thread.agent_unread_count
                            ? `<span class="badge">${thread.agent_unread_count}</span>`
                            : ""
                    }
                </div>
            `
                )
                .join("");

            this.threadListEl.querySelectorAll(".support-thread").forEach((el) => {
                el.addEventListener("click", () => {
                    const id = el.getAttribute("data-thread-id");
                    this.openSupportThread(id, threads.find((t) => String(t.id) === String(id)));
                    this.threadListEl.querySelectorAll(".support-thread").forEach((node) =>
                        node.classList.remove("is-active")
                    );
                    el.classList.add("is-active");
                });
            });
        }

        async openSupportThread(threadId, threadData) {
            if (!threadId) return;
            this.threadId = threadId;
            this.currentThread = threadData || null;
            this.setComposerEnabled(true);
            await this.fetchThreadMessages(threadId);
            this.openWebSocket();
            this.markRead();
        }

        async fetchThreadMessages(threadId) {
            if (!this.threadUrlTemplate || !threadId) return;
            const url = buildUrl(this.threadUrlTemplate, threadId);
            try {
                const resp = await fetch(url, { credentials: "same-origin" });
                if (!resp.ok) throw new Error("Failed to load messages");
                const data = await resp.json();
                this.currentThread = data.thread;
                this.renderParticipant(data.thread);
                this.renderMessages(data.messages || []);
            } catch (err) {
                console.error("Fetch messages error:", err);
                this.renderMessages([]);
            }
        }

        renderParticipant(thread) {
            if (!thread) return;
            if (this.role === "user") {
                const agentName = thread.assigned_agent?.display_name || "Customer Service";
                if (this.participantNameEl) this.participantNameEl.textContent = agentName;
                if (this.participantStatusEl) this.participantStatusEl.textContent = "Online";
                if (this.avatarEl) this.avatarEl.textContent = agentName?.slice(0, 2).toUpperCase();
            } else {
                const userName = thread.user?.display_name || `User #${thread.user_id}`;
                if (this.participantNameEl) this.participantNameEl.textContent = userName;
                if (this.participantStatusEl) this.participantStatusEl.textContent = "Active";
                if (this.avatarEl) this.avatarEl.textContent = userName?.slice(0, 2).toUpperCase();
            }
        }

        renderMessages(messages) {
            if (!this.messagesEl) return;
            if (!messages.length) {
                this.messagesEl.innerHTML = `
                    <div class="empty-state">
                        ${this.role === "user" ? "No messages yet." : "Select a user to start chatting."}
                    </div>`;
                return;
            }

            this.messagesEl.innerHTML = "";
            messages.forEach((msg) => this.appendMessage(msg));
            this.scrollMessagesToBottom(true);
        }

        appendMessage(msg) {
            if (!this.messagesEl) return;
            const wrapper = document.createElement("div");
            wrapper.classList.add("message-row");
            wrapper.dataset.messageId = msg.id;
            const senderIsUser = msg.sender_role === "user";
            if ((this.role === "user" && senderIsUser) || (this.role === "customerservice" && !senderIsUser)) {
                wrapper.classList.add("is-self");
            }

            const bubble = document.createElement("div");
            bubble.classList.add("message-bubble");
            if (msg.content) {
                const text = document.createElement("div");
                text.textContent = msg.content;
                bubble.appendChild(text);
            }
            if (msg.attachment && msg.attachment.url) {
                bubble.appendChild(this.buildAttachmentElement(msg.attachment));
            }

            if (this.canDeleteMessages()) {
                const actions = document.createElement("div");
                actions.classList.add("message-actions");
                const deleteBtn = document.createElement("button");
                deleteBtn.type = "button";
                deleteBtn.classList.add("message-delete-btn");
                deleteBtn.innerHTML = "&times;";
                deleteBtn.addEventListener("click", (event) => {
                    event.stopPropagation();
                    this.deleteMessage(msg.id);
                });
                actions.appendChild(deleteBtn);
                bubble.appendChild(actions);
            }

            const meta = document.createElement("div");
            meta.classList.add("message-meta");
            meta.textContent = formatTime(msg.created_at);

            wrapper.appendChild(bubble);
            wrapper.appendChild(meta);
            this.messagesEl.appendChild(wrapper);
            this.scrollMessagesToBottom(false);
        }

        buildAttachmentElement(attachment) {
            const wrapper = document.createElement("div");
            wrapper.classList.add("message-attachment");
            if (!attachment?.url) {
                return wrapper;
            }

            const mime = (attachment.mime_type || "").toLowerCase();
            if (mime.startsWith("image/")) {
                const img = document.createElement("img");
                img.src = attachment.url;
                img.alt = attachment.name || "Image attachment";
                img.loading = "lazy";
                wrapper.appendChild(img);
            } else if (mime.startsWith("audio/")) {
                const audio = document.createElement("audio");
                audio.controls = true;
                audio.src = attachment.url;
                audio.preload = "none";
                wrapper.appendChild(audio);
            } else if (mime.startsWith("video/")) {
                const video = document.createElement("video");
                video.controls = true;
                video.src = attachment.url;
                video.preload = "metadata";
                wrapper.appendChild(video);
            } else {
                const link = document.createElement("a");
                link.href = attachment.url;
                link.target = "_blank";
                link.rel = "noopener noreferrer";
                link.textContent = attachment.name || "Attachment";
                wrapper.appendChild(link);
            }
            return wrapper;
        }

        removeMessage(messageId) {
            if (!messageId || !this.messagesEl) return;
            const target = this.messagesEl.querySelector(`[data-message-id="${messageId}"]`);
            if (target) {
                target.remove();
            }
        }

        scrollMessagesToBottom(force) {
            if (!this.messagesEl) return;
            if (force || this.isAutoScroll) {
                this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
            }
        }

        async sendMessage() {
            if (!this.threadId || !this.inputEl) return;
            const text = this.inputEl.value.trim();
            if (!text) return;

            const url = buildUrl(this.sendUrlTemplate, this.threadId);

            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": this.getCsrfToken(),
                    },
                    body: JSON.stringify({ message: text }),
                    credentials: "same-origin",
                });
                if (!resp.ok) {
                    console.error("Send failed");
                    return;
                }
                this.inputEl.value = "";
                this.sendBtn.disabled = true;
            } catch (err) {
                console.error("Send error:", err);
            }
        }

        async markRead() {
            if (!this.threadId || !this.readUrlTemplate) return;
            const url = buildUrl(this.readUrlTemplate, this.threadId);
            try {
                await fetch(url, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": this.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });
            } catch (err) {
                console.error("Read error:", err);
            }
        }

        getCsrfToken() {
            const match = document.cookie.match(/csrftoken=([^;]+)/);
            return match ? match[1] : "";
        }

        async handleAttachmentUpload(event) {
            const file = event.target.files?.[0];
            if (!file) return;
            if (!this.threadId) {
                this.attachmentInput.value = "";
                return;
            }
            if (file.size > this.getMaxUploadBytes()) {
                alert("File must be ≤ 3 MB");
                this.attachmentInput.value = "";
                return;
            }
            const allowedPrefixes = ["image/", "video/", "audio/"];
            if (file.type && !allowedPrefixes.some((prefix) => file.type.startsWith(prefix))) {
                alert("Only image, video, or audio files are allowed.");
                this.attachmentInput.value = "";
                return;
            }

            const url = buildUrl(this.uploadUrlTemplate, this.threadId);
            const formData = new FormData();
            formData.append("attachment", file);

            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": this.getCsrfToken(),
                    },
                    body: formData,
                    credentials: "same-origin",
                });
                if (!resp.ok) {
                    console.error("Attachment upload failed");
                }
            } catch (err) {
                console.error("Attachment upload error:", err);
            } finally {
                this.attachmentInput.value = "";
            }
        }

        async deleteMessage(messageId) {
            if (!this.canDeleteMessages() || !this.threadId || !messageId) return;
            const confirmed = window.confirm("Delete this message for everyone?");
            if (!confirmed) return;
            const url = buildUrl(this.deleteUrlTemplate, this.threadId, messageId);
            try {
                const resp = await fetch(url, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": this.getCsrfToken(),
                    },
                    credentials: "same-origin",
                });
                if (!resp.ok) {
                    console.error("Failed to delete message");
                    return;
                }

                const data = await resp.json().catch(() => ({}));
                const removedId = data.deleted_message_id || messageId;
                this.removeMessage(removedId);
            } catch (err) {
                console.error("Delete message error:", err);
            }
        }

        openWebSocket() {
            if (!this.threadId) return;
            this.closeWebSocket();
            const url = `${WS_PROTOCOL}://${window.location.host}${this.wsBase}${this.threadId}/`;
            this.ws = new WebSocket(url);

            this.ws.addEventListener("message", (event) => {
                const payload = JSON.parse(event.data);
                if (payload.event === "message") {
                    this.appendMessage(payload.message);
                } else if (payload.event === "read") {
                    if (this.unreadPillEl) {
                        this.unreadPillEl.textContent = "";
                    }
                } else if (payload.event === "delete") {
                    this.removeMessage(payload.message_id);
                }
            });

            this.ws.addEventListener("open", () => {
                this.markRead();
            });

            this.ws.addEventListener("close", () => {
                this.ws = null;
            });
        }

        closeWebSocket() {
            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector(".support-shell");
        if (!root) return;
        new SupportPortal(root);
    });
})();
