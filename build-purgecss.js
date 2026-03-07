#!/usr/bin/env node
/**
 * build-purgecss.js
 * Runs PurgeCSS against all project HTML/JS templates to produce
 * minimal versions of the Bootstrap CSS files.
 *
 * Originals are kept untouched.  Purged files are written alongside them:
 *   backend/static/css/bootstrap.purged.css
 *   backend/static/css/bootstrap.rtl.purged.css
 *
 * Usage:  node build-purgecss.js
 */

const { PurgeCSS } = require('purgecss');
const fs           = require('fs');
const path         = require('path');

const STATIC_CSS = path.join(__dirname, 'backend', 'static', 'css');
const TEMPLATES  = path.join(__dirname, 'backend', 'templates');
const STATIC_JS  = path.join(__dirname, 'backend', 'static', 'js');

// Content globs — scan all HTML templates and local JS files
const CONTENT_GLOBS = [
  `${TEMPLATES}/**/*.html`,
  `${STATIC_JS}/**/*.js`,
];

// Safelist: keep dynamic Bootstrap classes that PurgeCSS cannot see in static HTML
// (Alpine.js / HTMX toggled classes, JS-added classes, etc.)
const SAFELIST = {
  // Patterns for commonly toggled Bootstrap utility classes
  patterns: [
    /^(show|active|fade|collaps|modal|dropdown|offcanvas|tooltip|popover|bs-)/,
    /^(is-invalid|is-valid|was-validated)/,
    /^(alert|badge|btn|nav|navbar|pagination|progress|spinner|toast)/,
    /^(d-none|d-block|d-flex|d-inline|d-grid)/,
    /^(text-|bg-|border-|fw-|fs-)/,
    /^(mb-|mt-|ms-|me-|my-|mx-|pb-|pt-|ps-|pe-|py-|px-)/,
    /^(col-|row-|g-|gx-|gy-)/,
    /^(order-|offset-)/,
    /^(w-|h-|mw-|mh-)/,
    /^(float-|position-|top-|bottom-|start-|end-)/,
    /^(opacity-|overflow-|rounded|shadow|z-)/,
    /^rtl|^ltr/,
  ],
};

async function purge(inputFile, outputFile) {
  const result = await new PurgeCSS().purge({
    css:      [inputFile],
    content:  CONTENT_GLOBS,
    safelist: SAFELIST,
    variables: true,
  });

  if (!result || result.length === 0) {
    console.error(`❌  No output for ${path.basename(inputFile)}`);
    return;
  }

  const purgedCSS = result[0].css;
  fs.writeFileSync(outputFile, purgedCSS, 'utf8');

  const origSize   = fs.statSync(inputFile).size;
  const purgedSize = Buffer.byteLength(purgedCSS, 'utf8');
  const reduction  = (((origSize - purgedSize) / origSize) * 100).toFixed(1);

  console.log(
    `✅  ${path.basename(outputFile)}` +
    `  ${(origSize / 1024).toFixed(1)} KiB → ${(purgedSize / 1024).toFixed(1)} KiB` +
    `  (−${reduction}%)`
  );
}

(async () => {
  const ltrIn  = path.join(STATIC_CSS, 'bootstrap.min.css');
  const ltrOut = path.join(STATIC_CSS, 'bootstrap.purged.css');
  const rtlIn  = path.join(STATIC_CSS, 'bootstrap.rtl.min.css');
  const rtlOut = path.join(STATIC_CSS, 'bootstrap.rtl.purged.css');

  // LTR — always present
  if (fs.existsSync(ltrIn)) {
    await purge(ltrIn, ltrOut);
  } else {
    console.warn(`⚠️  Not found: ${ltrIn}`);
  }

  // RTL — may not exist yet
  if (fs.existsSync(rtlIn)) {
    await purge(rtlIn, rtlOut);
  } else {
    console.warn(`⚠️  RTL file not found: ${rtlIn}  (skipping)`);
  }
})();
