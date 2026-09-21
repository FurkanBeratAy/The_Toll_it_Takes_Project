// Playwright screenshot script — before/after of each changed section
const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const BASE = path.resolve(__dirname);
const OUT = path.join(BASE, '_screenshots');
fs.mkdirSync(OUT, { recursive: true });

// Fetch before-HTML from git HEAD and inject data_bundle inline
const dataBundle = fs.readFileSync(path.join(BASE, 'docs', 'data_bundle.js'), 'utf8');
function injectBundle(html) {
  return html.replace(
    /<script[^>]+data_bundle\.js[^>]*><\/script>/,
    `<script>${dataBundle}</script>`
  );
}

const beforePart1Raw  = execSync('git show HEAD:docs/part1.html', { cwd: BASE }).toString();
const beforeIndexRaw  = execSync('git show HEAD:docs/index.html', { cwd: BASE }).toString();
const beforePart1Path = path.join(OUT, '_before_part1.html');
const beforeIndexPath = path.join(OUT, '_before_index.html');
fs.writeFileSync(beforePart1Path, injectBundle(beforePart1Raw));
fs.writeFileSync(beforeIndexPath, injectBundle(beforeIndexRaw));

const afterPart1Path = path.join(BASE, 'docs', 'part1.html');
const afterIndexPath = path.join(BASE, 'docs', 'index.html');

const SECTIONS = [
  // { name, bFile, aFile, sel, wait }
  { name:'hero_stat_cards', bFile:beforeIndexPath, aFile:afterIndexPath, sel:'#stat-row',       wait:3500 },
  { name:'corridor_strip',  bFile:beforeIndexPath, aFile:afterIndexPath, sel:'#corridor-strip', wait:3500 },
  { name:'sec1_map_legend', bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-1 .map-legend', wait:6000 },
  { name:'sec3_its_table',  bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-3',      wait:4000 },
  { name:'sec4_equity',     bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-4',      wait:4000 },
  { name:'check1_forest',   bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check1',         wait:4000 },
  { name:'check2_bar',      bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check2',         wait:4000 },
  { name:'check3_placebo',  bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check3',         wait:4000 },
  { name:'check4_spec_a',   bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check4',         wait:4000 },
  { name:'check5_scatter',  bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check5',         wait:4000 },
  { name:'check7_table',    bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check7',         wait:4000 },
  { name:'check8_table',    bFile:beforePart1Path, aFile:afterPart1Path, sel:'#check8',         wait:4000 },
  { name:'sec6_traffic_map',bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-6',      wait:6000 },
  { name:'sec7_crz',        bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-7',      wait:4000 },
  { name:'sec8_311',        bFile:beforePart1Path, aFile:afterPart1Path, sel:'#section-8',      wait:4000 },
];

async function shoot(page, htmlFile, sel, waitMs, outPng) {
  await page.goto('file:///' + htmlFile.replace(/\\/g, '/'), { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(waitMs);
  const el = await page.$(sel);
  if (el) {
    await el.screenshot({ path: outPng });
  } else {
    await page.screenshot({ path: outPng, fullPage: false });
    console.warn(`  [warn] selector "${sel}" not found in ${path.basename(htmlFile)} — viewport fallback`);
  }
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  for (const s of SECTIONS) {
    const bOut = path.join(OUT, `${s.name}_BEFORE.png`);
    const aOut = path.join(OUT, `${s.name}_AFTER.png`);
    console.log(`[BEFORE] ${s.name}`);
    await shoot(page, s.bFile, s.sel, s.wait, bOut);
    console.log(`[AFTER]  ${s.name}`);
    await shoot(page, s.aFile, s.sel, s.wait, aOut);
  }

  await browser.close();
  console.log('\nDone. Files in', OUT);
  fs.readdirSync(OUT).filter(f=>f.endsWith('.png')).sort().forEach(f=>console.log(' ', f));
})();
