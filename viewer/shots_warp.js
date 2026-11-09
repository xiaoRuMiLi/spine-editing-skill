const puppeteer = require("puppeteer-core");

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const OUT = "C:\\Users\\Administrator\\.openclaw\\workspace-dev\\_tmp\\";
const PAGES = ["path_rest", "path_bend", "path_kick"];

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });

  for (const name of PAGES) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1200, height: 900 });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:8765/viewer/_preview_" + name + ".html", {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
    await new Promise((resolve) => setTimeout(resolve, 6000));
    await page.screenshot({ path: OUT + name + ".png" });
    console.log(name + ": " + (errors.length ? "PAGE ERRORS: " + errors.join(" | ") : "NO PAGE ERRORS"));
    console.log("title: " + (await page.title()));
    await page.close();
  }

  await browser.close();
})().catch((e) => {
  console.error("FAILED: " + e.message);
  process.exit(1);
});








