const puppeteer = require("puppeteer-core");

const CHROME = "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe";
const TARGET = process.argv[2] || "http://127.0.0.1:8765/viewer/compare.html";
const OUT = process.argv[3] || "F:/projects/spine-forge/viewer/final.png";
const WAIT = parseInt(process.argv[4] || "10000", 10);

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto(TARGET, { waitUntil: "domcontentloaded", timeout: 60000 });
  // The player keeps a requestAnimationFrame loop running, so "networkidle"
  // never settles. Wait a fixed interval instead and let it paint.
  await new Promise((resolve) => setTimeout(resolve, WAIT));

  await page.screenshot({ path: OUT });

  console.log(errors.length ? "PAGE ERRORS: " + errors.join(" | ") : "NO PAGE ERRORS");
  console.log("saved: " + OUT);

  await browser.close();
})().catch((e) => {
  console.error("FAILED: " + e.message);
  process.exit(1);
});
