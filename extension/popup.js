const DEFAULT_BACKEND = "https://bookshelf-extractor-tingubachhi.fly.dev";

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
}

async function loadSettings() {
  const { backend } = await chrome.storage.sync.get({ backend: DEFAULT_BACKEND });
  $("backend").value = backend;
}

$("backend").addEventListener("change", () => {
  chrome.storage.sync.set({ backend: $("backend").value.trim() || DEFAULT_BACKEND });
});

function findSectionInPage() {
  const NS = 'http://www.idpf.org/2007/ops';
  const sections = [...document.querySelectorAll('section')];
  const types = [...new Set(sections.map(s => s.getAttribute('epub:type') || '(no epub:type)'))];
  const found =
       sections.find(s => s.getAttribute('epub:type') === 'division')
    || sections.find(s => s.getAttributeNS && s.getAttributeNS(NS, 'type') === 'division')
    || sections.find(s => [...s.attributes].some(a => a.value === 'division'));
  return { html: found ? found.outerHTML : null, count: sections.length, types };
}

async function extractFromActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) throw new Error("No active tab.");

  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id, allFrames: true },
    func: findSectionInPage,
  });
  const diag = [];
  for (const r of results) {
    const v = r && r.result;
    if (!v) continue;
    if (v.html) return { html: v.html, tabUrl: tab.url, diag: null };
    if (v.count > 0) diag.push(v.count + " <section> [" + v.types.slice(0, 4).join(", ") + "]");
  }
  return { html: null, tabUrl: tab.url, diag: diag.join(" | ") };
}

async function run() {
  const btn = $("extract");
  btn.disabled = true;
  try {
    setStatus("Looking for chapter section…");
    const { html, diag } = await extractFromActiveTab();
    if (!html) {
      setStatus(
        diag
          ? 'No "division" section found. Frames had: ' + diag
          : "No <section> elements found on this page.",
        true
      );
      return;
    }

    const backend = ($("backend").value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
    const mode = $("mode").value;
    const format = $("format").value;

    setStatus(`Sending ${(html.length / 1024).toFixed(0)} KB to backend…`);
    const resp = await fetch(backend + "/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html, mode, format }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      setStatus(`Server ${resp.status}: ${text.slice(0, 120)}`, true);
      return;
    }

    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="([^"]+)"/);
    const filename = m ? m[1] : (mode === "split" ? "extract.zip" : `extract.${format}`);

    const url = URL.createObjectURL(blob);
    await chrome.downloads.download({ url, filename, saveAs: false });
    setStatus(`Saved ${filename} (${(blob.size / 1024).toFixed(1)} KB).`);
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (err) {
    setStatus("Error: " + err.message, true);
  } finally {
    btn.disabled = false;
  }
}

$("extract").addEventListener("click", run);
loadSettings();
