(() => {
  "use strict";

  const PRESETS = {
    "Aero Blue": {
      theme_preset: "Aero Blue",
      accent_color: "#38BDF8",
      transparency: 0.72,
      blur_radius: 6,
      specular_edge_brightness: 0.35,
      corner_radius: 12,
      animation_speed: 1.0,
      spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
      wallpaper: "aero-glass-wave",
      surface_tint: "#0F172A",
      surface_rgb: "15, 23, 42",
    },
    "Frosted Obsidian": {
      theme_preset: "Frosted Obsidian",
      accent_color: "#818CF8",
      transparency: 0.78,
      blur_radius: 6,
      specular_edge_brightness: 0.28,
      corner_radius: 10,
      animation_speed: 1.0,
      spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
      wallpaper: "obsidian-minimal-mesh",
      surface_tint: "#090D16",
      surface_rgb: "9, 13, 22",
    },
    "Emerald Glass": {
      theme_preset: "Emerald Glass",
      accent_color: "#10B981",
      transparency: 0.70,
      blur_radius: 6,
      specular_edge_brightness: 0.40,
      corner_radius: 14,
      animation_speed: 1.0,
      spring_curve: "cubic-bezier(0.16, 1.0, 0.3, 1.0)",
      wallpaper: "emerald-aurora",
      surface_tint: "#06201A",
      surface_rgb: "6, 32, 26",
    },
    "Sunset Mica": {
      theme_preset: "Sunset Mica",
      accent_color: "#FB923C",
      transparency: 0.76,
      blur_radius: 5,
      specular_edge_brightness: 0.32,
      corner_radius: 12,
      animation_speed: 0.95,
      spring_curve: "cubic-bezier(0.25, 1.0, 0.5, 1.0)",
      wallpaper: "sunset-mica-horizon",
      surface_tint: "#1F1218",
      surface_rgb: "31, 18, 24",
    },
    "Ultra-Light Flat": {
      theme_preset: "Ultra-Light Flat",
      accent_color: "#60A5FA",
      transparency: 0.96,
      blur_radius: 0,
      specular_edge_brightness: 0.15,
      corner_radius: 8,
      animation_speed: 1.35,
      spring_curve: "cubic-bezier(0.2, 0.0, 0.0, 1.0)",
      wallpaper: "ultra-light-slate",
      surface_tint: "#111827",
      surface_rgb: "17, 24, 39",
    },
  };

  const START_APPS = [
    { id: "kite-settings", name: "kite-settings Studio", platform: "linux", ext: "", windowId: "kite-settings" },
    { id: "kitebridge", name: "KiteBridge Files", platform: "linux", ext: "", windowId: "kitebridge" },
    { id: "terminal", name: "foot Terminal", platform: "linux", ext: "", windowId: "terminal" },
    { id: "win-notepadpp", name: "Notepad++ (.exe)", platform: "win", ext: ".exe", windowId: "kitebridge" },
    { id: "win-office", name: "SetupWizard.exe", platform: "win", ext: ".exe", windowId: "kitebridge" },
    { id: "android-play", name: "Aurora Store (.apk)", platform: "android", ext: ".apk", windowId: "android" },
    { id: "android-whatsapp", name: "WhatsApp Waydroid", platform: "android", ext: ".apk", windowId: "android" },
    { id: "macos-finder", name: "XcodeCLI.dmg", platform: "macos", ext: ".dmg", windowId: "kitebridge" },
    { id: "macos-app", name: "Notes.app", platform: "macos", ext: ".app", windowId: "kitebridge" },
  ];

  const SPOTLIGHT_CORPUS = [
    { id: "F1", name: "Greenhouse_AI_Spec_v2.pdf", path: "/home/kite/Documents/Capstone/Greenhouse_AI_Spec_v2.pdf", badge: "[Doc]", badgeClass: "badge-linux", keywords: "capstone greenhouse esp32 sensor pid 2 drafts collapsed" },
    { id: "F2", name: "tent_monitor.ino", path: "/home/kite/Code/tent_monitor.ino", badge: "[Code]", badgeClass: "badge-linux", keywords: "arduino nano esp32cam pwm fan led greenhouse" },
    { id: "F3", name: "Agile_Report_Ch2.docx", path: "/home/kite/Documents/Capstone/Agile_Report_Ch2.docx", badge: "[Doc]", badgeClass: "badge-linux", keywords: "capstone methodology bom schedule" },
    { id: "F4", name: "SetupWizard.exe", path: "/var/lib/kitebridge/apps/SetupWizard.exe", badge: "[Win]", badgeClass: "badge-win", keywords: "windows wine ntsync dxvk 1.10.3" },
    { id: "F5", name: "AuroraStore.apk", path: "/var/lib/kitebridge/apps/AuroraStore.apk", badge: "[Android]", badgeClass: "badge-android", keywords: "android waydroid apk" },
    { id: "F6", name: "Notes.app", path: "/var/lib/kitebridge/apps/Notes.app", badge: "[macOS]", badgeClass: "badge-macos", keywords: "macos cocoa osx-kvm" },
  ];

  const state = {
    ramTier: "8G",
    powerSource: "AC",
    glassFxEnabled: true,
    activeOverlay: null,
    activeWindowId: "kite-settings",
    startFilter: "all",
    startSearch: "",
    startAllApps: false,
    aiProvider: "offline",
    aiTokenBudget: 400,
    aiSessionTokens: 0,
    calYear: 2026,
    calMonth: 10,
    notifications: [
      { id: 1, platform: "android", app: "Waydroid · WhatsApp", title: "Message received", body: "Build green on Folio 9480m!" },
      { id: 2, platform: "win", app: "Wine-ntsync", title: "DXVK 1.10.3 active", body: "MESA_LOADER_DRIVER_OVERRIDE=crocus" },
    ],
    settings: {
      schema_version: 1,
      theme_preset: "Aero Blue",
      accent_color: "#38BDF8",
      taskbar_alignment: "center",
      transparency: 0.72,
      blur_radius: 6,
      specular_edge_brightness: 0.35,
      corner_radius: 12,
      animation_speed: 1.0,
      spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
      wallpaper: "aero-glass-wave",
      battery_glass_autosimplify: true,
      mitigations_off_requested: false,
    },
  };

  function clampEffective() {
    const s = state.settings;
    const is4G = state.ramTier === "4G";
    const isBattery = state.powerSource === "Battery";

    let blurEnabled = true;
    let blurSize = s.blur_radius;
    let blurPasses = 2;
    let blurXray = true;
    let effectiveTier = state.ramTier === "16G" ? "kawase_full" : "kawase_2pass";
    let clampReason = "NONE";

    if (is4G || !state.glassFxEnabled) {
      blurEnabled = false;
      blurSize = 0;
      blurPasses = 0;
      blurXray = false;
      effectiveTier = "static";
      clampReason = is4G ? "4G_STATIC_FALLBACK" : "QUICK_SETTINGS_OFF";
    } else if (s.theme_preset === "Ultra-Light Flat" || s.blur_radius <= 0) {
      blurEnabled = false;
      blurSize = 0;
      blurPasses = 0;
      blurXray = false;
      effectiveTier = "flat";
      clampReason = "USER_GLASS_DISABLED";
    } else if (isBattery && s.battery_glass_autosimplify) {
      blurEnabled = true;
      blurSize = Math.max(1, Math.min(s.blur_radius, 4));
      blurPasses = 1;
      blurXray = true;
      effectiveTier = "kawase_1pass";
      clampReason = "BATTERY_AUTOSIMPLIFY_1PASS";
    } else if (isBattery) {
      blurEnabled = true;
      blurSize = Math.max(1, Math.min(s.blur_radius, 6));
      blurPasses = 2;
      blurXray = true;
      effectiveTier = "kawase_2pass";
      clampReason = s.blur_radius > 6 ? "HD4400_BATTERY_OVERRIDE_CAP" : "NONE";
    } else {
      blurEnabled = true;
      blurSize = Math.max(1, Math.min(s.blur_radius, 6));
      blurPasses = 2;
      blurXray = true;
      effectiveTier = state.ramTier === "16G" ? "kawase_full" : "kawase_2pass";
      clampReason = s.blur_radius > 6 ? "HD4400_AC_CAP" : "NONE";
    }

    return { blurEnabled, blurSize, blurPasses, blurXray, effectiveTier, clampReason };
  }

  function renderHyprConf(eff) {
    const s = state.settings;
    const hex = s.accent_color.replace("#", "").toUpperCase();
    const specHex = Math.round(s.specular_edge_brightness * 255).toString(16).padStart(2, "0").toUpperCase();
    return [
      `# Hardware: ${state.ramTier} | Power: ${state.powerSource} | Clamp: ${eff.clampReason}`,
      `general { col.active_border = rgba(${hex}${specHex}) }`,
      `decoration {`,
      `    rounding = ${s.corner_radius}`,
      `    blur {`,
      `        enabled = ${eff.blurEnabled}`,
      `        size = ${eff.blurSize}`,
      `        passes = ${eff.blurPasses}`,
      `        xray = ${eff.blurXray}`,
      `    }`,
      `}`,
      `animations { enabled = ${s.animation_speed > 0} }`,
    ].join("\n");
  }

  function syncUI() {
    const s = state.settings;
    const eff = clampEffective();
    const root = document.getElementById("desktop-root");
    const docStyle = document.documentElement.style;

    root.dataset.hwTier = state.ramTier;
    root.dataset.power = state.powerSource;
    root.dataset.blurMode = eff.effectiveTier;
    root.dataset.wallpaper = s.wallpaper;
    root.dataset.taskbarAlign = s.taskbar_alignment;

    const preset = PRESETS[s.theme_preset] || PRESETS["Aero Blue"];
    docStyle.setProperty("--glass-alpha", String(s.transparency));
    docStyle.setProperty("--glass-blur", eff.blurEnabled ? `${eff.blurSize * 3}px` : "0px");
    docStyle.setProperty("--specular-alpha", String(s.specular_edge_brightness));
    docStyle.setProperty("--corner-radius", `${s.corner_radius}px`);
    docStyle.setProperty("--anim-speed", String(s.animation_speed));
    docStyle.setProperty("--anim-duration", s.animation_speed <= 0 ? "0ms" : `${Math.round(220 / s.animation_speed)}ms`);
    docStyle.setProperty("--spring-curve", s.spring_curve);
    docStyle.setProperty("--accent-color", s.accent_color);
    docStyle.setProperty("--surface-tint-rgb", preset.surface_rgb);

    // Telemetry HUD
    const idleMb = state.ramTier === "4G" ? 240 : state.ramTier === "16G" ? 410 : 345;
    const blurSummary = eff.blurEnabled
      ? `Dual-Kawase ${eff.blurPasses}-pass (size=${eff.blurSize}, xray=true)`
      : (eff.effectiveTier === "flat" ? "Flat (0-pass)" : "Static Acrylic (0-pass)");
    document.querySelector('[data-testid="hw-telemetry"]').textContent =
      `${state.ramTier} · ${state.powerSource} · ${blurSummary} · ~${idleMb} MB idle · 60 FPS`;

    // Sync HUD active buttons
    document.querySelectorAll("#sim-hud [data-ram]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.ram === state.ramTier);
    });
    document.querySelectorAll("#sim-hud [data-power]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.power === state.powerSource);
    });

    // Taskbar alignment
    const taskbar = document.getElementById("taskbar");
    taskbar.dataset.alignment = s.taskbar_alignment;
    document.getElementById("taskbar-align-toggle").textContent = s.taskbar_alignment === "center" ? "CTR" : "LFT";
    document.getElementById("setting-align-center").classList.toggle("is-active", s.taskbar_alignment === "center");
    document.getElementById("setting-align-left").classList.toggle("is-active", s.taskbar_alignment === "left");

    // Settings controls sync
    document.getElementById("slider-transparency").value = String(s.transparency);
    document.getElementById("val-transparency").textContent = s.transparency.toFixed(2);
    document.getElementById("slider-blur").value = String(s.blur_radius);
    document.getElementById("val-blur").textContent = eff.blurSize !== s.blur_radius
      ? `${s.blur_radius}px (clamped ${eff.blurSize}px)`
      : `${s.blur_radius}px`;
    document.getElementById("slider-specular").value = String(s.specular_edge_brightness);
    document.getElementById("val-specular").textContent = s.specular_edge_brightness.toFixed(2);
    document.getElementById("slider-radius").value = String(s.corner_radius);
    document.getElementById("val-radius").textContent = `${s.corner_radius}px`;
    document.getElementById("slider-anim-speed").value = String(s.animation_speed);
    document.getElementById("val-anim-speed").textContent = `${s.animation_speed.toFixed(2)}x`;
    document.getElementById("select-spring-curve").value = s.spring_curve;
    document.getElementById("input-accent-color").value = s.accent_color;
    document.getElementById("select-wallpaper").value = s.wallpaper;
    document.getElementById("toggle-battery-autosimplify").checked = s.battery_glass_autosimplify;
    document.getElementById("toggle-mitigations-off").checked = s.mitigations_off_requested;
    document.querySelector('[data-testid="mitigations-warning"]').hidden = !s.mitigations_off_requested;

    document.querySelectorAll("[data-preset]").forEach((card) => {
      card.classList.toggle("is-active", card.dataset.preset === s.theme_preset);
    });

    document.querySelector('[data-testid="runtime-conf-preview"]').textContent = renderHyprConf(eff);
    document.querySelector('[data-testid="settings-json-preview"]').textContent = JSON.stringify(s, null, 2);

    // Sync Bento 2x2 Hardware Cards & AI Studio
    const zramMap = { "4G": "4G Tier · 150% lz4 (swappiness=180)", "8G": "8G Tier · 100% zstd (swappiness=150)", "16G": "16G Tier · 50% zstd (swappiness=100)" };
    const bridgeMap = { "4G": "Waydroid teardown (300s)", "8G": "Waydroid cgroup_freeze", "16G": "Prewarmed + KVM hugepages" };
    document.getElementById("bento-blur-val").textContent = eff.blurEnabled ? `${eff.blurPasses}-pass (size=${eff.blurSize})` : "Static (0-pass)";
    document.getElementById("bento-zram-val").textContent = zramMap[state.ramTier];
    document.getElementById("bento-bridge-val").textContent = `DXVK 1.10.3 + ntsync · ${bridgeMap[state.ramTier]}`;
    const aiPolicy = state.ramTier === "4G" && state.powerSource === "Battery" ? "4G Battery: Tier 0 Forced" : `SQLite FTS5 + SimHash · <=${state.aiTokenBudget} tok`;
    document.getElementById("bento-ai-sub").textContent = aiPolicy;
    document.getElementById("val-ai-budget").textContent = `${state.aiTokenBudget} tok`;
    document.getElementById("ai-session-cost").textContent = `${state.aiSessionTokens} tokens ($${(state.aiSessionTokens * 0.00000015).toFixed(6)})`;
  }

  function renderSpotlightResults(queryText) {
    const container = document.getElementById("spotlight-results");
    const badge = document.getElementById("spotlight-tier-badge");
    const q = (queryText || "").trim().toLowerCase();
    const matches = SPOTLIGHT_CORPUS.filter((item) => !q || item.name.toLowerCase().includes(q) || item.keywords.includes(q) || item.badge.toLowerCase().includes(q));
    const forced4g = state.ramTier === "4G" && state.powerSource === "Battery";
    const useCloud = q.length >= 2 && state.aiProvider !== "offline" && !forced4g;
    if (useCloud) {
      const est = Math.min(state.aiTokenBudget, 180 + matches.length * 22);
      state.aiSessionTokens += est;
      badge.textContent = `BYOK ${state.aiProvider} (${est} tok)`;
      document.getElementById("ai-session-cost").textContent = `${state.aiSessionTokens} tokens ($${(state.aiSessionTokens * 0.00000015).toFixed(6)})`;
    } else {
      badge.textContent = forced4g ? "Tier 0 (4G Battery, 0 tok)" : "Tier 0 (0 tokens)";
    }
    container.innerHTML = "";
    if (matches.length === 0) {
      container.innerHTML = '<div class="muted">No indexed files matched.</div>';
      return;
    }
    matches.forEach((item) => {
      const a = document.createElement("a");
      a.className = "spotlight-card";
      a.href = `kite://open?path=${encodeURIComponent(item.path)}`;
      a.innerHTML = `<span><strong>${item.name}</strong> <span class="muted">${item.keywords.split(" ").slice(0, 4).join(", ")}</span></span><span class="badge ${item.badgeClass}">${item.badge}</span>`;
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        toggleOverlay(null);
      });
      container.appendChild(a);
    });
  }

  function toggleOverlay(name) {
    state.activeOverlay = state.activeOverlay === name ? null : name;
    ["start-menu", "quick-settings", "notification-center", "snap-layouts", "ai-spotlight"].forEach((id) => {
      const el = document.getElementById(id);
      const isOpen = id === state.activeOverlay;
      el.hidden = !isOpen;
      el.setAttribute("aria-hidden", String(!isOpen));
      el.classList.toggle("is-open", isOpen);
    });
    if (state.activeOverlay === "start-menu") {
      document.getElementById("start-search-input").focus();
    } else if (state.activeOverlay === "ai-spotlight") {
      renderSpotlightResults(document.getElementById("spotlight-input").value);
      document.getElementById("spotlight-input").focus();
    }
  }

  function syncTaskbarWindows() {
    document.querySelectorAll(".app-window").forEach((w) => {
      const winKey = w.dataset.windowId;
      const isOpen = w.dataset.open === "true";
      const isVisible = !w.hidden;
      const isActive = isOpen && isVisible && state.activeWindowId === winKey;
      w.dataset.active = isActive ? "true" : "false";
      const tbBtn = document.querySelector(`.tb-app[data-focus-window="${winKey}"]`);
      if (tbBtn) {
        tbBtn.classList.toggle("is-open", isOpen);
        tbBtn.classList.toggle("is-active", isActive);
        tbBtn.classList.toggle("is-minimized", isOpen && !isVisible);
      }
    });
  }

  function focusWindow(winKey) {
    const target = document.getElementById(`win-${winKey}`);
    if (!target) return;
    target.hidden = false;
    target.dataset.open = "true";
    target.dataset.minimized = "false";
    state.activeWindowId = winKey;
    syncTaskbarWindows();
    const labelMap = {
      "kite-settings": "kite-settings Studio",
      kitebridge: "KiteBridge Universal Launcher",
      terminal: "foot Terminal",
      android: "Waydroid Multi-Window",
    };
    document.getElementById("snap-target-label").textContent = labelMap[winKey] || winKey;
  }

  function toggleMaximizeWindow(win) {
    const canvas = document.getElementById("desktop-canvas");
    if (!win || !canvas) return;
    const gap = 8;
    if (win.dataset.maximized === "true") {
      win.dataset.maximized = "false";
      const prev = win._restoreBounds;
      if (prev) {
        win.style.left = prev.left;
        win.style.top = prev.top;
        win.style.width = prev.width;
        win.style.height = prev.height;
        win.dataset.snapZone = prev.snapZone || "none";
      }
      return;
    }
    win._restoreBounds = {
      left: win.style.left || `${win.offsetLeft}px`,
      top: win.style.top || `${win.offsetTop}px`,
      width: win.style.width || `${win.offsetWidth}px`,
      height: win.style.height || `${win.offsetHeight}px`,
      snapZone: win.dataset.snapZone || "none",
    };
    win.dataset.maximized = "true";
    win.dataset.snapZone = "none";
    win.style.left = `${gap}px`;
    win.style.top = `${gap}px`;
    win.style.width = `${Math.max(200, canvas.clientWidth - gap * 2)}px`;
    win.style.height = `${Math.max(160, canvas.clientHeight - gap * 2)}px`;
  }

  function snapWindow(zone) {
    const win = document.getElementById(`win-${state.activeWindowId}`);
    const canvas = document.getElementById("desktop-canvas");
    if (!win || !canvas) return;
    win.hidden = false;
    win.dataset.open = "true";
    win.dataset.minimized = "false";
    win.dataset.maximized = "false";
    win.dataset.snapZone = zone;
    syncTaskbarWindows();

    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const gap = 8;
    const halfW = Math.floor((cw - gap * 3) / 2);
    const halfH = Math.floor((ch - gap * 3) / 2);

    const geom = {
      "left-half": { x: gap, y: gap, w: halfW, h: ch - gap * 2 },
      "right-half": { x: gap * 2 + halfW, y: gap, w: halfW, h: ch - gap * 2 },
      "top-left": { x: gap, y: gap, w: halfW, h: halfH },
      "top-right": { x: gap * 2 + halfW, y: gap, w: halfW, h: halfH },
      "bottom-left": { x: gap, y: gap * 2 + halfH, w: halfW, h: halfH },
      "bottom-right": { x: gap * 2 + halfW, y: gap * 2 + halfH, w: halfW, h: halfH },
      "split-60": { x: gap, y: gap, w: Math.floor((cw - gap * 3) * 0.6), h: ch - gap * 2 },
      "split-40": {
        x: gap * 2 + Math.floor((cw - gap * 3) * 0.6),
        y: gap,
        w: cw - gap * 3 - Math.floor((cw - gap * 3) * 0.6),
        h: ch - gap * 2,
      },
    }[zone];

    if (geom) {
      win.style.left = `${geom.x}px`;
      win.style.top = `${geom.y}px`;
      win.style.width = `${geom.w}px`;
      win.style.height = `${geom.h}px`;
    }
    toggleOverlay(null);
  }

  function renderStartApps() {
    const grid = document.getElementById("start-apps-grid");
    grid.classList.toggle("is-list", state.startAllApps);
    const q = state.startSearch.trim().toLowerCase();
    const filtered = START_APPS.filter((app) => {
      if (state.startFilter !== "all" && app.platform !== state.startFilter) return false;
      if (!q) return true;
      const tag = app.platform === "win" ? "[win]" : app.platform === "android" ? "[android]" : app.platform === "macos" ? "[macos]" : "linux";
      return app.name.toLowerCase().includes(q) || tag.includes(q) || app.ext.includes(q);
    });

    grid.innerHTML = "";
    filtered.forEach((app) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "start-app-card";
      btn.dataset.platform = app.platform;
      const badgeClass = `badge-${app.platform}`;
      const badgeText = app.platform === "win" ? "[Win]" : app.platform === "android" ? "[Android]" : app.platform === "macos" ? "[macOS]" : "Linux";
      btn.innerHTML = `<span>${app.name}</span><span class="badge ${badgeClass}">${badgeText}</span>`;
      btn.addEventListener("click", () => {
        focusWindow(app.windowId);
        toggleOverlay(null);
      });
      grid.appendChild(btn);
    });
  }

  function renderNotifications() {
    const list = document.getElementById("notification-list");
    list.innerHTML = "";
    document.getElementById("tray-notif-count").textContent = String(state.notifications.length);
    if (state.notifications.length === 0) {
      list.innerHTML = '<div class="muted">No new notifications</div>';
      return;
    }
    state.notifications.forEach((n) => {
      const item = document.createElement("div");
      item.className = "notif-item";
      const badgeText = n.platform === "android" ? "[Android]" : n.platform === "win" ? "[Win]" : "Linux";
      const badgeClass = `badge-${n.platform}`;
      item.innerHTML = `
        <div class="notif-item-head">
          <span><span class="badge ${badgeClass}">${badgeText}</span> ${n.app}</span>
          <button type="button" class="hud-btn" data-dismiss="${n.id}">x</button>
        </div>
        <strong>${n.title}</strong>
        <span class="muted">${n.body}</span>
      `;
      item.querySelector("[data-dismiss]").addEventListener("click", () => {
        state.notifications = state.notifications.filter((x) => x.id !== n.id);
        renderNotifications();
      });
      list.appendChild(item);
    });
  }

  function renderCalendar() {
    const monthNames = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    document.getElementById("cal-month-label").textContent = `${monthNames[state.calMonth]} ${state.calYear}`;
    const grid = document.getElementById("cal-grid");
    grid.innerHTML = "";
    const firstDay = new Date(state.calYear, state.calMonth, 1).getDay();
    const days = new Date(state.calYear, state.calMonth + 1, 0).getDate();
    for (let i = 0; i < firstDay; i++) {
      const pad = document.createElement("span");
      pad.className = "cal-cell";
      grid.appendChild(pad);
    }
    for (let d = 1; d <= days; d++) {
      const cell = document.createElement("span");
      cell.className = "cal-cell" + (d === 17 ? " is-today" : "");
      cell.textContent = String(d);
      grid.appendChild(cell);
    }
  }

  function bindEvents() {
    // Hardware Simulator buttons
    document.querySelectorAll("#sim-hud [data-ram]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.ramTier = btn.dataset.ram;
        syncUI();
      });
    });
    document.querySelectorAll("#sim-hud [data-power]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.powerSource = btn.dataset.power;
        syncUI();
      });
    });

    // Hotkey bar & taskbar triggers
    document.querySelector('[data-testid="hotkey-win"]').addEventListener("click", () => toggleOverlay("start-menu"));
    document.querySelector('[data-testid="hotkey-win-a"]').addEventListener("click", () => toggleOverlay("quick-settings"));
    document.querySelector('[data-testid="hotkey-win-n"]').addEventListener("click", () => toggleOverlay("notification-center"));
    document.querySelector('[data-testid="hotkey-win-z"]').addEventListener("click", () => toggleOverlay("snap-layouts"));
    document.querySelector('[data-testid="hotkey-win-i"]').addEventListener("click", () => focusWindow("kite-settings"));

    document.getElementById("start-button").addEventListener("click", () => toggleOverlay("start-menu"));
    document.getElementById("taskbar-search-pill").addEventListener("click", () => toggleOverlay("ai-spotlight"));
    document.getElementById("spotlight-input").addEventListener("input", (e) => {
      renderSpotlightResults(e.target.value);
    });
    document.getElementById("ai-provider-select").addEventListener("change", (e) => {
      state.aiProvider = e.target.value;
    });
    document.getElementById("ai-token-slider").addEventListener("input", (e) => {
      state.aiTokenBudget = Math.max(150, Math.min(800, parseInt(e.target.value, 10) || 400));
      syncUI();
    });
    document.getElementById("tray-quick-settings").addEventListener("click", () => toggleOverlay("quick-settings"));
    document.getElementById("tray-notifications").addEventListener("click", () => toggleOverlay("notification-center"));
    document.getElementById("taskbar-align-toggle").addEventListener("click", () => {
      state.settings.taskbar_alignment = state.settings.taskbar_alignment === "center" ? "left" : "center";
      syncUI();
    });

    // Global keyboard shortcuts (Alt+* browser-safe & Meta+*)
    window.addEventListener("keydown", (e) => {
      const k = e.key.toLowerCase();
      if ((e.altKey || e.metaKey) && k === "a") {
        e.preventDefault();
        toggleOverlay("quick-settings");
      } else if ((e.altKey || e.metaKey) && k === "n") {
        e.preventDefault();
        toggleOverlay("notification-center");
      } else if ((e.altKey || e.metaKey) && k === "z") {
        e.preventDefault();
        toggleOverlay("snap-layouts");
      } else if ((e.altKey || e.metaKey) && k === "i") {
        e.preventDefault();
        focusWindow("kite-settings");
      } else if ((e.altKey || e.metaKey) && k === "s") {
        e.preventDefault();
        toggleOverlay("start-menu");
      } else if (e.key === "Escape" && state.activeOverlay) {
        toggleOverlay(null);
      }
    });

    // Windows focus, launch, drag, and buttons
    document.querySelectorAll("[data-launch]").forEach((el) => {
      el.addEventListener("click", () => focusWindow(el.dataset.launch));
    });
    document.querySelectorAll("[data-focus-window]").forEach((el) => {
      el.addEventListener("click", () => focusWindow(el.dataset.focusWindow));
    });
    document.querySelectorAll(".app-window").forEach((win) => {
      win.addEventListener("mousedown", () => focusWindow(win.dataset.windowId));
      const bar = win.querySelector(".window-titlebar");
      bar.addEventListener("mousedown", (ev) => {
        if (ev.target.closest("button")) return;
        const canvas = document.getElementById("desktop-canvas");
        const startX = ev.clientX - win.offsetLeft;
        const startY = ev.clientY - win.offsetTop;
        function onMove(m) {
          const maxX = canvas ? Math.max(0, canvas.clientWidth - 160) : 1000;
          const maxY = canvas ? Math.max(0, canvas.clientHeight - 40) : 600;
          const nextX = Math.min(maxX, Math.max(0, m.clientX - startX));
          const nextY = Math.min(maxY, Math.max(0, m.clientY - startY));
          win.style.left = `${nextX}px`;
          win.style.top = `${nextY}px`;
        }
        function onUp() {
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
        }
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      win.querySelectorAll("[data-action]").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const act = btn.dataset.action;
          const winKey = win.dataset.windowId;
          if (act === "snap") {
            focusWindow(winKey);
            toggleOverlay("snap-layouts");
          } else if (act === "min") {
            win.hidden = true;
            win.dataset.open = "true";
            win.dataset.minimized = "true";
            if (state.activeWindowId === winKey) {
              const nextVisible = Array.from(document.querySelectorAll(".app-window")).find(
                (w) => !w.hidden && w.dataset.windowId !== winKey
              );
              state.activeWindowId = nextVisible ? nextVisible.dataset.windowId : null;
            }
            syncTaskbarWindows();
          } else if (act === "close") {
            win.hidden = true;
            win.dataset.open = "false";
            win.dataset.minimized = "false";
            win.dataset.maximized = "false";
            if (state.activeWindowId === winKey) {
              const nextVisible = Array.from(document.querySelectorAll(".app-window")).find(
                (w) => !w.hidden && w.dataset.windowId !== winKey
              );
              state.activeWindowId = nextVisible ? nextVisible.dataset.windowId : null;
            }
            syncTaskbarWindows();
          } else if (act === "max") {
            focusWindow(winKey);
            toggleMaximizeWindow(win);
          }
        });
      });
    });

    // Snap Layout zones
    document.querySelectorAll("[data-snap]").forEach((btn) => {
      btn.addEventListener("click", () => snapWindow(btn.dataset.snap));
    });

    // Settings sidebar categories
    document.querySelectorAll(".cat-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".cat-btn").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        document.querySelectorAll(".studio-pane").forEach((p) => {
          p.classList.toggle("is-active", p.dataset.pane === btn.dataset.cat);
        });
      });
    });

    // Settings Presets
    document.querySelectorAll("[data-preset]").forEach((card) => {
      card.addEventListener("click", () => {
        const p = PRESETS[card.dataset.preset];
        if (!p) return;
        Object.assign(state.settings, {
          theme_preset: p.theme_preset,
          accent_color: p.accent_color,
          transparency: p.transparency,
          blur_radius: p.blur_radius,
          specular_edge_brightness: p.specular_edge_brightness,
          corner_radius: p.corner_radius,
          animation_speed: p.animation_speed,
          spring_curve: p.spring_curve,
          wallpaper: p.wallpaper,
        });
        syncUI();
      });
    });

    // Settings sliders & toggles
    document.getElementById("slider-transparency").addEventListener("input", (e) => {
      state.settings.transparency = parseFloat(e.target.value);
      syncUI();
    });
    document.getElementById("slider-blur").addEventListener("input", (e) => {
      state.settings.blur_radius = parseInt(e.target.value, 10);
      syncUI();
    });
    document.getElementById("slider-specular").addEventListener("input", (e) => {
      state.settings.specular_edge_brightness = parseFloat(e.target.value);
      syncUI();
    });
    document.getElementById("slider-radius").addEventListener("input", (e) => {
      state.settings.corner_radius = parseInt(e.target.value, 10);
      syncUI();
    });
    document.getElementById("slider-anim-speed").addEventListener("input", (e) => {
      state.settings.animation_speed = parseFloat(e.target.value);
      syncUI();
    });
    document.getElementById("select-spring-curve").addEventListener("change", (e) => {
      state.settings.spring_curve = e.target.value;
      syncUI();
    });
    document.getElementById("setting-align-center").addEventListener("click", () => {
      state.settings.taskbar_alignment = "center";
      syncUI();
    });
    document.getElementById("setting-align-left").addEventListener("click", () => {
      state.settings.taskbar_alignment = "left";
      syncUI();
    });
    document.getElementById("input-accent-color").addEventListener("input", (e) => {
      state.settings.accent_color = e.target.value.toUpperCase();
      syncUI();
    });
    document.getElementById("select-wallpaper").addEventListener("change", (e) => {
      state.settings.wallpaper = e.target.value;
      syncUI();
    });
    document.getElementById("toggle-battery-autosimplify").addEventListener("change", (e) => {
      state.settings.battery_glass_autosimplify = e.target.checked;
      syncUI();
    });
    document.getElementById("toggle-mitigations-off").addEventListener("change", (e) => {
      state.settings.mitigations_off_requested = e.target.checked;
      syncUI();
    });

    // Start Menu filters & power
    document.getElementById("start-search-input").addEventListener("input", (e) => {
      state.startSearch = e.target.value;
      renderStartApps();
    });
    document.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.startFilter = btn.dataset.filter;
        document.querySelectorAll("[data-filter]").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        renderStartApps();
      });
    });
    document.getElementById("start-all-apps-toggle").addEventListener("click", () => {
      state.startAllApps = !state.startAllApps;
      renderStartApps();
    });
    document.getElementById("start-open-settings").addEventListener("click", () => {
      focusWindow("kite-settings");
      toggleOverlay(null);
    });
    document.getElementById("start-power-btn").addEventListener("click", () => {
      const pm = document.getElementById("power-menu");
      pm.hidden = !pm.hidden;
    });

    // Quick Settings controls
    document.querySelectorAll("[data-qs-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => btn.classList.toggle("is-on"));
    });
    document.getElementById("qs-glass-fx-toggle").addEventListener("click", (e) => {
      state.glassFxEnabled = !state.glassFxEnabled;
      e.currentTarget.classList.toggle("is-on", state.glassFxEnabled);
      syncUI();
    });
    document.querySelectorAll("[data-pm]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-pm]").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
      });
    });

    // Notifications & Calendar
    document.getElementById("notifications-clear-btn").addEventListener("click", () => {
      state.notifications = [];
      renderNotifications();
    });
    document.getElementById("cal-prev").addEventListener("click", () => {
      if (state.calMonth === 0) {
        state.calMonth = 11;
        state.calYear -= 1;
      } else {
        state.calMonth -= 1;
      }
      renderCalendar();
    });
    document.getElementById("cal-next").addEventListener("click", () => {
      if (state.calMonth === 11) {
        state.calMonth = 0;
        state.calYear += 1;
      } else {
        state.calMonth += 1;
      }
      renderCalendar();
    });
  }

  bindEvents();
  syncTaskbarWindows();
  renderStartApps();
  renderNotifications();
  renderCalendar();
  syncUI();
})();
