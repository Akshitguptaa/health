/*
 * NHPR capture helper. Paste into the browser console (F12 -> Console) on
 * https://nhpr.abdm.gov.in/nhpr/v4/search/facility
 *
 * What it does: it only LISTENS to the search responses your own browser
 * already receives and keeps a copy. YOU still solve every captcha and click
 * Search yourself. It does not fill the captcha, call the API, or skip anything.
 *
 * Commands after pasting:
 *   hfrStatus()  how many pages / facilities captured so far
 *   hfrSave()    download everything captured as one nhpr-capture-*.json file
 *   hfrClear()   forget everything captured (also clears the local backup)
 * It auto-downloads a file every 20 captured pages, and keeps a localStorage
 * backup so a page refresh does not lose your work (paste the script again after refresh).
 */
(() => {
  if (window.__hfr) { console.log("[hfr] already installed. Use hfrStatus() / hfrSave()."); return; }

  const BACKUP_KEY = "hfr_capture_backup";
  const AUTOSAVE_EVERY = 20;
  const MATCH = /\/search\/searchFacility/i;      // the request the site itself makes
  const store = { captures: [], seen: new Set(), apiUrls: new Set(), unsaved: 0 };
  window.__hfr = store;

  try {
    const old = JSON.parse(localStorage.getItem(BACKUP_KEY) || "[]");
    for (const body of old) { store.captures.push(body); store.seen.add(JSON.stringify(body)); }
    if (old.length) console.log(`[hfr] restored ${old.length} pages from the local backup`);
  } catch { /* backup is optional */ }

  const countFacilities = (b) => {
    for (const k of ["facilities", "content", "facilityList", "records"]) {
      if (Array.isArray(b?.[k])) return b[k].length;
      if (Array.isArray(b?.data?.[k])) return b.data[k].length;
    }
    return b?.facilityId || b?.data?.facilityId ? 1 : 0;
  };
  const totalFacilities = () => store.captures.reduce((n, b) => n + countFacilities(b), 0);

  // small on-page counter so you can see it is working
  const badge = document.createElement("div");
  badge.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:99999;background:#0b6b6b;color:#fff;" +
    "font:13px system-ui;padding:6px 10px;border-radius:6px;opacity:.92;pointer-events:none";
  document.body.append(badge);
  const refresh = () => { badge.textContent = `HFR capture: ${store.captures.length} pages, ${totalFacilities()} facilities`; };
  refresh();

  function record(url, status, text) {
    try {
      const u = new URL(url, location.href);
      if (u.hostname.endsWith("abdm.gov.in")) store.apiUrls.add(u.origin + u.pathname);
    } catch { /* ignore */ }
    if (!MATCH.test(url) || status !== 200) return;
    let body;
    try { body = JSON.parse(text); } catch { return; }
    const key = JSON.stringify(body);
    if (store.seen.has(key)) return;               // same page captured twice
    const n = countFacilities(body);
    if (n === 0) {
      console.warn("[hfr] a search response had 0 facilities (wrong captcha or unknown shape). Not saved.", body);
      return;
    }
    store.seen.add(key);
    store.captures.push(body);
    store.unsaved++;
    try { localStorage.setItem(BACKUP_KEY, JSON.stringify(store.captures)); } catch { /* quota */ }
    refresh();
    console.log(`[hfr] saved page ${store.captures.length}: ${n} facilities (total ${totalFacilities()})`);
    if (store.unsaved >= AUTOSAVE_EVERY) window.hfrSave();
  }

  // The site uses XHR (axios); fetch is hooked too in case that changes.
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await origFetch.apply(this, args);
    try { res.clone().text().then((t) => record(res.url, res.status, t)); } catch { /* ignore */ }
    return res;
  };
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.addEventListener("load", () => {
      try {
        const t = this.responseType === "" || this.responseType === "text"
          ? this.responseText
          : typeof this.response === "string" ? this.response : JSON.stringify(this.response);
        record(this.responseURL || String(url), this.status, t);
      } catch { /* ignore */ }
    });
    return origOpen.call(this, method, url, ...rest);
  };

  window.hfrSave = () => {
    if (!store.captures.length) { console.log("[hfr] nothing captured yet"); return; }
    const blob = new Blob([JSON.stringify({ captures: store.captures }, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `nhpr-capture-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    a.click();
    store.unsaved = 0;
    console.log(`[hfr] downloaded ${store.captures.length} pages. Move the file into data/raw/`);
  };
  window.hfrStatus = () => {
    console.log(`[hfr] ${store.captures.length} pages, ${totalFacilities()} facilities, ${store.unsaved} not yet downloaded`);
    console.log("[hfr] API URLs seen:", [...store.apiUrls]);
  };
  window.hfrClear = () => {
    store.captures.length = 0; store.seen.clear(); store.unsaved = 0;
    try { localStorage.removeItem(BACKUP_KEY); } catch { /* ignore */ }
    refresh();
  };

  console.log("[hfr] installed. Solve the captcha and search as normal; I just keep a copy of each result page.");
})();
