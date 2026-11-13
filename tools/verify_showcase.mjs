// Local browser verification only. No model/API invocation.
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const url=process.argv[2] || 'http://127.0.0.1:8000';
const out=path.resolve(process.argv[3] || 'outputs/showcase-verification');fs.mkdirSync(out,{recursive:true});
const executablePath=process.env.PPT_AGENT_CHROMIUM || undefined;
const browser=await chromium.launch({headless:true,executablePath});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const failures=[];const requests=[];
 page.on('pageerror',error=>failures.push(String(error)));
 page.on('response',response=>{if(response.status()>=400)failures.push(response.url()+': '+response.status());});
 page.on('request',request=>requests.push(request.url()));
 await page.goto(url,{waitUntil:'networkidle'});
 await page.locator('details').evaluateAll(items=>items.forEach(item=>item.open=true));
 await page.locator('img').evaluateAll(items=>items.forEach(item=>{item.loading='eager';}));
 await page.waitForFunction(()=>[...document.images].every(img=>img.complete));
 const missing=await page.locator('img').evaluateAll(items=>items.filter(img=>!img.naturalWidth).map(img=>img.src));
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 const mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 const remote=requests.filter(request=>!request.startsWith(url));
 const result={failures,missing,overflow,mobileOverflow,remote,requests:requests.length};
 fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));
 if(failures.length||missing.length||overflow||mobileOverflow||remote.length)throw new Error(JSON.stringify(result));
 console.log(JSON.stringify(result));
} finally {await browser.close();}
