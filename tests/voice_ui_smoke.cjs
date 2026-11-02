// Browser-independent smoke check of the hands-free microphone control.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const elements = new Map();
function element() {
  return {
    value: '', textContent: '', hidden: false, disabled: false,
    dataset: {}, listeners: {}, classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(name, handler) { this.listeners[name] = handler; },
    setAttribute(name, value) { this[name] = value; },
    querySelectorAll() { return []; }, append() {}, focus() {},
  };
}
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
  querySelectorAll() { return []; },
  createElement() { return element(); },
};
const requests = [];
let recognizer;
class FakeRecognition {
  constructor() { recognizer = this; this.starts = 0; }
  start() { this.starts++; }
  stop() {}
}
const context = {
  document, navigator: { language: 'en-US' },
  window: { SpeechRecognition: FakeRecognition },
  fetch: async (url) => {
    requests.push(url);
    return { ok: true, json: async () => url === '/api/session'
      ? { history: [] } : { history: [
        { role: 'user', content: 'Show me headphones' },
        { role: 'assistant', content: 'P001', route: 'shopping' },
      ] } };
  },
  setTimeout: callback => callback(),
};
const source = fs.readFileSync(path.join(__dirname, '..', 'superchat', 'static', 'app.js'), 'utf8');
vm.runInNewContext(source, context);

(async () => {
  await new Promise(resolve => setImmediate(resolve));
  const microphone = elements.get('voice-button');
  microphone.listeners.click();
  assert.equal(recognizer.continuous, true);
  assert.equal(recognizer.interimResults, true);
  assert.equal(recognizer.starts, 1);
  recognizer.onresult({ resultIndex: 0, results: [{
    isFinal: true, 0: { transcript: 'Show me headphones' },
  }] });
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(requests.includes('/api/chat'));
  recognizer.onend();
  assert.equal(recognizer.starts, 2);
  console.log('Voice UI smoke check passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
