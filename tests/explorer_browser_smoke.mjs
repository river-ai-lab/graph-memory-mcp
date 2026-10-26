/**
 * Headless Explorer smoke. Skipped in CI unless EXPLORER_BROWSER=1.
 * NODE_PATH must include playwright (this environment: /tmp/node_modules).
 */
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const playwrightEntry =
  process.env.PLAYWRIGHT_MODULE || "/tmp/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(playwrightEntry).href);

const base = process.env.EXPLORER_URL || "http://127.0.0.1:8088";
const authUrl = process.env.EXPLORER_AUTH_URL || "";
const unicodeOwner = process.env.EXPLORER_UNICODE_OWNER || "";
const shots = process.env.EXPLORER_SHOTS || "/opt/cursor/artifacts";
const errors = [];

function track(page, { ignoreAborted = false } = {}) {
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (ignoreAborted && /ERR_FAILED|net::ERR/.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => errors.push(String(err)));
}

async function overflow(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const footer = document.querySelector(".canvas-footer");
    const toolbar = document.querySelector(".graph-toolbar");
    const footerBox = footer ? footer.getBoundingClientRect() : null;
    const toolbarBox = toolbar ? toolbar.getBoundingClientRect() : null;
    let overlap = 0;
    if (footerBox && toolbarBox) {
      const top = Math.max(footerBox.top, toolbarBox.top);
      const bottom = Math.min(footerBox.bottom, toolbarBox.bottom);
      overlap = Math.max(0, bottom - top);
    }
    return {
      doc: doc.scrollWidth - doc.clientWidth,
      body: document.body.scrollWidth - document.body.clientWidth,
      footerBottom: footerBox ? Math.round(footerBox.bottom) : null,
      viewport: window.innerHeight,
      toolbarFooterOverlap: Math.round(overlap),
      legend: footer ? footer.innerText.replace(/\s+/g, " ") : "",
    };
  });
}

async function waitConnected(page) {
  await page.waitForFunction(
    () => /connected/i.test(document.querySelector("#status-badge")?.textContent || ""),
    null,
    { timeout: 20000 },
  );
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
track(page);
await mkdir(shots, { recursive: true });

try {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${base}/?owner=readme_demo`, { waitUntil: "domcontentloaded" });
  await waitConnected(page);
  await page.fill("#owner-id", "readme_demo");
  await page.click("#btn-brief");
  await page.waitForFunction(
    () => document.querySelectorAll("#overview [data-id]").length > 0,
    null,
    { timeout: 20000 },
  );
  const wide = await overflow(page);
  if (wide.doc > 1 || wide.body > 1) {
    throw new Error(`horizontal overflow at 1280: ${JSON.stringify(wide)}`);
  }
  if (!/Contradicts/.test(wide.legend) || !/Follows from/.test(wide.legend)) {
    throw new Error(`legend missing: ${wide.legend}`);
  }
  if (wide.toolbarFooterOverlap > 8) {
    throw new Error(`toolbar covers legend at 1280: ${JSON.stringify(wide)}`);
  }

  await page.fill("#search-query", "deadline");
  await page.click("#btn-search");
  await page.waitForSelector("#search-results > ul.ov-list > li[data-id]", {
    timeout: 20000,
  });
  await page.click("#search-results > ul.ov-list > li[data-id]");
  await page.waitForFunction(
    () => (document.querySelector("#detail-text")?.textContent || "").length > 0,
  );
  const rawOpen = await page.locator("details summary", { hasText: "Raw fields" }).locator("xpath=..").evaluate((el) => el.open);
  if (rawOpen) throw new Error("raw fields should start collapsed");
  const validity = await page.locator("#detail-validity").textContent();
  if (validity && !/Valid from/.test(validity)) {
    throw new Error(`unexpected validity: ${validity}`);
  }

  await page.locator("summary", { hasText: "More tools" }).click();
  await page.waitForSelector("#trace-from", { state: "visible" });
  await page.selectOption("#node-preview", "always");
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitConnected(page);
  const preview = await page.inputValue("#node-preview");
  if (preview !== "always") throw new Error(`preview did not persist: ${preview}`);
  await page.selectOption("#node-preview", "hover");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(200);
  const narrow = await overflow(page);
  if (narrow.doc > 1 || narrow.body > 1) {
    throw new Error(`horizontal overflow at 390: ${JSON.stringify(narrow)}`);
  }
  if (narrow.toolbarFooterOverlap > 4) {
    throw new Error(`toolbar covers legend at 390: ${JSON.stringify(narrow)}`);
  }
  await page.screenshot({ path: `${shots}/explorer-narrow.png`, fullPage: true });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.fill("#owner-id", "");
  await page.click("#btn-brief");
  await page.waitForFunction(
    () =>
      document.querySelector("#notice-text")?.textContent ===
      "Enter a memory name, then click Load.",
    null,
    { timeout: 5000 },
  );
  const ownerAfter = await page.inputValue("#owner-id");
  const titleAfter = await page.locator("#map-title").textContent();
  if (ownerAfter !== "") throw new Error(`empty owner was rewritten to ${ownerAfter}`);
  if (titleAfter === "default") throw new Error("empty owner loaded the default memory");
  await page.screenshot({ path: `${shots}/explorer-empty-owner.png` });

  if (unicodeOwner) {
    await page.fill("#owner-id", unicodeOwner);
    await page.click("#btn-brief");
    await page.waitForSelector("#overview [data-id]", { timeout: 20000 });
    await page.click("#overview [data-id]");
    await page.waitForFunction(
      () => /Привет|длинн/.test(document.querySelector("#detail-text")?.textContent || ""),
    );
    const text = await page.locator("#detail-text").textContent();
    if (!text.includes("Привет")) throw new Error(`unicode detail missing: ${text.slice(0, 80)}`);
    const uni = await overflow(page);
    if (uni.doc > 1) throw new Error(`unicode overflow: ${JSON.stringify(uni)}`);
    await page.screenshot({ path: `${shots}/explorer-unicode.png` });
  }

  if (authUrl) {
    const auth = await browser.newPage();
    track(auth);
    await auth.setViewportSize({ width: 1280, height: 800 });
    await auth.goto(authUrl, { waitUntil: "domcontentloaded" });
    await waitConnected(auth);
    const disabled = await auth.locator("#owner-id").isDisabled();
    const bound = await auth.locator("#owner-bound").isVisible();
    if (!disabled || !bound) throw new Error("auth owner field is not locked");
    await auth.close();
  }

  const offline = await browser.newPage();
  track(offline, { ignoreAborted: true });
  await offline.route("**/health", (route) => route.abort());
  await offline.route("**/api/tool", (route) => route.abort());
  await offline.goto(base, { waitUntil: "domcontentloaded" });
  await offline.waitForFunction(
    () => /offline/i.test(document.querySelector("#status-badge")?.textContent || ""),
    null,
    { timeout: 10000 },
  );
  const emptyTitle = await offline.locator("#empty-title").textContent();
  if (!/Cannot reach/.test(emptyTitle || "")) {
    throw new Error(`offline empty state: ${emptyTitle}`);
  }
  await offline.close();

  if (errors.length) throw new Error(`console errors:\n${errors.join("\n")}`);
  console.log("explorer smoke ok");
} finally {
  await browser.close();
}
