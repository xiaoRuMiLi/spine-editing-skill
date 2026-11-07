const puppeteer = require("puppeteer-core");

const CHROME = "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe";

(async () => {
  const target = process.argv[2] || "http://127.0.0.1:8765/viewer/probe2.html";
  const waitMs = parseInt(process.argv[3] || "12000", 10);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu", "--window-size=1540,950"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1540, height: 950 });

  const consoleLines = [];
  page.on("console", (m) => consoleLines.push("[console] " + m.text()));
  page.on("pageerror", (e) => consoleLines.push("[pageerror] " + e.message));

  await page.goto(target, { waitUntil: "networkidle2", timeout: 60000 });
  await new Promise((r) => setTimeout(r, waitMs));

  const logText = await page.evaluate(() => {
    const el = document.getElementById("log");
    return el ? el.innerText : "(no #log element)";
  });

  console.log("===== LOG PANEL =====");
  console.log(logText);
  if (consoleLines.length) {
    console.log("===== CONSOLE =====");
    console.log(consoleLines.join("\n"));
  }

  await browser.close();
})().catch((e) => {
  console.error("FAILED: " + e.message);
  process.exit(1);
});
