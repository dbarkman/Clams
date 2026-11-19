// Hands a fresh extension token to the Clams extension's content script.
(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const show = (id) => {
    for (const el of document.querySelectorAll("[data-step]")) el.classList.toggle("hidden", el.id !== id);
  };
  let started = false;

  async function connect(browser) {
    if (started) return;
    started = true;
    show("step-working");
    try {
      const r = await fetch("/extension/connect/token", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf, "X-Clams-Browser": browser || "Browser" },
      });
      if (!r.ok) throw new Error("token");
      const { token, email } = await r.json();
      window.postMessage({ source: "clams-page", type: "token", token, email }, location.origin);
    } catch {
      show("step-error");
    }
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    const m = e.data || {};
    if (m.source !== "clams-ext") return;
    if (m.type === "ready") connect(m.browser);
    if (m.type === "connected") {
      const n = m.claimed || 0;
      document.getElementById("claimed").textContent =
        n ? `We also saved ${n} Clam${n === 1 ? "" : "s"} you made before signing in.` : "";
      show("step-done");
    }
    if (m.type === "failed") show("step-error");
  });

  if (document.documentElement.dataset.clamsExtension) {
    connect(document.documentElement.dataset.clamsBrowser);
  } else {
    window.postMessage({ source: "clams-page", type: "hello" }, location.origin);
  }
  setTimeout(() => { if (!started) show("step-missing"); }, 2500);
})();
