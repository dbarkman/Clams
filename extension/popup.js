// Click the toolbar button → the current page becomes a Clam, copied and ready.
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => { $(id).hidden = !on; };

function fail(message) {
  show("working", false);
  $("error-text").textContent = message;
  show("error");
}

function openTab(path) {
  ext.tabs.create({ url: `${CLAMS}${path}` });
  window.close();
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    $("short").select();
    return document.execCommand && document.execCommand("copy");
  }
}

// If the browser already has a cla.ms sign-in, trade it for an extension token.
async function trySessionUpgrade() {
  try {
    const r = await fetch(`${CLAMS}/api/v1/extension/token`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Clams-Extension": "1", "X-Clams-Browser": browserName() },
    });
    if (!r.ok) return null;
    const { token, email } = await r.json();
    await ext.storage.local.set({ token, email });
    await claimPending(token);
    return token;
  } catch {
    return null;
  }
}

async function shorten(url, title, token) {
  const headers = { "Content-Type": "application/json", "X-Clams-Extension": "1" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${CLAMS}/api/v1/shorten`, {
    method: "POST", credentials: "omit", headers, body: JSON.stringify({ url, title }),
  });
  const body = await r.json().catch(() => ({}));
  return { status: r.status, body };
}

async function main() {
  const [tab] = await ext.tabs.query({ active: true, currentWindow: true });
  const url = tab && tab.url;
  if (!url || !/^https?:\/\//i.test(url)) return fail("Clams can only shorten regular web pages (http or https).");
  if (/^https:\/\/(www\.)?cla\.ms\//i.test(url)) return fail("This page is already on cla.ms! 🐚");

  let { token, email, anon = {}, pending = [], signedOut } = await store(["token", "email", "anon", "pending", "signedOut"]);
  // After an explicit sign-out, don't quietly reconnect from the website's session.
  if (!token && !signedOut) token = await trySessionUpgrade();
  if (token) ({ email } = await store("email"));

  let link;
  if (!token && anon[url]) {
    link = anon[url];  // already made a Clam for this page while signed out
  } else {
    let res = await shorten(url, tab.title || "", token);
    if (res.status === 401 && token) {
      await ext.storage.local.remove(["token", "email"]);
      token = null;
      res = await shorten(url, tab.title || "", null);
    }
    if (res.status >= 400) return fail(res.body.error || "Something went wrong. Please try again.");
    link = res.body;
    if (!token && link.claim_token) {
      anon[url] = { short_url: link.short_url, url: link.url, claim_token: link.claim_token, saved: false };
      pending = [...pending, link.claim_token];
      await ext.storage.local.set({ anon, pending });
    }
  }

  show("working", false);
  $("short").value = link.short_url.replace(/^https:\/\//, "");
  $("dest").textContent = `→ ${link.url}`;
  show("result");
  $("copy").onclick = async () => {
    await copy(link.short_url);
    $("copy").textContent = "Copied!";
    show("copied");
  };
  show("copied", await copy(link.short_url));

  if (token) {
    $("stats").href = link.stats_url || `${CLAMS}/links`;
    show("saved");
    $("who").textContent = email ? `Signed in as ${email}` : "Signed in";
    show("account");
  } else {
    show("nudge");
  }
}

$("signup").onclick = () => openTab("/signup?next=/extension/connect");
$("signin").onclick = $("signin2").onclick = () => openTab("/login?next=/extension/connect");
$("signout").onclick = async () => {
  const { token } = await store("token");
  if (token) {
    fetch(`${CLAMS}/api/v1/extension/token`, { method: "DELETE", credentials: "omit", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  }
  await ext.storage.local.remove(["token", "email"]);
  await ext.storage.local.set({ signedOut: true });
  show("account", false);
  show("saved", false);
  show("signedout");
};

main().catch(() => fail("Couldn't reach cla.ms. Check your connection and try again."));
