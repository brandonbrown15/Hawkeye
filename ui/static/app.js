(() => {
  const token = window.__AUTOCODE_TOKEN__ || "";
  const toastEl = document.getElementById("toast");
  let toastTimer = null;
  let currentBoard = "hawkeye";
  let boardCache = null;
  let selectedTask = null;

  const BUILD_STATUSES = ["Ready", "Running", "Needs review", "Blocked", "Backlog", "Done"];
  const ROSE_STATUSES = ["Now", "Next", "Blocked", "Done", "Parked"];

  function toast(msg) {
    toastEl.textContent = msg || "";
    clearTimeout(toastTimer);
    if (msg) toastTimer = setTimeout(() => { toastEl.textContent = ""; }, 4000);
  }

  async function get(path) {
    const r = await fetch(path, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("login required");
    }
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Autocode-Token": token,
      },
      body: JSON.stringify({ ...body, token }),
    });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("login required");
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.error || `${path} → ${r.status}`);
    return data;
  }

  function ageLabel(sec) {
    if (sec == null) return "n/a";
    if (sec < 5) return "just now";
    if (sec < 60) return `${Math.floor(sec)}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    return `${Math.floor(sec / 3600)}h ago`;
  }

  function phaseSentence(snap) {
    const st = snap.status || {};
    const ctl = snap.control || {};
    if (ctl.abort) return "Abort requested — finishing the current step, then stopping.";
    if (ctl.paused || st.phase === "paused") return "Paused. Hit Resume when you want it to continue.";
    if (snap.stuck) return "Heartbeat is stale while a task is running — it may be stuck.";
    switch (st.phase) {
      case "idle":
        return "Idle. Hawkeye drains Ready Notion tasks for the team. Add work on the board or ask in chat.";
      case "starting":
        return "Work cycle is starting…";
      case "routing":
        return `Choosing a route for ${st.task_id || "the next task"}…`;
      case "running_local":
        return `Local model is working on ${st.task_name || st.task_id || "a task"}.`;
      case "escalating":
        return `Escalating ${st.task_id || "a task"} to ${st.route || "cloud / human"}.`;
      case "done":
        return "Cycle finished.";
      case "aborted":
        return "Cycle aborted.";
      default:
        return st.detail || `Phase: ${st.phase || "unknown"}`;
    }
  }

  function renderStatus(snap) {
    const st = snap.status || {};
    const ctl = snap.control || {};
    let phase = st.phase || "idle";
    let label = phase;
    if (ctl.abort) { phase = "aborted"; label = "aborting"; }
    else if (ctl.paused) { phase = "paused"; label = "paused"; }
    document.getElementById("liveChip").dataset.phase = phase;
    document.getElementById("phaseLabel").textContent = label;
    document.getElementById("statusLede").textContent = phaseSentence(snap);
    document.getElementById("taskVal").textContent =
      [st.task_id, st.task_name].filter(Boolean).join(" — ") || "—";
    document.getElementById("routeVal").textContent = st.route || "—";
    document.getElementById("hbVal").textContent = ageLabel(snap.heartbeat_age_sec);
    document.getElementById("stuckVal").textContent = snap.stuck ? "YES" : "no";
  }

  function renderReady(data) {
    const ul = document.getElementById("checks");
    if (!ul) return;
    ul.innerHTML = "";
    for (const c of data.checks || []) {
      const li = document.createElement("li");
      const badge = document.createElement("span");
      badge.className = `badge ${c.ok ? "ok" : c.optional ? "warn" : "fail"}`;
      badge.textContent = c.ok ? "ok" : c.optional ? "skip" : "need";
      const label = document.createElement("span");
      label.textContent = c.label;
      const hint = document.createElement("span");
      hint.className = "hint";
      hint.textContent = c.ok ? "" : (c.hint || "");
      li.append(badge, label, hint);
      ul.appendChild(li);
    }
    const bits = [
      data.ready ? "Core stack looks ready" : "Finish the red checklist items",
      `product=${data.product || "Hawkeye"}`,
      data.private_mode ? "login ON" : null,
      data.autopilot ? "autopilot ON" : "autopilot off",
    ].filter(Boolean);
    const readyMeta = document.getElementById("readyMeta");
    if (readyMeta) readyMeta.textContent = bits.join(" · ");
  }

  function renderLogs(data) {
    const path = document.getElementById("logPath");
    const text = document.getElementById("logText");
    if (path) path.textContent = data.path || "";
    if (text) text.textContent = data.text || "(empty)";
  }

  function columnOrder(boardKind, counts) {
    const preferred = boardKind === "projects" ? ROSE_STATUSES : BUILD_STATUSES;
    const keys = Object.keys(counts || {});
    const ordered = preferred.filter((s) => keys.includes(s) || preferred.includes(s));
    for (const k of keys) {
      if (!ordered.includes(k)) ordered.push(k);
    }
    // Always show core columns even if empty
    for (const s of preferred.slice(0, 4)) {
      if (!ordered.includes(s)) ordered.push(s);
    }
    return ordered;
  }

  function renderBoardTabs(boards) {
    const tabs = document.getElementById("boardTabs");
    if (!tabs) return;
    tabs.innerHTML = "";
    for (const b of boards || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "board-tab";
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-selected", b.id === currentBoard ? "true" : "false");
      btn.textContent = b.name;
      btn.dataset.board = b.id;
      btn.addEventListener("click", () => {
        currentBoard = b.id;
        loadBoard();
      });
      tabs.appendChild(btn);
    }
  }

  function renderKanban(data) {
    const board = data.board || {};
    const tasks = data.tasks || [];
    const counts = data.counts || {};
    const filter = document.getElementById("statusFilter").value || "all";
    const visible = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

    const meta = document.getElementById("boardMeta");
    const bits = [
      `${visible.length} task${visible.length === 1 ? "" : "s"}`,
      board.name || currentBoard,
      data.mock || data.offline ? "sample / offline data" : "live from Notion",
    ];
    if (data.warning) bits.push(data.warning);
    meta.textContent = bits.join(" · ");

    const banner = document.getElementById("pmBanner");
    if (data.offline || data.warning) {
      banner.hidden = false;
      banner.textContent = data.warning
        || "Notion token not connected on this machine — showing sample board. Connect with ./scripts/connect_notion.sh for live team data.";
    } else {
      banner.hidden = true;
    }

    const pills = document.getElementById("countPills");
    pills.innerHTML = "";
    for (const [status, n] of Object.entries(counts)) {
      const span = document.createElement("span");
      span.className = "count-pill";
      span.textContent = `${status}: ${n}`;
      pills.appendChild(span);
    }

    const kanban = document.getElementById("kanban");
    kanban.innerHTML = "";
    const cols = filter === "all"
      ? columnOrder(board.kind, counts)
      : [filter];

    for (const status of cols) {
      const colTasks = visible.filter((t) => (t.status || "Unknown") === status);
      const col = document.createElement("div");
      col.className = "kanban-col";
      const h = document.createElement("h3");
      h.innerHTML = `${status}<span class="col-count">${colTasks.length}</span>`;
      col.appendChild(h);
      for (const t of colTasks) {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "task-card";
        card.innerHTML = `
          <p class="tid">${t.task_id || "—"}</p>
          <p class="tname"></p>
          <div class="tmeta"></div>
        `;
        card.querySelector(".tname").textContent = t.name || "(untitled)";
        const metaEl = card.querySelector(".tmeta");
        if (t.priority) {
          const c = document.createElement("span");
          c.className = `chip ${(t.priority || "").toLowerCase()}`;
          c.textContent = t.priority;
          metaEl.appendChild(c);
        }
        if (t.area) {
          const c = document.createElement("span");
          c.className = "chip";
          c.textContent = t.area;
          metaEl.appendChild(c);
        }
        if (t.complexity) {
          const c = document.createElement("span");
          c.className = "chip";
          c.textContent = t.complexity;
          metaEl.appendChild(c);
        }
        card.addEventListener("click", () => openDrawer(t, board.kind));
        col.appendChild(card);
      }
      if (!colTasks.length) {
        const empty = document.createElement("p");
        empty.className = "section-note";
        empty.textContent = "No tasks";
        col.appendChild(empty);
      }
      kanban.appendChild(col);
    }
  }

  function openDrawer(task, boardKind) {
    selectedTask = task;
    const drawer = document.getElementById("taskDrawer");
    drawer.hidden = false;
    document.getElementById("drawerId").textContent = task.task_id || task.page_id;
    document.getElementById("drawerTitle").textContent = task.name || "(untitled)";
    document.getElementById("drawerAccept").textContent = task.acceptance || "";
    document.getElementById("drawerNotes").textContent = task.notes || "";
    const meta = document.getElementById("drawerMeta");
    meta.innerHTML = "";
    const rows = [
      ["Status", task.status],
      ["Priority", task.priority],
      ["Area", task.area],
      ["Complexity", task.complexity],
      ["Route", task.model_route],
    ];
    for (const [k, v] of rows) {
      if (!v) continue;
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v;
      meta.append(dt, dd);
    }
    const sel = document.getElementById("drawerStatus");
    const options = boardKind === "projects" ? ROSE_STATUSES : BUILD_STATUSES;
    sel.innerHTML = options.map((s) => `<option value="${s}">${s}</option>`).join("");
    sel.value = options.includes(task.status) ? task.status : options[0];
    const link = document.getElementById("drawerNotion");
    if (task.url) {
      link.href = task.url;
      link.hidden = false;
    } else {
      link.hidden = true;
    }
  }

  function closeDrawer() {
    document.getElementById("taskDrawer").hidden = true;
    selectedTask = null;
  }

  async function loadBoard() {
    const status = document.getElementById("statusFilter").value || "all";
    const data = await get(`/api/tasks?board=${encodeURIComponent(currentBoard)}&status=${encodeURIComponent(status)}&limit=100`);
    boardCache = data;
    renderKanban(data);
    // Sync tab selection
    document.querySelectorAll(".board-tab").forEach((btn) => {
      btn.setAttribute("aria-selected", btn.dataset.board === currentBoard ? "true" : "false");
    });
  }

  async function loadProjects() {
    const data = await get("/api/projects");
    renderBoardTabs(data.boards || data.projects || []);
    if (!currentBoard && data.boards && data.boards[0]) currentBoard = data.boards[0].id;
    await loadBoard();
  }

  async function loadInbox() {
    const list = document.getElementById("inboxList");
    const note = document.getElementById("inboxNote");
    if (!list) return;
    try {
      const data = await get("/api/mail?limit=30");
      if (note) {
        note.textContent = data.enabled
          ? "Inbox live — drafts stay local until you hit Send."
          : "Mail is off. Set HAWKEYE_MAIL_ENABLED=1 + Resend keys to connect receiving.";
      }
      list.innerHTML = "";
      const messages = data.messages || [];
      if (!messages.length) {
        const empty = document.createElement("p");
        empty.className = "inbox-empty";
        empty.textContent = data.enabled
          ? "No messages yet."
          : "Enable mail in .env, then point Resend webhook to /api/webhooks/resend.";
        list.appendChild(empty);
        return;
      }
      for (const msg of messages) {
        list.appendChild(renderMailItem(msg));
      }
    } catch (e) {
      list.innerHTML = "";
      const err = document.createElement("p");
      err.className = "inbox-empty";
      err.textContent = String(e.message || e);
      list.appendChild(err);
    }
  }

  function renderMailItem(msg) {
    const wrap = document.createElement("article");
    wrap.className = "inbox-item";
    wrap.dataset.id = msg.id;

    const meta = document.createElement("div");
    meta.className = "inbox-meta";
    meta.textContent = `${msg.status} · from ${msg.from_addr || "?"} · ${new Date((msg.received_at || 0) * 1000).toLocaleString()}`;

    const subject = document.createElement("h3");
    subject.className = "inbox-subject";
    subject.textContent = msg.subject || "(no subject)";

    const body = document.createElement("p");
    body.className = "inbox-body";
    body.textContent = (msg.body || msg.reject_reason || "").slice(0, 600);

    wrap.append(meta, subject, body);

    if (msg.draft) {
      const draft = document.createElement("p");
      draft.className = "inbox-draft";
      draft.textContent = msg.draft.slice(0, 800);
      wrap.appendChild(draft);
    }

    if (msg.status !== "rejected" && msg.status !== "ignored" && msg.status !== "sent") {
      const actions = document.createElement("div");
      actions.className = "inbox-actions";
      const draftBtn = document.createElement("button");
      draftBtn.type = "button";
      draftBtn.className = "btn compact";
      draftBtn.textContent = msg.draft ? "Redraft" : "Draft reply";
      draftBtn.addEventListener("click", async () => {
        draftBtn.disabled = true;
        try {
          await post(`/api/mail/${encodeURIComponent(msg.id)}/draft`, {});
          toast("Draft ready");
          await loadInbox();
        } catch (e) {
          toast(String(e.message || e));
        } finally {
          draftBtn.disabled = false;
        }
      });
      const sendBtn = document.createElement("button");
      sendBtn.type = "button";
      sendBtn.className = "btn primary compact";
      sendBtn.textContent = "Send reply";
      sendBtn.disabled = !msg.draft;
      sendBtn.addEventListener("click", async () => {
        if (!confirm("Send this reply via Resend?")) return;
        sendBtn.disabled = true;
        try {
          await post(`/api/mail/${encodeURIComponent(msg.id)}/send`, {});
          toast("Reply sent");
          await loadInbox();
        } catch (e) {
          toast(String(e.message || e));
        } finally {
          sendBtn.disabled = false;
        }
      });
      const ignoreBtn = document.createElement("button");
      ignoreBtn.type = "button";
      ignoreBtn.className = "btn ghost compact";
      ignoreBtn.textContent = "Ignore";
      ignoreBtn.addEventListener("click", async () => {
        try {
          await post(`/api/mail/${encodeURIComponent(msg.id)}/ignore`, {});
          await loadInbox();
        } catch (e) {
          toast(String(e.message || e));
        }
      });
      actions.append(draftBtn, sendBtn, ignoreBtn);
      wrap.appendChild(actions);
    }
    return wrap;
  }

  async function refreshOps() {
    const [snap, ready, logs, demo, work] = await Promise.all([
      get("/api/status"),
      get("/api/ready"),
      get("/api/logs"),
      get("/api/demo"),
      get("/api/work"),
    ]);
    renderStatus(snap);
    renderReady(ready);
    renderLogs(logs);
    const demoBtn = document.getElementById("demoBtn");
    const workBtn = document.getElementById("workBtn");
    if (demoBtn) {
      demoBtn.disabled = !!demo.running || !!work.running;
      demoBtn.textContent = demo.running ? "Mock cycle running…" : "Run mock cycle";
    }
    if (workBtn) {
      workBtn.disabled = !!work.running || !!demo.running;
      workBtn.textContent = work.running ? "Work cycle running…" : "Run work cycle";
    }
  }

  document.getElementById("statusFilter").addEventListener("change", () => {
    loadBoard().catch((e) => toast(String(e.message || e)));
  });
  document.getElementById("refreshBoard").addEventListener("click", () => {
    loadBoard().then(() => toast("Board refreshed")).catch((e) => toast(String(e.message || e)));
  });
  document.getElementById("drawerClose").addEventListener("click", closeDrawer);
  document.getElementById("taskDrawer").addEventListener("click", (ev) => {
    if (ev.target.id === "taskDrawer") closeDrawer();
  });
  document.getElementById("drawerSave").addEventListener("click", async () => {
    if (!selectedTask) return;
    const status = document.getElementById("drawerStatus").value;
    try {
      await post(`/api/tasks/${encodeURIComponent(selectedTask.page_id)}`, { status });
      toast(`Moved to ${status}`);
      closeDrawer();
      await loadBoard();
    } catch (e) {
      toast(String(e.message || e));
    }
  });

  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.getAttribute("data-action");
      btn.disabled = true;
      try {
        await post("/api/control", { action });
        toast(`${action} sent`);
        await refreshOps();
      } catch (e) {
        toast(String(e.message || e));
      } finally {
        btn.disabled = false;
      }
    });
  });

  const skipForm = document.getElementById("skipForm");
  if (skipForm) {
    skipForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const task_id = document.getElementById("skipId").value.trim();
      if (!task_id) return toast("Enter a task id");
      try {
        await post("/api/control", { action: "skip", task_id });
        toast(`Will skip ${task_id}`);
        await refreshOps();
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  const demoBtn = document.getElementById("demoBtn");
  if (demoBtn) {
    demoBtn.addEventListener("click", async () => {
      demoBtn.disabled = true;
      try {
        await post("/api/demo", {});
        toast("Mock cycle started");
        await refreshOps();
      } catch (e) {
        toast(String(e.message || e));
        demoBtn.disabled = false;
      }
    });
  }

  const workBtnEl = document.getElementById("workBtn");
  if (workBtnEl) {
    workBtnEl.addEventListener("click", async () => {
      workBtnEl.disabled = true;
      try {
        await post("/api/work", { force: true });
        toast("Work cycle started");
        await refreshOps();
      } catch (e) {
        toast(String(e.message || e));
        workBtnEl.disabled = false;
      }
    });
  }

  function appendChat(role, text) {
    const log = document.getElementById("chatLog");
    if (!log) return;
    const line = document.createElement("div");
    line.className = `chat-line ${role}`;
    const who = role === "you" ? "You" : role === "local" ? "Hawkeye" : role === "cloud" ? "Cloud" : "System";
    line.textContent = `${who}: ${text}`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  const chatForm = document.getElementById("chatForm");
  if (chatForm) {
    chatForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const input = document.getElementById("chatInput");
      const seed = document.getElementById("chatSeed");
      const msg = (input.value || "").trim();
      if (!msg) return;
      const sendBtn = document.getElementById("chatSend");
      sendBtn.disabled = true;
      appendChat("you", msg);
      input.value = "";
      try {
        const data = await post("/api/chat", {
          message: msg,
          seed_notion: !!(seed && seed.checked),
        });
        if (data.local_reply) appendChat("local", data.local_reply);
        if (data.escalated && data.cloud_reply) appendChat("cloud", `[${data.provider || "cloud"}] ${data.cloud_reply}`);
        if (data.seeded_task) {
          appendChat("system", `Added to Notion: ${data.seeded_task}`);
          loadBoard().catch(() => {});
        }
        toast(data.escalated ? `Escalated to ${data.provider || "premium"}` : "Hawkeye replied");
      } catch (e) {
        appendChat("system", String(e.message || e));
        toast(String(e.message || e));
      } finally {
        sendBtn.disabled = false;
      }
    });
  }

  loadProjects().catch((e) => toast(String(e.message || e)));
  refreshOps().catch((e) => toast(String(e.message || e)));
  loadInbox().catch(() => {});
  setInterval(() => { refreshOps().catch(() => {}); }, 4000);
  setInterval(() => { loadBoard().catch(() => {}); }, 20000);
  setInterval(() => { loadInbox().catch(() => {}); }, 30000);

  const inboxRefresh = document.getElementById("inboxRefresh");
  if (inboxRefresh) {
    inboxRefresh.addEventListener("click", () => {
      loadInbox().catch((e) => toast(String(e.message || e)));
    });
  }

  get("/api/auth")
    .then((auth) => {
      const btn = document.getElementById("logoutBtn");
      if (btn && auth.private_mode) {
        btn.hidden = false;
        btn.addEventListener("click", async () => {
          try {
            await fetch("/api/logout", {
              method: "POST",
              credentials: "same-origin",
              headers: { "Content-Type": "application/json", "X-Autocode-Token": token },
              body: JSON.stringify({ token }),
            });
          } catch (_) { /* still leave */ }
          location.href = "/login";
        });
      }
    })
    .catch(() => {});
})();
