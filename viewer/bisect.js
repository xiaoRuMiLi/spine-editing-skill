const puppeteer = require("puppeteer-core");
const CHROME = "C:\\Users\\Administrator\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe";

// Each case is passed as three argv slots per test: label, json, atlas.
const args = process.argv.slice(2);
const cases = [];
for (let i = 0; i + 2 < args.length; i += 3) {
  cases.push({ label: args[i], json: args[i + 1], atlas: args[i + 2] });
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu"],
  });

  for (const c of cases) {
    const page = await browser.newPage();
    const errs = [];
    page.on("pageerror", (e) => errs.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errs.push("console: " + m.text());
    });

    const url =
      "http://127.0.0.1:8765/viewer/one.html?skeleton=" +
      encodeURIComponent(c.json) +
      "&atlas=" +
      encodeURIComponent(c.atlas);

    try {
      await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
      await new Promise((r) => setTimeout(r, 5000));
      const state = await page.evaluate(() => ({
        error: document.getElementById("errbox")?.textContent || "",
        loaded: (window.__ok || []).length,
      }));
      const failed = errs.length > 0 || state.error.length > 0 || state.loaded === 0;
      const detail = errs.length ? errs[0] : state.error;
      console.log(
        (failed ? "FAIL " : "OK   ") + c.label.padEnd(26) + (detail ? "| " + String(detail).slice(0, 90) : "")
      );
    } catch (e) {
      console.log("FAIL " + c.label.padEnd(26) + "| harness: " + e.message.slice(0, 80));
    }
    await page.close();
  }
  await browser.close();
})();
