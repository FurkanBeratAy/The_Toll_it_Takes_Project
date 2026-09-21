// Screenshot: Section 1 map-wrap (map + toggle buttons)
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

(async () => {
  const port = 8762;
  await new Promise(r => server.listen(port, r));

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();

  await page.goto(`http://localhost:${port}/part1.html`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(10000); // wait for map tiles + fitBounds

  // Capture the full map-wrap including toggles and captions
  const wrap = await page.$('.map-wrap');
  const out = path.join(OUT, 'sec1_map_wrap.png');
  if (wrap) {
    await wrap.scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
    await wrap.screenshot({ path: out });
    console.log('✓', out);
  } else {
    await page.screenshot({ path: out, fullPage: false });
    console.warn('map-wrap not found — viewport fallback');
  }

  await browser.close();
  server.close();
})();
