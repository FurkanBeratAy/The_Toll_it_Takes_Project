// Re-shoot checks 1, 2, 4 after Plotly.restyle fix
const { chromium } = require('@playwright/test');
const http = require('http');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const BASE = path.resolve(__dirname);
const DOCS = path.join(BASE, 'docs');
const OUT  = path.join(BASE, '_screenshots');

const beforePart1Raw = execSync('git show HEAD:docs/part1.html', { cwd: BASE }).toString();
fs.writeFileSync(path.join(DOCS, '_before_part1.html'), beforePart1Raw);

function mime(ext) {
  return { '.html':'text/html', '.css':'text/css', '.js':'application/javascript',
           '.json':'application/json', '.png':'image/png', '.jpg':'image/jpeg' }[ext] || 'application/octet-stream';
}
const server = http.createServer((req, res) => {
  const file = path.join(DOCS, req.url.split('?')[0]);
  if (fs.existsSync(file) && fs.statSync(file).isFile()) {
    res.writeHead(200, { 'Content-Type': mime(path.extname(file)) });
    fs.createReadStream(file).pipe(res);
  } else { res.writeHead(404); res.end('Not found'); }
});

const SECTIONS = [
  { name:'check1_forest', bPage:'_before_part1.html', aPage:'part1.html', sel:'#rb-check1',  wait:6000 },
  { name:'check2_bar',    bPage:'_before_part1.html', aPage:'part1.html', sel:'#rb-check2',  wait:6000 },
  { name:'check4_spec_a', bPage:'_before_part1.html', aPage:'part1.html', sel:'#rb-check4a', wait:6000 },
];

async function shoot(page, port, pageName, sel, waitMs, outPng) {
  await page.goto(`http://localhost:${port}/${pageName}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(waitMs);
  const el = await page.$(sel);
  if (el) {
    await el.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await el.screenshot({ path: outPng });
    console.log(`  ✓ ${path.basename(outPng)}`);
  } else {
    await page.screenshot({ path: outPng });
    console.warn(`  ⚠ "${sel}" not found — fallback`);
  }
}

(async () => {
  const port = 8755;
  await new Promise(r => server.listen(port, r));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  for (const s of SECTIONS) {
    console.log(`\n[${s.name}]`);
    await shoot(page, port, s.bPage, s.sel, s.wait, path.join(OUT, `${s.name}_BEFORE.png`));
    await shoot(page, port, s.aPage, s.sel, s.wait, path.join(OUT, `${s.name}_AFTER.png`));
  }

  await browser.close();
  server.close();
  fs.unlinkSync(path.join(DOCS, '_before_part1.html'));
  console.log('\nDone.');
})();
