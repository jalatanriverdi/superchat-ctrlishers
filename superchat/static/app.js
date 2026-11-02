const messages = document.getElementById('messages');
const welcome = document.getElementById('welcome');
const form = document.getElementById('chat-form');
const input = document.getElementById('message');
const send = document.getElementById('send');
const status = document.getElementById('status');
const photo = document.getElementById('photo');
const photoButton = document.getElementById('photo-button');
const voiceButton = document.getElementById('voice-button');
const voiceLanguage = document.getElementById('voice-language');
let history = [];
let busy = false;
const voiceQueue = [];

function render(entries) {
  messages.querySelectorAll('.message').forEach(node => node.remove());
  welcome.hidden = entries.length > 0;
  for (const entry of entries) {
    const item = document.createElement('article');
    item.className = `message ${entry.role === 'user' ? 'user' : 'assistant'}${entry.pending ? ' pending' : ''}`;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = entry.role === 'user' ? 'You' : `SuperChat${entry.route && entry.route !== 'followup' ? ' · ' + entry.route.replaceAll('_', ' ') : ''}`;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    const sections = Array.isArray(entry.card_sections)
      ? entry.card_sections.filter(section => Array.isArray(section.items) && section.items.length)
      : [];
    bubble.textContent = sections.length ? entry.content.split('\n')[0] : entry.content;
    item.append(meta, bubble);
    if (sections.length) {
      const labels = { flights: 'Flights', shopping: 'Shopping', cinema: 'Cinema' };
      const icons = { flight: '✈', product: '◈', movie: '▣', showtime: '◷' };
      for (const section of sections) {
        const group = document.createElement('section');
        group.className = 'result-section';
        const heading = document.createElement('h3');
        heading.textContent = section.heading || labels[section.domain] || section.domain;
        group.append(heading);
        const grid = document.createElement('div');
        grid.className = 'result-grid';
        for (const card of section.items) {
          const panel = document.createElement('article');
          panel.className = `result-card ${card.kind}`;
          const artwork = document.createElement('div');
          artwork.className = 'card-artwork';
          artwork.textContent = icons[card.kind] || '◈';
          artwork.setAttribute('aria-hidden', 'true');
          const top = document.createElement('div');
          top.className = 'card-top';
          const label = document.createElement('span');
          label.className = 'card-id';
          label.textContent = card.id;
          const price = document.createElement('strong');
          price.className = 'card-price';
          price.textContent = card.price || '';
          top.append(label, price);
          const title = document.createElement('h4');
          title.textContent = card.title;
          const subtitle = document.createElement('p');
          subtitle.className = 'card-subtitle';
          subtitle.textContent = card.subtitle;
          const facts = document.createElement('div');
          facts.className = 'card-facts';
          for (const fact of card.facts) {
            const chip = document.createElement('span');
            chip.textContent = fact;
            facts.append(chip);
          }
          const detail = document.createElement('p');
          detail.className = 'card-detail';
          detail.textContent = card.detail || '';
          const action = document.createElement('button');
          action.type = 'button';
          action.className = 'card-action';
          action.textContent = `${card.action_label} ↗`;
          action.addEventListener('click', () => {
            if (!busy) runRequest('/api/card-action', {
              domain: card.domain, id: card.id, action: card.action,
            }, `${card.action_label} · ${card.id}`);
          });
          panel.append(artwork, top, title, subtitle, facts);
          if (card.detail) panel.append(detail);
          panel.append(action);
          grid.append(panel);
        }
        group.append(grid);
        item.append(group);
      }
      const full = document.createElement('details');
      full.className = 'full-response';
      const summary = document.createElement('summary');
      summary.textContent = ({ az: 'Tam mətn', ru: 'Полный текст' })[entry.language]
        || 'Full text response';
      const content = document.createElement('p');
      content.textContent = entry.content;
      full.append(summary, content);
      item.append(full);
    }
    messages.append(item);
  }
  messages.scrollTop = messages.scrollHeight;
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

function setBusy(value) {
  busy = value;
  send.disabled = value;
  photoButton.disabled = value;
  status.classList.toggle('busy', value);
  messages.setAttribute('aria-busy', String(value));
}

async function runRequest(path, body, shownMessage) {
  if (busy) return false;
  setBusy(true);
  status.textContent = 'Checking the mock data…';
  render([...history, { role: 'user', content: shownMessage },
    { role: 'assistant', content: 'Working on your request…', pending: true }]);
  try {
    const data = await request(path, body);
    history = data.history;
    render(history);
    status.textContent = '';
    input.focus();
    return true;
  } catch (error) {
    render(history);
    status.textContent = error.message;
    return false;
  } finally {
    setBusy(false);
    if (voiceQueue.length) sendNextVoiceMessage();
  }
}

async function sendMessage(message) {
  const trimmed = message.trim();
  if (!trimmed) return;
  const sent = await runRequest('/api/chat', { message: trimmed }, trimmed);
  if (sent && input.value.trim() === trimmed) input.value = '';
}

function sendNextVoiceMessage() {
  if (!busy && voiceQueue.length) sendMessage(voiceQueue.shift());
}

async function loadSession() {
  try {
    history = (await request('/api/session')).history;
    render(history);
  } catch (error) {
    status.textContent = 'Could not load this chat. Check that the server is running.';
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  if (!busy) sendMessage(input.value);
});

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

async function resetChat() {
  if (busy) return;
  status.textContent = '';
  try {
    history = (await request('/api/reset', {})).history;
    render(history);
    input.focus();
  } catch (error) {
    status.textContent = error.message;
  }
}
document.getElementById('reset').addEventListener('click', resetChat);
document.getElementById('reset-mobile').addEventListener('click', resetChat);

document.querySelectorAll('[data-prompt]').forEach(button => {
  button.addEventListener('click', () => {
    input.value = button.dataset.prompt;
    form.requestSubmit();
  });
});

photoButton.addEventListener('click', () => photo.click());
photo.addEventListener('change', async () => {
  const file = photo.files?.[0];
  if (!file) return;
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 4 * 1024 * 1024) {
    status.textContent = 'Choose a JPEG, PNG or WebP image under 4 MB.';
    photo.value = '';
    return;
  }
  try {
    const image = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('Could not read the photo.'));
      reader.readAsDataURL(file);
    });
    await runRequest('/api/visual-search', { image }, '[Photo uploaded]');
  } catch (error) {
    status.textContent = error.message;
  } finally {
    photo.value = '';
  }
});

// The browser recognizer detects speech start/end after the user enables the mic.
// It does not record or send microphone audio to the SuperChat server.
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let listening = false;
if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onresult = event => {
    for (let index = event.resultIndex; index < event.results.length; index++) {
      if (event.results[index].isFinal) {
        const transcript = event.results[index][0].transcript.trim();
        if (transcript) voiceQueue.push(transcript);
      }
    }
    sendNextVoiceMessage();
  };
  recognition.onerror = event => {
    if (['not-allowed', 'service-not-allowed'].includes(event.error)) {
      listening = false;
      voiceButton.setAttribute('aria-pressed', 'false');
      status.textContent = 'Microphone permission is needed for voice input.';
    } else if (event.error !== 'no-speech') {
      status.textContent = `Voice input: ${event.error}.`;
    }
  };
  recognition.onend = () => {
    if (listening) setTimeout(() => {
      if (listening) {
        try { recognition.start(); } catch { /* already restarting */ }
      }
    }, 350);
  };
  voiceLanguage.value = ['en-US', 'az-AZ', 'ru-RU'].includes(navigator.language)
    ? navigator.language : 'en-US';
  voiceButton.addEventListener('click', () => {
    listening = !listening;
    voiceButton.setAttribute('aria-pressed', String(listening));
    if (listening) {
      recognition.lang = voiceLanguage.value;
      status.textContent = 'Listening for speech…';
      try { recognition.start(); } catch (error) {
        listening = false;
        voiceButton.setAttribute('aria-pressed', 'false');
        status.textContent = 'Could not start the microphone.';
      }
    } else {
      recognition.stop();
      status.textContent = '';
    }
  });
  voiceLanguage.addEventListener('change', () => {
    if (listening) recognition.stop();
    recognition.lang = voiceLanguage.value;
  });
} else {
  voiceButton.disabled = true;
  voiceButton.title = 'Voice recognition is unavailable in this browser.';
}

loadSession();
