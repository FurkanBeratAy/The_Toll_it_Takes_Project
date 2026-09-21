// Screenshots for map legend, clutter, and scorecard review
const { chromium } = require('@playwright/test');
const http = require('http');
const path = require('path');
const fs = require('fs');

const DOCS = path.join(__dirname, 'docs');
const OUT  = path.join(__dirname, '_screenshots');
fs.mkdirSync(OUT, { recursive: true });

function mime(ext) {
  return { '.html':'text/html', '.css':'text/css', '.js':'application/javascript',
           '.json':'application/json', '.png':'image/png', '.jpg':'image/jpeg',
           '.woff2':'font/woff2', '.woff':'font/woff' }[ext] || 'application/octet-stream';
}
const server = http.createServer((req, res) => {
  const file = path.join(DOCS, req.url.split('?')[0]);
  if (fs.existsSync(file) && fs.statSync(file).isFile()) {
    res.writeHead(200, { 'Content-Type': mime(path.extname(file)) });
    fs.createReadStream(file).pipe(res);
  } else { res.writeHead(404); res.end('Not found: ' + req.url); }
});

const SHOTS = [
  // Section 1 map — full map including legend
  { name:'sec1_map_full',      page:'part1.html', sel:'#map-aqi',             wait:9000 },
  // Traffic map — full map including legend
  { name:'sec6_traffic_full',  page:'part1.html', sel:'#map-traffic',         wait:9000 },
  // Scorecard — full table
  { name:'scorecard_full',     page:'part1.html', sel:'#sc-wrap',             wait:5000 },
  // ITS table — for style comparison
  { name:'its_table',          page:'part1.html', sel:'#its-table-wrap',      wait:5000 },
  // Compact scorecard on index
  { name:'scorecard_compact',  page:'index.html', sel:'#sc-compact-wrap',     wait:5000 },
];

async function shoot(page, port, pageName, sel, waitMs, outPng) {
  await page.goto(`http://localhost:${port}/${pageName}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(waitMs);
  let el = await page.$(sel);
  if (!el) {
    try { el = await page.waitForSelector(sel, { timeout: 3000 }); } catch(_) {}
  }
  if (el) {
    await el.scrollIntoViewIfNeeded();
    await page.waitForTimeout(600);
    await el.screenshot({ path: outPng });
    console.log(`  ✓ ${path.basename(outPng)}`);
  } else {
    await page.screenshot({ path: outPng, fullPage: false });
    console.warn(`  ⚠ "${sel}" not found — fallback`);
  }
}

(async () => {
  const port = 8761;
  await new Promise(r => server.listen(port, r));
  console.log(`Server on http://localhost:${port}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();

  for (const s of SHOTS) {
    const out = path.join(OUT, `${s.name}.png`);
    console.log(`\n[${s.name}]`);
    await shoot(page, port, s.page, s.sel, s.wait, out);
  }

  await browser.close();
  server.close();
  console.log('\nDone. Files:');
  SHOTS.forEach(s => console.log(' ', path.join(OUT, `${s.name}.png`)));
})();
