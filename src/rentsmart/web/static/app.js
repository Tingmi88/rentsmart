// rentsmart: tabs (progressive enhancement), print expansion, and the asking-price what-if.
(() => {
  let current = "panel-advice";

  const show = (wanted) => {
    const tabs = document.querySelectorAll('[role="tab"]');
    if (!tabs.length) return;
    const id = document.getElementById(wanted) ? wanted : tabs[0].dataset.panel;
    current = id;
    tabs.forEach((t) => {
      const on = t.dataset.panel === id;
      t.setAttribute("aria-selected", String(on));
      const panel = document.getElementById(t.dataset.panel);
      if (panel) panel.hidden = !on;
    });
  };

  // Delegated, so it keeps working after the what-if replaces the live region.
  document.addEventListener("click", (e) => {
    const el = e.target instanceof Element ? e.target.closest("[data-panel], [data-tab-link]") : null;
    if (!el) return;
    e.preventDefault();
    show(el.dataset.panel || el.dataset.tabLink);
  });

  if (document.querySelector('[role="tab"]')) {
    document.documentElement.classList.add("js-tabs");
    show(current);
  }

  window.addEventListener("beforeprint", () => {
    document.querySelectorAll(".panel").forEach((p) => { p.hidden = false; });
    document.querySelectorAll("details").forEach((d) => { d.open = true; });
  });
  window.addEventListener("afterprint", () => show(current));

  // A second click on Run would spend API calls again.
  document.querySelectorAll('form[method="post"]').forEach((f) =>
    f.addEventListener("submit", () => {
      const button = f.querySelector("button");
      if (button) button.disabled = true;
    }));

  // Remember the last address entry in this browser, so Back or "New address" doesn't wipe it.
  // Server-filled values (an input error) win; storage may be blocked, so every access is guarded.
  const KEY = "rentsmart:last-entry";
  const entry = document.querySelector("form[data-remember]");
  if (entry) {
    const fields = [...entry.elements].filter((el) => el.name);
    const clear = entry.querySelector("[data-clear]");
    if (fields.every((el) => !el.value)) {
      try {
        const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
        fields.forEach((el) => { if (typeof saved[el.name] === "string") el.value = saved[el.name]; });
      } catch { /* blocked or unreadable: start empty */ }
    }
    if (clear) {
      clear.hidden = false;
      clear.addEventListener("click", () => {
        fields.forEach((el) => { el.value = ""; });
        try { localStorage.removeItem(KEY); } catch { /* nothing saved */ }
        fields[0].focus();
      });
    }
    entry.addEventListener("submit", () => {
      try { localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(new FormData(entry)))); } catch { /* not remembered */ }
    });
  }

  const form = document.querySelector("form[data-whatif]");
  const live = document.getElementById("live");
  if (!form || !live) return;
  const num = form.elements.namedItem("asking");
  const range = form.elements.namedItem("asking_range");
  const listed = form.elements.namedItem("listed");
  let timer;
  let seq = 0;

  const update = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const params = new URLSearchParams(new FormData(form));
      params.delete("asking_range");
      if (!params.get("asking")) params.delete("listed"); // listed needs an asking price
      const mine = ++seq;
      try {
        const resp = await fetch("/brief/sections?" + params.toString());
        const html = await resp.text();
        if (mine !== seq) return; // a newer request superseded this one
        live.innerHTML = html; // server-rendered and autoescaped
        show(current);
      } catch {
        live.insertAdjacentHTML("afterbegin", '<p class="banner">The local server stopped. Restart rentsmart-ui.</p>');
      }
    }, 250);
  };

  if (range) range.addEventListener("input", () => { num.value = range.value; update(); });
  num.addEventListener("input", () => { if (range && num.value) range.value = num.value; update(); });
  if (listed) listed.addEventListener("change", update);
  form.addEventListener("submit", (e) => { e.preventDefault(); update(); });
})();
