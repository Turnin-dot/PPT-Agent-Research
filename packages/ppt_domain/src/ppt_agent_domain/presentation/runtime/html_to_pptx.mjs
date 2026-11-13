import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const pptxgen = require("pptxgenjs");

function args(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 2) out[argv[i].replace(/^--/, "")] = argv[i + 1];
  return out;
}

function hexColor(value, fallback = "000000") {
  if (!value || value === "transparent") return fallback;
  if (/^rgba\([^)]*,\s*0(?:\.0+)?\s*\)$/i.test(value)) return fallback;
  const direct = value.match(/^#([0-9a-f]{6})$/i);
  if (direct) return direct[1].toUpperCase();
  const rgb = value.match(/rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)/i);
  if (!rgb) return fallback;
  return [rgb[1], rgb[2], rgb[3]].map((part) => Number(part).toString(16).padStart(2, "0")).join("").toUpperCase();
}

function normalizeFont(value) {
  return String(value || "Microsoft YaHei").split(",")[0].replace(/["']/g, "").trim();
}

function localImageSource(source) {
  if (source.startsWith("data:")) return { data: source.replace(/^data:/, "") };
  if (source.startsWith("file:")) return { path: fileURLToPath(source) };
  return { path: source };
}

const options = args(process.argv);
for (const key of ["request", "output", "map"]) if (!options[key]) throw new Error(`missing --${key}`);
const request = JSON.parse(fs.readFileSync(path.resolve(options.request), "utf8"));
const widthPx = Number(request.theme?.width_px || 1600);
const heightPx = Number(request.theme?.height_px || 900);
const slideWidth = 13.333333;
const slideHeight = 7.5;
const sx = slideWidth / widthPx;
const sy = slideHeight / heightPx;

const browser = await chromium.launch({
  headless: true,
  executablePath: options.browser || undefined,
  args: ["--allow-file-access-from-files", "--disable-web-security", "--font-render-hinting=none"],
});
const presentation = new pptxgen();
presentation.layout = "LAYOUT_WIDE";
presentation.author = "PPT Agent";
presentation.subject = "Editable export from versioned HTML slides";
presentation.title = request.task_id || "PPT Agent Export";
presentation.company = "PPT Agent";
presentation.lang = "zh-CN";
presentation.theme = {
  headFontFace: request.theme?.heading_font || "Microsoft YaHei",
  bodyFontFace: request.theme?.body_font || "Microsoft YaHei",
  lang: "zh-CN",
};

const objectMap = {
  schema_version: "ppt-editable-object-map/v1",
  task_id: request.task_id,
  slides: [],
  totals: { text: 0, image: 0, shape: 0 },
  unsupported_features: [],
  created_at: new Date().toISOString(),
};

try {
  for (const source of request.slides) {
    const page = await browser.newPage({ viewport: { width: widthPx, height: heightPx }, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(path.resolve(source.html_path)).href, { waitUntil: "load", timeout: 60000 });
    await page.evaluate(async () => {
      if (document.fonts?.ready) await document.fonts.ready;
      await Promise.all([...document.images].map((image) => image.complete ? null : new Promise((resolve) => {
        image.addEventListener("load", resolve, { once: true });
        image.addEventListener("error", resolve, { once: true });
      })));
    });
    const model = await page.evaluate(() => {
      const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
      // Keep author-intended line breaks (for example <br>) when converting
      // editable text. Collapsing innerText to one line makes PowerPoint pick
      // different wrap points and can materially change the slide hierarchy.
      const cleanText = (value) => (value || "")
        .replace(/\r\n?/g, "\n")
        .split("\n")
        .map((line) => line.replace(/[\t\f\v ]+/g, " ").trim())
        .filter((line, index, lines) => line.length > 0 || (index > 0 && index < lines.length - 1))
        .join("\n")
        .trim();
      const visible = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0 && rect.width > 0 && rect.height > 0;
      };
      const elements = [];
      // Walk the rendered DOM, including container decoration and inline text.
      // Browser line boxes are authoritative; PowerPoint must not reflow paragraphs.
      function walk(element) {
        if (!visible(element) || ['SCRIPT','STYLE','HEAD','NOSCRIPT'].includes(element.tagName)) return;
        const style = getComputedStyle(element), rect = element.getBoundingClientRect();
        const base = { id: element.id || `auto-${elements.length}`, x:rect.x,y:rect.y,width:rect.width,height:rect.height,
          color:style.color, backgroundColor:style.backgroundColor,borderColor:style.borderColor,
          borderWidth:parseFloat(style.borderWidth)||0,fontSize:parseFloat(style.fontSize)||16,
          fontFamily:style.fontFamily,fontWeight:style.fontWeight,fontStyle:style.fontStyle,
          textAlign:'left',opacity:parseFloat(style.opacity),unsupported:[] };
        if (style.transform !== 'none') throw new Error(`Unsupported transform: ${base.id}`);
        if (style.backgroundImage !== 'none') throw new Error(`Unsupported background image: ${base.id}`);
        if (style.backgroundColor !== 'rgba(0, 0, 0, 0)' || base.borderWidth > 0) {
          elements.push({...base,type:'shape',shape:'rect',borderWidth:0});
        }
        for (const side of ['Left','Right','Top','Bottom']) {
          const size=parseFloat(style[`border${side}Width`])||0;
          if (!size) continue;
          const vertical=side==='Left'||side==='Right';
          elements.push({...base,type:'shape',shape:'rect',id:base.id+'-border-'+side,
            x:rect.x+(side==='Right'?rect.width-size:0),y:rect.y+(side==='Bottom'?rect.height-size:0),
            width:vertical?size:rect.width,height:vertical?rect.height:size,
            backgroundColor:style[`border${side}Color`],borderWidth:0});
        }
        if (element.tagName === 'IMG') {
          if (!element.complete || !element.naturalWidth) throw new Error(`Image failed to load: ${element.src}`);
          if (style.objectFit === 'cover') throw new Error(`Image cover would crop scientific content: ${base.id}`);
          for (let parent=element.parentElement;parent;parent=parent.parentElement) {
            const ps=getComputedStyle(parent),pr=parent.getBoundingClientRect();
            if ((['hidden','clip'].includes(ps.overflowX) && (rect.left<pr.left-1 || rect.right>pr.right+1)) ||
                (['hidden','clip'].includes(ps.overflowY) && (rect.top<pr.top-1 || rect.bottom>pr.bottom+1)))
              throw new Error(`Ancestor clips scientific image: ${base.id}`);
          }
          elements.push({...base,type:'image',src:element.currentSrc||element.src,naturalWidth:element.naturalWidth,
            naturalHeight:element.naturalHeight,objectFit:style.objectFit,objectPosition:style.objectPosition});
          return;
        }
        for (const child of element.childNodes) {
          if (child.nodeType === Node.ELEMENT_NODE) { walk(child); continue; }
          if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim()) continue;
          let line=null;
          function flush() { if (line && line.text.trim()) elements.push({...base,type:'text',...line,id:base.id+'-line-'+elements.length}); line=null; }
          for (let i=0;i<child.length;i++) {
            const range=document.createRange(); range.setStart(child,i);range.setEnd(child,i+1);
            const r=range.getBoundingClientRect(); if (!r.width || !r.height) continue;
            if (line && Math.abs(line.y-r.y)>1) flush();
            if (!line) line={text:'',x:r.x,y:r.y,width:0,height:r.height};
            line.text+=child.textContent[i];line.width=Math.max(line.width,r.right-line.x);line.height=Math.max(line.height,r.height);
          }
          flush();
        }
      }
      walk(document.body);
      const fallback = !document.querySelector('[data-pptx]');
      const bodyStyle = getComputedStyle(document.body);
      return { fallback, elements, backgroundColor: bodyStyle.backgroundColor };
    });

    const slide = presentation.addSlide();
    slide.background = { color: hexColor(model.backgroundColor, hexColor(request.theme?.background, "FFFFFF")) };
    const slideMap = { slide_id: source.slide_id, html_version: source.html_version, fallback_mode: model.fallback, objects: [] };
    for (const element of model.elements) {
      const x = Math.max(0, element.x * sx);
      const y = Math.max(0, element.y * sy);
      const w = Math.max(0.02, element.width * sx);
      const h = Math.max(0.02, element.height * sy);
      const object = { element_id: element.id, type: element.type, x, y, w, h };
      for (const feature of element.unsupported) {
        objectMap.unsupported_features.push({ slide_id: source.slide_id, element_id: element.id, feature });
      }
      if (element.type === "text") {
        slide.addText(element.text || " ", {
          x, y, w: w + sx * 2, h,
          margin: 0,
          fontFace: normalizeFont(element.fontFamily),
          fontSize: Math.max(6, element.fontSize * sy * 72),
          color: hexColor(element.color, "000000"),
          bold: Number.parseInt(element.fontWeight, 10) >= 600 || element.fontWeight === "bold",
          italic: element.fontStyle === "italic",
          align: ["center", "right", "justify"].includes(element.textAlign) ? element.textAlign : "left",
          valign: "mid",
          breakLine: false,
          fit: "shrink",
          wrap: false,
          transparency: Math.round((1 - element.opacity) * 100),
        });
        objectMap.totals.text += 1;
      } else if (element.type === "image") {
        if (!element.src) {
          objectMap.unsupported_features.push({ slide_id: source.slide_id, element_id: element.id, feature: "image-without-source" });
          continue;
        }
        let ix = x, iy = y, iw = w, ih = h;
        if (element.naturalWidth && element.naturalHeight && element.objectFit !== "fill") {
          const ratio = element.naturalWidth / element.naturalHeight;
          if (iw / ih > ratio) {
            iw = ih * ratio;
            ix += (w - iw) / 2;
          } else {
            ih = iw / ratio;
            iy += (h - ih) / 2;
          }
          if (element.objectFit === "cover") objectMap.unsupported_features.push({ slide_id: source.slide_id, element_id: element.id, feature: "object-fit:cover exported as contain" });
        }
        slide.addImage({ ...localImageSource(element.src), x: ix, y: iy, w: iw, h: ih, altText: element.id });
        objectMap.totals.image += 1;
      } else if (element.type === "shape") {
        const transparent = /rgba\([^)]*,\s*0\s*\)$/.test(element.backgroundColor);
        const fill = { color: hexColor(element.backgroundColor, "FFFFFF"), transparency: transparent ? 100 : Math.round((1 - element.opacity) * 100) };
        const line = { color: hexColor(element.borderColor, fill.color), width: Math.max(0, element.borderWidth * sy * 72), transparency: element.borderWidth ? 0 : 100 };
        if (element.shape === "line") {
          slide.addShape(presentation.ShapeType.line, { x, y, w, h: Math.max(0, h), line });
        } else {
          const shapeType = element.shape === "ellipse" ? presentation.ShapeType.ellipse : element.shape === "roundRect" ? presentation.ShapeType.roundRect : presentation.ShapeType.rect;
          slide.addShape(shapeType, { x, y, w, h, fill, line });
        }
        objectMap.totals.shape += 1;
      } else {
        objectMap.unsupported_features.push({ slide_id: source.slide_id, element_id: element.id, feature: `unknown data-pptx type ${element.type}` });
        continue;
      }
      slideMap.objects.push(object);
    }
    objectMap.slides.push(slideMap);
    await page.close();
  }
  fs.mkdirSync(path.dirname(path.resolve(options.output)), { recursive: true });
  await presentation.writeFile({ fileName: path.resolve(options.output) });
  fs.writeFileSync(path.resolve(options.map), JSON.stringify(objectMap, null, 2) + "\n", "utf8");
} finally {
  await browser.close();
}
