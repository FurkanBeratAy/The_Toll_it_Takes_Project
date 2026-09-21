// Playwright screenshot script — before/after, served via local HTTP
const { chromium } = require('@playwright/test');
const http = require('http');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const BASE = path.resolve(__dirname);
const DOCS = path.join(BASE, 'docs');
const OUT  = path.join(BASE, '_screenshots');
fs.mkdirSync(OUT, { recursive: true });

// Pull git HEAD versions and write to docs/ as _before_*.html
const beforePart1Raw = execSync('git show HEAD:docs/part1.html', { cwd: BASE }).toString();
const beforeIndexRaw = execSync('git show HEAD:docs/index.html', { cwd: BASE }).toString();
fs.writeFileSync(path.join(DOCS, '_before_part1.html'), beforePart1Raw);
fs.writeFileSync(path.join(DOCS, '_before_index.html'), beforeIndexRaw);

// Simple static file server for docs/
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
  } else {
    res.writeHead(404); res.end('Not found: ' + req.url);
  }
});

const SECTIONS = [
  { name:'hero_stat_cards', bPage:'_before_part1.html', aPage:'part1.html',       sel:'#stat-row',                wait:4000 },
  { name:'corridor_strip',  bPage:'_before_index.html', aPage:'index.html',        sel:'.corridor-strip',          wait:4000 },
  { name:'sec1_map_legend', bPage:'_before_part1.html', aPage:'part1.html',        sel:'#legend-aqi',              wait:8000 },
  { name:'sec3_its_table',  bPage:'_before_part1.html', aPage:'part1.html',        sel:'#its-table-wrap',          wait:5000 },
  { name:'sec4_equity',     bPage:'_before_part1.html', aPage:'part1.html',        sel:'#chart-equity-container',  wait:5000 },
  { name:'check1_forest',   bPage:'_before_part1.html', aPage:'part1.html',        sel:'#rb-check1',               wait:5000 },
  { name:'check2_bar',      bPage:'_before_part1.html', aPage:'part1.html',        sel:'#rb-check2',               wait:5000 },
  { name:'check3_placebo',  bPage:'_before_part1.html', aPage:'part1.html',        sel:'#rb-check3',               wait:5000 },
  { name:'check4_spec_a',   bPage:'_before_part1.html', aPage:'part1.html',        sel:'#rb-check4a',              wait:5000 },
  { name:'check5_scatter',  bPage:'_before_part1.html', aPage:'part1.html',        sel:'#rb-check5',               wait:5000 },
  { name:'check7_table',    bPage:'_before_part1.html', aPage:'part1.html',        sel:'#check7-table-wrap',       wait:5000 },
  { name:'check8_table',    bPage:'_before_part1.html', aPage:'part1.html',        sel:'table:nth-of-type(1)',     wait:5000, scrollSel:'h3' },
  { name:'sec6_traffic_map',bPage:'_before_part1.html', aPage:'part1.html',        sel:'#map-traffic',             wait:9000 },
  { name:'sec7_crz',        bPage:'_before_part1.html', aPage:'part1.html',        sel:'#chart-crz',               wait:5000 },
  { name:'sec8_311',        bPage:'_before_part1.html', aPage:'part1.html',        sel:'#chart-idling-complaints', wait:5000 },
];

async function shoot(page, port, pageName, sel, waitMs, outPng) {
  const url = `http://localhost:${port}/${pageName}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(waitMs);
  let el = await page.$(sel);
  if (!el) {
    // Try waiting for it
    try { el = await page.waitForSelector(sel, { timeout: 3000 }); } catch(_) {}
  }
  if (el) {
    await el.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await el.screenshot({ path: outPng });
    console.log(`  ✓ ${outPng.split('\\').pop()}`);
  } else {
    await page.screenshot({ path: outPng, fullPage: false });
    console.warn(`  ⚠ "${sel}" not found in ${pageName} — viewport fallback`);
  }
}

(async () => {
  const port = 8754;
  await new Promise(r => server.listen(port, r));
  console.log(`Server on http://localhost:${port}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  for (const s of SECTIONS) {
    const bOut = path.join(OUT, `${s.name}_BEFORE.png`);
    const aOut = path.join(OUT, `${s.name}_AFTER.png`);
    console.log(`\n[${s.name}]`);
    await shoot(page, port, s.bPage, s.sel, s.wait, bOut);
    await shoot(page, port, s.aPage, s.sel, s.wait, aOut);
  }

  await browser.close();
  server.close();

  // Clean up temp before files
  fs.unlinkSync(path.join(DOCS, '_before_part1.html'));
  fs.unlinkSync(path.join(DOCS, '_before_index.html'));

  console.log('\nAll screenshots saved to:', OUT);
  fs.readdirSync(OUT).filter(f=>f.endsWith('.png')).sort().forEach(f=>console.log(' ', f));
})();
