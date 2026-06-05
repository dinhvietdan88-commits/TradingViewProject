/**
 * read_and_update_alerts.mjs
 * Đọc 3 alerts hiện có và update webhook URL + secret sang VBS.
 */
import CDP from 'chrome-remote-interface';

const VBS_SECRET = '9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b';
const VBS_URL    = `https://trading.utopiavn.co/ingest?secret=${VBS_SECRET}`;

async function findChartPage() {
  const resp = await fetch('http://127.0.0.1:9222/json/list');
  const targets = await resp.json();
  return targets.find(t => t.type === 'page' && /tradingview\.com\/chart/i.test(t.url));
}

async function evalAsync(client, expr) {
  const r = await client.Runtime.evaluate({ expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result?.value;
}

async function main() {
  const target = await findChartPage();
  if (!target) { console.error('❌ TradingView chart not found'); process.exit(1); }
  console.log('✅ Connected:', target.title.substring(0, 60));

  const client = await CDP({ host: '127.0.0.1', port: 9222, target: target.id });
  await client.Runtime.enable();

  // ── 1. List alerts ────────────────────────────────────────────────────
  const raw = await evalAsync(client, `
    fetch('https://pricealerts.tradingview.com/list_alerts', { credentials: 'include' })
      .then(r => r.json())
      .then(d => JSON.stringify(d))
  `);
  const data = JSON.parse(raw);

  if (data.s !== 'ok') { console.error('❌ API error:', data); await client.close(); return; }

  const alerts = data.r;
  console.log(`\n📋 Found ${alerts.length} alert(s):\n`);
  for (const a of alerts) {
    const msg = (a.message || '').substring(0, 100);
    console.log(`  [${a.alert_id}] ${a.name || '(no name)'}`);
    console.log(`    Symbol:  ${a.symbol} | Active: ${a.active}`);
    console.log(`    Message: ${msg}`);
    console.log(`    Condition: ${JSON.stringify(a.condition || {}).substring(0, 80)}`);
    console.log('');
  }

  // ── 2. Identify which need updating ───────────────────────────────────
  const needUpdate = alerts.filter(a => {
    const msg = a.message || '';
    // Has old secret OR doesn't have VBS URL
    return msg.includes('7086c59c523e87c90f9d56db63a66fd9045cb081264afe65c4ce8c37cff89104')
      || !msg.includes('trading.utopiavn.co')
      || !a.webhook_url?.includes('trading.utopiavn.co');
  });

  console.log(`🔧 ${needUpdate.length} alert(s) need webhook update.\n`);

  // ── 3. Build new message for each alert ──────────────────────────────
  function buildNewMessage(oldMsg) {
    // Parse old message JSON if possible
    let parsed = null;
    try {
      // Remove old secret field if in body
      parsed = JSON.parse(oldMsg);
      delete parsed.secret;
      // Ensure required VBS fields
      if (!parsed.symbol) parsed.symbol = '{{ticker}}';
      if (!parsed.action) parsed.action = '{{strategy.order.action}}';
      if (!parsed.price) parsed.price = '{{close}}';
      if (!parsed.exchange) parsed.exchange = 'binance';
      if (!parsed.interval) parsed.interval = '{{interval}}';
      parsed.source = parsed.source || 'tradingview';
      parsed.time = '{{timenow}}';
      return JSON.stringify(parsed);
    } catch(e) {
      // Not valid JSON — build fresh template
      return JSON.stringify({
        symbol: '{{ticker}}',
        action: '{{strategy.order.action}}',
        price: '{{close}}',
        exchange: 'binance',
        interval: '{{interval}}',
        source: 'tradingview',
        time: '{{timenow}}'
      });
    }
  }

  // ── 4. Update via edit_alert API ──────────────────────────────────────
  for (const alert of needUpdate) {
    const newMsg = buildNewMessage(alert.message || '');
    console.log(`\n🔄 Updating alert [${alert.alert_id}]: ${alert.name || '(no name)'}`);
    console.log(`   New message: ${newMsg.substring(0, 120)}`);

    // Build edit payload — mirror the original alert but change message + webhook
    const editPayload = {
      alert_id: alert.alert_id,
      condition: alert.condition,
      resolution: alert.resolution,
      name: alert.name,
      message: newMsg,
      email: alert.email ?? false,
      email_content: alert.email_content ?? '',
      sms: alert.sms ?? false,
      notify_on_app: alert.notify_on_app ?? true,
      webhook_enabled: true,
      webhook_url: VBS_URL,
      sound_file: alert.sound_file ?? '',
      sound_duration: alert.sound_duration ?? 0,
      popup: alert.popup ?? false,
    };

    const editScript = `
      fetch('https://pricealerts.tradingview.com/edit_alert', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(${JSON.stringify(editPayload)})
      }).then(r => r.json()).then(d => JSON.stringify(d))
    `;

    const editRaw = await evalAsync(client, editScript);
    const editResult = JSON.parse(editRaw);

    if (editResult.s === 'ok') {
      console.log(`   ✅ Updated successfully!`);
    } else {
      console.log(`   ⚠️  Update response:`, JSON.stringify(editResult).substring(0, 200));
    }
  }

  // ── 5. Re-activate stopped alerts ────────────────────────────────────
  const stopped = alerts.filter(a => !a.active);
  for (const alert of stopped) {
    console.log(`\n▶️  Re-activating stopped alert [${alert.alert_id}]: ${alert.name}`);
    const reactivateScript = `
      fetch('https://pricealerts.tradingview.com/activate_alert', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alert_id: ${alert.alert_id} })
      }).then(r => r.json()).then(d => JSON.stringify(d))
    `;
    const raw2 = await evalAsync(client, reactivateScript);
    const res2 = JSON.parse(raw2);
    console.log(`   Result:`, res2.s === 'ok' ? '✅ Reactivated' : JSON.stringify(res2));
  }

  // ── 6. Final verify ───────────────────────────────────────────────────
  console.log('\n📊 Final alert state:');
  const verifyRaw = await evalAsync(client, `
    fetch('https://pricealerts.tradingview.com/list_alerts', { credentials: 'include' })
      .then(r => r.json())
      .then(d => JSON.stringify(d.r?.map(a => ({ id: a.alert_id, name: a.name, active: a.active, webhook: a.webhook_url?.substring(0, 50) }))))
  `);
  const finalAlerts = JSON.parse(verifyRaw);
  for (const a of finalAlerts) {
    console.log(`  [${a.id}] ${a.name} | active=${a.active} | webhook=${a.webhook || '(none)'}`);
  }

  await client.close();
  console.log('\n✅ Done!');
}

main().catch(e => { console.error('❌', e.message); process.exit(1); });
