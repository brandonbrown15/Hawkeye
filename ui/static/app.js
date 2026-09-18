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
        || "Notion token not connected — showing sample board. Add Notion under Account → Connections for live team data.";
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
  setInterval(() => { refreshOps().catch(() => {}); }, 4000);
  setInterval(() => { loadBoard().catch(() => {}); }, 20000);

  let currentUser = null;
  let dmThreadId = null;
  let coworkers = [];

  function openAccount(tab) {
    const dlg = document.getElementById("accountDialog");
    if (!dlg) return;
    if (tab) switchAccountTab(tab);
    if (typeof dlg.showModal === "function") dlg.showModal();
    loadAccountData().catch((e) => toast(String(e.message || e)));
  }

  function switchAccountTab(tab) {
    document.querySelectorAll(".account-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.tab === tab);
    });
    document.querySelectorAll(".account-pane").forEach((pane) => {
      pane.classList.toggle("is-active", pane.dataset.pane === tab);
    });
  }

  async function loadAccountData() {
    const [me, conns, projects, threads, users, machine] = await Promise.all([
      get("/api/me"),
      get("/api/connections"),
      get("/api/account/projects"),
      get("/api/messages/threads"),
      get("/api/users"),
      get("/api/machine").catch(() => null),
    ]);
    const profile = me.profile || {};
    currentUser = profile.email || currentUser;
    document.getElementById("profFirst").value = profile.first_name || "";
    document.getElementById("profLast").value = profile.last_name || "";
    document.getElementById("profEmp").value = profile.employee_number || "";
    document.getElementById("profEmail").textContent = profile.email || "";
    renderConnections(conns);
    renderMachine(machine);
    renderAccountProjects(projects.projects || []);
    renderMineProjects(projects.projects || []);
    coworkers = (users.users || []).filter((u) => u.email !== currentUser);
    renderDmStart(coworkers);
    renderDmThreads(threads);
    updateMsgBadge(threads.unread_total || 0);
  }

  function renderMachine(data) {
    const note = document.getElementById("machineStatusNote");
    const log = document.getElementById("machineLog");
    if (!data || !note) return;
    const auto = data.autostart || {};
    const bits = [
      data.tunnel_token_set ? "tunnel token set" : "tunnel token missing",
      data.encryption_ready ? "encryption ready" : "set memory key",
      auto.timer_active ? "update timer active" : "update timer inactive",
      auto.ui_active ? "UI service up" : "UI service down",
      `branch ${auto.update_branch || "?"}`,
    ];
    note.textContent = bits.join(" · ");
    if (auto.update_check) {
      log.hidden = false;
      log.textContent = auto.update_check;
    }
    const branch = document.getElementById("machBranch");
    const host = document.getElementById("machHost");
    const on = document.getElementById("machUpdateOn");
    if (branch && !branch.dataset.touched) branch.value = auto.update_branch || "";
    if (host && !host.dataset.touched) host.value = data.public_host || "";
    if (on) on.checked = !!auto.update_enabled;
    const tunnel = document.getElementById("machTunnel");
    if (tunnel) tunnel.placeholder = data.tunnel_token_set ? "(saved — enter to replace)" : "Paste Cloudflare install token";
    const mem = document.getElementById("machMemKey");
    if (mem) mem.placeholder = data.memory_key_set ? "(set — enter to rotate)" : "Long passphrase for encryption";
  }

  function renderConnections(data) {
    const note = document.getElementById("connEncryptNote");
    if (note) {
      note.textContent = data.encryption_ready
        ? "Secret encryption is on (HAWKEYE_MEMORY_KEY / HAWKEYE_SECRETS_KEY)."
        : "Set HAWKEYE_MEMORY_KEY under Account → Machine so connection secrets encrypt at rest.";
    }
    const list = document.getElementById("connectionsList");
    if (!list) return;
    list.innerHTML = "";
    const providers = data.providers || {};
    for (const id of Object.keys(providers)) {
      const p = providers[id];
      const card = document.createElement("article");
      card.className = "conn-card";
      const head = document.createElement("div");
      head.className = "conn-head";
      const statusClass =
        p.status === "connected" ? "on" : p.status === "machine" ? "machine" : "off";
      const statusLabel =
        p.status === "connected"
          ? "connected"
          : p.status === "machine"
            ? "machine .env"
            : "disconnected";
      head.innerHTML = `<strong>${p.label}</strong><span class="conn-status ${statusClass}">${statusLabel}</span>`;
      const hint = document.createElement("p");
      hint.className = "section-note";
      hint.textContent = p.hint || "";
      const fields = document.createElement("div");
      fields.className = "conn-fields";
      for (const field of p.fields || []) {
        const label = document.createElement("label");
        label.textContent = field;
        const input = document.createElement("input");
        input.type = "password";
        input.autocomplete = "off";
        input.dataset.field = field;
        input.placeholder = p.status === "connected" ? "(saved — enter to replace)" : "";
        fields.append(label, input);
      }
      const labelIn = document.createElement("input");
      labelIn.placeholder = "Account label (optional)";
      labelIn.value = p.account_label || "";
      fields.appendChild(labelIn);
      const actions = document.createElement("div");
      actions.className = "conn-actions";
      const save = document.createElement("button");
      save.type = "button";
      save.className = "btn primary compact";
      save.textContent = "Save connection";
      save.addEventListener("click", async () => {
        const secrets = {};
        fields.querySelectorAll("input[data-field]").forEach((inp) => {
          if (inp.value.trim()) secrets[inp.dataset.field] = inp.value.trim();
        });
        try {
          await post(`/api/connections/${encodeURIComponent(id)}`, {
            secrets,
            account_label: labelIn.value.trim(),
          });
          toast(`${p.label} connected for your account`);
          loadAccountData().catch(() => {});
        } catch (e) {
          toast(String(e.message || e));
        }
      });
      const disc = document.createElement("button");
      disc.type = "button";
      disc.className = "btn ghost compact";
      disc.textContent = "Disconnect";
      disc.disabled = p.status !== "connected";
      disc.addEventListener("click", async () => {
        try {
          await post(`/api/connections/${encodeURIComponent(id)}`, { action: "disconnect" });
          toast(`${p.label} disconnected`);
          loadAccountData().catch(() => {});
        } catch (e) {
          toast(String(e.message || e));
        }
      });
      actions.append(save, disc);
      card.append(head, hint, fields, actions);
      list.appendChild(card);
    }
  }

  function renderAccountProjects(projects) {
    const wrap = document.getElementById("accountProjects");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!projects.length) {
      wrap.textContent = "No projects yet.";
      return;
    }
    for (const p of projects) {
      wrap.appendChild(projectCard(p, true));
    }
  }

  function renderMineProjects(projects) {
    const wrap = document.getElementById("mineProjectsList");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!projects.length) {
      wrap.textContent = "No account projects yet. Create one under Account → Projects.";
      return;
    }
    for (const p of projects) wrap.appendChild(projectCard(p, false));
  }

  function projectCard(p, withShare) {
    const card = document.createElement("article");
    card.className = "proj-card";
    const head = document.createElement("div");
    head.className = "proj-head";
    head.innerHTML = `<strong>${p.name}</strong><span class="conn-status">${p.my_role || ""}</span>`;
    const meta = document.createElement("p");
    meta.className = "section-note";
    const names = (p.members || []).map((m) => m.display_name || m.email).join(", ");
    meta.textContent = `${p.description || "No description"} · Shared with: ${names || "you"}`;
    card.append(head, meta);
    if (withShare && p.my_role === "owner") {
      const actions = document.createElement("div");
      actions.className = "proj-actions";
      const sel = document.createElement("select");
      for (const u of coworkers) {
        const opt = document.createElement("option");
        opt.value = u.email;
        opt.textContent = `${u.display_name || u.email}`;
        sel.appendChild(opt);
      }
      const share = document.createElement("button");
      share.type = "button";
      share.className = "btn compact";
      share.textContent = "Share";
      share.addEventListener("click", async () => {
        if (!sel.value) return;
        try {
          await post(`/api/account/projects/${encodeURIComponent(p.id)}/share`, {
            email: sel.value,
            role: "editor",
          });
          toast(`Shared with ${sel.value}`);
          loadAccountData().catch(() => {});
        } catch (e) {
          toast(String(e.message || e));
        }
      });
      actions.append(sel, share);
      card.appendChild(actions);
    }
    return card;
  }

  function updateMsgBadge(n) {
    const badge = document.getElementById("msgBadge");
    if (!badge) return;
    if (n > 0) {
      badge.hidden = false;
      badge.textContent = String(n);
    } else {
      badge.hidden = true;
    }
  }

  function renderDmStart(users) {
    const sel = document.getElementById("dmCoworker");
    if (!sel) return;
    sel.innerHTML = "";
    for (const u of users) {
      const opt = document.createElement("option");
      opt.value = u.email;
      opt.textContent = u.display_name || u.email;
      sel.appendChild(opt);
    }
  }

  function renderDmThreads(data) {
    const wrap = document.getElementById("dmThreads");
    if (!wrap) return;
    wrap.innerHTML = "";
    for (const t of data.threads || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dm-thread-btn" + (t.thread_id === dmThreadId ? " is-active" : "");
      btn.textContent = `${t.with_name}${t.unread ? ` (${t.unread})` : ""}`;
      btn.addEventListener("click", () => openDmThread(t.thread_id, t.with_name));
      wrap.appendChild(btn);
    }
  }

  async function openDmThread(threadId, withName) {
    dmThreadId = threadId;
    document.getElementById("dmWith").textContent = withName || "Conversation";
    document.getElementById("dmForm").hidden = false;
    const data = await get(`/api/messages/threads/${encodeURIComponent(threadId)}`);
    const log = document.getElementById("dmLog");
    log.textContent = (data.messages || [])
      .map((m) => `${m.from === currentUser ? "You" : m.from}: ${m.body}`)
      .join("\n\n");
    await post(`/api/messages/threads/${encodeURIComponent(threadId)}/read`, {});
    const threads = await get("/api/messages/threads");
    renderDmThreads(threads);
    updateMsgBadge(threads.unread_total || 0);
  }

  document.querySelectorAll(".account-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchAccountTab(btn.dataset.tab));
  });

  document.querySelectorAll(".view-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-tab").forEach((b) => b.classList.toggle("is-active", b === btn));
      const mine = btn.dataset.view === "mine";
      document.getElementById("notionSummary").hidden = mine;
      document.getElementById("notionKanban").hidden = mine;
      document.getElementById("boardTabs").hidden = mine;
      document.getElementById("statusFilter").hidden = mine;
      document.getElementById("mineProjects").hidden = !mine;
      if (mine) {
        get("/api/account/projects").then((d) => renderMineProjects(d.projects || [])).catch((e) => toast(String(e.message || e)));
      }
    });
  });

  const profSave = document.getElementById("profSave");
  if (profSave) {
    profSave.addEventListener("click", async () => {
      try {
        await post("/api/me", {
          first_name: document.getElementById("profFirst").value,
          last_name: document.getElementById("profLast").value,
          employee_number: document.getElementById("profEmp").value,
        });
        toast("Profile saved");
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  ["machBranch", "machHost"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => { el.dataset.touched = "1"; });
  });

  const machSave = document.getElementById("machSave");
  if (machSave) {
    machSave.addEventListener("click", async () => {
      const body = {
        update_enabled: document.getElementById("machUpdateOn")?.checked ? "1" : "0",
        update_branch: document.getElementById("machBranch")?.value || "",
        public_host: document.getElementById("machHost")?.value || "",
        restart_tunnel: "1",
      };
      const tunnel = document.getElementById("machTunnel")?.value?.trim();
      const mem = document.getElementById("machMemKey")?.value?.trim();
      if (tunnel) body.tunnel_token = tunnel;
      if (mem) {
        body.memory_key = mem;
        if (document.getElementById("machForceMem")?.checked) body.force_memory_key = "1";
      }
      try {
        const out = await post("/api/machine", body);
        toast("Machine settings saved");
        if (document.getElementById("machTunnel")) document.getElementById("machTunnel").value = "";
        if (document.getElementById("machMemKey")) document.getElementById("machMemKey").value = "";
        renderMachine(out);
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  const machForce = document.getElementById("machForceUpdate");
  if (machForce) {
    machForce.addEventListener("click", async () => {
      try {
        toast("Pulling GitHub + refreshing UI…");
        const out = await post("/api/machine", { force_update: "1" });
        toast("Force update finished");
        renderMachine(out);
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  const newProjectForm = document.getElementById("newProjectForm");
  if (newProjectForm) {
    newProjectForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await post("/api/account/projects", {
          name: document.getElementById("newProjectName").value,
        });
        document.getElementById("newProjectName").value = "";
        toast("Project created");
        loadAccountData().catch(() => {});
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  const dmStartForm = document.getElementById("dmStartForm");
  if (dmStartForm) {
    dmStartForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const to = document.getElementById("dmCoworker").value;
      if (!to) return;
      // Create thread by sending an empty opener if none — require a first message via form.
      document.getElementById("dmForm").hidden = false;
      document.getElementById("dmWith").textContent = to;
      dmThreadId = null;
      window.__dmPendingTo = to;
      document.getElementById("dmLog").textContent = "(new conversation — send the first message)";
    });
  }

  const dmForm = document.getElementById("dmForm");
  if (dmForm) {
    dmForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const body = document.getElementById("dmInput").value.trim();
      if (!body) return;
      try {
        let to = window.__dmPendingTo;
        if (dmThreadId) {
          const parts = dmThreadId.split(":");
          to = parts[1] === currentUser ? parts[2] : parts[1];
        }
        const data = await post("/api/messages", { to, body });
        document.getElementById("dmInput").value = "";
        window.__dmPendingTo = null;
        await openDmThread(data.message.thread_id, to);
        loadAccountData().catch(() => {});
      } catch (e) {
        toast(String(e.message || e));
      }
    });
  }

  get("/api/auth")
    .then((auth) => {
      currentUser = auth.user || (auth.profile && auth.profile.email) || null;
      const btn = document.getElementById("logoutBtn");
      const accountBtn = document.getElementById("accountBtn");
      const messagesBtn = document.getElementById("messagesBtn");
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
      if (accountBtn && (auth.authed || !auth.private_mode)) {
        accountBtn.hidden = false;
        accountBtn.addEventListener("click", () => openAccount("profile"));
      }
      if (messagesBtn && (auth.authed || !auth.private_mode)) {
        messagesBtn.hidden = false;
        messagesBtn.addEventListener("click", () => openAccount("messages"));
      }
      if (auth.profile && !auth.profile.profile_complete && auth.authed) {
        openAccount("profile");
        toast("Add your name and employee number to finish setup");
      }
      get("/api/messages/threads").then((t) => updateMsgBadge(t.unread_total || 0)).catch(() => {});
    })
    .catch(() => {});
})();
