/* DOM helpers */
export const $ = (id) => document.getElementById(id);

export function log(msg) {
  const el = $("log");
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  el.textContent = `${line}
${el.textContent}`.slice(0, 4000);
}

export function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export async function copyText(text, okMsg = "copied") {
  const value = String(text || "");
  if (!value) {
    log("nothing to copy");
    return;
  }
  try {
    await navigator.clipboard.writeText(value);
    log(okMsg);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = value;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    log(okMsg);
  }
}
