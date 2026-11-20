/**
 * CLIP IT Client Application (ES6 Vanilla JavaScript)
 * Replicates the warm-espresso and vibrant-amber UI system, real-time SSE progress,
 * instant Big Text live re-rendering, Creator Review multi-platform uploads,
 * scheduled dispatch calendar, and AI niche keyword research.
 */

class ClipItApp {
  constructor() {
    this.currentClip = null;
    this.activeJobId = null;
    this.eventSource = null;
    this.connectedAccounts = [];
    this.selectedLength = "15-60";
    this.selectedFont = "bounce";
    this.facecamEnabled = true;
    this.cropEnabled = false;
    this.selectedPlatform = "youtube";
    this.analyticsCache = {};
    this.currentTab = "clips";
    this.creatorsList = [];
    this.livePollInterval = null;
  }

  async init() {
    this.setupDropzone();
    await this.checkSystemStatus();
    await this.loadAccounts();
    await this.loadAnalytics();
    await this.loadClips();
    await this.loadCreators();
    await this.loadPostQueue();
    await this.loadSchedule();
    await this.loadJobs();
    await this.loadLiveStatus();

    // Check OAuth callback parameters in URL
    const params = new URLSearchParams(window.location.search);
    if (params.get("youtube_connected") === "true") {
      this.showToast("YouTube channel connected successfully!", "success");
      window.history.replaceState({}, document.title, window.location.pathname);
      await this.loadAccounts();
      await this.checkSystemStatus();
    }
  }

  showToast(message, type = "info") {
    const toast = document.getElementById("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.className = `show ${type}`;
    setTimeout(() => {
      toast.className = "";
    }, 4200);
  }

  // =========================================================================
  // Tab & View Navigation
  // =========================================================================

  switchTab(tabName) {
    this.currentTab = tabName;

    // Clear live polling if leaving live tab
    if (tabName !== "live") {
      this.stopLivePolling();
    }

    // Sidebar active state
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
    const navEl = document.getElementById(`nav-${tabName}`);
    if (navEl) navEl.classList.add("active");

    // Hide all view panels
    const panels = [
      "view-clips",
      "view-live",
      "view-creators",
      "view-queue",
      "view-calendar",
      "view-research",
      "view-jobs"
    ];
    panels.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    });

    // Show target view panel
    const targetPanel = document.getElementById(`view-${tabName}`);
    if (targetPanel) targetPanel.style.display = "block";

    // Update Topbar Breadcrumb & Tab Loader
    const crumb = document.getElementById("topbar-crumb");
    if (tabName === "clips") {
      if (crumb) crumb.textContent = "Shorts Generator";
      this.loadClips();
    } else if (tabName === "live") {
      if (crumb) crumb.textContent = "Live Stream Ingest & Real-Time Clipping";
      this.loadLiveStatus();
      this.startLivePolling();
    } else if (tabName === "creators") {
      if (crumb) crumb.textContent = "Creator Workspaces & Channel Profiles";
      this.loadCreators();
    } else if (tabName === "queue") {
      if (crumb) crumb.textContent = "Multi-Platform Post Queue";
      this.loadPostQueue();
    } else if (tabName === "calendar") {
      if (crumb) crumb.textContent = "Content Calendar & Dispatch Queue";
      this.loadSchedule();
    } else if (tabName === "research") {
      if (crumb) crumb.textContent = "Keyword & Viral Angle Research";
    } else if (tabName === "jobs") {
      if (crumb) crumb.textContent = "Activity & Processing Jobs";
      this.loadJobs();
    }
  }

  // =========================================================================
  // System Status & Connected Accounts
  // =========================================================================

  async checkSystemStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();

      const accPill = document.getElementById("topbar-acc-pill");
      const accText = document.getElementById("acc-pill-text");
      const accLed = document.getElementById("acc-led");
      const sidebarYt = document.getElementById("sidebar-yt-status");
      const sidebarAi = document.getElementById("sidebar-ai-badge");

      if (data.youtube_connected && data.youtube_channel) {
        if (accPill) accPill.className = "acc-pill";
        if (accLed) accLed.className = "led pulse";
        if (accText) accText.textContent = `YouTube: ${data.youtube_channel}`;
        if (sidebarYt) sidebarYt.textContent = "Live";
      } else {
        if (accPill) accPill.className = "acc-pill disconnected";
        if (accLed) accLed.className = "led off";
        if (accText) accText.textContent = "YouTube Not Connected";
        if (sidebarYt) sidebarYt.textContent = "Offline";
      }

      if (sidebarAi) {
        sidebarAi.textContent = (data.ai_provider || "Gemini").toUpperCase();
      }
    } catch (err) {
      console.warn("Status check failed:", err);
    }
  }

  async loadAccounts() {
    try {
      const res = await fetch("/api/accounts");
      this.connectedAccounts = await res.json();
      const select = document.getElementById("mdl-channel-select");
      if (!select) return;
      select.innerHTML = "";

      if (this.connectedAccounts.length === 0) {
        select.innerHTML = '<option value="">No channels connected (Click Connect Channel)</option>';
      } else {
        this.connectedAccounts.forEach(acc => {
          const opt = document.createElement("option");
          opt.value = acc.id;
          opt.textContent = `${acc.name} (${acc.platform.toUpperCase()})`;
          select.appendChild(opt);
        });
      }
    } catch (err) {
      console.warn("Accounts load error:", err);
    }
  }

  // =========================================================================
  // Composer & Media Ingestion (.composer)
  // =========================================================================

  onUrlInput(val) {
    const url = val.trim();
    const lpCard = document.getElementById("lp-card");
    const lpThumb = document.getElementById("lp-thumb");
    const lpTitle = document.getElementById("lp-title");
    const lpChannel = document.getElementById("lp-channel");

    const ytMatch = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})/);
    if (ytMatch) {
      const vidId = ytMatch[1];
      lpThumb.src = `https://img.youtube.com/vi/${vidId}/hqdefault.jpg`;
      lpTitle.textContent = "YouTube Video Stream";
      lpChannel.textContent = `Video ID: ${vidId}`;
      lpCard.classList.add("show");
    } else if (url.includes("twitch.tv")) {
      lpThumb.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='90' fill='%236441a5'><text x='50%' y='50%' fill='%23fff' font-weight='bold' font-size='16' text-anchor='middle'>Twitch Stream</text></svg>";
      lpTitle.textContent = "Twitch Broadcast Stream";
      lpChannel.textContent = url;
      lpCard.classList.add("show");
    } else if (url.length === 0) {
      lpCard.classList.remove("show");
    }
  }

  clearLinkPreview() {
    document.getElementById("composer-url").value = "";
    document.getElementById("lp-card").classList.remove("show");
  }

  selectChip(el, group) {
    const parent = el.parentElement;
    parent.querySelectorAll(".option-chip").forEach(c => c.classList.remove("active"));
    el.classList.add("active");
    if (group === "len") this.selectedLength = el.dataset.len;
    if (group === "font") this.selectedFont = el.dataset.font;
  }

  toggleFacecam(el) {
    this.facecamEnabled = !this.facecamEnabled;
    el.classList.toggle("active", this.facecamEnabled);
  }

  toggleCrop(el) {
    this.cropEnabled = !this.cropEnabled;
    el.classList.toggle("active", this.cropEnabled);
  }

  setupDropzone() {
    window.addEventListener("dragover", e => e.preventDefault());
    window.addEventListener("drop", e => {
      e.preventDefault();
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        this.handleFileSelect(e.dataTransfer.files);
      }
    });
  }

  async submitVideo() {
    const input = document.getElementById("composer-url");
    const url = input.value.trim();
    if (!url) {
      this.showToast("Please paste a valid YouTube or Twitch link.", "error");
      return;
    }

    const creatorId = document.getElementById("composer-creator-select")?.value || null;
    const gameChoice = document.getElementById("composer-game-select")?.value || "auto";
    const layout = this.facecamEnabled ? "split" : (this.cropEnabled ? "crop" : "blur");
    const style = this.selectedFont;

    const payload = {
      url,
      layout,
      style
    };
    if (creatorId) payload.creator_id = creatorId;
    if (gameChoice && gameChoice !== "auto") payload.game = gameChoice;

    const btn = document.getElementById("btn-generate");
    try {
      btn.disabled = true;
      btn.textContent = "Starting...";

      const res = await fetch("/api/jobs/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Submission failed");
      }

      const data = await res.json();
      input.value = "";
      this.clearLinkPreview();
      this.showToast("Job initialized! Ingesting video & audio...", "success");
      this.trackJob(data.job_id);
    } catch (err) {
      this.showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Generate Clips";
    }
  }

  async handleFileSelect(files) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const formData = new FormData();
    formData.append("file", file);

    const creatorId = document.getElementById("composer-creator-select")?.value || null;
    const gameChoice = document.getElementById("composer-game-select")?.value || "auto";
    if (creatorId) formData.append("creator_id", creatorId);
    if (gameChoice && gameChoice !== "auto") formData.append("game", gameChoice);
    formData.append("layout", this.facecamEnabled ? "split" : (this.cropEnabled ? "crop" : "blur"));
    formData.append("style", this.selectedFont);

    try {
      this.showToast(`Uploading ${file.name}...`, "info");
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      this.showToast(`File uploaded! Processing "${data.title}"...`, "success");
      this.trackJob(data.job_id);
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // Real-time Multi-Stage Job Progress (.job-card)
  // =========================================================================

  trackJob(jobId) {
    this.activeJobId = jobId;
    const card = document.getElementById("job-card");
    const fill = document.getElementById("job-fill");
    const pctEl = document.getElementById("job-pct");
    const titleEl = document.getElementById("job-title");
    const msgEl = document.getElementById("job-message");

    card.classList.add("show");
    fill.style.width = "5%";
    pctEl.textContent = "5%";
    msgEl.textContent = "Ingesting media stream...";

    if (this.eventSource) {
      this.eventSource.close();
    }

    this.eventSource = new EventSource(`/api/jobs/${jobId}/events`);

    this.eventSource.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.title) titleEl.textContent = data.title;
      const pct = Math.max(5, data.progress || 0);
      fill.style.width = `${pct}%`;
      pctEl.textContent = `${pct}%`;
      msgEl.textContent = data.message || "Processing audio & video...";

      this.updateJobStages(data.stage);

      if (data.status === "completed") {
        this.eventSource.close();
        this.showToast("All 9:16 Shorts generated successfully!", "success");
        setTimeout(() => {
          card.classList.remove("show");
          this.loadClips();
          this.loadJobs();
        }, 1800);
      } else if (data.status === "failed") {
        this.eventSource.close();
        this.showToast(`Pipeline error: ${data.error || data.message}`, "error");
      }
    };

    this.eventSource.onerror = () => {
      this.pollJob(jobId);
    };
  }

  async pollJob(jobId) {
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) return;
        const data = await res.json();
        const job = data.job;

        const fill = document.getElementById("job-fill");
        const pctEl = document.getElementById("job-pct");
        const msgEl = document.getElementById("job-message");

        const pct = Math.max(5, job.progress || 0);
        fill.style.width = `${pct}%`;
        pctEl.textContent = `${pct}%`;
        msgEl.textContent = job.stage_message || "Processing...";
        this.updateJobStages(job.stage);

        if (job.status === "completed") {
          clearInterval(timer);
          document.getElementById("job-card").classList.remove("show");
          this.loadClips();
          this.loadJobs();
        } else if (job.status === "failed") {
          clearInterval(timer);
          this.showToast(job.error || "Job failed", "error");
        }
      } catch (err) {
        clearInterval(timer);
      }
    }, 2000);
  }

  updateJobStages(stage) {
    const nodes = ["sn-download", "sn-audio", "sn-scout", "sn-render"];
    const stageMap = {
      downloading: 0,
      audio_analysis: 1,
      transcribing: 1,
      ai_scouting: 2,
      rendering: 3,
      done: 4
    };
    const activeIdx = stageMap[stage] !== undefined ? stageMap[stage] : -1;

    nodes.forEach((id, idx) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (idx < activeIdx) {
        el.className = "stage-node done";
      } else if (idx === activeIdx) {
        el.className = "stage-node active";
      } else {
        el.className = "stage-node";
      }
    });
  }

  // =========================================================================
  // Performance Analytics (Feature 8)
  // =========================================================================

  async loadAnalytics() {
    try {
      const res = await fetch("/api/analytics");
      if (!res.ok) return;
      const list = await res.json();
      this.analyticsCache = {};
      list.forEach(a => {
        if (a.clip_id) {
          this.analyticsCache[a.clip_id] = a;
        }
      });
    } catch (err) {
      console.warn("Analytics load error:", err);
    }
  }

  async syncAnalytics() {
    try {
      this.showToast("Syncing live view & like statistics...", "info");
      const res = await fetch("/api/analytics/sync", { method: "POST" });
      if (!res.ok) throw new Error("Sync failed");
      const data = await res.json();
      await this.loadAnalytics();
      this.loadClips();
      this.showToast(`Statistics synced for ${data.synced_count || 0} clips!`, "success");
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // 9:16 Shorts Grid & Card Rendering
  // =========================================================================

  async loadClips() {
    try {
      const res = await fetch("/api/clips");
      const clips = await res.json();
      const grid = document.getElementById("clips-grid");
      const countEl = document.getElementById("clips-total");
      const sideCount = document.getElementById("sidebar-clip-count");

      if (countEl) countEl.textContent = clips.length;
      if (sideCount) sideCount.textContent = clips.length;

      if (!grid) return;
      grid.innerHTML = "";

      if (clips.length === 0) {
        grid.innerHTML = `
          <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; color: var(--faint);">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 12px; color: var(--line-2);"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
            <p style="font-size: 14.5px; font-weight: 500;">No clips generated yet. Paste a video URL or upload a file above.</p>
          </div>
        `;
        return;
      }

      clips.forEach(clip => {
        grid.appendChild(this.buildClipCard(clip));
      });
    } catch (err) {
      console.warn("Clips load error:", err);
    }
  }

  buildClipCard(clip) {
    const card = document.createElement("div");
    card.className = "clip-card";

    const coverUrl = clip.cover_file ? `/clips/${clip.cover_file}` : "";
    const hookText = clip.hook || "WAIT FOR THE END 💀";

    // Detect Hinglish badge
    const isHinglish = clip.is_hinglish || /bhai|kya|yaar|arre|karo|dekho|twist|rukna/i.test(clip.title + " " + hookText);
    const langBadgeHtml = isHinglish
      ? `<span class="shot-hinglish-badge" title="Intelligent Hinglish Generation">🇮🇳 Hinglish</span>`
      : `<span class="shot-hinglish-badge" style="background: rgba(240,240,240,0.9); color: var(--dim);" title="Standard English">🇬🇧 English</span>`;

    // Analytics stats pill if available
    const stats = this.analyticsCache[clip.id];
    let analyticsBadgeHtml = "";
    if (stats && (stats.views > 0 || stats.likes > 0)) {
      analyticsBadgeHtml = `
        <div class="shot-analytics-badge">
          <span>👁️ ${stats.views.toLocaleString()}</span>
          <span>👍 ${stats.likes.toLocaleString()}</span>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="shot-container" onclick="app.openModal('${clip.id}')">
        <img class="shot-img" src="${coverUrl}" alt="${clip.title}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'100\\' height=\\'177\\' fill=\\'%231E1612\\'><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23FF8B33\\' font-size=\\'12\\' font-weight=\\'bold\\' text-anchor=\\'middle\\'>9:16 Short</text></svg>'" />
        
        <!-- Big Text Hook Overlay Banner (Feature 2) -->
        <div class="shot-hook-banner">${hookText}</div>

        <!-- Badges Row -->
        <div class="shot-top-row" style="gap: 6px;">
          ${langBadgeHtml}
          <span class="shot-score-badge">🔥 ${clip.score}/100</span>
        </div>

        ${analyticsBadgeHtml}
        <span class="shot-dur-badge">${clip.duration}s</span>

        <!-- Hover Veil -->
        <div class="shot-veil">
          <div class="play-circle">▶</div>
        </div>
      </div>

      <div class="clip-body">
        <span class="clip-cat-tag">${(clip.category || "HIGHLIGHT").toUpperCase()}</span>
        <h3 class="clip-title" title="${clip.title}">${clip.title}</h3>

        <div class="clip-action-bar">
          <button class="btn btn-subtle btn-sm" style="flex: 1;" onclick="app.openModal('${clip.id}')">
            ✏️ Edit Text
          </button>
          <button class="btn btn-subtle btn-sm" onclick="app.quickRegenSeo('${clip.id}', event)" title="Regenerate AI SEO">
            ✨
          </button>
          <a class="btn btn-subtle btn-sm" href="/clips/${clip.video_file}" download title="Download MP4" onclick="event.stopPropagation()">
            ⬇️
          </a>
        </div>
      </div>
    `;
    return card;
  }

  // =========================================================================
  // Clip Detail, Big Text Editor & Approval Modal
  // =========================================================================

  async openModal(clipId) {
    try {
      const res = await fetch(`/api/clips/${clipId}`);
      if (!res.ok) throw new Error("Clip not found");
      const clip = await res.json();
      this.currentClip = clip;

      const video = document.getElementById("modal-video-player");
      video.src = `/clips/${clip.video_file}?t=${Date.now()}`;

      document.getElementById("mdl-score").textContent = `🔥 ${clip.score}/100`;
      document.getElementById("mdl-cat").textContent = (clip.category || "CLUTCH").toUpperCase();

      // Language Tag
      const isHinglish = clip.is_hinglish || /bhai|kya|yaar|arre|karo|dekho|twist|rukna/i.test(clip.title + " " + (clip.hook || ""));
      const langTag = document.getElementById("mdl-lang-tag");
      if (langTag) {
        langTag.textContent = isHinglish ? "🇮🇳 Hinglish" : "🇬🇧 English";
      }

      document.getElementById("mdl-hook-input").value = clip.hook || "";
      document.getElementById("mdl-layout-select").value = clip.layout || "blur";

      const titleInput = document.getElementById("mdl-title-input");
      titleInput.value = clip.title || "";
      document.getElementById("mdl-title-chars").textContent = (clip.title || "").length;

      document.getElementById("mdl-desc-input").value = clip.description || "";
      document.getElementById("mdl-tags-input").value = (clip.tags || []).join(", ");

      const dlBtn = document.getElementById("btn-dl-mp4");
      dlBtn.href = `/clips/${clip.video_file}`;
      dlBtn.download = `${clip.id}.mp4`;

      // Reset scheduling mode to false
      const schedToggle = document.getElementById("mdl-schedule-toggle");
      if (schedToggle) {
        schedToggle.checked = false;
        this.toggleScheduleMode(false);
      }

      // Set default scheduled time to 24h from now
      const schedInput = document.getElementById("mdl-schedule-time");
      if (schedInput) {
        const d = new Date(Date.now() + 24 * 3600 * 1000);
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        schedInput.value = d.toISOString().slice(0, 16);
      }

      // Reset active platform to youtube
      this.selectUploadPlatform("youtube");

      document.getElementById("clip-modal").style.display = "flex";
      video.play().catch(() => {});
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  closeModal() {
    const video = document.getElementById("modal-video-player");
    video.pause();
    video.src = "";
    document.getElementById("clip-modal").style.display = "none";
    this.currentClip = null;
  }

  setHookPreset(text) {
    document.getElementById("mdl-hook-input").value = text;
  }

  // Feature 2: Fast Big Text Hook Re-burn (< 5 seconds)
  async applyHookFast() {
    if (!this.currentClip) return;
    const btn = document.getElementById("btn-update-hook");
    const hook = document.getElementById("mdl-hook-input").value.trim();
    const layout = document.getElementById("mdl-layout-select").value;
    const style = document.getElementById("mdl-style-select").value;

    if (!hook) {
      this.showToast("Hook banner text cannot be empty.", "error");
      return;
    }

    try {
      btn.disabled = true;
      btn.textContent = "⚡ Fast re-burning video banner...";
      this.showToast("Applying new Big Text Hook (< 5s fast re-burn)...", "info");

      const res = await fetch(`/api/jobs/${this.currentClip.job_id}/clips/${this.currentClip.id}/apply_hook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hook, layout, style })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Fast re-render failed");
      }

      const data = await res.json();
      this.currentClip = data.clip;

      // Update player with fresh video
      const video = document.getElementById("modal-video-player");
      video.src = `/clips/${data.clip.video_file}?t=${Date.now()}`;
      video.play().catch(() => {});

      this.showToast("Big Text Hook updated on video successfully!", "success");
      this.loadClips();
    } catch (err) {
      this.showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "⚡ Apply Big Text to Video (< 5s Fast Re-burn)";
    }
  }

  // Feature 1 & 3: Context-Aware AI SEO (Title, Description, Tags, Hinglish)
  async regenerateSeo() {
    if (!this.currentClip) return;
    try {
      this.showToast("AI analyzing full conversation dynamics for viral SEO...", "info");
      const res = await fetch(`/api/jobs/${this.currentClip.job_id}/clips/${this.currentClip.id}/generate_seo`, {
        method: "POST"
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "SEO generation failed");
      }

      const data = await res.json();
      const seo = data.seo;

      document.getElementById("mdl-hook-input").value = seo.hook;
      document.getElementById("mdl-title-input").value = seo.title;
      document.getElementById("mdl-title-chars").textContent = seo.title.length;
      document.getElementById("mdl-desc-input").value = seo.description;
      document.getElementById("mdl-tags-input").value = (seo.tags || []).join(", ");

      const langTag = document.getElementById("mdl-lang-tag");
      if (langTag) {
        langTag.textContent = seo.is_hinglish ? "🇮🇳 Hinglish" : "🇬🇧 English";
      }

      this.showToast("High-CTR SEO refreshed! Click 'Apply Big Text' to burn the new hook to video.", "success");
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  async quickRegenSeo(clipId, e) {
    e.stopPropagation();
    try {
      this.showToast("Refreshing AI SEO...", "info");
      const res = await fetch(`/api/clips/${clipId}/regenerate-seo`, { method: "POST" });
      if (res.ok) {
        this.showToast("SEO Package updated!", "success");
        this.loadClips();
      }
    } catch (err) {
      this.showToast("SEO update failed", "error");
    }
  }

  // =========================================================================
  // Multi-Platform Publishing & Scheduling (Features 4 & 5)
  // =========================================================================

  selectUploadPlatform(plat) {
    this.selectedPlatform = plat;
    const btnYt = document.getElementById("btn-plat-yt");
    const btnIg = document.getElementById("btn-plat-ig");
    const btnTt = document.getElementById("btn-plat-tt");

    if (btnYt) btnYt.classList.toggle("active-plat", plat === "youtube");
    if (btnIg) btnIg.classList.toggle("active-plat", plat === "instagram");
    if (btnTt) btnTt.classList.toggle("active-plat", plat === "tiktok");

    this.updateUploadButtonText();
  }

  toggleScheduleMode(checked) {
    const box = document.getElementById("schedule-inputs-box");
    if (box) box.style.display = checked ? "block" : "none";
    this.updateUploadButtonText();
  }

  updateUploadButtonText() {
    const btn = document.getElementById("btn-upload-yt");
    if (!btn) return;
    const isScheduled = document.getElementById("mdl-schedule-toggle")?.checked;
    const platName = this.selectedPlatform === "youtube" ? "YouTube Shorts" :
                     this.selectedPlatform === "instagram" ? "Instagram Reels" : "TikTok";

    if (isScheduled) {
      btn.textContent = `📅 Schedule for ${platName}`;
    } else {
      btn.textContent = `🚀 Approve & Upload to ${platName}`;
    }
  }

  async executePublishOrSchedule() {
    if (!this.currentClip) return;
    const channelSelect = document.getElementById("mdl-channel-select");
    const accountId = channelSelect.value;

    const title = document.getElementById("mdl-title-input").value.trim();
    const description = document.getElementById("mdl-desc-input").value.trim();
    const tagsRaw = document.getElementById("mdl-tags-input").value;
    const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);
    const privacy = document.getElementById("mdl-privacy-select").value;

    const isScheduled = document.getElementById("mdl-schedule-toggle")?.checked;
    const btn = document.getElementById("btn-upload-yt");

    // Scheduling flow (Feature 5)
    if (isScheduled) {
      const timeVal = document.getElementById("mdl-schedule-time")?.value;
      if (!timeVal) {
        this.showToast("Please choose a valid publish date and time.", "error");
        return;
      }

      const scheduledUnix = new Date(timeVal).getTime() / 1000;
      if (isNaN(scheduledUnix) || scheduledUnix <= Date.now() / 1000) {
        this.showToast("Scheduled time must be in the future.", "error");
        return;
      }

      try {
        btn.disabled = true;
        btn.textContent = "Scheduling Post...";
        const res = await fetch(`/api/clips/${this.currentClip.id}/schedule`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            platform: this.selectedPlatform,
            account_id: accountId || "default",
            title,
            description,
            tags,
            privacy,
            scheduled_time: scheduledUnix
          })
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Scheduling failed");
        }

        this.showToast(`Post scheduled for ${new Date(timeVal).toLocaleString()}!`, "success");
        this.closeModal();
        await this.loadSchedule();
      } catch (err) {
        this.showToast(err.message, "error");
      } finally {
        btn.disabled = false;
        this.updateUploadButtonText();
      }
      return;
    }

    // Direct Creator Review Multi-Platform Upload flow (Feature 4)
    if (this.selectedPlatform === "youtube" && !accountId) {
      this.showToast("Please connect a YouTube channel first.", "error");
      return;
    }

    try {
      btn.disabled = true;
      btn.textContent = `Publishing to ${this.selectedPlatform.toUpperCase()}...`;
      this.showToast(`Publishing strictly after Creator Approval to ${this.selectedPlatform}...`, "info");

      const res = await fetch(`/api/clips/${this.currentClip.id}/upload-multi`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: this.selectedPlatform,
          account_id: accountId || "default",
          title,
          description,
          tags,
          privacy
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      if (data.result && data.result.url) {
        this.showToast(`Published to ${this.selectedPlatform}! URL: ${data.result.url}`, "success");
        window.open(data.result.url, "_blank");
      } else {
        this.showToast(`Clip successfully uploaded to ${this.selectedPlatform}!`, "success");
      }

      this.closeModal();
      this.loadClips();
    } catch (err) {
      this.showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      this.updateUploadButtonText();
    }
  }

  // =========================================================================
  // Content Calendar View & Dispatcher Queue (Feature 5)
  // =========================================================================

  async loadSchedule() {
    try {
      const res = await fetch("/api/schedule");
      if (!res.ok) return;
      const posts = await res.json();
      const countEl = document.getElementById("sidebar-cal-count");
      if (countEl) countEl.textContent = posts.length;

      const container = document.getElementById("calendar-table-container");
      if (!container) return;

      if (posts.length === 0) {
        container.innerHTML = `
          <div style="text-align: center; padding: 60px 20px; color: var(--faint);">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 12px; color: var(--line-2);"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            <p style="font-size: 14.5px; font-weight: 500;">No scheduled posts in the queue. Open any clip and toggle 'Schedule for Later'.</p>
          </div>
        `;
        return;
      }

      let rowsHtml = "";
      posts.forEach(p => {
        const targetDate = new Date(p.scheduled_time * 1000).toLocaleString();
        const cdSec = p.countdown_seconds || 0;
        let countdownStr = "Ready to publish";
        if (cdSec > 0) {
          const hours = Math.floor(cdSec / 3600);
          const mins = Math.floor((cdSec % 3600) / 60);
          countdownStr = `in ${hours}h ${mins}m`;
        }

        const platClass = p.platform === "youtube" ? "youtube" : (p.platform === "instagram" ? "instagram" : "tiktok");
        const statusClass = p.status || "pending";
        const clipTitle = p.title || (p.clip ? p.clip.title : "Untitled Clip");
        const thumbUrl = p.clip && p.clip.cover_file ? `/clips/${p.clip.cover_file}` : "";

        rowsHtml += `
          <tr>
            <td style="display: flex; align-items: center; gap: 12px;">
              <img src="${thumbUrl}" onerror="this.style.display='none'" style="width: 38px; height: 56px; object-fit: cover; border-radius: 4px; background: #000;" />
              <div>
                <strong style="font-size: 13.5px; color: var(--text);">${clipTitle}</strong>
                <p style="font-size: 11px; color: var(--dim);">Clip ID: ${p.clip_id}</p>
              </div>
            </td>
            <td>
              <span class="badge-plat ${platClass}">${p.platform.toUpperCase()}</span>
            </td>
            <td>
              <span style="font-weight: 600;">${targetDate}</span>
              <p style="font-size: 11px; color: var(--brand-deep);">${countdownStr}</p>
            </td>
            <td>
              <span class="badge-status ${statusClass}">${statusClass.toUpperCase()}</span>
            </td>
            <td>
              <button class="btn btn-subtle btn-sm" onclick="app.cancelScheduledPost('${p.id}')">Cancel</button>
            </td>
          </tr>
        `;
      });

      container.innerHTML = `
        <table class="sched-table">
          <thead>
            <tr>
              <th>Short / Video</th>
              <th>Platform</th>
              <th>Scheduled Time</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
      `;
    } catch (err) {
      console.warn("Schedule load error:", err);
    }
  }

  async cancelScheduledPost(postId) {
    try {
      const res = await fetch(`/api/schedule/${postId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to cancel");
      this.showToast("Scheduled post cancelled.", "info");
      await this.loadSchedule();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // Channel Keyword & Niche Research (Feature 8)
  // =========================================================================

  async runKeywordResearch() {
    const input = document.getElementById("research-topic-input");
    const topic = input ? input.value.trim() : "";
    if (!topic) {
      this.showToast("Please enter a channel topic or niche.", "error");
      return;
    }

    const container = document.getElementById("research-results-area");
    if (!container) return;

    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--dim);">
        <div class="job-icon-pulse" style="margin: 0 auto 12px auto;"></div>
        <p>AI analyzing YouTube trends, search volume, and high-CTR hooks for "${topic}"...</p>
      </div>
    `;

    try {
      const res = await fetch("/api/research/keywords", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, niche: topic })
      });

      if (!res.ok) throw new Error("Keyword research failed");
      const data = await res.json();
      const r = data.research;

      let tagsHtml = "";
      (r.trending_tags || []).forEach(tag => {
        tagsHtml += `<span class="keyword-pill" onclick="navigator.clipboard.writeText('${tag}'); app.showToast('Copied tag ${tag}!', 'success');">${tag}</span>`;
      });

      let kwHtml = "";
      (r.target_keywords || []).forEach(kw => {
        kwHtml += `<span class="keyword-pill" onclick="navigator.clipboard.writeText('${kw}'); app.showToast('Copied keyword ${kw}!', 'success');">${kw}</span>`;
      });

      let anglesHtml = "";
      (r.viral_angles || []).forEach(angle => {
        anglesHtml += `
          <div class="angle-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <strong style="font-size: 14px; color: var(--brand-deep);">${angle.title}</strong>
              <span class="shot-score-badge" style="background: var(--brand-soft); color: var(--brand-deep);">${angle.emotion}</span>
            </div>
            <p style="font-size: 12.5px; color: var(--dim); margin: 2px 0;"><strong>Hook:</strong> "${angle.hook}"</p>
          </div>
        `;
      });

      container.innerHTML = `
        <div style="display: flex; flex-direction: column; gap: 24px;">
          <div class="panel-box">
            <span class="panel-title">🔥 10–15 High-Ranking YouTube Keywords (Click to Copy)</span>
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;">
              ${kwHtml}
            </div>
          </div>

          <div class="panel-box">
            <span class="panel-title">🏷️ Trending Hashtags</span>
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px;">
              ${tagsHtml}
            </div>
          </div>

          <div class="panel-box">
            <span class="panel-title">💡 High-CTR Viral Video Angles &amp; Hook Concepts</span>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; margin-top: 8px;">
              ${anglesHtml}
            </div>
          </div>
        </div>
      `;
    } catch (err) {
      this.showToast(err.message, "error");
      container.innerHTML = `<p style="color: var(--bad); padding: 20px;">Research failed: ${err.message}</p>`;
    }
  }

  // =========================================================================
  // Recent Jobs Activity View
  // =========================================================================

  async loadJobs() {
    try {
      const res = await fetch("/api/jobs");
      const jobs = await res.json();
      const countEl = document.getElementById("sidebar-job-count");
      if (countEl) countEl.textContent = jobs.length;

      const container = document.getElementById("jobs-list-container");
      if (!container) return;

      if (jobs.length === 0) {
        container.innerHTML = `
          <div style="text-align: center; padding: 40px; color: var(--faint);">
            <p>No video jobs yet.</p>
          </div>
        `;
        return;
      }

      let html = "";
      jobs.forEach(j => {
        const isDone = j.status === "completed";
        const isFailed = j.status === "failed";
        const statusColor = isDone ? "var(--good)" : (isFailed ? "var(--bad)" : "var(--brand)");
        const statusBg = isDone ? "var(--good-soft)" : (isFailed ? "var(--bad-soft)" : "var(--brand-soft)");

        html += `
          <div class="job-row">
            <div>
              <strong style="font-size: 14px; color: var(--text);">${j.title || "Untitled"}</strong>
              <p style="font-size: 11.5px; color: var(--dim); margin-top: 2px;">
                ID: ${j.id} • ${j.source_type} • ${new Date((j.created_at || Date.now()) * 1000).toLocaleTimeString()}
              </p>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 100px; height: 6px; background: var(--line-2); border-radius: 3px; overflow: hidden;">
                <div style="height: 100%; width: ${j.progress || 0}%; background: ${statusColor};"></div>
              </div>
              <span class="badge-status" style="background: ${statusBg}; color: ${statusColor}; font-weight: 700;">
                ${(j.status || "QUEUED").toUpperCase()}
              </span>
            </div>
          </div>
        `;
      });
      container.innerHTML = html;
    } catch (err) {
      console.warn("Jobs load error:", err);
    }
  }

  connectYouTube() {
    window.location.href = "/oauth/youtube/connect";
  }

  // =========================================================================
  // Settings & Configuration
  // =========================================================================

  async openSettings(tab) {
    try {
      const res = await fetch("/api/settings");
      const data = await res.json();
      document.getElementById("cfg-ai-provider").value = data.ai_provider || "gemini";
      document.getElementById("cfg-ai-model").value = data.ai_model || "gemini-2.5-flash";
      const chainEl = document.getElementById("cfg-ai-chain");
      if (chainEl) chainEl.value = data.ai_models_chain || "";
      document.getElementById("cfg-client-id").value = data.google_client_id || "";
      
      const appToggle = document.getElementById("cfg-require-approval");
      if (appToggle) {
        appToggle.checked = data.require_approval !== false;
      }

      await this.loadAiUsage();
      await this.loadStorageInfo();

      document.getElementById("settings-modal").style.display = "flex";
    } catch (err) {
      this.showToast("Could not load settings", "error");
    }
  }

  closeSettings() {
    document.getElementById("settings-modal").style.display = "none";
  }

  async saveSettings() {
    const ai_provider = document.getElementById("cfg-ai-provider").value;
    const ai_model = document.getElementById("cfg-ai-model").value;
    const ai_key = document.getElementById("cfg-ai-key").value;
    const ai_models_chain = document.getElementById("cfg-ai-chain")?.value.trim();
    const google_client_id = document.getElementById("cfg-client-id").value;
    const google_client_secret = document.getElementById("cfg-client-secret").value;
    const require_approval = document.getElementById("cfg-require-approval")?.checked;

    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ai_provider,
          ai_model,
          ai_key,
          ai_models_chain,
          google_client_id,
          google_client_secret,
          require_approval
        })
      });

      if (!res.ok) throw new Error("Failed to save settings");
      this.showToast("Settings saved successfully!", "success");
      this.closeSettings();
      await this.checkSystemStatus();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // Feature 1: Live Stream Ingest & Real-Time Clipping (.live-telemetry)
  // =========================================================================

  async startLiveStream() {
    const streamUrl = document.getElementById("live-stream-url")?.value.trim();
    if (!streamUrl) {
      this.showToast("Please provide a Twitch, YouTube Live, or Kick URL.", "error");
      return;
    }
    const creatorId = document.getElementById("live-creator-select")?.value || null;

    try {
      this.showToast("Connecting to live stream...", "info");
      const res = await fetch("/api/live/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stream_url: streamUrl, creator_id: creatorId })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start live ingest");
      }
      const data = await res.json();
      this.showToast("Live stream ingest active! Rolling buffer started.", "success");
      this.renderLiveStatus(data.session);
      this.startLivePolling();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  async stopLiveStream() {
    try {
      const res = await fetch("/api/live/stop", { method: "POST" });
      if (!res.ok) throw new Error("Failed to stop live session");
      const data = await res.json();
      this.showToast("Live stream session stopped.", "info");
      this.stopLivePolling();
      await this.loadLiveStatus();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  startLivePolling() {
    if (this.livePollInterval) clearInterval(this.livePollInterval);
    this.livePollInterval = setInterval(() => {
      if (this.currentTab === "live") {
        this.loadLiveStatus();
      }
    }, 1500);
  }

  stopLivePolling() {
    if (this.livePollInterval) {
      clearInterval(this.livePollInterval);
      this.livePollInterval = null;
    }
  }

  async loadLiveStatus() {
    try {
      const res = await fetch("/api/live/status");
      if (!res.ok) return;
      const data = await res.json();
      this.renderLiveStatus(data);
    } catch (err) {
      console.warn("Live status poll failed:", err);
    }
  }

  renderLiveStatus(data) {
    if (!data) return;
    const isActive = !!data.active;
    
    // Status Pill & Sidebar Badge
    const pill = document.getElementById("live-status-pill");
    const sidebarBadge = document.getElementById("sidebar-live-status");
    const startBtn = document.getElementById("btn-live-start");
    const stopBtn = document.getElementById("btn-live-stop");

    if (pill) {
      pill.textContent = isActive ? "🔴 LIVE INGESTING" : "STANDBY";
      pill.className = isActive ? "live-status-pill active" : "live-status-pill";
    }
    if (sidebarBadge) {
      sidebarBadge.textContent = isActive ? "REC" : "OFF";
      sidebarBadge.style.background = isActive ? "rgba(211,52,63,0.3)" : "";
      sidebarBadge.style.color = isActive ? "var(--bad)" : "";
    }
    if (startBtn && stopBtn) {
      startBtn.style.display = isActive ? "none" : "inline-flex";
      stopBtn.style.display = isActive ? "inline-flex" : "none";
    }

    // Buffer duration & chunks
    const durSec = data.buffer_duration_sec || 0;
    const mins = Math.floor(durSec / 60);
    const secs = Math.floor(durSec % 60);
    const durEl = document.getElementById("live-buffer-dur");
    if (durEl) {
      durEl.textContent = `${mins}m ${secs < 10 ? '0' : ''}${secs}s / 15m`;
    }

    const chunksEl = document.getElementById("live-buffer-chunks");
    if (chunksEl) chunksEl.textContent = data.chunks_count || 0;

    const bufferFill = document.getElementById("live-buffer-fill");
    if (bufferFill) {
      const pct = Math.min(100, Math.round((durSec / 900) * 100));
      bufferFill.style.width = `${pct}%`;
    }

    // Chat velocity
    const velocity = data.chat_velocity || 0;
    const velBadge = document.getElementById("live-velocity-badge");
    const velText = document.getElementById("live-chat-rate-txt");
    const velFill = document.getElementById("live-velocity-fill");

    if (velBadge) velBadge.textContent = `${velocity.toFixed(1)} msg/s`;
    if (velText) {
      if (velocity >= 4.0) {
        velText.textContent = "🔥 HYPE SPIKE (Clipping!)";
        velText.style.color = "var(--bad)";
      } else if (velocity >= 2.0) {
        velText.textContent = "⚡ Active Chat Movement";
        velText.style.color = "var(--brand)";
      } else {
        velText.textContent = "Normal Activity";
        velText.style.color = "var(--text)";
      }
    }
    if (velFill) {
      const velPct = Math.min(100, Math.round((velocity / 6.0) * 100));
      velFill.style.width = `${velPct}%`;
    }

    // Highlight trigger phrases
    const recentTriggers = data.recent_triggers || [];
    const triggerPills = document.querySelectorAll("#live-trigger-pills .trigger-pill");
    triggerPills.forEach(p => {
      const txt = p.textContent.toLowerCase();
      const isHit = recentTriggers.some(t => t.toLowerCase().includes(txt));
      if (isHit) {
        p.classList.add("hit");
      } else {
        p.classList.remove("hit");
      }
    });

    // Captured clips counter
    const clipsTotal = document.getElementById("live-clips-total");
    if (clipsTotal) clipsTotal.textContent = data.clips_captured || 0;
  }

  async sendSimulatedChat() {
    const input = document.getElementById("live-chat-sim-input");
    const msg = input?.value.trim();
    if (!msg) return;
    try {
      const res = await fetch("/api/live/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, username: "studio_tester" })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Chat simulation failed");
      }
      input.value = "";
      this.showToast(`Simulated: "${msg}"`, "info");
      await this.loadLiveStatus();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  async triggerLiveClip() {
    try {
      this.showToast("Extracting moment from rolling disk buffer...", "info");
      const res = await fetch("/api/live/clip", { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Clip trigger failed");
      }
      const data = await res.json();
      this.showToast("Viral moment extracted from live buffer!", "success");
      await this.loadClips();
      await this.loadLiveStatus();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // Feature 3: Creator Workspaces & Channel Profiles (.creators-grid)
  // =========================================================================

  async loadCreators() {
    try {
      const res = await fetch("/api/creators");
      if (!res.ok) return;
      this.creatorsList = await res.json();

      // Update sidebar counter
      const sideEl = document.getElementById("sidebar-creators-count");
      if (sideEl) sideEl.textContent = this.creatorsList.length;

      // Update composer creator selector
      const compSelect = document.getElementById("composer-creator-select");
      const liveSelect = document.getElementById("live-creator-select");
      if (compSelect) {
        compSelect.innerHTML = `<option value="">Default Profile</option>` +
          this.creatorsList.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
      }
      if (liveSelect) {
        liveSelect.innerHTML = `<option value="">Select Creator Workspace</option>` +
          this.creatorsList.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
      }

      // Render creator cards
      const grid = document.getElementById("creators-grid");
      if (!grid) return;

      if (this.creatorsList.length === 0) {
        grid.innerHTML = `
          <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--dim); background: var(--bg); border: 1px dashed var(--line); border-radius: var(--r);">
            <p>No creator workspaces created yet.</p>
            <button class="btn btn-brand btn-sm" style="margin-top: 12px;" onclick="app.openCreatorModal()">➕ Create First Creator Profile</button>
          </div>
        `;
        return;
      }

      grid.innerHTML = this.creatorsList.map(c => {
        const ch = c.channels || {};
        let chBadges = "";
        if (ch.youtube) chBadges += `<span class="channel-badge yt">🔴 ${ch.youtube}</span>`;
        if (ch.twitch) chBadges += `<span class="channel-badge twitch">👾 ${ch.twitch}</span>`;
        if (ch.kick) chBadges += `<span class="channel-badge kick">🟩 ${ch.kick}</span>`;
        if (ch.tiktok) chBadges += `<span class="channel-badge tt">🎵 ${ch.tiktok}</span>`;
        if (ch.instagram) chBadges += `<span class="channel-badge ig">📸 ${ch.instagram}</span>`;
        if (!chBadges) chBadges = `<span style="font-size: 11px; color: var(--faint);">No linked channels</span>`;

        const autopostBadge = c.autopost ?
          `<span class="badge-status" style="background: var(--good-soft); color: var(--good);">Auto-Post: ON</span>` :
          `<span class="badge-status" style="background: var(--muted); color: var(--dim);">Auto-Post: OFF</span>`;

        return `
          <div class="creator-card">
            <div>
              <div class="creator-header">
                <div>
                  <h3 class="creator-title">${c.name}</h3>
                  <span class="creator-id-badge">${c.id}</span>
                </div>
                ${autopostBadge}
              </div>

              <div class="creator-channels-row">
                ${chBadges}
              </div>

              <div class="creator-specs">
                <div>Style: <strong>${c.style}</strong></div>
                <div>Layout: <strong>${c.layout}</strong></div>
                <div>Length: <strong>${c.min_len}s–${c.max_len}s</strong></div>
                <div>Min Score: <strong>🔥 ${c.min_score}+</strong></div>
                <div>Daily Cap: <strong>${c.daily_cap} / day</strong></div>
                <div>Post Gap: <strong>≥ ${c.post_gap_min} min</strong></div>
              </div>

              ${c.default_tags && c.default_tags.length ? `
                <div style="font-size: 11px; color: var(--faint); margin-top: 4px;">
                  Tags: ${c.default_tags.slice(0, 4).join(", ")}${c.default_tags.length > 4 ? "..." : ""}
                </div>
              ` : ""}
            </div>

            <div class="creator-card-actions">
              <button class="btn btn-subtle btn-sm" style="flex: 1;" onclick="app.openCreatorModal('${c.id}')">✏️ Edit</button>
              <button class="btn btn-subtle btn-sm" style="color: var(--bad);" onclick="app.deleteCreator('${c.id}')">🗑️ Delete</button>
            </div>
          </div>
        `;
      }).join("");

    } catch (err) {
      console.warn("Load creators failed:", err);
    }
  }

  openCreatorModal(creatorId = null) {
    const title = document.getElementById("creator-modal-title");
    const editIdInput = document.getElementById("creator-edit-id");

    if (creatorId) {
      const creator = this.creatorsList.find(c => c.id === creatorId);
      if (creator) {
        if (title) title.textContent = `Edit Workspace: ${creator.name}`;
        if (editIdInput) editIdInput.value = creator.id;
        document.getElementById("cr-name").value = creator.name || "";
        document.getElementById("cr-yt").value = creator.channels?.youtube || "";
        document.getElementById("cr-twitch").value = creator.channels?.twitch || "";
        document.getElementById("cr-kick").value = creator.channels?.kick || "";
        document.getElementById("cr-tiktok").value = creator.channels?.tiktok || "";
        document.getElementById("cr-style").value = creator.style || "bounce";
        document.getElementById("cr-layout").value = creator.layout || "split";
        document.getElementById("cr-min-len").value = creator.min_len || 15;
        document.getElementById("cr-max-len").value = creator.max_len || 60;
        document.getElementById("cr-min-score").value = creator.min_score || 80;
        document.getElementById("cr-autopost").checked = !!creator.autopost;
        document.getElementById("cr-daily-cap").value = creator.daily_cap || 5;
        document.getElementById("cr-post-gap").value = creator.post_gap_min || 45;
        document.getElementById("cr-tags").value = (creator.default_tags || []).join(", ");
      }
    } else {
      if (title) title.textContent = "New Creator Workspace";
      if (editIdInput) editIdInput.value = "";
      document.getElementById("cr-name").value = "";
      document.getElementById("cr-yt").value = "";
      document.getElementById("cr-twitch").value = "";
      document.getElementById("cr-kick").value = "";
      document.getElementById("cr-tiktok").value = "";
      document.getElementById("cr-style").value = "bounce";
      document.getElementById("cr-layout").value = "split";
      document.getElementById("cr-min-len").value = 15;
      document.getElementById("cr-max-len").value = 60;
      document.getElementById("cr-min-score").value = 80;
      document.getElementById("cr-autopost").checked = false;
      document.getElementById("cr-daily-cap").value = 5;
      document.getElementById("cr-post-gap").value = 45;
      document.getElementById("cr-tags").value = "";
    }

    document.getElementById("creator-modal").style.display = "flex";
  }

  closeCreatorModal() {
    document.getElementById("creator-modal").style.display = "none";
  }

  async saveCreator() {
    const editId = document.getElementById("creator-edit-id")?.value;
    const name = document.getElementById("cr-name")?.value.trim();
    if (!name) {
      this.showToast("Creator name is required.", "error");
      return;
    }

    const channels = {};
    const yt = document.getElementById("cr-yt")?.value.trim();
    const twitch = document.getElementById("cr-twitch")?.value.trim();
    const kick = document.getElementById("cr-kick")?.value.trim();
    const tiktok = document.getElementById("cr-tiktok")?.value.trim();
    if (yt) channels.youtube = yt;
    if (twitch) channels.twitch = twitch;
    if (kick) channels.kick = kick;
    if (tiktok) channels.tiktok = tiktok;

    const style = document.getElementById("cr-style")?.value || "bounce";
    const layout = document.getElementById("cr-layout")?.value || "split";
    const min_len = parseInt(document.getElementById("cr-min-len")?.value, 10) || 15;
    const max_len = parseInt(document.getElementById("cr-max-len")?.value, 10) || 60;
    const min_score = parseInt(document.getElementById("cr-min-score")?.value, 10) || 80;
    const autopost = document.getElementById("cr-autopost")?.checked || false;
    const daily_cap = parseInt(document.getElementById("cr-daily-cap")?.value, 10) || 5;
    const post_gap_min = parseInt(document.getElementById("cr-post-gap")?.value, 10) || 45;
    const tagsRaw = document.getElementById("cr-tags")?.value.trim();
    const default_tags = tagsRaw ? tagsRaw.split(",").map(t => t.trim()).filter(Boolean) : [];

    const payload = {
      name,
      channels,
      style,
      layout,
      min_len,
      max_len,
      min_score,
      autopost,
      daily_cap,
      post_gap_min,
      default_tags
    };

    try {
      let res;
      if (editId) {
        res = await fetch(`/api/creators/${editId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch("/api/creators", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
      }

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to save creator workspace");
      }

      this.showToast(`Creator workspace "${name}" saved!`, "success");
      this.closeCreatorModal();
      await this.loadCreators();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  async deleteCreator(creatorId) {
    if (!confirm(`Are you sure you want to delete this creator profile?`)) return;
    try {
      const res = await fetch(`/api/creators/${creatorId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      this.showToast("Creator workspace removed.", "info");
      await this.loadCreators();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  onCreatorSelected(creatorId) {
    if (!creatorId) return;
    const c = this.creatorsList.find(cr => cr.id === creatorId);
    if (!c) return;

    // Apply creator preferences to composer options
    if (c.style) {
      const fontChip = document.querySelector(`.option-chip[data-font="${c.style}"]`);
      if (fontChip) this.selectChip(fontChip, 'font');
    }
    if (c.layout === "crop") {
      const cropChip = document.getElementById("chip-crop");
      if (cropChip) this.toggleCrop(cropChip);
    } else if (c.layout === "split") {
      const faceChip = document.getElementById("chip-facecam");
      if (faceChip && !this.facecamEnabled) this.toggleFacecam(faceChip);
    }
  }

  // =========================================================================
  // Feature 2: Multi-Platform Auto-Posting & Scheduling Queue (.queue-view)
  // =========================================================================

  async loadPostQueue() {
    try {
      const res = await fetch("/api/posts/queue");
      if (!res.ok) return;
      const posts = await res.json();

      // Stats counters
      let total = posts.length;
      let scheduled = 0;
      let published = 0;
      let failed = 0;

      posts.forEach(p => {
        const st = (p.status || "").toLowerCase();
        if (st === "scheduled" || st === "queued") scheduled++;
        else if (st === "published") published++;
        else if (st === "failed") failed++;
      });

      const totalEl = document.getElementById("queue-count-total");
      const schedEl = document.getElementById("queue-count-scheduled");
      const pubEl = document.getElementById("queue-count-published");
      const failEl = document.getElementById("queue-count-failed");
      const sideEl = document.getElementById("sidebar-queue-count");

      if (totalEl) totalEl.textContent = total;
      if (schedEl) schedEl.textContent = scheduled;
      if (pubEl) pubEl.textContent = published;
      if (failEl) failEl.textContent = failed;
      if (sideEl) sideEl.textContent = scheduled;

      const container = document.getElementById("queue-table-container");
      if (!container) return;

      if (posts.length === 0) {
        container.innerHTML = `
          <div style="padding: 40px; text-align: center; color: var(--dim);">
            <p>Queue is empty. Approve and schedule clips from the Shorts Clips tab or enable Auto-Post on a Creator profile.</p>
          </div>
        `;
        return;
      }

      let html = `
        <table class="sched-table">
          <thead>
            <tr>
              <th>Clip Title</th>
              <th>Platform</th>
              <th>Channel / Account</th>
              <th>Publish Timing</th>
              <th>Status</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
      `;

      posts.forEach(p => {
        const diff = (p.scheduled_time || 0) - (Date.now() / 1000);
        let countdown = "Due now";
        if (diff > 0) {
          const m = Math.floor(diff / 60);
          const s = Math.floor(diff % 60);
          countdown = `in ${m}m ${s < 10 ? '0' : ''}${s}s`;
        }
        const timeStr = new Date((p.scheduled_time || 0) * 1000).toLocaleString();

        const plat = (p.platform || "youtube").toLowerCase();
        const platBadge = plat === "youtube" ? `<span class="badge-plat youtube">🔴 Shorts</span>` :
                          plat === "instagram" ? `<span class="badge-plat instagram">📸 Reels</span>` :
                          `<span class="badge-plat tiktok">🎵 TikTok</span>`;

        const st = (p.status || "queued").toLowerCase();
        const statusBadge = `<span class="status-badge ${st}">${st}</span>`;

        html += `
          <tr>
            <td>
              <strong style="color: var(--text);">${p.title || "Untitled Short"}</strong>
              ${p.error ? `<div style="color: var(--bad); font-size: 11px; margin-top: 2px;">⚠️ ${p.error}</div>` : ""}
            </td>
            <td>${platBadge}</td>
            <td style="color: var(--dim);">${p.account_id || p.channel || "Default"}</td>
            <td>
              <div>${countdown}</div>
              <div style="font-size: 11px; color: var(--faint);">${timeStr}</div>
            </td>
            <td>${statusBadge}</td>
            <td style="text-align: right;">
              <button class="btn btn-subtle btn-sm" onclick="app.publishPostNow('${p.id}')" title="Publish Immediately">🚀 Publish Now</button>
              <button class="btn btn-subtle btn-sm" style="color: var(--bad);" onclick="app.deleteQueuePost('${p.id}')" title="Delete">🗑️</button>
            </td>
          </tr>
        `;
      });

      html += `</tbody></table>`;
      container.innerHTML = html;

    } catch (err) {
      console.warn("Load post queue failed:", err);
    }
  }

  async publishPostNow(postId) {
    try {
      this.showToast("Publishing post now...", "info");
      const res = await fetch(`/api/posts/${postId}/publish`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Publish failed");
      }
      this.showToast("Post dispatched for immediate publishing!", "success");
      await this.loadPostQueue();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  async deleteQueuePost(postId) {
    if (!confirm("Cancel and delete this queued post?")) return;
    try {
      const res = await fetch(`/api/posts/${postId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      this.showToast("Post removed from queue.", "info");
      await this.loadPostQueue();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }

  // =========================================================================
  // Feature 5 & 6: AI Usage Analytics & Storage Safety
  // =========================================================================

  async loadAiUsage() {
    try {
      const res = await fetch("/api/settings/ai-usage");
      if (!res.ok) return;
      const data = await res.json();

      const tokensEl = document.getElementById("usage-total-tokens");
      const costEl = document.getElementById("usage-total-cost");
      if (tokensEl) tokensEl.textContent = (data.total_tokens || 0).toLocaleString();
      if (costEl) costEl.textContent = `$${(data.total_cost || 0).toFixed(4)}`;

      const container = document.getElementById("settings-ai-usage-container");
      if (container && data.records && data.records.length > 0) {
        let tableHtml = `
          <div style="display: flex; gap: 12px; font-size: 12px; color: var(--dim); margin-bottom: 6px;">
            <span>Total Tokens: <strong style="color: var(--text);">${(data.total_tokens || 0).toLocaleString()}</strong></span>
            <span>Est. Cost: <strong style="color: var(--good);">$${(data.total_cost || 0).toFixed(4)}</strong></span>
          </div>
          <table class="usage-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
        `;
        data.records.slice(0, 5).forEach(r => {
          tableHtml += `
            <tr>
              <td>${r.provider}</td>
              <td>${r.model}</td>
              <td>${(r.total_tokens || 0).toLocaleString()}</td>
              <td>$${(r.estimated_cost || 0).toFixed(4)}</td>
            </tr>
          `;
        });
        tableHtml += `</tbody></table>`;
        container.innerHTML = tableHtml;
      }
    } catch (err) {
      console.warn("AI usage fetch error:", err);
    }
  }

  async loadStorageInfo() {
    try {
      const res = await fetch("/api/storage/info");
      if (!res.ok) return;
      const data = await res.json();

      const freeEl = document.getElementById("storage-free-txt");
      const totalEl = document.getElementById("storage-total-txt");
      const pathEl = document.getElementById("cfg-storage-path");
      const fillEl = document.getElementById("storage-bar-fill");
      const pill = document.getElementById("storage-status-pill");

      if (freeEl) freeEl.textContent = `${data.free_gb} GB`;
      if (totalEl) totalEl.textContent = `${data.total_gb} GB`;
      if (pathEl) pathEl.value = data.data_dir || "";

      if (fillEl) {
        fillEl.style.width = `${data.percent_used || 0}%`;
        fillEl.style.background = data.warning ? "var(--bad)" : "var(--brand)";
      }

      if (pill) {
        if (data.warning) {
          pill.textContent = "⚠️ LOW DISK (<5GB)";
          pill.className = "live-status-pill active";
        } else {
          pill.textContent = "HEALTHY";
          pill.className = "live-status-pill";
        }
      }
    } catch (err) {
      console.warn("Storage info fetch error:", err);
    }
  }

  async moveDataStorage() {
    const targetPath = document.getElementById("cfg-new-storage-path")?.value.trim();
    if (!targetPath) {
      this.showToast("Please enter a new target directory path.", "error");
      return;
    }
    try {
      this.showToast("Migrating data directory...", "info");
      const res = await fetch("/api/storage/move-data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_path: targetPath })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Data move failed");
      }
      this.showToast(`Storage migrated to ${targetPath}!`, "success");
      document.getElementById("cfg-new-storage-path").value = "";
      await this.loadStorageInfo();
    } catch (err) {
      this.showToast(err.message, "error");
    }
  }
}

const PeakCutApp = ClipItApp;
const ClipItUpApp = ClipItApp;
const app = new ClipItApp();
document.addEventListener("DOMContentLoaded", () => app.init());
