/* Generate the portfolio media in docs/ with Playwright (headless Chromium) + ffmpeg.
 *
 * Usage (server already running on BASE, default http://127.0.0.1:8000, with the
 * full Metrica Game 1 downloaded):
 *   NODE_PATH=$(npm root -g) node scripts/make_demo.js
 *
 * Produces docs/demo.gif, docs/screenshot_pitch_control.png,
 * docs/screenshot_heatmap.png and docs/screenshot_mobile.png.
 */
const { chromium, devices } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const BASE = process.env.BASE || "http://127.0.0.1:8000";
const MATCH = process.env.MATCH || "metrica_game_1";
const DOCS = path.resolve(__dirname, "..", "docs");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function seekFrame(page, frame) {
  await page.evaluate((f) => window.__lmt.send({ cmd: "seek", frame: f }), frame);
}

async function goalFrame(n) {
  const res = await fetch(`${BASE}/api/matches/${MATCH}/events`);
  const ev = (await res.json()).filter((e) => e.goal);
  return ev[n].gf ?? ev[n].f;
}

(async () => {
  const browser = await chromium.launch();
  const gf = await goalFrame(1);

  // ---------------------------------------------------------------- demo.gif
  const vidDir = fs.mkdtempSync(path.join(os.tmpdir(), "lmt-video-"));
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 860 },
    recordVideo: { dir: vidDir, size: { width: 1280, height: 860 } },
  });
  const page = await ctx.newPage();
  const t0 = Date.now();
  await page.goto(`${BASE}/?match=${MATCH}`);
  await page.waitForSelector("#playersTable tbody tr");
  await seekFrame(page, gf - 25 * 13);
  await page.click('#speeds button[data-speed="2"]');
  await sleep(1500);
  const start = (Date.now() - t0) / 1000;
  await sleep(2000);
  await page.click("#togglePC");
  await sleep(2000);
  await page.click("#playersTable tbody tr:nth-child(2)");
  await sleep(3500);
  await page.click("#togglePC");
  await sleep(4000);
  const end = (Date.now() - t0) / 1000;
  await ctx.close();
  const webm = fs.readdirSync(vidDir).find((f) => f.endsWith(".webm"));
  const src = path.join(vidDir, webm);
  const filters = "fps=10,scale=880:-1:flags=lanczos";
  const palette = path.join(vidDir, "palette.png");
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", String(start), "-to", String(end), "-i", src,
    "-vf", `${filters},palettegen=max_colors=96:stats_mode=diff`, palette]);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", String(start), "-to", String(end), "-i", src,
    "-i", palette, "-lavfi", `${filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4`,
    path.join(DOCS, "demo.gif")]);
  console.log("demo.gif", (fs.statSync(path.join(DOCS, "demo.gif")).size / 1e6).toFixed(1), "MB");

  // ---------------------------------------------------------------- screenshots
  const p = await browser.newPage({ viewport: { width: 1480, height: 1000 }, deviceScaleFactor: 2 });
  await p.goto(`${BASE}/?match=${MATCH}`);
  await p.waitForSelector("#playersTable tbody tr");
  await p.evaluate(() => window.__lmt.send({ cmd: "seek", fraction: 0.33 }));
  await p.click("#togglePC");
  await sleep(3000);
  await p.screenshot({ path: path.join(DOCS, "screenshot_pitch_control.png") });
  await p.click("#togglePC");
  await p.click('#teamTabs button[data-team="away"]');
  await p.click("#playersTable tbody tr:nth-child(1)");
  await sleep(1500);
  await p.screenshot({ path: path.join(DOCS, "screenshot_heatmap.png"), fullPage: true });

  const m = await browser.newContext({ ...devices["iPhone 13"] });
  const mp = await m.newPage();
  await mp.goto(`${BASE}/?match=${MATCH}`);
  await mp.waitForSelector("#playersTable tbody tr");
  await mp.evaluate(() => window.__lmt.send({ cmd: "seek", fraction: 0.5 }));
  await sleep(2500);
  await mp.screenshot({ path: path.join(DOCS, "screenshot_mobile.png") });
  await browser.close();
  console.log("screenshots written to", DOCS);
})();
