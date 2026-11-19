// Runs only on https://cla.ms/extension/connect. The page mints a token while
// signed in and hands it over with window.postMessage; we keep it.
(() => {
  const CLAMS = "https://cla.ms";
  const ext = globalThis.browser ?? globalThis.chrome;
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Browser";

  document.documentElement.dataset.clamsExtension = "1";
  document.documentElement.dataset.clamsBrowser = browser;
  const say = (msg) => window.postMessage({ source: "clams-ext", ...msg }, location.origin);

  window.addEventListener("message", async (e) => {
    if (e.source !== window || e.origin !== CLAMS) return;
    const m = e.data || {};
    if (m.source !== "clams-page") return;
    if (m.type === "hello") return say({ type: "ready", browser });
    if (m.type !== "token" || typeof m.token !== "string" || !m.token.startsWith("clm_")) return;
    try {
      await ext.storage.local.set({ token: m.token, email: m.email || "", signedOut: false });
      const { pending = [] } = await ext.storage.local.get("pending");
      let claimed = 0;
      if (pending.length) {
        const r = await fetch(`${CLAMS}/api/v1/links/claim`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${m.token}` },
          body: JSON.stringify({ claim_tokens: pending }),
        });
        if (r.ok) claimed = (await r.json()).claimed || 0;
        await ext.storage.local.set({ pending: [], anon: {} });
      }
      say({ type: "connected", claimed });
    } catch (err) {
      say({ type: "failed" });
    }
  });
})();
