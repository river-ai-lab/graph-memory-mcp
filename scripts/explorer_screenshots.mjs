/**
 * Headless Explorer screenshots for the docs.
 *
 * Seed first, against a running server and Explorer (default :8000 and :8088):
 *   uv run python assets/demo/seed.py
 *   uv run python assets/demo/generate_demo.py --scenario dense
 *   node scripts/explorer_screenshots.mjs
 *
 * Playwright loads from PLAYWRIGHT_MODULE or /tmp/node_modules/playwright/index.mjs.
 * PNGs land in EXPLORER_SHOTS (default docs/images).
 */
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const playwrightEntry =
  process.env.PLAYWRIGHT_MODULE || "/tmp/node_modules/playwright/index.mjs";
const { chromium } = await import(pathToFileURL(playwrightEntry).href);

const base = process.env.EXPLORER_URL || "http://127.0.0.1:8088";
const outDir = process.env.EXPLORER_SHOTS || "docs/images";

async function waitConnected(page) {
  await page.waitForFunction(
    () => /connected/i.test(document.querySelector("#status-badge")?.textContent || ""),
    null,
    { timeout: 20000 },
  );
}

async function loadOwner(page, owner) {
  await page.goto(`${base}/?owner=${encodeURIComponent(owner)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitConnected(page);
  await page.fill("#owner-id", owner);
  await page.click("#btn-brief");
  await page.waitForFunction(
    () => document.querySelectorAll("#overview [data-id]").length > 0,
    null,
    { timeout: 20000 },
  );
  await page.waitForFunction(
    () => /(\d+)\s+items?/.test(document.querySelector("#stats-bar")?.textContent || ""),
    null,
    { timeout: 20000 },
  );
  await page.waitForTimeout(500);
}

async function recall(page, query) {
  await page.fill("#search-query", query);
  await page.click("#btn-recall");
  await page.waitForFunction(
    () => {
      const match = (document.querySelector("#stats-bar")?.textContent || "").match(/(\d+)\s+items?/);
      return match && Number(match[1]) > 1;
    },
    null,
    { timeout: 20000 },
  );
  await page.waitForTimeout(800);
}

async function hoverANode(page) {
  const box = await page.locator("#cy").boundingBox();
  if (!box) throw new Error("map canvas is missing");
  for (let y = 70; y < box.height - 90; y += 22) {
    for (let x = 36; x < box.width - 36; x += 28) {
      await page.mouse.move(box.x + x, box.y + y);
      const tip = page.locator("#node-preview-tip");
      if (await tip.isVisible()) return;
    }
  }
  throw new Error("hover did not open a node preview");
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await mkdir(outDir, { recursive: true });

try {
  await page.addInitScript(() => {
    localStorage.setItem("gm_node_preview", "always");
  });
  await loadOwner(page, "readme_demo");
  if ((await page.inputValue("#node-preview")) !== "always") {
    await page.selectOption("#node-preview", "always");
    await page.waitForTimeout(500);
  }
  await recall(page, "November deadline");
  const legend = await page.locator(".canvas-footer").innerText();
  if (!/Contradicts/.test(legend) || !/Follows from/.test(legend) || !/Related/.test(legend)) {
    throw new Error(`legend missing: ${legend}`);
  }
  await page.screenshot({ path: `${outDir}/explorer-readme-always.png` });

  await page.fill("#search-query", "beta ships");
  await page.click("#btn-search");
  await page.waitForSelector("#search-results > ul.ov-list > li[data-id]", {
    timeout: 20000,
  });
  await page.click("#search-results > ul.ov-list > li[data-id]");
  await page.waitForFunction(
    () => (document.querySelector("#detail-text")?.textContent || "").length > 8,
    null,
    { timeout: 15000 },
  );
  await page.screenshot({ path: `${outDir}/explorer-readme-details.png` });

  await page.addInitScript(() => {
    localStorage.setItem("gm_node_preview", "hover");
  });
  await loadOwner(page, "demo_team");
  await page.selectOption("#node-preview", "hover");
  await recall(page, "API gateway");
  await hoverANode(page);
  await page.screenshot({ path: `${outDir}/explorer-dense-hover.png` });
  console.log("explorer screenshots ok");
} finally {
  await browser.close();
}
