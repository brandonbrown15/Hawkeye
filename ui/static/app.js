(() => {
  const token = window.__AUTOCODE_TOKEN__ || "";
  const toastEl = document.getElementById("toast");
  let toastTimer = null;

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
        return "Idle. Autocode will keep draining Ready Notion tasks until the project is finished. Add work, run a cycle, or try a mock.";
      case "starting":
        return "Work cycle is starting…";
      case "routing":
        return `Choosing a route for ${st.task_id || "the next task"}…`;
      case "running_local":
        return `Local Hermes is working on ${st.task_name || st.task_id || "a task"}.`;
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
      `profile=${data.cost_profile || "?"}`,
      data.personal_local_only
        ? "local-only (escalate off)"
        : data.local_only
          ? "local-first (task cloud off)"
          : "local-first → Cursor/Grok",
      data.private_mode ? "login ON" : null,
      data.autopilot ? "autopilot ON" : "autopilot off",
      data.continuous ? "continuous ON" : "continuous off",
    ].filter(Boolean);
    document.getElementById("readyMeta").textContent = bits.join(" · ");

    const chatNote = document.getElementById("chatNote");
    if (chatNote && data.private_mode && !data.personal_local_only) {
      const host = data.public_host || "hawkeye.brownhawke.engineering";
      chatNote.textContent =
        `${data.product || "Hawkeye"} @ ${host}: free local LLM all day; Cursor & Grok Bot take strenuous asks.`;
    }
  }

  function renderLogs(data) {
    document.getElementById("logPath").textContent = data.path || "";
    document.getElementById("logText").textContent = data.text || "(empty)";
  }

  async function refresh() {
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
    demoBtn.disabled = !!demo.running || !!work.running;
    demoBtn.textContent = demo.running ? "Mock cycle running…" : "Run mock cycle";
    if (workBtn) {
      workBtn.disabled = !!work.running || !!demo.running;
      workBtn.textContent = work.running ? "Work cycle running…" : "Run work cycle";
    }
  }

  document.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.getAttribute("data-action");
      btn.disabled = true;
      try {
        await post("/api/control", { action });
        toast(`${action} sent`);
        await refresh();
      } catch (e) {
        toast(String(e.message || e));
      } finally {
        btn.disabled = false;
      }
    });
  });

  document.getElementById("skipForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const task_id = document.getElementById("skipId").value.trim();
    if (!task_id) return toast("Enter a task id");
    try {
      await post("/api/control", { action: "skip", task_id });
      toast(`Will skip ${task_id}`);
      await refresh();
    } catch (e) {
      toast(String(e.message || e));
    }
  });

  document.getElementById("demoBtn").addEventListener("click", async () => {
    const btn = document.getElementById("demoBtn");
    btn.disabled = true;
    try {
      await post("/api/demo", {});
      toast("Mock cycle started");
      await refresh();
    } catch (e) {
      toast(String(e.message || e));
      btn.disabled = false;
    }
  });

  const workBtnEl = document.getElementById("workBtn");
  if (workBtnEl) {
    workBtnEl.addEventListener("click", async () => {
      const btn = workBtnEl;
      btn.disabled = true;
      try {
        await post("/api/work", { force: true });
        toast("Work cycle started");
        await refresh();
      } catch (e) {
        toast(String(e.message || e));
        btn.disabled = false;
      }
    });
  }

  function appendChat(role, text) {
    const log = document.getElementById("chatLog");
    if (!log) return;
    const line = document.createElement("div");
    line.className = `chat-line ${role}`;
    line.textContent = `${role === "you" ? "You" : role === "local" ? "Local" : role === "cloud" ? "Cloud" : "System"}: ${text}`;
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
        if (data.seeded_task) appendChat("system", `Added to Notion checklist: ${data.seeded_task}`);
        if (data.local_only) toast("Local model replied (escalate disabled)");
        else toast(data.escalated ? `Escalated to ${data.provider || "premium"}` : "Local model replied");
      } catch (e) {
        appendChat("system", String(e.message || e));
        toast(String(e.message || e));
      } finally {
        sendBtn.disabled = false;
      }
    });
  }

  refresh().catch((e) => toast(String(e.message || e)));
  setInterval(() => { refresh().catch(() => {}); }, 2500);

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
