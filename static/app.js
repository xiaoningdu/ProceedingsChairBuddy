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
  currentReview: null,
  reviews: [],
  submissions: [],
  submissionFilter: "all",
  selectedId: null,
  saveTimer: null,
  pdfLoadToken: 0
};

const els = {
  homeView: document.querySelector("#homeView"),
  reviewView: document.querySelector("#reviewView"),
  trackList: document.querySelector("#trackList"),
  addTrackForm: document.querySelector("#addTrackForm"),
  addTrackMessage: document.querySelector("#addTrackMessage"),
  addTrackChecklist: document.querySelector("#addTrackChecklist"),
  selectAllChecks: document.querySelector("#selectAllChecks"),
  reviewChainBar: document.querySelector("#reviewChainBar"),
  sourceSummary: document.querySelector("#sourceSummary"),
  submissionCount: document.querySelector("#submissionCount"),
  submissionFilters: document.querySelector("#submissionFilters"),
  submissionList: document.querySelector("#submissionList"),
  paperTitle: document.querySelector("#paperTitle"),
  paperMeta: document.querySelector("#paperMeta"),
  openPdf: document.querySelector("#openPdf"),
  pdfViewer: document.querySelector("#pdfViewer"),
  pdfUnavailable: document.querySelector("#pdfUnavailable"),
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

async function openTrack(trackId, reviewId = null) {
  const previousId = state.selectedId;
  const previousSubmission = selectedSubmission();
  showPdfUnavailable("Loading review...");
  const url = reviewId
    ? `/api/tracks/${encodeURIComponent(trackId)}?review_id=${encodeURIComponent(reviewId)}`
    : `/api/tracks/${encodeURIComponent(trackId)}`;
  const response = await fetch(url);
  const data = await response.json();
  state.currentTrack = data.track;
  state.currentReview = data.review;
  state.reviews = data.reviews || [];
  state.submissions = data.submissions;
  state.submissionFilter = "all";
  const sources = data.sources;
  els.sourceSummary.textContent = `${data.track.name} · ${data.review.label} · Sources: ${sources.xml}, ${sources.hotcrp_html}, ${sources.zip}`;
  updateSubmissionCount();
  renderReviewChain();
  updateReviewControls();
  els.rerunChecks.hidden = false;
  els.exportCsv.hidden = false;
  els.backToTracks.hidden = false;
  els.homeView.hidden = true;
  els.reviewView.hidden = false;
  renderSubmissionList();
  if (state.submissions.length) {
    if (previousId && state.submissions.some(item => item.id === previousId)) {
      selectSubmission(previousId);
    } else if (previousId) {
      showResolvedPaper(previousId, previousSubmission?.title || "");
    } else {
      selectSubmission(state.submissions[0].id);
    }
  } else {
    if (previousId) {
      showResolvedPaper(previousId, previousSubmission?.title || "");
    } else {
      state.selectedId = null;
      clearSubmission();
    }
  }
}

function showHome() {
  state.currentTrack = null;
  state.currentReview = null;
  state.reviews = [];
  state.submissions = [];
  state.submissionFilter = "all";
  state.selectedId = null;
  els.sourceSummary.textContent = "";
  updateReviewControls();
  els.reviewChainBar.hidden = true;
  els.rerunChecks.hidden = true;
  els.exportCsv.hidden = true;
  els.backToTracks.hidden = true;
  els.homeView.hidden = false;
  els.reviewView.hidden = true;
}

function renderTrackList() {
  els.trackList.replaceChildren(...state.tracks.map(track => {
    const card = document.createElement("article");
    card.className = "trackCard";

    const header = document.createElement("div");
    header.className = "trackHeader";

    const title = document.createElement("span");
    title.className = "trackTitle";
    title.textContent = track.name;

    const actions = document.createElement("div");
    actions.className = "trackActions";
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "dangerButton";
    removeButton.textContent = "Remove track";
    removeButton.addEventListener("click", () => removeTrack(track));
    actions.append(removeButton);
    header.append(title, actions);

    const reviewPanels = document.createElement("div");
    reviewPanels.className = "reviewPanels";
    const panels = (track.reviews || []).map(review => createReviewPanel(track, review));
    reviewPanels.replaceChildren(...panels);
    card.append(header, reviewPanels);
    return card;
  }));
}

function createReviewPanel(track, review) {
  const panel = document.createElement("section");
  panel.className = "followUpPanel";
  panel.classList.toggle("active", review.id === track.review?.id);
  panel.dataset.reviewId = review.id;
  panel.addEventListener("click", event => {
    if (event.target.closest("button, a, input, select, textarea, label, form")) {
      return;
    }
    openTrack(track.id, review.id);
  });

  const header = document.createElement("div");
  header.className = "followUpPanelHeader";

  const title = document.createElement("h3");
  title.textContent = review.label;
  header.append(title);

  const sources = document.createElement("div");
  sources.className = "followUpSources";
  sources.textContent = reviewSourceText(review);

  const badges = document.createElement("span");
  badges.className = "badges";
  badges.append(
    badge(review.paper_count ? "pass" : "manual", `${review.paper_count} papers`),
    badge(review.issue_paper_count ? "issue" : "pass", `${review.issue_paper_count} issue papers`),
    badge(review.remaining_count ? "manual" : "pass", `${review.completed_count || 0}/${review.paper_count || 0} finished`)
  );
  if (review.locked || review.child_count) {
    badges.append(badge("manual", "locked"));
  }

  const actions = document.createElement("div");
  actions.className = "followUpActions";

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "dangerButton";
  removeButton.textContent = review.parent_id ? "Remove follow-up" : "Remove";
  removeButton.addEventListener("click", () => review.parent_id ? removeReviewPanel(track, review, removeButton) : null);

  const updateButton = document.createElement("button");
  updateButton.type = "button";
  updateButton.className = "panelActionButton";
  updateButton.textContent = "Update files";

  const createButton = document.createElement("button");
  createButton.type = "button";
  createButton.className = "panelActionButton";
  createButton.textContent = "Create follow-up";
  const hasFollowUp = Boolean(review && review.child_count);
  createButton.disabled = !(review && review.issue_paper_count) || hasFollowUp;
  createButton.title = hasFollowUp
    ? "This review already has a follow-up."
    : createButton.disabled
      ? "This review has no issue papers to carry forward."
      : "Upload revised files and run follow-up checks.";

  if (!review.parent_id) {
    actions.append(updateButton);
  }
  actions.append(createButton);
  if (review.parent_id) {
    actions.append(removeButton);
  }

  const updatePanel = createUpdateReviewPanel(track, review);
  updatePanel.hidden = true;
  const createSection = createFollowUpForm(track, review);
  const createUploadPanel = createSection.querySelector(".followUpUploadPanel");

  if (!review.parent_id) {
    updateButton.addEventListener("click", () => {
      const willOpen = updatePanel.hidden;
      updatePanel.hidden = !willOpen;
      updateButton.classList.toggle("active", !updatePanel.hidden);
      if (willOpen && createUploadPanel) {
        createUploadPanel.hidden = true;
        createButton.classList.remove("active");
      }
    });
  }

  createButton.addEventListener("click", () => {
    if (!createUploadPanel) {
      return;
    }
    const willOpen = createUploadPanel.hidden;
    createUploadPanel.hidden = !willOpen;
    createButton.classList.toggle("active", !createUploadPanel.hidden);
    if (willOpen) {
      updatePanel.hidden = true;
      updateButton.classList.remove("active");
    }
  });

  const panelParts = [header, badges, sources, actions];
  if (!review.parent_id) {
    panelParts.push(updatePanel);
  }
  panelParts.push(createSection);
  panel.append(...panelParts);
  return panel;
}

function reviewSourceText(review) {
  const sources = review.sources || {};
  return [sources.zip, sources.xml, sources.html]
    .map(source => source ? source.split("/").pop() : "")
    .filter(Boolean)
    .join(" · ") || "No source snapshot available";
}

function createFollowUpForm(track, review) {
  const form = document.createElement("form");
  form.className = "followUpForm";
  form.enctype = "multipart/form-data";

  const uploadPanel = document.createElement("div");
  uploadPanel.className = "followUpUploadPanel";
  uploadPanel.hidden = true;
  uploadPanel.append(
    fileField("zip", "ZIP", ".zip,application/zip"),
    fileField("xml", "TOC XML", ".xml,text/xml,application/xml"),
    fileField("html", "HotCRP HTML", ".html,.htm,text/html")
  );
  uploadPanel.querySelectorAll('input[type="file"]').forEach(input => {
    input.required = true;
  });

  const actions = document.createElement("span");
  actions.className = "followUpActions";

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Create and run follow-up checks";

  const message = document.createElement("span");
  message.className = "formMessage";

  actions.append(submit, message);
  uploadPanel.append(actions);
  form.append(uploadPanel);
  form.addEventListener("submit", event => createTrackFollowUp(event, track, review, submit, message));
  return form;
}

function createUpdateReviewPanel(track, review) {
  const form = document.createElement("form");
  form.className = "updateTrackForm";
  form.hidden = true;
  form.enctype = "multipart/form-data";

  if (!review.parent_id) {
    const warning = document.createElement("p");
    warning.className = "warningText";
    warning.textContent = "Updating the initial review files will remove all existing follow-up panels for this track.";
    form.append(warning);
  }

  form.append(
    fileField("zip", "Replacement ZIP", ".zip,application/zip"),
    fileField("xml", "Replacement TOC XML", ".xml,text/xml,application/xml"),
    fileField("html", "Replacement HotCRP HTML", ".html,.htm,text/html")
  );

  const actions = document.createElement("span");
  actions.className = "updateTrackActions";

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Save updates";

  const message = document.createElement("span");
  message.className = "formMessage";

  actions.append(submit, message);
  form.append(actions);
  form.addEventListener("submit", event => updateReviewFiles(event, track, review, message));
  return form;
}

function fileField(name, labelText, accept) {
  const label = document.createElement("label");
  label.textContent = labelText;

  const input = document.createElement("input");
  input.name = name;
  input.type = "file";
  input.accept = accept;
  label.append(input);
  return label;
}

async function updateReviewFiles(event, track, review, message) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const hasReplacement = [...formData.values()].some(value => value instanceof File && value.name);
  if (!hasReplacement) {
    message.textContent = "Select at least one file to update.";
    return;
  }
  if (!review.parent_id && review.child_count) {
    const confirmed = confirm("Updating the initial review files will delete all existing follow-up panels for this track. Continue?");
    if (!confirmed) {
      return;
    }
  }

  message.textContent = "Updating...";
  try {
    const response = await fetch(`/api/tracks/${encodeURIComponent(track.id)}/reviews/${encodeURIComponent(review.id)}/files`, {
      method: "POST",
      body: formData
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    form.reset();
    form.hidden = true;
    message.textContent = "";
    await loadTracks();
  } catch (error) {
    message.textContent = cleanErrorMessage(error.message);
  }
}

async function removeTrack(track) {
  const confirmed = confirm(`Remove track "${track.name}" and all review history? This cannot be undone.`);
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

async function removeReviewPanel(track, review, button) {
  const confirmed = confirm(`Remove follow-up "${review.label}" from track "${track.name}"? This also removes any follow-up reviews beneath it.`);
  if (!confirmed) {
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch(`/api/tracks/${encodeURIComponent(track.id)}/reviews/${encodeURIComponent(review.id)}`, {
      method: "DELETE"
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await loadTracks();
  } catch (error) {
    alert(cleanErrorMessage(error.message));
  } finally {
    button.disabled = false;
  }
}

async function rerunChecks() {
  if (!state.currentTrack) {
    return;
  }
  if (reviewIsLocked()) {
    alert("This review is locked because it already has a follow-up.");
    return;
  }
  const reviewLabel = state.currentReview?.label || "the selected review";
  const confirmed = confirm(`Rerun automated checks for ${reviewLabel}? This will replace saved check results and evidence, but keep each paper's finished/open status.`);
  if (!confirmed) {
    return;
  }
  clearTimeout(state.saveTimer);
  els.rerunChecks.disabled = true;
  try {
    const response = await fetch(`/api/tracks/${encodeURIComponent(state.currentTrack.id)}/rerun-checks`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({review_id: state.currentReview?.id || null})
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    await openTrack(state.currentTrack.id, state.currentReview?.id || null);
  } catch (error) {
    alert(cleanErrorMessage(error.message));
  } finally {
    els.rerunChecks.disabled = false;
  }
}

async function createTrackFollowUp(event, track, review, button, message) {
  event.preventDefault();
  if (!review) {
    return;
  }
  const form = event.currentTarget;
  const zip = form.querySelector('input[name="zip"]');
  const xml = form.querySelector('input[name="xml"]');
  const html = form.querySelector('input[name="html"]');
  if (!zip?.files?.length || !xml?.files?.length || !html?.files?.length) {
    message.textContent = "Upload ZIP, XML, and HTML before creating the follow-up.";
    return;
  }
  const formData = new FormData(form);
  button.disabled = true;
  message.textContent = "Creating follow-up...";
  try {
    formData.set("parent_review_id", review.id);
    const response = await fetch(`/api/tracks/${encodeURIComponent(track.id)}/follow-ups`, {
      method: "POST",
      body: formData
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    form.reset();
    message.textContent = "";
    await loadTracks();
  } catch (error) {
    message.textContent = cleanErrorMessage(error.message);
  } finally {
    button.disabled = false;
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
    const comparison = submission.comparison_counts || {};
    if (comparison.fixed || comparison.still_present || comparison.new) {
      badges.append(
        badge("comparison fixed", `${comparison.fixed || 0} fixed`),
        badge("comparison still-present", `${comparison.still_present || 0} still present`),
        badge("comparison new", `${comparison.new || 0} new`)
      );
    }

    button.append(title, meta, badges);
    return button;
  }));
}

function renderReviewChain() {
  if (!state.reviews.length) {
    els.reviewChainBar.hidden = true;
    els.reviewChainBar.replaceChildren();
    return;
  }

  const chips = state.reviews.map(review => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "reviewChip";
    button.classList.toggle("active", review.id === state.currentReview?.id);
    button.style.setProperty("--review-depth", review.depth || 0);
    button.textContent = review.label;
    button.title = `${review.label} · ${review.paper_count} papers · ${review.issue_paper_count} issue papers`;
    button.addEventListener("click", async () => {
      await saveSelectedSubmission();
      await openTrack(state.currentTrack.id, review.id);
    });
    return button;
  });

  els.reviewChainBar.hidden = false;
  els.reviewChainBar.replaceChildren(...chips);
}

function reviewIsLocked() {
  return Boolean(state.currentReview?.locked || state.currentReview?.child_count);
}

function updateReviewControls() {
  const locked = reviewIsLocked();
  els.rerunChecks.disabled = locked;
  els.rerunChecks.title = locked ? "This review is locked because it already has a follow-up." : "";
  els.completedToggle.disabled = locked;
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
  const current = visibleSubmissions.find(submission => submission.id === state.selectedId);
  if (current) {
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
  if (!submission) {
    clearSubmission();
    return;
  }
  renderSubmission(submission);
}

function clearSubmission() {
  els.paperTitle.textContent = "No submissions";
  els.paperMeta.textContent = "";
  els.openPdf.href = "#";
  els.openPdf.style.visibility = "hidden";
  hidePdfViewer();
  els.completedToggle.checked = false;
  els.completedToggle.disabled = reviewIsLocked();
  els.checkSummary.textContent = "";
  els.metadataContent.replaceChildren();
  els.issueSummary.replaceChildren();
  els.checklist.replaceChildren();
}

function showResolvedPaper(paperId, title) {
  state.selectedId = paperId;
  document.querySelectorAll(".submissionItem").forEach(item => {
    item.classList.toggle("active", false);
  });
  els.paperTitle.textContent = title ? `#${paperId} ${title}` : `#${paperId}`;
  els.paperMeta.textContent = "";
  els.openPdf.href = "#";
  els.openPdf.style.visibility = "hidden";
  showPdfUnavailable("This paper has no issues anymore in this review.");
  els.completedToggle.checked = false;
  els.completedToggle.disabled = true;
  els.checkSummary.textContent = "No issues in this review";
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
  if (submission.pdf.url) {
    loadPdf(submission.pdf.url);
  } else {
    showPdfUnavailable("No PDF is available for this paper in this review.");
  }
  els.completedToggle.checked = Boolean(submission.completed);
  els.completedToggle.disabled = reviewIsLocked();

  updateComparisonState(submission);
  const counts = submission.status_counts;
  els.checkSummary.textContent = `${counts.pass} pass · ${counts.issue} issue · ${counts.manual} manual · ${counts.unavailable} unavailable`;
  assignCheckDisplayNumbers(submission.checks);
  renderMetadata(submission);
  renderIssueSummary(submission.checks);
  renderChecks(submission.checks);
}

function hidePdfViewer() {
  state.pdfLoadToken += 1;
  els.pdfViewer.src = "about:blank";
  els.pdfViewer.hidden = true;
  els.pdfUnavailable.hidden = true;
}

function showPdfUnavailable(message) {
  state.pdfLoadToken += 1;
  els.pdfViewer.src = "about:blank";
  els.pdfViewer.hidden = true;
  els.pdfUnavailable.hidden = false;
  els.pdfUnavailable.textContent = message;
}

async function loadPdf(url) {
  const token = state.pdfLoadToken + 1;
  state.pdfLoadToken = token;
  els.pdfViewer.src = "about:blank";
  els.pdfViewer.hidden = true;
  els.pdfUnavailable.hidden = false;
  els.pdfUnavailable.textContent = "Loading PDF...";
  try {
    const response = await fetch(url, {method: "HEAD"});
    if (state.pdfLoadToken !== token) {
      return;
    }
    if (!response.ok) {
      showPdfUnavailable("This paper has no issues anymore in this review.");
      return;
    }
    els.pdfUnavailable.hidden = true;
    els.pdfViewer.hidden = false;
    els.pdfViewer.src = url;
  } catch (error) {
    if (state.pdfLoadToken === token) {
      showPdfUnavailable("This paper has no issues anymore in this review.");
    }
  }
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
  const isFollowUp = Boolean(state.currentReview?.parent_id);
  if (!isFollowUp) {
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
      label.textContent = check.label;
      const evidence = document.createElement("span");
      evidence.textContent = `: ${check.evidence}`;
      item.append(label, evidence);
      return item;
    }));

    els.issueSummary.replaceChildren(heading, list);
    return;
  }

  const fixed = checks.filter(check => check.comparison === "fixed");
  const stillPresent = checks.filter(check => check.comparison === "still_present");
  const newIssues = checks.filter(check => check.comparison === "new");

  if (!fixed.length && !stillPresent.length && !newIssues.length) {
    els.issueSummary.replaceChildren();
    return;
  }

  const heading = document.createElement("h3");
  heading.textContent = "Follow-up Summary";

  const summary = document.createElement("p");
  summary.textContent = `${fixed.length} fixed · ${stillPresent.length} still present · ${newIssues.length} new`;

  const sections = [];
  for (const [label, items, kind] of [
    ["Still present", stillPresent, "still-present"],
    ["New", newIssues, "new"],
    ["Fixed", fixed, "fixed"]
  ]) {
    if (!items.length) {
      continue;
    }
    const section = document.createElement("section");
    section.className = "issueGroup";
    const subheading = document.createElement("h4");
    subheading.textContent = label;
    const list = document.createElement("ul");
    list.className = "issueList";
    list.replaceChildren(...items.map(check => {
      const item = document.createElement("li");
      const labelEl = document.createElement("strong");
      labelEl.textContent = check.label;
      const evidence = document.createElement("span");
      evidence.textContent = `: ${check.evidence}`;
      item.append(comparisonBadge(kind), document.createTextNode(" "), labelEl, evidence);
      return item;
    }));
    section.append(subheading, list);
    sections.push(section);
  }

  els.issueSummary.replaceChildren(heading, summary, ...sections);
}

function renderChecks(checks) {
  const submission = selectedSubmission();
  const locked = reviewIsLocked();
  els.checklist.replaceChildren(...checks.map(check => {
    const item = document.createElement("article");
    item.className = `check ${check.status}`;

    const header = document.createElement("div");
    header.className = "checkHeader";

    const titleWrap = document.createElement("div");
    titleWrap.className = "checkTitleWrap";

    const title = document.createElement("div");
    title.className = "checkTitle";
    title.textContent = `${check.display_no}. ${check.label}`;
    titleWrap.append(title);
    if (check.comparison) {
      titleWrap.append(comparisonBadge(check.comparison));
    }

    const status = document.createElement("select");
    status.className = `statusSelect ${check.status}`;
    status.setAttribute("aria-label", `${check.label} result`);
    status.disabled = locked;
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
      updateComparisonState(submission);
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
    evidence.readOnly = locked;
    evidence.addEventListener("input", () => {
      check.evidence = evidence.value;
      evidence.rows = Math.max(2, Math.min(8, Math.ceil(evidence.value.length / 58)));
      updateComparisonState(submission);
      renderIssueSummary(checks);
      scheduleSaveSubmission(submission);
    });

    const source = document.createElement("div");
    source.className = "source";
    source.textContent = `Source: ${check.source}`;

    header.append(titleWrap, status);
    item.append(header, evidence, source);
    return item;
  }));
}

function assignCheckDisplayNumbers(checks) {
  checks.forEach((check, index) => {
    check.display_no = index + 1;
  });
}

function updateComparisonState(submission) {
  if (!submission || !submission.checks) {
    return;
  }
  if (!state.currentReview?.parent_id) {
    submission.checks.forEach(check => {
      check.comparison = "";
    });
    submission.comparison_counts = {fixed: 0, still_present: 0, new: 0, unchanged: submission.checks.length};
    return;
  }
  const counts = {fixed: 0, still_present: 0, new: 0, unchanged: 0};
  submission.checks.forEach(check => {
    const baselineIssue = check.baseline_status === "issue";
    const currentIssue = check.status === "issue";
    let comparison = "";
    if (baselineIssue && currentIssue) {
      comparison = "still_present";
    } else if (baselineIssue && !currentIssue) {
      comparison = "fixed";
    } else if (!baselineIssue && currentIssue) {
      comparison = "new";
    }
    check.comparison = comparison;
    if (comparison) {
      counts[comparison] += 1;
    } else {
      counts.unchanged += 1;
    }
  });
  submission.comparison_counts = counts;
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

function comparisonBadge(kind) {
  const normalized = String(kind || "").replaceAll("_", "-");
  const label = {
    fixed: "fixed",
    "still-present": "still present",
    new: "new"
  }[normalized] || normalized;
  return badge(`comparison ${normalized}`, label);
}

function selectedSubmission() {
  return state.submissions.find(item => item.id === state.selectedId);
}

function scheduleSaveSubmission(submission) {
  if (reviewIsLocked()) {
    return;
  }
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => saveSubmission(submission), 350);
}

async function saveSelectedSubmission() {
  const submission = selectedSubmission();
  return saveSubmission(submission);
}

async function saveSubmission(submission) {
  if (!state.currentTrack || !submission || reviewIsLocked()) {
    return;
  }
  await fetch(`/api/tracks/${encodeURIComponent(state.currentTrack.id)}/reviews`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      review_id: state.currentReview?.id || null,
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

  const rows = [["review_id", "review_label", "paper_id", "issue_summary", ...checkLabels]];
  for (const submission of state.submissions) {
    const checksByLabel = new Map(submission.checks.map((check, index) => [`${index + 1}. ${check.label}`, check]));
    const issueSummary = submission.checks
      .filter(check => check.status === "issue")
      .map(check => `${check.display_no || submission.checks.indexOf(check) + 1}. ${check.label}: ${check.evidence}`)
      .join("\n");
    rows.push([
      state.currentReview?.id || "",
      state.currentReview?.label || "",
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
  if (reviewIsLocked()) {
    els.completedToggle.checked = Boolean(selectedSubmission()?.completed);
    return;
  }
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
