/* Explicit local preview and clipboard copy. Never uploads or downloads a file. */
(() => {
  'use strict';
  const preview = document.getElementById('phase-preview');
  const copy = document.getElementById('phase-copy');
  const text = document.getElementById('phase-text');
  const status = document.getElementById('phase-status');
  let pending = false;
  preview.addEventListener('click', async () => {
    if (pending) return;
    pending = true; preview.disabled = true; copy.disabled = true;
    text.value = ''; text.hidden = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/handoff/phase-plan', {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal
      });
      if (response.status === 401) throw Error('Unlock NEXEN, then open the handoff again.');
      if (!response.ok) throw Error('The handoff is not ready yet. Your saved files remain in place.');
      const data = await response.json();
      if (typeof data.text !== 'string' || !data.text.trim() || data.text.includes('\0') || data.text.length > 262144) {
        throw Error('The handoff response could not be verified.');
      }
      text.value = data.text; text.hidden = false; copy.disabled = false;
      status.textContent = 'Saved on H:. Review this text before sharing it with ChatGPT.';
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'Preview timed out. Try again when NEXEN responds.' : error.message;
    } finally {
      clearTimeout(timer); pending = false; preview.disabled = false;
    }
  });
  copy.addEventListener('click', async () => {
    if (!text.value || copy.disabled) return;
    copy.disabled = true;
    try {
      await navigator.clipboard.writeText(text.value);
      status.textContent = 'Copied. Paste into regular ChatGPT when you are ready.';
    } catch {
      text.focus(); text.select();
      status.textContent = 'Clipboard access is unavailable. The text is selected; press Ctrl+C to copy it.';
    } finally { copy.disabled = false; }
  });
})();
