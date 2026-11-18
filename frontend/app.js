/* Health Facility Finder: dependency-free single-page app.
 * Routes: /  (search, state kept in the query string)  /facility/<id>  /stats
 * All API text is inserted with textContent, never innerHTML. */
(function () {
  "use strict";
  const API = window.HFR_CONFIG.API_BASE;
  const main = document.getElementById("main");
  document.getElementById("api-docs-link").href = API + "/docs";

  // ---------- tiny helpers ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "text") el.textContent = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) el.append(kid);
    return el;
  }

  async function api(path, params) {
    const url = new URL(API + path);
    for (const [k, v] of Object.entries(params || {})) if (v) url.searchParams.set(k, v);
    let res;
    try { res = await fetch(url); }
    catch { throw new Error("Cannot reach the server. Check your connection and try again."); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = body.error && body.error.message;
      const err = new Error(msg || `Request failed (${res.status}).`);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  const cache = {};
  const cached = (path) => (cache[path] ||= api(path));

  function go(url, replace) {
    history[replace ? "replaceState" : "pushState"]({}, "", url);
    render();
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-link]");
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    go(a.getAttribute("href"));
  });
  window.addEventListener("popstate", render);

  function setTitle(t) { document.title = t ? `${t} · Health Facility Finder` : "Health Facility Finder"; }
  function status(text) { // announced by screen readers
    let live = document.getElementById("live");
    if (!live) { live = h("p", { id: "live", class: "sr", role: "status", "aria-live": "polite" }); document.body.append(live); live.style.cssText = "position:absolute;left:-999px"; }
    live.textContent = text;
  }

  // ---------- router ----------
  function render() {
    const path = location.pathname;
    const m = path.match(/^\/facility\/([A-Za-z0-9]+)\/?$/);
    if (m) return renderDetails(m[1].toUpperCase());
    if (path === "/stats") return renderStats();
    return renderSearch();
  }

  // ---------- search ----------
  const SEARCH_BY = [
    ["name", "Facility name"], ["facilityType", "Facility type"],
    ["facilityId", "Facility ID"], ["systemOfMedicine", "System of medicine"],
  ];
  const SORTS = [["name", "Name"], ["district", "District"], ["beds", "Beds (most first)"]];

  function selectField(id, label, options, value, onchange) {
    const sel = h("select", { id, name: id, onchange }, h("option", { value: "", text: "All" }),
      options.map(([v, t]) => h("option", { value: v, text: t, selected: v === value })));
    return h("div", {}, h("label", { for: id, text: label }), sel);
  }

  async function renderSearch() {
    setTitle("Search");
    const q = Object.fromEntries(new URLSearchParams(location.search));
    q.by = q.by || "name";
    main.replaceChildren(h("h1", { text: "Find a health facility" }));

    const [states, ownerships, types, systems, specs] = await Promise.all([
      cached("/api/masters/states"), cached("/api/masters/ownership"), cached("/api/masters/facility-types"),
      cached("/api/masters/systems-of-medicine"), cached("/api/masters/specialities"),
    ]).catch((err) => { main.append(h("p", { class: "notice error", role: "alert", text: err.message })); return []; });
    if (!states) return;

    const stateSel = selectField("state", "State", states.map((s) => [s.stateLGDCode, s.stateName]), q.state, onStateChange);
    const districtSel = selectField("district", "District", [], q.district);
    const districtEl = districtSel.querySelector("select");
    const stateEl = stateSel.querySelector("select");

    async function loadDistricts(stateCode, selected) {
      districtEl.replaceChildren(h("option", { value: "", text: "All" }));
      districtEl.disabled = !stateCode;
      if (!stateCode) return;
      try {
        const list = await cached(`/api/masters/states/${stateCode}/districts`);
        for (const d of list) districtEl.append(h("option", { value: d.districtLGDCode, text: d.districtName, selected: d.districtLGDCode === selected }));
      } catch (err) { status(err.message); }
    }
    function onStateChange() { loadDistricts(stateEl.value, ""); }
    loadDistricts(q.state, q.district);

    const byEl = h("select", { id: "by", name: "by", onchange: drawValueField }, SEARCH_BY.map(([v, t]) => h("option", { value: v, text: t, selected: v === q.by })));
    const valueBox = h("div", {});
    function drawValueField() {
      const by = byEl.value;
      const lists = { facilityType: types.map((t) => [t.code, t.name]), systemOfMedicine: systems.map((s) => [s.code, s.name]) };
      if (lists[by]) valueBox.replaceChildren(selectField("q", "Matching", lists[by], q.by === by ? q.q : "", null));
      else valueBox.replaceChildren(h("label", { for: "q", text: by === "facilityId" ? "Facility ID (e.g. IN0310000334)" : "Facility name" }),
        h("input", { type: "text", id: "q", name: "q", value: q.by === by ? q.q || "" : "", autocomplete: "off", maxlength: "100" }));
    }
    drawValueField();

    const filters = h("details", { class: "filters", open: !!(q.ownership || q.icu || q.speciality) },
      h("summary", { text: "All filters" }),
      h("div", { class: "row" },
        selectField("ownership", "Ownership", ownerships.map((o) => [o.code, o.name]), q.ownership),
        selectField("icu", "ICU services", [["yes", "Yes"], ["no", "No"]], q.icu),
        selectField("speciality", "Speciality", specs.map((s) => [s.name, s.name]), q.speciality)));

    const sortSel = selectField("sort", "Sort by", SORTS, q.sort, () => submit(1));
    const msg = h("div", { id: "msg" });
    const results = h("div", { id: "results", "aria-live": "polite" });

    const form = h("form", { class: "search", onsubmit: (e) => { e.preventDefault(); submit(1); } },
      h("div", { class: "row" }, stateSel, districtSel),
      h("div", { class: "row" }, h("div", {}, h("label", { for: "by", text: "Search by" }), byEl), valueBox),
      filters, sortSel,
      h("div", { class: "actions" },
        h("button", { type: "submit", text: "Search" }),
        h("button", { type: "button", class: "secondary", text: "Reset filters", onclick: () => go("/") })));
    main.append(form, msg, results);

    function submit(page) {
      const data = {
        state: stateEl.value, district: districtEl.value, by: byEl.value,
        q: (form.elements.q.value || "").trim(), ownership: form.elements.ownership.value,
        icu: form.elements.icu.value, speciality: form.elements.speciality.value, sort: form.elements.sort.value,
        page: page > 1 ? String(page) : "",
      };
      const hasFilter = data.state || data.q || data.ownership || data.icu || data.speciality;
      if (!hasFilter) {
        msg.replaceChildren(h("p", { class: "notice error", role: "alert", text: "Choose at least one filter (state, a search value, or an option under All filters)." }));
        results.replaceChildren();
        return;
      }
      const qs = new URLSearchParams(Object.entries(data).filter(([, v]) => v));
      go("/?" + qs.toString());
    }

    if (q.state || q.q || q.ownership || q.icu || q.speciality) runSearch(q, results, msg, submit);
  }

  async function runSearch(q, results, msg, submit) {
    msg.replaceChildren();
    results.replaceChildren(h("p", { class: "notice" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Searching…"));
    const params = { state: q.state, district: q.district, ownership: q.ownership, icu: q.icu, speciality: q.speciality, sort: q.sort, page: q.page || "1", pageSize: "10" };
    if (q.q) params[q.by] = q.q;
    let data;
    try { data = await api("/api/facilities", params); }
    catch (err) {
      results.replaceChildren(h("div", { class: "notice error", role: "alert" }, h("p", { text: err.message }),
        err.status === 400 ? null : h("button", { type: "button", text: "Try again", onclick: () => runSearch(q, results, msg, submit) })));
      return;
    }
    const page = Number(q.page || 1);
    status(`${data.totalFacilities} facilities found`);
    if (!data.facilities.length) {
      results.replaceChildren(h("p", { class: "notice", text: "No facilities match these filters. Try removing a filter or checking the spelling." }));
      return;
    }
    results.replaceChildren(
      h("div", { class: "summary" }, h("strong", { text: `${data.totalFacilities.toLocaleString()} facilities found` }),
        h("span", { class: "meta", text: `Page ${page} of ${data.numberOfPages}` })),
      h("ul", { class: "cards" }, data.facilities.map(card)),
      h("div", { class: "pager" },
        h("button", { type: "button", class: "secondary", text: "Previous", disabled: page <= 1, onclick: () => submit(page - 1) }),
        h("button", { type: "button", class: "secondary", text: "Next", disabled: page >= data.numberOfPages, onclick: () => submit(page + 1) })));
  }

  function mapLink(f) {
    if (!f.latitude || !f.longitude) return null;
    const lat = encodeURIComponent(f.latitude), lon = encodeURIComponent(f.longitude);
    return h("a", { href: `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=16/${lat}/${lon}`, target: "_blank", rel: "noopener noreferrer", text: "View on map" });
  }

  function badge(status) {
    return h("span", { class: "badge " + (status === "Approved" ? "approved" : "other"), text: status });
  }

  function card(f) {
    return h("li", { class: "card" },
      h("h2", {}, h("a", { href: `/facility/${f.facilityId}`, "data-link": true, text: f.facilityName }), badge(f.facilityStatus)),
      h("p", { class: "meta", text: `ID ${f.facilityId} · ${f.ownership || "Ownership n/a"} · ${f.facilityType || "Type n/a"}` }),
      h("p", { class: "meta", text: `ICU services: ${f.hasIcuBeds} · ABDM-enabled software: ${f.abdmSoftware}` }),
      h("p", { class: "meta", text: [f.address, f.districtName, f.stateName, f.pincode].filter(Boolean).join(", ") }),
      mapLink(f));
  }

  // ---------- details ----------
  async function renderDetails(id) {
    setTitle(id);
    main.replaceChildren(h("p", { class: "notice" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Loading…"));
    let f;
    try { f = await api(`/api/facilities/${id}`); }
    catch (err) {
      main.replaceChildren(h("p", { class: "notice error", role: "alert", text: err.status === 404 ? `No facility found with ID ${id}.` : err.message }),
        h("p", {}, h("a", { href: "/", "data-link": true, text: "← Back to search" })));
      return;
    }
    setTitle(f.facilityName);
    const row = (k, v) => (v == null || v === "" ? [] : [h("dt", { text: k }), h("dd", {}, v)]);
    main.replaceChildren(
      h("p", {}, h("a", { href: "#", text: "← Back to results", onclick: (e) => { e.preventDefault(); history.length > 1 ? history.back() : go("/"); } })),
      h("h1", {}, f.facilityName, badge(f.facilityStatus)),
      h("dl", { class: "details" },
        row("Facility ID", f.facilityId), row("Ownership", f.ownership), row("Facility type", f.facilityType),
        row("System of medicine", f.systemOfMedicine), row("ICU services", f.hasIcuBeds),
        row("ABDM-enabled software", f.abdmSoftware), row("Total beds", f.totalBeds), row("ICU beds", f.icuBeds),
        row("Address", f.address), row("Village / city / town", f.villageCityTownName), row("Sub-district", f.subDistrictName),
        row("District", f.districtName), row("State", f.stateName), row("Pincode", f.pincode),
        row("Coordinates", f.latitude && f.longitude ? `${f.latitude}, ${f.longitude}` : null),
        row("Map", mapLink(f)),
        row("Specialities", f.specialities.length ? h("ul", { class: "tags" }, f.specialities.map((s) => h("li", { text: s }))) : "None listed")));
    main.focus();
  }

  // ---------- statistics ----------
  async function renderStats() {
    setTitle("Statistics");
    main.replaceChildren(h("h1", { text: "Statistics" }), h("p", { class: "notice" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Loading…"));
    let s;
    try { s = await api("/api/stats"); }
    catch (err) { main.replaceChildren(h("h1", { text: "Statistics" }), h("p", { class: "notice error", role: "alert", text: err.message })); return; }
    const max = Math.max(1, ...s.byState.map((r) => r.count));
    const tile = (label, n) => h("div", { class: "tile" }, h("b", { text: n.toLocaleString() }), label);
    main.replaceChildren(
      h("h1", { text: "Statistics" }),
      h("div", { class: "tiles" }, tile("Facilities", s.totalFacilities), tile("Total beds", s.totalBeds), tile("ICU beds", s.totalIcuBeds)),
      h("h2", { id: "by-state", text: "Facilities by state" }),
      h("ul", { class: "bars", "aria-labelledby": "by-state" }, s.byState.map((r) =>
        h("li", {}, h("span", { text: r.stateName }),
          h("span", { class: "bar-wrap" }, h("div", { class: "bar", style: `width:${(r.count / max) * 100}%` })),
          h("span", { class: "num", text: r.count.toLocaleString() })))));
  }

  render();
})();
