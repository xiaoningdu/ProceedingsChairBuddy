const DEFAULT_CHECKLIST_ITEMS = [
  {id: "title_pdf_vs_xml", label: "PDF title matches metadata"},
  {id: "authors_pdf_vs_xml", label: "PDF author list matches metadata"},
  {id: "affiliations_pdf_vs_xml", label: "PDF affiliations match metadata"},
  {id: "emails_in_pdf", label: "All author emails in metadata appear in the PDF"},
  {id: "orcid", label: "All authors have ORCID in metadata"},
  {id: "hotcrp_acm_keywords", label: "ACM keywords added on HotCRP"},
  {id: "hotcrp_ccs", label: "ACM Computing Classification added on HotCRP"},
  {id: "hotcrp_references", label: "References added on HotCRP"},
  {id: "source_files", label: "Source files submitted"},
  {id: "proceeding_messages", label: "Other issues"},
  {id: "pdf_copyright_isbn", label: "PDF copyright information includes ISBN"},
  {id: "pdf_exists", label: "Paper PDF provided"},
  {id: "pdf_page_numbers", label: "PDF has no visible page numbers"},
  {id: "latest_acm_template", label: "Latest ACM template used"},
  {id: "authors_stacked", label: "Authors stacked individually"},
  {id: "last_page_balanced", label: "Last page balanced"},
  {id: "track_page_limit", label: "Track-specific page limit followed"}
];

let state = {
  tracks: [],
  checklistItems: DEFAULT_CHECKLIST_ITEMS,
  currentTrack: null,
  submissions: [],
  submissionFilter: "all",
  selectedId: null,
  saveTimer: null
};

const els = {
  homeView: document.querySelector("#homeView"),
  reviewView: document.querySelector("#reviewView"),
  trackList: document.querySelector("#trackList"),
  addTrackForm: document.querySelector("#addTrackForm"),
  addTrackMessage: document.querySelector("#addTrackMessage"),
  addTrackChecklist: document.querySelector("#addTrackChecklist"),
  selectAllChecks: document.querySelector("#selectAllChecks"),
  sourceSummary: document.querySelector("#sourceSummary"),
  submissionCount: document.querySelector("#submissionCount"),
  submissionFilters: document.querySelector("#submissionFilters"),
  submissionList: document.querySelector("#submissionList"),
  paperTitle: document.querySelector("#paperTitle"),
  paperMeta: document.querySelector("#paperMeta"),
  openPdf: document.querySelector("#openPdf"),
  pdfViewer: document.querySelector("#pdfViewer"),
  checkSummary: document.querySelector("#checkSummary"),
  metadataContent: document.querySelector("#metadataContent"),
  issueSummary: document.querySelector("#issueSummary"),
  checklist: document.querySelector("#checklist"),
  completedToggle: document.querySelector("#completedToggle"),
  backToTracks: document.querySelector("#backToTracks"),
  rerunChecks: document.querySelector("#rerunChecks"),
  exportCsv: document.querySelector("#exportCsv")
};

async function init() {
  renderAddTrackChecklist();
  await Promise.all([loadChecklistItems(), loadTracks()]);
}

async function loadChecklistItems() {
  try {
    const response = await fetch("/api/checklist-items");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (Array.isArray(data.items) && data.items.length) {
      state.checklistItems = data.items;
      renderAddTrackChecklist();
    }
  } catch (error) {
    // Keep the built-in checklist options available if the metadata endpoint is unavailable.
  }
}

async function loadTracks() {
  const response = await fetch("/api/tracks");
  const data = await response.json();
  state.tracks = data.tracks;
  renderTrackList();
  showHome();
}

async function addTrack(event) {
  event.preventDefault();
  const formData = new FormData(els.addTrackForm);
  showAddTrackMessage("Adding...");
  try {
    const response = await fetch("/api/tracks", {
      method: "POST",
      body: formData
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    els.addTrackForm.reset();
    syncSelectAllChecks();
    const panel = els.addTrackForm.closest(".addTrackPanel");
    if (panel) {
      panel.open = false;
    }
    showAddTrackMessage("");
    await loadTracks();
  } catch (error) {
    showAddTrackMessage(cleanErrorMessage(error.message));
  }
}

function showAddTrackMessage(message) {
  els.addTrackMessage.textContent = message;
}

function renderAddTrackChecklist() {
  const selectedIds = new Set(addTrackChecklistInputs().filter(input => input.checked).map(input => input.value));
  const hadRenderedItems = addTrackChecklistInputs().length > 0;
  els.addTrackChecklist.replaceChildren(...state.checklistItems.map(item => {
    const label = document.createElement("label");
    label.className = "checklistOption";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "checklist_ids";
    input.value = item.id;
    input.checked = hadRenderedItems ? selectedIds.has(item.id) : true;
    input.defaultChecked = true;
    input.addEventListener("change", syncSelectAllChecks);

    const text = document.createElement("span");
    text.textContent = item.label;

    label.append(input, text);
    return label;
  }));
  syncSelectAllChecks();
}

function addTrackChecklistInputs() {
  return Array.from(els.addTrackChecklist.querySelectorAll('input[name="checklist_ids"]'));
}

function syncSelectAllChecks() {
  const inputs = addTrackChecklistInputs();
  const checkedCount = inputs.filter(input => input.checked).length;
  els.selectAllChecks.checked = inputs.length > 0 && checkedCount === inputs.length;
  els.selectAllChecks.indeterminate = checkedCount > 0 && checkedCount < inputs.length;
}

function cleanErrorMessage(message) {
  const match = message.match(/Message: ([\s\S]*?)\.\n/);
  return match ? match[1] : message;
}

async function openTrack(trackId) {
  const response = await fetch(`/api/tracks/${encodeURIComponent(trackId)}`);
  const data = await response.json();
  state.currentTrack = data.track;
  state.submissions = data.submissions;
  state.submissionFilter = "all";
  const sources = data.sources;
  els.sourceSummary.textContent = `${data.track.name} · Sources: ${sources.xml}, ${sources.hotcrp_html}, ${sources.zip}`;
  updateSubmissionCount();
  els.rerunChecks.hidden = false;
  els.exportCsv.hidden = false;
  els.backToTracks.hidden = false;
  els.homeView.hidden = true;
  els.reviewView.hidden = false;
  renderSubmissionList();
  if (state.submissions.length) {
    selectSubmission(state.selectedId && state.submissions.some(item => item.id === state.selectedId) ? state.selectedId : state.submissions[0].id);
  }
}

function showHome() {
  state.currentTrack = null;
  state.submissions = [];
  state.submissionFilter = "all";
  state.selectedId = null;
  els.sourceSummary.textContent = "Select a track to continue review.";
  els.rerunChecks.hidden = true;
  els.exportCsv.hidden = true;
  els.backToTracks.hidden = true;
  els.homeView.hidden = false;
  els.reviewView.hidden = true;
}

function renderTrackList() {
  els.trackList.replaceChildren(...state.tracks.map(track => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "trackCard";
    card.addEventListener("click", () => openTrack(track.id));

    const title = document.createElement("span");
    title.className = "trackTitle";
    title.textContent = track.name;

    const meta = document.createElement("span");
    meta.className = "trackMeta";
    meta.textContent = `${track.paper_count} papers · ${track.completed_count} finished · ${track.remaining_count} remaining`;

    const badges = document.createElement("span");
    badges.className = "badges";
    badges.append(
      badge(track.remaining_count ? "manual" : "pass", `${track.completed_count}/${track.paper_count} finished`),
      badge(track.issue_count ? "issue" : "pass", `${track.issue_count} issues`)
    );

    const sources = document.createElement("span");
    sources.className = "trackSources";
    sources.textContent = `${track.sources.zip} · ${track.sources.xml} · ${track.sources.hotcrp_html}`;

    const actions = document.createElement("span");
    actions.className = "trackActions";
    const openButton = document.createElement("span");
    openButton.className = "trackOpenLabel";
    openButton.textContent = "Open";
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "dangerButton";
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", event => {
      event.stopPropagation();
      removeTrack(track);
    });
    actions.append(openButton, removeButton);

    card.append(title, meta, badges, sources, actions);
    return card;
  }));
}

async function removeTrack(track) {
  const confirmed = confirm(`Remove track "${track.name}"? Review progress for this track will also be removed.`);
  if (!confirmed) {
    return;
  }
  // The backend performs the destructive cleanup. It always removes the track
  // registry entry and review state, and it only deletes uploaded files when
  // they live in the app-managed track_data/<track-id>/ layout.
  const response = await fetch(`/api/tracks/${encodeURIComponent(track.id)}`, {method: "DELETE"});
  if (!response.ok) {
    alert(cleanErrorMessage(await response.text()));
    return;
  }
  await loadTracks();
}

async function rerunChecks() {
  if (!state.currentTrack) {
    return;
  }
  const confirmed = confirm("Rerun automated checks for this track? This will replace saved check results and evidence, but keep each paper's finished/open status.");
  if (!confirmed) {
    return;
  }
  clearTimeout(state.saveTimer);
  els.rerunChecks.disabled = true;
  try {
    const response = await fetch(`/api/tracks/${encodeURIComponent(state.currentTrack.id)}/rerun-checks`, {
      method: "POST"
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await openTrack(state.currentTrack.id);
  } catch (error) {
    alert(cleanErrorMessage(error.message));
  } finally {
    els.rerunChecks.disabled = false;
  }
}

function renderSubmissionList() {
  const visibleSubmissions = filteredSubmissions();
  updateSubmissionCount();
  updateSubmissionFilterButtons();
  els.submissionList.replaceChildren(...visibleSubmissions.map(submission => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "submissionItem";
    button.classList.toggle("active", submission.id === state.selectedId);
    button.dataset.id = submission.id;
    button.addEventListener("click", () => selectSubmission(submission.id));

    const title = document.createElement("span");
    title.className = "submissionTitle";
    title.textContent = `#${submission.id} ${submission.title}`;

    const meta = document.createElement("span");
    meta.className = "submissionMeta";
    const hotcrp = submission.hotcrp;
    meta.textContent = hotcrp ? `${hotcrp.acm_class || "Unknown class"} · ${hotcrp.page_count ?? "?"} pages` : "No HotCRP row";

    const badges = document.createElement("span");
    badges.className = "badges";
    badges.append(
      badge("pass", `${submission.status_counts.pass} pass`),
      badge("issue", `${submission.status_counts.issue} issues`),
      badge("manual", `${submission.status_counts.manual} manual`),
      badge(submission.completed ? "pass" : "manual", submission.completed ? "finished" : "open")
    );

    button.append(title, meta, badges);
    return button;
  }));
}

function filteredSubmissions() {
  if (state.submissionFilter === "open") {
    return state.submissions.filter(submission => !submission.completed);
  }
  if (state.submissionFilter === "finished") {
    return state.submissions.filter(submission => submission.completed);
  }
  return state.submissions;
}

function updateSubmissionCount() {
  const visibleCount = filteredSubmissions().length;
  els.submissionCount.textContent = state.submissionFilter === "all"
    ? `${state.submissions.length} papers`
    : `${visibleCount}/${state.submissions.length} papers`;
}

function updateSubmissionFilterButtons() {
  els.submissionFilters.querySelectorAll("button").forEach(button => {
    const isActive = button.dataset.filter === state.submissionFilter;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

async function setSubmissionFilter(filter) {
  if (!["open", "finished", "all"].includes(filter)) {
    return;
  }
  state.submissionFilter = filter;
  renderSubmissionList();
  await ensureVisibleSelection();
}

async function ensureVisibleSelection() {
  const visibleSubmissions = filteredSubmissions();
  if (visibleSubmissions.some(submission => submission.id === state.selectedId)) {
    return;
  }
  await saveSelectedSubmission();
  if (visibleSubmissions.length) {
    selectSubmission(visibleSubmissions[0].id);
    return;
  }
  state.selectedId = null;
  clearSubmission();
}

function selectSubmission(id) {
  saveSelectedSubmission();
  state.selectedId = id;
  document.querySelectorAll(".submissionItem").forEach(item => {
    item.classList.toggle("active", item.dataset.id === id);
  });
  const submission = state.submissions.find(item => item.id === id);
  renderSubmission(submission);
}

function clearSubmission() {
  els.paperTitle.textContent = "No submissions";
  els.paperMeta.textContent = "";
  els.openPdf.href = "#";
  els.openPdf.style.visibility = "hidden";
  els.pdfViewer.src = "about:blank";
  els.completedToggle.checked = false;
  els.checkSummary.textContent = "";
  els.metadataContent.replaceChildren();
  els.issueSummary.replaceChildren();
  els.checklist.replaceChildren();
}

function renderSubmission(submission) {
  const hotcrp = submission.hotcrp;
  const xml = submission.xml;
  els.paperTitle.textContent = `#${submission.id} ${submission.title}`;
  els.paperMeta.textContent = [
    hotcrp?.acm_class || xml?.paper_type || "Unknown class",
    hotcrp?.page_count ? `${hotcrp.page_count} HotCRP pages` : null,
    submission.pdf.page_count_estimate ? `${submission.pdf.page_count_estimate} local PDF pages` : null
  ].filter(Boolean).join(" · ");

  els.openPdf.href = submission.pdf.url || "#";
  els.openPdf.style.visibility = submission.pdf.url ? "visible" : "hidden";
  els.pdfViewer.src = submission.pdf.url || "about:blank";
  els.completedToggle.checked = Boolean(submission.completed);

  const counts = submission.status_counts;
  els.checkSummary.textContent = `${counts.pass} pass · ${counts.issue} issue · ${counts.manual} manual · ${counts.unavailable} unavailable`;
  assignCheckDisplayNumbers(submission.checks);
  renderMetadata(submission);
  renderIssueSummary(submission.checks);
  renderChecks(submission.checks);
}

function renderMetadata(submission) {
  const xml = submission.xml;
  const hotcrp = submission.hotcrp;
  const authors = xml?.authors?.map(author => {
    const marker = author.contact_author ? " (contact)" : "";
    return `${author.name}${marker}`;
  }).join(", ") || "Unavailable";

  const dl = document.createElement("dl");
  dl.className = "metadataGrid";
  addMeta(dl, "Tracking", xml?.tracking_number || `#${submission.id}`);
  addMeta(dl, "XML type", xml?.paper_type || "Unavailable");
  addMeta(dl, "ACM class", hotcrp?.acm_class || "Unavailable");
  addMeta(dl, "Page count", hotcrp?.page_count ?? submission.pdf.page_count_estimate ?? "Unavailable");
  addMeta(dl, "Authors", authors);
  addMeta(dl, "Source files", hotcrp?.source_files?.map(file => file.name).join(", ") || "None found");
  els.metadataContent.replaceChildren(dl);
}

function renderIssueSummary(checks) {
  const issues = checks.filter(check => check.status === "issue");
  if (!issues.length) {
    els.issueSummary.replaceChildren();
    return;
  }

  const heading = document.createElement("h3");
  heading.textContent = "Issue Summary";

  const list = document.createElement("ul");
  list.className = "issueList";
  list.replaceChildren(...issues.map(check => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = `${check.display_no}. ${check.label}`;
    const evidence = document.createElement("span");
    evidence.textContent = `: ${check.evidence}`;
    item.append(label, evidence);
    return item;
  }));

  els.issueSummary.replaceChildren(heading, list);
}

function renderChecks(checks) {
  const submission = selectedSubmission();
  els.checklist.replaceChildren(...checks.map(check => {
    const item = document.createElement("article");
    item.className = `check ${check.status}`;

    const header = document.createElement("div");
    header.className = "checkHeader";

    const title = document.createElement("div");
    title.className = "checkTitle";
    title.textContent = `${check.display_no}. ${check.label}`;

    const status = document.createElement("select");
    status.className = `statusSelect ${check.status}`;
    status.setAttribute("aria-label", `${check.label} result`);
    for (const optionValue of ["pass", "issue", "manual", "unavailable"]) {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      option.selected = check.status === optionValue;
      status.append(option);
    }
    status.addEventListener("change", () => {
      check.status = status.value;
      status.className = `statusSelect ${check.status}`;
      item.className = `check ${check.status}`;
      updateStatusCounts(submission);
      renderIssueSummary(checks);
      renderSubmissionList();
      updateCheckSummary(submission);
      scheduleSaveSubmission(submission);
    });

    const evidence = document.createElement("textarea");
    evidence.className = "evidence";
    evidence.value = check.evidence;
    evidence.rows = Math.max(2, Math.min(8, Math.ceil(check.evidence.length / 58)));
    evidence.setAttribute("aria-label", `${check.label} evidence`);
    evidence.addEventListener("input", () => {
      check.evidence = evidence.value;
      evidence.rows = Math.max(2, Math.min(8, Math.ceil(evidence.value.length / 58)));
      renderIssueSummary(checks);
      scheduleSaveSubmission(submission);
    });

    const source = document.createElement("div");
    source.className = "source";
    source.textContent = `Source: ${check.source}`;

    header.append(title, status);
    item.append(header, evidence, source);
    return item;
  }));
}

function assignCheckDisplayNumbers(checks) {
  checks.forEach((check, index) => {
    check.display_no = index + 1;
  });
}

function updateStatusCounts(submission) {
  submission.status_counts = {
    pass: submission.checks.filter(check => check.status === "pass").length,
    issue: submission.checks.filter(check => check.status === "issue").length,
    manual: submission.checks.filter(check => check.status === "manual").length,
    unavailable: submission.checks.filter(check => check.status === "unavailable").length
  };
}

function updateCheckSummary(submission) {
  const counts = submission.status_counts;
  els.checkSummary.textContent = `${counts.pass} pass · ${counts.issue} issue · ${counts.manual} manual · ${counts.unavailable} unavailable`;
}

function addMeta(dl, label, value) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  dl.append(dt, dd);
}

function badge(kind, text) {
  const span = document.createElement("span");
  span.className = `badge ${kind}`;
  span.textContent = text;
  return span;
}

function selectedSubmission() {
  return state.submissions.find(item => item.id === state.selectedId);
}

function scheduleSaveSubmission(submission) {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveSubmission(submission), 350);
}

async function saveSelectedSubmission() {
  const submission = selectedSubmission();
  return saveSubmission(submission);
}

async function saveSubmission(submission) {
  if (!state.currentTrack || !submission) {
    return;
  }
  await fetch(`/api/tracks/${encodeURIComponent(state.currentTrack.id)}/reviews`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      paper_id: submission.id,
      completed: submission.completed,
      checks: submission.checks.map(check => ({
        id: check.id,
        status: check.status,
        evidence: check.evidence
      }))
    })
  });
}

function exportCsv() {
  const checkLabels = [];
  for (const submission of state.submissions) {
    for (const check of submission.checks) {
      const numberedLabel = `${submission.checks.indexOf(check) + 1}. ${check.label}`;
      if (!checkLabels.includes(numberedLabel)) {
        checkLabels.push(numberedLabel);
      }
    }
  }

  const rows = [["paper_id", "issue_summary", ...checkLabels]];
  for (const submission of state.submissions) {
    const checksByLabel = new Map(submission.checks.map((check, index) => [`${index + 1}. ${check.label}`, check]));
    const issueSummary = submission.checks
      .filter(check => check.status === "issue")
      .map(check => `${check.display_no || submission.checks.indexOf(check) + 1}. ${check.label}: ${check.evidence}`)
      .join("\n");
    rows.push([
      submission.id,
      issueSummary,
      ...checkLabels.map(label => {
        const check = checksByLabel.get(label);
        return check ? `${check.status}: ${check.evidence}` : "";
      })
    ]);
  }
  const csv = rows.map(row => row.map(csvCell).join(",")).join("\n");
  const blob = new Blob([csv], {type: "text/csv"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "proceeding-chair-results.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

els.completedToggle.addEventListener("change", () => {
  const submission = selectedSubmission();
  if (!submission) {
    return;
  }
  submission.completed = els.completedToggle.checked;
  renderSubmissionList();
  scheduleSaveSubmission(submission);
  ensureVisibleSelection();
});
els.submissionFilters.addEventListener("click", event => {
  const button = event.target.closest("button[data-filter]");
  if (button) {
    setSubmissionFilter(button.dataset.filter);
  }
});
els.backToTracks.addEventListener("click", async () => {
  await saveSelectedSubmission();
  await loadTracks();
});
els.rerunChecks.addEventListener("click", rerunChecks);
els.exportCsv.addEventListener("click", exportCsv);
els.addTrackForm.addEventListener("submit", addTrack);
els.addTrackForm.addEventListener("reset", () => setTimeout(syncSelectAllChecks, 0));
els.selectAllChecks.addEventListener("change", () => {
  for (const input of addTrackChecklistInputs()) {
    input.checked = els.selectAllChecks.checked;
  }
  syncSelectAllChecks();
});
init().catch(error => {
  els.sourceSummary.textContent = `Failed to load prototype data: ${error.message}`;
});
