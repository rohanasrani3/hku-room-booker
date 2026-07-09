const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = Number(process.env.PORT || 8787);
const PUBLIC_DIR = path.join(__dirname, "public");

function loadDotEnv() {
  const envPath = path.join(__dirname, ".env");
  if (!fs.existsSync(envPath)) {
    return;
  }

  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const equalsAt = trimmed.indexOf("=");
    if (equalsAt === -1) {
      continue;
    }
    const key = trimmed.slice(0, equalsAt).trim();
    const value = trimmed.slice(equalsAt + 1).trim().replace(/^["']|["']$/g, "");
    if (key && !process.env[key]) {
      process.env[key] = value;
    }
  }
}

loadDotEnv();

const TARGETS = [
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

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function json(res, statusCode, body) {
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 16_384) {
        req.destroy();
        reject(new Error("Request body is too large."));
      }
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Invalid JSON."));
      }
    });
    req.on("error", reject);
  });
}

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function assertAppAccess(req) {
  const expected = process.env.APP_ACCESS_TOKEN;
  if (!expected) {
    return;
  }

  const provided = req.headers["x-app-token"];
  if (provided !== expected) {
    const err = new Error("Unauthorized.");
    err.statusCode = 401;
    throw err;
  }
}

function normalizeInputs(body) {
  const action = String(body.action || "");
  const date = String(body.date || "");
  const time = String(body.time || "");
  const duration = String(body.duration || "");
  const roomTarget = String(body.room_target || "");
  const purpose = String(body.purpose || "Study").trim() || "Study";
  const dryRun = Boolean(body.dry_run);

  if (!["book_now", "schedule_future"].includes(action)) {
    throw new Error("Invalid action.");
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error("Date must be YYYY-MM-DD.");
  }
  if (!/^\d{2}:00$/.test(time)) {
    throw new Error("Time must be HH:00.");
  }
  if (!["1", "2", "3", "4"].includes(duration)) {
    throw new Error("Duration must be 1, 2, 3, or 4.");
  }
  if (!TARGETS.includes(roomTarget)) {
    throw new Error("Invalid room target.");
  }
  if (purpose.length > 80) {
    throw new Error("Purpose must be 80 characters or fewer.");
  }

  return {
    action,
    date,
    time,
    duration,
    room_target: roomTarget,
    purpose,
    dry_run: dryRun,
  };
}

async function dispatchWorkflow(inputs) {
  const owner = requireEnv("GITHUB_OWNER");
  const repo = requireEnv("GITHUB_REPO");
  const token = requireEnv("GITHUB_TOKEN");
  const workflow = process.env.GITHUB_WORKFLOW_FILE || "book.yml";
  const ref = process.env.GITHUB_REF || "main";

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "hku-room-booker-ui",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref, inputs }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`GitHub dispatch failed (${response.status}): ${text}`);
  }

  return {
    actionsUrl: `https://github.com/${owner}/${repo}/actions/workflows/${workflow}`,
    repo: `${owner}/${repo}`,
    ref,
  };
}

function serveStatic(req, res, headOnly = false) {
  const requestPath = new URL(req.url, "http://localhost").pathname;
  const safePath = requestPath === "/" ? "/index.html" : requestPath;
  const filePath = path.normalize(path.join(PUBLIC_DIR, safePath));

  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, {
      "Content-Type": MIME_TYPES[ext] || "application/octet-stream",
      "Cache-Control": ext === ".html" ? "no-store" : "public, max-age=3600",
    });
    if (headOnly) {
      res.end();
      return;
    }
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") {
      json(res, 200, { ok: true });
      return;
    }

    if (req.method === "GET" && req.url === "/api/config") {
      json(res, 200, {
        authRequired: Boolean(process.env.APP_ACCESS_TOKEN),
        repo: process.env.GITHUB_OWNER && process.env.GITHUB_REPO
          ? `${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}`
          : "",
        ref: process.env.GITHUB_REF || "main",
        targets: TARGETS,
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/dispatch") {
      assertAppAccess(req);
      const body = await readJson(req);
      const inputs = normalizeInputs(body);
      const result = await dispatchWorkflow(inputs);
      json(res, 202, { ok: true, inputs, ...result });
      return;
    }

    if (req.method === "GET") {
      serveStatic(req, res);
      return;
    }

    if (req.method === "HEAD") {
      serveStatic(req, res, true);
      return;
    }

    res.writeHead(405);
    res.end("Method not allowed");
  } catch (err) {
    const statusCode = err.statusCode || 400;
    json(res, statusCode, { ok: false, error: err.message || "Request failed." });
  }
});

server.listen(PORT, () => {
  console.log(`HKU Room Booker UI listening on port ${PORT}`);
});
