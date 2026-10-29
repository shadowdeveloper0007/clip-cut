/* ========================================
   ClipClean — Application Logic
   ======================================== */

(function () {
  'use strict';

  // ── Constants ──────────────────────────
  const ALLOWED_EXTENSIONS = ['mp4', 'mov', 'mkv', 'webm'];
  const MAX_FILE_SIZE = 1 * 1024 * 1024 * 1024; // 1 GB
  const POLL_INTERVAL_MS = 2000;
  const STEP_ORDER = [
    'uploading',
    'validating',
    'analyzing',
    'processing',
    'finalizing',
    'completed',
  ];

  // ── State ──────────────────────────────
  let state = 'idle'; // idle | uploading | processing | completed | failed
  let selectedFile = null;
  let replacementAudio = null;
  let srtContent = null;
  let currentJobId = null;
  let pollTimer = null;
  let elapsedTimer = null;
  let processingStartTime = null;

  // ── DOM References ─────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const dom = {
    statusDot: $('#statusDot'),
    statusLabel: $('#statusLabel'),
    dropZone: $('#dropZone'),
    fileInput: $('#fileInput'),
    fileInfo: $('#fileInfo'),
    fileName: $('#fileName'),
    fileMeta: $('#fileMeta'),
    fileRemove: $('#fileRemove'),
    advancedSection: $('#advancedSection'),
    advancedToggle: $('#advancedToggle'),
    advancedBody: $('#advancedBody'),
    splitModeSelect: $('#splitModeSelect'),
    customPartsGroup: $('#customPartsGroup'),
    customPartsInput: $('#customPartsInput'),
    btnModeDropdown: $('#btnModeDropdown'),
    btnModeManual: $('#btnModeManual'),
    clipDropdownControls: $('#clipDropdownControls'),
    clipManualControls: $('#clipManualControls'),
    clipStartMin: $('#clipStartMin'),
    clipStartSec: $('#clipStartSec'),
    clipEndMin: $('#clipEndMin'),
    clipEndSec: $('#clipEndSec'),
    clipStart: $('#clipStart'),
    clipEnd: $('#clipEnd'),
    preset60sBtn: $('#preset60sBtn'),
    preset30sBtn: $('#preset30sBtn'),
    clearClipBtn: $('#clearClipBtn'),
    trimStart: $('#trimStart'),
    trimEnd: $('#trimEnd'),
    audioInput: $('#audioInput'),
    audioFileName: $('#audioFileName'),
    audioRemove: $('#audioRemove'),
    muteStart: $('#muteStart'),
    muteEnd: $('#muteEnd'),
    srtInput: $('#srtInput'),
    srtFileName: $('#srtFileName'),
    srtRemove: $('#srtRemove'),
    actionBar: $('#actionBar'),
    processBtn: $('#processBtn'),
    uploadSection: $('#uploadSection'),
    processingSection: $('#processingSection'),
    elapsedTime: $('#elapsedTime'),
    progressBarFill: $('#progressBarFill'),
    progressPercent: $('#progressPercent'),
    statusSteps: $('#statusSteps'),
    statusMessage: $('#statusMessage'),
    errorSection: $('#errorSection'),
    errorMessage: $('#errorMessage'),
    errorRetryBtn: $('#errorRetryBtn'),
    resultSection: $('#resultSection'),
    resultFilename: $('#resultFilename'),
    resultDuration: $('#resultDuration'),
    resultSize: $('#resultSize'),
    multiPartSection: $('#multiPartSection'),
    partsList: $('#partsList'),
    downloadBtn: $('#downloadBtn'),
    processAnotherBtn: $('#processAnotherBtn'),
  };

  // ── Utilities ──────────────────────────
  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
  }

  function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '—';
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
  }

  function formatElapsed(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  function getExtension(filename) {
    return (filename || '').split('.').pop().toLowerCase();
  }

  function show(el) {
    el.hidden = false;
  }

  function hide(el) {
    el.hidden = true;
  }

  // ── Health Check ───────────────────────
  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('Health check failed');
      const data = await res.json();
      dom.statusDot.className = 'status-dot online';
      const parts = [];
      if (data.version) parts.push('v' + data.version);
      if (data.ffmpeg_available) parts.push('FFmpeg ✓');
      if (data.ai_available) parts.push('AI ✓');
      dom.statusLabel.textContent =
        parts.length > 0 ? 'Engine ready · ' + parts.join(' · ') : 'Engine ready';
    } catch {
      dom.statusDot.className = 'status-dot offline';
      dom.statusLabel.textContent = 'Engine offline';
    }
  }

  // ── File Selection ─────────────────────
  function validateFile(file) {
    if (!file) return 'No file selected.';
    const ext = getExtension(file.name);
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `Unsupported format ".${ext}". Please use ${ALLOWED_EXTENSIONS.join(', ').toUpperCase()}.`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File too large (${formatBytes(file.size)}). Maximum size is 1 GB.`;
    }
    return null;
  }

  function selectFile(file) {
    const error = validateFile(file);
    if (error) {
      showError(error);
      return;
    }
    selectedFile = file;
    dom.fileName.textContent = file.name;
    dom.fileMeta.textContent = formatBytes(file.size);
    show(dom.fileInfo);
    show(dom.advancedSection);
    show(dom.actionBar);
    dom.processBtn.disabled = false;
    hideError();
  }

  function clearFile() {
    selectedFile = null;
    dom.fileInput.value = '';
    hide(dom.fileInfo);
    hide(dom.advancedSection);
    hide(dom.actionBar);
    dom.processBtn.disabled = true;
  }

  // ── Audio / SRT Handling ───────────────
  function selectAudio(file) {
    if (!file) return;
    replacementAudio = file;
    dom.audioFileName.textContent = file.name;
    show(dom.audioRemove);
  }

  function clearAudio() {
    replacementAudio = null;
    dom.audioInput.value = '';
    dom.audioFileName.textContent = 'No file chosen';
    hide(dom.audioRemove);
  }

  function selectSrt(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      srtContent = e.target.result;
      dom.srtFileName.textContent = file.name;
      show(dom.srtRemove);
    };
    reader.readAsText(file);
  }

  function clearSrt() {
    srtContent = null;
    dom.srtInput.value = '';
    dom.srtFileName.textContent = 'No file chosen';
    hide(dom.srtRemove);
  }

  // ── Build Processing Options ───────────
  let clipInputMode = 'dropdown'; // 'dropdown' | 'manual'

  function formatTimeFromSec(sec) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function buildOptions() {
    const opts = {};

    // 1. Split into parts
    const splitMode = dom.splitModeSelect ? dom.splitModeSelect.value : 'none';
    if (splitMode === 'parts_2') opts.split_parts = 2;
    else if (splitMode === 'parts_3') opts.split_parts = 3;
    else if (splitMode === 'parts_4') opts.split_parts = 4;
    else if (splitMode === 'parts_5') opts.split_parts = 5;
    else if (splitMode === 'dur_60') opts.split_duration = 60;
    else if (splitMode === 'dur_30') opts.split_duration = 30;
    else if (splitMode === 'custom_parts' && dom.customPartsInput) {
      const p = parseInt(dom.customPartsInput.value, 10);
      if (p >= 2) opts.split_parts = p;
    }

    // 2. Extract / Clip section
    if (clipInputMode === 'dropdown' && dom.clipEndMin && dom.clipEndSec) {
      const sMin = parseInt(dom.clipStartMin.value, 10) || 0;
      const sSec = parseInt(dom.clipStartSec.value, 10) || 0;
      const eMin = parseInt(dom.clipEndMin.value, 10) || 0;
      const eSec = parseInt(dom.clipEndSec.value, 10) || 0;
      const startTotal = sMin * 60 + sSec;
      const endTotal = eMin * 60 + eSec;

      if (endTotal > startTotal) {
        opts.clip_start = formatTimeFromSec(startTotal);
        opts.clip_end = formatTimeFromSec(endTotal);
      }
    } else {
      const clipStart = dom.clipStart ? dom.clipStart.value.trim() : '';
      const clipEnd = dom.clipEnd ? dom.clipEnd.value.trim() : '';
      if (clipStart || clipEnd) {
        opts.clip_start = clipStart || '00:00';
        opts.clip_end = clipEnd || '01:00';
      }
    }

    const trimStart = dom.trimStart.value.trim();
    const trimEnd = dom.trimEnd.value.trim();
    if (trimStart || trimEnd) {
      opts.trim = {};
      if (trimStart) opts.trim.start = trimStart;
      if (trimEnd) opts.trim.end = trimEnd;
    }

    const muteStart = dom.muteStart.value.trim();
    const muteEnd = dom.muteEnd.value.trim();
    if (muteStart || muteEnd) {
      opts.mute = {};
      if (muteStart) opts.mute.start = muteStart;
      if (muteEnd) opts.mute.end = muteEnd;
    }

    if (srtContent) {
      opts.subtitles = srtContent;
    }

    return Object.keys(opts).length > 0 ? opts : null;
  }

  // ── State Transitions ─────────────────
  function transitionTo(newState) {
    state = newState;

    // Reset visibility
    hide(dom.processingSection);
    hide(dom.errorSection);
    hide(dom.resultSection);

    switch (newState) {
      case 'idle':
        show(dom.uploadSection);
        show(dom.actionBar);
        dom.processBtn.disabled = !selectedFile;
        break;

      case 'uploading':
        hide(dom.actionBar);
        show(dom.processingSection);
        hide(dom.uploadSection);
        hide(dom.advancedSection);
        startElapsedTimer();
        updateSteps('uploading');
        dom.statusMessage.textContent = 'Uploading your video…';
        setProgress(0);
        break;

      case 'processing':
        show(dom.processingSection);
        break;

      case 'completed':
        stopTimers();
        show(dom.resultSection);
        break;

      case 'failed':
        stopTimers();
        show(dom.errorSection);
        break;
    }
  }

  // ── Progress & Steps ──────────────────
  function setProgress(percent) {
    const p = Math.min(100, Math.max(0, Math.round(percent)));
    dom.progressBarFill.style.width = p + '%';
    dom.progressPercent.textContent = p + '%';
  }

  function updateSteps(currentStep) {
    const currentIdx = STEP_ORDER.indexOf(currentStep);
    const steps = $$('.status-step');
    steps.forEach((stepEl) => {
      const stepName = stepEl.dataset.step;
      const stepIdx = STEP_ORDER.indexOf(stepName);
      stepEl.classList.remove('active', 'done');
      if (stepIdx < currentIdx) {
        stepEl.classList.add('done');
      } else if (stepIdx === currentIdx) {
        stepEl.classList.add('active');
      }
    });
  }

  // ── Timers ────────────────────────────
  function startElapsedTimer() {
    processingStartTime = Date.now();
    elapsedTimer = setInterval(() => {
      const elapsed = Date.now() - processingStartTime;
      dom.elapsedTime.textContent = 'Elapsed: ' + formatElapsed(elapsed);
    }, 1000);
  }

  function stopTimers() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (elapsedTimer) {
      clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
  }

  // ── Error Display ─────────────────────
  function showError(message) {
    dom.errorMessage.textContent = message;
    transitionTo('failed');
  }

  function hideError() {
    hide(dom.errorSection);
  }

  // ── Upload & Process ──────────────────
  async function startProcessing() {
    if (!selectedFile || state !== 'idle') return;

    transitionTo('uploading');

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const options = buildOptions();
      if (options) {
        formData.append('options', JSON.stringify(options));
      }

      if (replacementAudio) {
        formData.append('replacement_audio', replacementAudio);
      }

      const res = await fetch('/api/jobs', { method: 'POST', body: formData });

      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        throw new Error(
          errData?.detail || errData?.message || `Upload failed (HTTP ${res.status})`
        );
      }

      const data = await res.json();
      currentJobId = data.job_id;

      transitionTo('processing');
      updateSteps(data.status || 'validating');
      dom.statusMessage.textContent = data.message || 'Processing started…';
      setProgress(data.progress || 5);

      // Start polling
      startPolling();
    } catch (err) {
      showError(err.message || 'An unexpected error occurred during upload.');
    }
  }

  // ── Polling ───────────────────────────
  function startPolling() {
    pollTimer = setInterval(pollJobStatus, POLL_INTERVAL_MS);
  }

  async function pollJobStatus() {
    if (!currentJobId) return;

    try {
      const res = await fetch('/api/jobs/' + currentJobId);
      if (!res.ok) throw new Error('Failed to fetch job status.');

      const job = await res.json();

      // Update UI based on status
      if (job.status === 'completed') {
        stopTimers();
        setProgress(100);
        updateSteps('completed');
        dom.statusMessage.textContent = 'Complete!';

        // Short delay to show the 100% state before switching
        setTimeout(() => {
          showResult(job);
        }, 600);
        return;
      }

      if (job.status === 'failed' || job.status === 'cancelled') {
        showError(job.error || 'Processing failed. Please try again.');
        return;
      }

      // Still in progress
      if (job.progress != null) {
        setProgress(job.progress);
      }
      if (job.status && STEP_ORDER.includes(job.status)) {
        updateSteps(job.status);
      }
      if (job.status_message) {
        dom.statusMessage.textContent = job.status_message;
      }
    } catch (err) {
      // Don't fail hard on a single poll error — keep polling
      console.warn('Poll error:', err);
    }
  }

  // ── Results ───────────────────────────
  function showResult(job) {
    dom.resultFilename.textContent = job.output_filename || 'output.mp4';
    dom.resultDuration.textContent = formatDuration(job.output_duration);
    dom.resultSize.textContent = job.output_size ? formatBytes(job.output_size) : '—';

    if (job.is_multi_part && job.output_parts && job.output_parts.length > 0) {
      dom.multiPartSection.style.display = 'block';
      dom.partsList.innerHTML = '';
      job.output_parts.forEach((p) => {
        const row = document.createElement('div');
        row.className = 'part-row';
        row.innerHTML = `
          <div class="part-info">
            <span class="part-title">${p.filename}</span>
            <span class="part-meta">Duration: ${formatDuration(p.duration)} · Size: ${formatBytes(p.size)}</span>
          </div>
          <a href="/api/jobs/${job.job_id}/download?part=${p.part}" class="btn btn-secondary btn-sm" download="${p.filename}">
            ⬇️ Download Part ${p.part}
          </a>
        `;
        dom.partsList.appendChild(row);
      });
      dom.downloadBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download All Parts (.ZIP)
      `;
    } else {
      dom.multiPartSection.style.display = 'none';
      dom.partsList.innerHTML = '';
      dom.downloadBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download Video
      `;
    }

    transitionTo('completed');
  }

  function downloadResult() {
    if (!currentJobId) return;
    const a = document.createElement('a');
    a.href = '/api/jobs/' + currentJobId + '/download';
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // ── Reset ─────────────────────────────
  function resetAll() {
    stopTimers();
    currentJobId = null;
    srtContent = null;
    clearFile();
    clearAudio();
    clearSrt();

    // Reset form fields
    if (dom.clipStart) dom.clipStart.value = '';
    if (dom.clipEnd) dom.clipEnd.value = '';
    dom.trimStart.value = '';
    dom.trimEnd.value = '';
    dom.muteStart.value = '';
    dom.muteEnd.value = '';

    // Collapse advanced
    dom.advancedToggle.setAttribute('aria-expanded', 'false');
    dom.advancedBody.classList.remove('open');

    // Reset progress
    setProgress(0);
    dom.elapsedTime.textContent = 'Elapsed: 0s';
    dom.statusMessage.textContent = 'Preparing…';

    // Reset steps
    $$('.status-step').forEach((s) => s.classList.remove('active', 'done'));

    transitionTo('idle');
  }

  // ── Drag & Drop ───────────────────────
  function setupDragDrop() {
    const dz = dom.dropZone;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((evt) => {
      dz.addEventListener(evt, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });

    dz.addEventListener('dragenter', () => dz.classList.add('drag-over'));
    dz.addEventListener('dragover', () => dz.classList.add('drag-over'));
    dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));

    dz.addEventListener('drop', (e) => {
      dz.classList.remove('drag-over');
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        selectFile(files[0]);
      }
    });

    // Click on drop zone should also trigger file input
    dz.addEventListener('click', (e) => {
      // Don't retrigger if clicking the button directly
      if (e.target.closest('.browse-btn')) return;
      dom.fileInput.click();
    });
  }

  // ── Event Binding ─────────────────────
  function bindEvents() {
    // File input
    dom.fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) selectFile(e.target.files[0]);
    });

    // Remove file
    dom.fileRemove.addEventListener('click', (e) => {
      e.stopPropagation();
      clearFile();
    });

    // Advanced toggle
    dom.advancedToggle.addEventListener('click', () => {
      const expanded = dom.advancedToggle.getAttribute('aria-expanded') === 'true';
      dom.advancedToggle.setAttribute('aria-expanded', String(!expanded));
      dom.advancedBody.classList.toggle('open');
    });

    // Split mode change
    if (dom.splitModeSelect) {
      dom.splitModeSelect.addEventListener('change', () => {
        if (dom.customPartsGroup) {
          dom.customPartsGroup.style.display =
            dom.splitModeSelect.value === 'custom_parts' ? 'flex' : 'none';
        }
      });
    }

    // Dropdown / Manual mode switches
    if (dom.btnModeDropdown && dom.btnModeManual) {
      dom.btnModeDropdown.addEventListener('click', () => {
        clipInputMode = 'dropdown';
        dom.btnModeDropdown.classList.add('active');
        dom.btnModeManual.classList.remove('active');
        if (dom.clipDropdownControls) dom.clipDropdownControls.style.display = 'flex';
        if (dom.clipManualControls) dom.clipManualControls.style.display = 'none';
      });

      dom.btnModeManual.addEventListener('click', () => {
        clipInputMode = 'manual';
        dom.btnModeManual.classList.add('active');
        dom.btnModeDropdown.classList.remove('active');
        if (dom.clipDropdownControls) dom.clipDropdownControls.style.display = 'none';
        if (dom.clipManualControls) dom.clipManualControls.style.display = 'flex';
      });
    }

    // Preset buttons
    if (dom.preset60sBtn) {
      dom.preset60sBtn.addEventListener('click', () => {
        if (dom.clipStartMin) dom.clipStartMin.value = '0';
        if (dom.clipStartSec) dom.clipStartSec.value = '0';
        if (dom.clipEndMin) dom.clipEndMin.value = '1';
        if (dom.clipEndSec) dom.clipEndSec.value = '0';
        if (dom.clipStart) dom.clipStart.value = '00:00';
        if (dom.clipEnd) dom.clipEnd.value = '01:00';
      });
    }
    if (dom.preset30sBtn) {
      dom.preset30sBtn.addEventListener('click', () => {
        if (dom.clipStartMin) dom.clipStartMin.value = '0';
        if (dom.clipStartSec) dom.clipStartSec.value = '0';
        if (dom.clipEndMin) dom.clipEndMin.value = '0';
        if (dom.clipEndSec) dom.clipEndSec.value = '30';
        if (dom.clipStart) dom.clipStart.value = '00:00';
        if (dom.clipEnd) dom.clipEnd.value = '00:30';
      });
    }
    if (dom.clearClipBtn) {
      dom.clearClipBtn.addEventListener('click', () => {
        if (dom.clipStartMin) dom.clipStartMin.value = '0';
        if (dom.clipStartSec) dom.clipStartSec.value = '0';
        if (dom.clipEndMin) dom.clipEndMin.value = '0';
        if (dom.clipEndSec) dom.clipEndSec.value = '0';
        if (dom.clipStart) dom.clipStart.value = '';
        if (dom.clipEnd) dom.clipEnd.value = '';
      });
    }

    // Audio input
    dom.audioInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) selectAudio(e.target.files[0]);
    });
    dom.audioRemove.addEventListener('click', (e) => {
      e.stopPropagation();
      clearAudio();
    });

    // SRT input
    dom.srtInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) selectSrt(e.target.files[0]);
    });
    dom.srtRemove.addEventListener('click', (e) => {
      e.stopPropagation();
      clearSrt();
    });

    // Process button
    dom.processBtn.addEventListener('click', startProcessing);

    // Download
    dom.downloadBtn.addEventListener('click', downloadResult);

    // Process another
    dom.processAnotherBtn.addEventListener('click', resetAll);

    // Error retry
    dom.errorRetryBtn.addEventListener('click', resetAll);

    // Prevent default drag on body
    document.body.addEventListener('dragover', (e) => e.preventDefault());
    document.body.addEventListener('drop', (e) => e.preventDefault());
  }

  // ── Init Dropdowns ───────────────────
  function initDropdownOptions() {
    const populateMins = (sel) => {
      if (!sel) return;
      sel.innerHTML = '';
      for (let m = 0; m <= 20; m++) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m + 'm';
        sel.appendChild(opt);
      }
    };
    const populateSecs = (sel) => {
      if (!sel) return;
      sel.innerHTML = '';
      for (let s = 0; s < 60; s += 5) {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = String(s).padStart(2, '0') + 's';
        sel.appendChild(opt);
      }
    };

    populateMins(dom.clipStartMin);
    populateSecs(dom.clipStartSec);
    populateMins(dom.clipEndMin);
    populateSecs(dom.clipEndSec);
  }

  // ── Init ──────────────────────────────
  function init() {
    initDropdownOptions();
    setupDragDrop();
    bindEvents();
    checkHealth();

    // Re-check health every 30 seconds
    setInterval(checkHealth, 30000);
  }

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
