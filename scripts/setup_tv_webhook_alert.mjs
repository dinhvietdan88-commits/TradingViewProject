/**
 * setup_tv_webhook_alert.mjs
 *
 * Tự động tạo TradingView Alert với Webhook URL vào Server A VBS
 * thông qua Chrome DevTools Protocol (CDP) kết nối với TradingView Desktop.
 *
 * Usage:
 *   node scripts/setup_tv_webhook_alert.mjs
 *   node scripts/setup_tv_webhook_alert.mjs --symbol BTCUSDT --list-only
 */

import CDP from '../tradingview-mcp/node_modules/chrome-remote-interface/index.js';

const CDP_PORT = 9222;
const CDP_HOST = '127.0.0.1';

const WEBHOOK_URL = 'https://trading.utopiavn.co/ingest?secret=9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b';

const ALERT_MESSAGE = JSON.stringify({
  symbol: '{{ticker}}',
  action: '{{strategy.order.action}}',
  price: '{{close}}',
  exchange: 'binance',
  interval: '{{interval}}',
  source: 'tradingview',
  time: '{{timenow}}'
});

const args = process.argv.slice(2);
const listOnly = args.includes('--list-only');

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function findChartPage() {
  const resp = await fetch(`http://${CDP_HOST}:${CDP_PORT}/json/list`);
  const targets = await resp.json();
  return targets.find(t => t.type === 'page' && /tradingview\.com\/chart/i.test(t.url)) || null;
}

async function evalInPage(client, expr, awaitPromise = false) {
  const result = await client.Runtime.evaluate({
    expression: expr,
    returnByValue: true,
    awaitPromise,
  });
  if (result.exceptionDetails) {
    const msg = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
    throw new Error(`JS error: ${msg}`);
  }
  return result.result?.value;
}

async function listAlerts(client) {
  console.log('\n📋 Fetching existing alerts from pricealerts API...');
  const result = await evalInPage(client, `
    fetch('https://pricealerts.tradingview.com/list_alerts', { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.s !== 'ok' || !Array.isArray(data.r)) return { alerts: [], error: data.errmsg };
        return {
          alerts: data.r.map(a => {
            let sym = a.symbol;
            try { sym = JSON.parse(a.symbol.replace(/^=/, '')).symbol || a.symbol; } catch(e) {}
            return {
              id: a.alert_id,
              symbol: sym,
              type: a.type,
              active: a.active,
              message: (a.message || '').substring(0, 80),
              created: a.create_time,
            };
          })
        };
      })
      .catch(e => ({ alerts: [], error: e.message }))
  `, true);
  return result;
}

async function openAlertDialog(client) {
  console.log('\n🔔 Opening Create Alert dialog (Alt+A)...');

  // Focus the page first
  await evalInPage(client, `window.focus(); document.body.click();`);
  await sleep(500);

  // Try clicking "Create alert" button first
  const clicked = await evalInPage(client, `
    (function() {
      // Try aria-label "Create Alert"
      var btn = document.querySelector('[aria-label="Create Alert"]')
        || document.querySelector('[data-name="create-alert-button"]')
        || document.querySelector('button[aria-label*="alert" i]');
      if (btn) { btn.click(); return 'clicked:' + (btn.ariaLabel || btn.textContent); }
      return null;
    })()
  `);

  if (clicked) {
    console.log(`  ✅ Clicked: ${clicked}`);
  } else {
    // Fallback: Alt+A keyboard shortcut
    console.log('  ⌨️  Using Alt+A shortcut...');
    await client.Input.dispatchKeyEvent({
      type: 'keyDown', modifiers: 1, key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65
    });
    await client.Input.dispatchKeyEvent({ type: 'keyUp', key: 'a', code: 'KeyA' });
  }

  await sleep(1500);

  // Verify dialog opened
  const dialogOpen = await evalInPage(client, `
    !!(document.querySelector('[role="dialog"]')
      || document.querySelector('[class*="alert-dialog"]')
      || document.querySelector('[class*="AlertDialog"]')
      || document.querySelector('[data-name="alert-dialog"]'))
  `);

  return dialogOpen;
}

async function fillWebhookSection(client) {
  console.log('\n🔗 Configuring Webhook URL...');

  // Step 1: Click "Notifications" tab
  const notifTab = await evalInPage(client, `
    (function() {
      var tabs = document.querySelectorAll('[role="tab"], button');
      for (var t of tabs) {
        if (/notification/i.test(t.textContent) || /notification/i.test(t.ariaLabel || '')) {
          t.click(); return t.textContent.trim();
        }
      }
      return null;
    })()
  `);

  if (notifTab) {
    console.log(`  ✅ Clicked Notifications tab: "${notifTab}"`);
    await sleep(800);
  } else {
    console.log('  ⚠️  Notifications tab not found - may already be visible');
  }

  // Step 2: Find and enable Webhook URL checkbox
  const webhookEnabled = await evalInPage(client, `
    (function() {
      // Find checkbox or toggle near "Webhook" label
      var labels = document.querySelectorAll('label, span, div');
      for (var label of labels) {
        if (/webhook/i.test(label.textContent) && label.textContent.length < 30) {
          // Find nearby checkbox
          var cb = label.querySelector('input[type="checkbox"]')
            || label.previousElementSibling?.querySelector('input[type="checkbox"]')
            || label.parentElement?.querySelector('input[type="checkbox"]')
            || label.closest('[class*="row"]')?.querySelector('input[type="checkbox"]');
          if (cb && !cb.checked) {
            cb.click();
            return 'enabled_checkbox';
          } else if (cb && cb.checked) {
            return 'already_enabled';
          }
        }
      }
      return null;
    })()
  `);

  console.log(`  Webhook checkbox: ${webhookEnabled || 'not_found'}`);
  await sleep(500);

  // Step 3: Fill Webhook URL input
  const webhookFilled = await evalInPage(client, `
    (function() {
      var inputs = document.querySelectorAll('input[type="text"], input[type="url"], input:not([type])');
      for (var inp of inputs) {
        var placeholder = (inp.placeholder || '').toLowerCase();
        var nearLabel = inp.closest('[class*="row"], [class*="field"], label')?.textContent?.toLowerCase() || '';
        if (placeholder.includes('webhook') || placeholder.includes('url')
            || nearLabel.includes('webhook') || nearLabel.includes('url')) {
          // Set value using React's internal setter
          var nativeSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          nativeSet.call(inp, ${JSON.stringify(WEBHOOK_URL)});
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          inp.dispatchEvent(new Event('change', { bubbles: true }));
          inp.focus();
          return 'filled:' + placeholder.substring(0, 30);
        }
      }
      return null;
    })()
  `);

  console.log(`  Webhook URL input: ${webhookFilled || 'not_found - may need to enable checkbox first'}`);
  return !!webhookFilled;
}

async function fillAlertMessage(client, message) {
  console.log('\n📝 Setting Alert Message...');

  const msgSet = await evalInPage(client, `
    (function() {
      var textarea = document.querySelector('textarea[placeholder*="message" i]')
        || document.querySelector('[class*="alert"] textarea')
        || document.querySelector('[class*="Message"] textarea');
      if (textarea) {
        var nativeSet = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
        nativeSet.call(textarea, ${JSON.stringify(message)});
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
        return 'set:' + textarea.value.substring(0, 50);
      }
      return null;
    })()
  `);

  console.log(`  Message: ${msgSet || 'not_found'}`);
  return !!msgSet;
}

async function takeScreenshot(client, label) {
  try {
    const { data } = await client.Page.captureScreenshot({ format: 'png' });
    const fs = await import('fs');
    const path = `./tradingview-mcp/screenshots/setup_${label}_${Date.now()}.png`;
    fs.writeFileSync(path, Buffer.from(data, 'base64'));
    console.log(`  📸 Screenshot: ${path}`);
    return path;
  } catch (e) {
    console.log(`  📸 Screenshot failed: ${e.message}`);
    return null;
  }
}

async function main() {
  console.log('🚀 TradingView Webhook Alert Setup via CDP');
  console.log('==========================================');
  console.log(`Webhook URL: ${WEBHOOK_URL.substring(0, 60)}...`);

  // Connect to TradingView
  console.log('\n🔌 Connecting to TradingView Desktop (CDP port 9222)...');
  const target = await findChartPage();
  if (!target) {
    console.error('❌ No TradingView chart page found. Is TradingView Desktop running?');
    process.exit(1);
  }
  console.log(`  ✅ Found chart page: ${target.title.substring(0, 60)}`);
  console.log(`  URL: ${target.url}`);

  const client = await CDP({ host: CDP_HOST, port: CDP_PORT, target: target.id });
  await client.Runtime.enable();
  await client.Page.enable();
  await client.DOM.enable();

  try {
    // List existing alerts
    const alertData = await listAlerts(client);
    if (alertData.error) {
      console.log(`  ⚠️  Alert list error: ${alertData.error}`);
    } else {
      console.log(`  Found ${alertData.alerts.length} existing alert(s):`);
      for (const a of alertData.alerts.slice(0, 5)) {
        console.log(`    - [${a.id}] ${a.symbol} | active=${a.active} | msg="${a.message}"`);
      }
    }

    if (listOnly) {
      console.log('\n✅ List-only mode. Done.');
      return;
    }

    // Check if webhook alert already exists
    const hasWebhook = alertData.alerts.some(a =>
      (a.message || '').includes('trading.utopiavn.co')
    );
    if (hasWebhook) {
      console.log('\n✅ Webhook alert already configured! No action needed.');
      return;
    }

    // Screenshot before
    await takeScreenshot(client, 'before');

    // Open alert dialog
    const dialogOpen = await openAlertDialog(client);
    if (!dialogOpen) {
      console.log('  ⚠️  Dialog may not have opened. Taking screenshot...');
    }
    await takeScreenshot(client, 'dialog_opened');

    // Fill webhook
    const webhookOk = await fillWebhookSection(client);

    // Fill message
    await fillAlertMessage(client, ALERT_MESSAGE);

    await sleep(500);
    await takeScreenshot(client, 'filled');

    console.log('\n📊 Setup Summary:');
    console.log(`  Webhook URL configured: ${webhookOk ? '✅' : '⚠️ partial'}`);
    console.log(`  Message template set: ${ALERT_MESSAGE.substring(0, 60)}...`);
    console.log('\n⚠️  NOTE: The alert dialog is open in TradingView.');
    console.log('   Please review the settings and click "Create" to save.');
    console.log('   (Auto-submit is disabled to allow manual review)');

  } finally {
    await client.close();
  }
}

main().catch(err => {
  console.error('❌ Fatal error:', err.message);
  process.exit(1);
});
