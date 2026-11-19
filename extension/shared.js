// Shared by the popup and the connect content script.
const CLAMS = "https://cla.ms";
const ext = globalThis.browser ?? globalThis.chrome;

function browserName() {
  const ua = navigator.userAgent;
  if (/Edg\//.test(ua)) return "Edge";
  if (/Chrome\//.test(ua)) return "Chrome";
  if (/Safari\//.test(ua)) return "Safari";
  if (/Firefox\//.test(ua)) return "Firefox";
  return "Browser";
}

async function store(get) {
  return await ext.storage.local.get(get);
}

async function claimPending(token) {
  const { pending = [] } = await store("pending");
  if (!pending.length) return 0;
  const r = await fetch(`${CLAMS}/api/v1/links/claim`, {
    method: "POST",
    credentials: "omit",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, "X-Clams-Extension": "1" },
    body: JSON.stringify({ claim_tokens: pending }),
  });
  if (!r.ok) return 0;
  const { claimed } = await r.json();
  // The anonymous cache now points at Clams the account owns; let the server dedupe from here.
  await ext.storage.local.set({ pending: [], anon: {} });
  return claimed;
}
