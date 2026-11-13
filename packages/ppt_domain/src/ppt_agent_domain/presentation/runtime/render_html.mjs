import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

function args(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) out[argv[i].replace(/^--/, "")] = argv[i + 1];
  return out;
}

const options = args(process.argv);
for (const key of ["html", "output", "metadata", "width", "height"]) {
  if (!options[key]) throw new Error(`missing --${key}`);
}

const viewport = { width: Number(options.width), height: Number(options.height) };
const consoleErrors = [];
const failedRequests = [];
const browser = await chromium.launch({
  headless: true,
  executablePath: options.browser || undefined,
  args: ["--allow-file-access-from-files", "--disable-web-security", "--font-render-hinting=none"],
});

try {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    failedRequests.push(`${request.url()} :: ${request.failure()?.errorText || "failed"}`);
  });
  await page.goto(pathToFileURL(path.resolve(options.html)).href, { waitUntil: "load", timeout: 60000 });
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
    const images = [...document.images];
    await Promise.all(images.map((image) => image.complete ? null : new Promise((resolve) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", resolve, { once: true });
    })));
  });

  const analysis = await page.evaluate(({ width, height }) => {
    const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0 && rect.width > 0 && rect.height > 0;
    };
    let selected = [...document.querySelectorAll("[data-pptx]")];
    if (!selected.length) {
      selected = [...document.querySelectorAll("img, h1, h2, h3, h4, p, li, td, th")].filter((element) => {
        if (!visible(element)) return false;
        if (element.tagName === "IMG") return true;
        return clean(element.innerText).length > 0 && ![...element.children].some((child) => clean(child.innerText).length > 0);
      });
    }
    const elements = selected.filter(visible).map((element, index) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const type = element.dataset.pptx || (element.tagName === "IMG" ? "image" : "text");
      return {
        id: element.id || `auto-${index + 1}`,
        type,
        text: type === "text" ? clean(element.innerText) : "",
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        font_size_px: Number.parseFloat(style.fontSize) || null,
        font_family: style.fontFamily,
        color: style.color,
        background_color: style.backgroundColor,
        overflow_x: style.overflowX,
        overflow_y: style.overflowY,
        allow_overlap: element.dataset.allowOverlap === "true",
      };
    });
    const overflowElements = [];
    for (const element of document.querySelectorAll("[data-pptx], [id]")) {
      if (!visible(element)) continue;
      const reasons = [];
      if (element.scrollWidth > element.clientWidth + 1) reasons.push(`horizontal ${element.scrollWidth}>${element.clientWidth}`);
      if (element.scrollHeight > element.clientHeight + 1) reasons.push(`vertical ${element.scrollHeight}>${element.clientHeight}`);
      const rect = element.getBoundingClientRect();
      if (rect.left < -1 || rect.top < -1 || rect.right > width + 1 || rect.bottom > height + 1) reasons.push("outside viewport");
      if (reasons.length) overflowElements.push({ id: element.id || element.tagName, reason: reasons.join("; ") });
    }
    const overlapCandidates = elements.filter((item) => !item.allow_overlap && item.type !== "shape");
    const overlaps = [];
    for (let i = 0; i < overlapCandidates.length; i++) {
      for (let j = i + 1; j < overlapCandidates.length; j++) {
        const a = overlapCandidates[i];
        const b = overlapCandidates[j];
        const w = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
        const h = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
        const area = w * h;
        if (area > 64) overlaps.push({ a: a.id, b: b.id, area_px: Math.round(area) });
      }
    }
    const missingImages = [...document.images]
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => ({ id: image.id || null, src: image.currentSrc || image.src }));
    const unsupported = [];
    for (const element of document.querySelectorAll("[data-pptx]")) {
      const style = getComputedStyle(element);
      const id = element.id || element.tagName;
      if (style.backgroundImage && style.backgroundImage !== "none") unsupported.push({ id, feature: "background-image/gradient" });
      if (style.filter && style.filter !== "none") unsupported.push({ id, feature: "filter" });
      if (style.transform && style.transform !== "none") unsupported.push({ id, feature: "transform" });
    }
    return {
      elements,
      diagnostics: {
        document_overflow: document.documentElement.scrollWidth > width + 1 || document.documentElement.scrollHeight > height + 1,
        overflow_elements: overflowElements,
        overlaps,
        missing_images: missingImages,
        unsupported_features: unsupported,
        fonts_status: document.fonts?.status || "unknown",
      },
    };
  }, viewport);
  analysis.diagnostics.console_errors = consoleErrors;
  analysis.diagnostics.failed_requests = failedRequests;
  analysis.schema_version = "html-slide-render/v1";
  analysis.html_path = path.resolve(options.html);
  analysis.viewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  analysis.created_at = new Date().toISOString();
  fs.mkdirSync(path.dirname(path.resolve(options.output)), { recursive: true });
  await page.screenshot({ path: path.resolve(options.output), fullPage: false, type: "png" });
  fs.writeFileSync(path.resolve(options.metadata), JSON.stringify(analysis, null, 2) + "\n", "utf8");
} finally {
  await browser.close();
}
