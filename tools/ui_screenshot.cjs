// Optional local visual check using the installed Chrome and its DevTools protocol.
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');

const chrome = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const output = path.resolve(process.argv[2] || 'superchat-preview.png');
const width = Number(process.argv[3] || 1280);
const height = Number(process.argv[4] || 800);

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function main() {
  const port = await freePort();
  const profile = await fs.mkdtemp(path.join(os.tmpdir(), 'superchat-preview-'));
  const browser = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-first-run',
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    'about:blank',
  ], { stdio: 'ignore' });
  let socket;
  try {
    let target;
    for (let attempt = 0; attempt < 50; attempt++) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json`);
        target = (await response.json()).find(item => item.type === 'page');
        if (target) break;
      } catch { /* Chrome is starting. */ }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!target) throw new Error('Chrome did not expose a page.');
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      socket.addEventListener('open', resolve, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    let nextId = 0;
    const pending = new Map();
    socket.addEventListener('message', event => {
      const payload = JSON.parse(event.data);
      const task = pending.get(payload.id);
      if (!task) return;
      pending.delete(payload.id);
      if (payload.error) task.reject(new Error(payload.error.message));
      else task.resolve(payload.result);
    });
    function call(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = ++nextId;
        pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params }));
      });
    }
    await call('Page.enable');
    await call('Runtime.enable');
    await call('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor: 1, mobile: false,
    });
    await call('Page.navigate', { url: 'http://127.0.0.1:8000/' });
    for (let attempt = 0; attempt < 40; attempt++) {
      const result = await call('Runtime.evaluate', {
        expression: 'Boolean(document.getElementById("chat-form"))', returnByValue: true,
      });
      if (result.result.value) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    await call('Runtime.evaluate', {
      expression: 'fetch("/api/chat", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({message:"Find flights from Baku to Istanbul on Friday"})}).then(r=>r.json()).then(d=>{ history=d.history; render(history); })',
      awaitPromise: true,
    });
    const count = await call('Runtime.evaluate', {
      expression: 'document.querySelectorAll(".result-card").length', returnByValue: true,
    });
    if (count.result.value !== 3) throw new Error(`Expected three flight cards, got ${count.result.value}`);
    const screenshot = await call('Page.captureScreenshot', { format: 'png' });
    await fs.writeFile(output, Buffer.from(screenshot.data, 'base64'));
    console.log(`Saved ${output} with ${count.result.value} cards`);
    if (process.argv[5] === 'click') {
      await call('Runtime.evaluate', {
        expression: 'document.querySelector(".card-action").click()',
      });
      let clicked = false;
      for (let attempt = 0; attempt < 50; attempt++) {
        const result = await call('Runtime.evaluate', {
          expression: 'history.length === 4 && history[3].route === "flights" && history[3].content.includes("CA101")',
          returnByValue: true,
        });
        if (result.result.value) { clicked = true; break; }
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      if (!clicked) throw new Error('Flight card button did not show verified details.');
      console.log('Flight card button returned verified F001 details');
    }
  } finally {
    socket?.close();
    browser.kill();
    if (path.resolve(profile).startsWith(path.resolve(os.tmpdir()) + path.sep)) {
      await fs.rm(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
    }
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
