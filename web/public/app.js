const defaultTargets = [
  "all_study_rooms",
  "chi_wah_study_rooms",
  "chi_wah_study_booths",
  "discussion_rooms",
  "single_study_rooms",
  "study_tables",
  "main_library_discussion_rooms",
  "main_library_single_study_rooms",
  "dental_discussion_rooms",
  "law_discussion_rooms",
  "medical_discussion_rooms",
  "medical_single_study_rooms",
  "music_discussion_rooms",
];

const targetLabels = {
  all_study_rooms: "All study rooms",
  chi_wah_study_rooms: "Chi Wah study rooms",
  chi_wah_study_booths: "Chi Wah study booths",
  discussion_rooms: "All discussion rooms",
  single_study_rooms: "All single study rooms",
  study_tables: "Study tables",
  main_library_discussion_rooms: "Main Library discussion",
  main_library_single_study_rooms: "Main Library single study",
  dental_discussion_rooms: "Dental discussion",
  law_discussion_rooms: "Law discussion",
  medical_discussion_rooms: "Medical discussion",
  medical_single_study_rooms: "Medical single study",
  music_discussion_rooms: "Music discussion",
};

const form = document.querySelector("#bookingForm");
const roomTarget = document.querySelector("#roomTarget");
const statusTitle = document.querySelector("#statusTitle");
const connectionState = document.querySelector("#connectionState");
const repoName = document.querySelector("#repoName");
const repoRef = document.querySelector("#repoRef");
const lastRequest = document.querySelector("#lastRequest");
const actionsLink = document.querySelector("#actionsLink");
const tokenField = document.querySelector("#tokenField");
const directGithubFields = document.querySelector("#directGithubFields");
const dryRunRow = document.querySelector("#dryRunRow");
const submitButton = document.querySelector("#submitButton");

const appState = {
  dispatchMode: "direct",
  serverRepo: "",
  serverRef: "main",
};

function tomorrowIso() {
  const now = new Date();
  now.setDate(now.getDate() + 1);
  return now.toISOString().slice(0, 10);
}

function setStatus(text, state = "") {
  statusTitle.textContent = text;
  statusTitle.className = state;
  connectionState.textContent = text;
  connectionState.className = `run-state ${state}`;
}

function setActionsLink(href) {
  if (!href) {
    actionsLink.href = "#";
    actionsLink.classList.add("disabled");
    return;
  }
  actionsLink.href = href;
  actionsLink.classList.remove("disabled");
}

function updateMode() {
  const action = new FormData(form).get("action");
  const isFuture = action === "schedule_future";
  dryRunRow.classList.toggle("hidden", isFuture);
  submitButton.querySelector("span:last-child").textContent = isFuture ? "Queue Booking" : "Run Booking";
}

function fillTargets(targets) {
  roomTarget.innerHTML = "";
  for (const target of targets) {
    const option = document.createElement("option");
    option.value = target;
    option.textContent = targetLabels[target] || target.replaceAll("_", " ");
    roomTarget.append(option);
  }
  roomTarget.value = targets.includes("all_study_rooms") ? "all_study_rooms" : targets[0];
}

function setDirectMode() {
  appState.dispatchMode = "direct";
  directGithubFields.classList.remove("hidden");
  tokenField.classList.add("hidden");
  repoName.textContent = "Enter fork details";
  repoRef.textContent = "main";
  setActionsLink("");
  fillTargets(defaultTargets);
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("No server config.");
    }
    const config = await response.json();
    if (!config.repo) {
      setDirectMode();
      return;
    }

    appState.dispatchMode = "server";
    appState.serverRepo = config.repo || "";
    appState.serverRef = config.ref || "main";
    directGithubFields.classList.add("hidden");
    tokenField.classList.toggle("hidden", !config.authRequired);
    fillTargets(config.targets || defaultTargets);
    repoName.textContent = appState.serverRepo || "Not configured";
    repoRef.textContent = appState.serverRef;
    setActionsLink(appState.serverRepo ? `https://github.com/${appState.serverRepo}/actions` : "");
  } catch {
    setDirectMode();
  }
}

function workflowInputs(data) {
  return {
    action: data.get("action"),
    date: data.get("date"),
    time: data.get("time"),
    duration: data.get("duration"),
    room_target: data.get("room_target"),
    purpose: data.get("purpose"),
    dry_run: data.get("dry_run") === "on",
  };
}

function directConfig(data) {
  const owner = String(data.get("github_owner") || "").trim();
  const repo = String(data.get("github_repo") || "").trim();
  const ref = String(data.get("github_ref") || "main").trim();
  const workflow = String(data.get("github_workflow") || "book.yml").trim();
  const token = String(data.get("github_token") || "").trim();

  if (!owner || !repo || !ref || !workflow || !token) {
    throw new Error("GitHub owner, repo, branch, workflow, and token are required.");
  }

  return { owner, repo, ref, workflow, token };
}

function requestSummary(inputs) {
  return `${inputs.date} ${inputs.time} / ${targetLabels[inputs.room_target]}`;
}

async function dispatchThroughServer(inputs, appToken) {
  const response = await fetch("/api/dispatch", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-App-Token": appToken,
    },
    body: JSON.stringify(inputs),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || "Dispatch failed.");
  }
  return result.actionsUrl;
}

async function dispatchDirect(inputs, config) {
  const url = `https://api.github.com/repos/${encodeURIComponent(config.owner)}/${encodeURIComponent(config.repo)}/actions/workflows/${encodeURIComponent(config.workflow)}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${config.token}`,
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: config.ref, inputs }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`GitHub dispatch failed (${response.status}): ${message}`);
  }

  return `https://github.com/${config.owner}/${config.repo}/actions/workflows/${config.workflow}`;
}

async function submitBooking(event) {
  event.preventDefault();
  const data = new FormData(form);
  const inputs = workflowInputs(data);

  submitButton.disabled = true;
  setStatus("Dispatching", "is-pending");
  lastRequest.textContent = requestSummary(inputs);

  try {
    let actionsUrl;
    if (appState.dispatchMode === "server") {
      actionsUrl = await dispatchThroughServer(inputs, data.get("app_token") || "");
    } else {
      const config = directConfig(data);
      repoName.textContent = `${config.owner}/${config.repo}`;
      repoRef.textContent = config.ref;
      actionsUrl = await dispatchDirect(inputs, config);
    }

    setStatus("Dispatched", "is-success");
    setActionsLink(actionsUrl);
  } catch (err) {
    setStatus("Failed", "is-error");
    lastRequest.textContent = err.message;
  } finally {
    submitButton.disabled = false;
  }
}

form.date.value = tomorrowIso();
form.addEventListener("change", updateMode);
form.addEventListener("submit", submitBooking);
updateMode();

loadConfig()
  .then(() => setStatus("Ready"))
  .catch((err) => {
    setDirectMode();
    setStatus("Config Error", "is-error");
    lastRequest.textContent = err.message;
  });
