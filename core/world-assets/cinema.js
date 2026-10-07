/** WDR cinema dock with local game controls and a user-loaded YouTube player. */
import {mountGameControls} from './game-controls.js';
export const DEFAULT_VIDEO_URL = 'https://www.youtube.com/watch?v=esAfAQV7p9I&t=534s';
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const HOSTS = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be']);

export function parseTime(value) {
  if (value === null || value === undefined || value === '') return 0;
  const text = String(value).trim().toLowerCase();
  let seconds;
  if (/^\d+$/.test(text)) seconds = Number(text);
  else {
    const parts = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(text);
    if (!parts || !parts.slice(1).some(Boolean)) throw new Error('Start time must use seconds or h/m/s, such as 534s or 8m54s.');
    seconds = Number(parts[1] || 0) * 3600 + Number(parts[2] || 0) * 60 + Number(parts[3] || 0);
  }
  if (!Number.isSafeInteger(seconds) || seconds < 0 || seconds > 604800) throw new Error('Start time must be between 0 seconds and 7 days.');
  return seconds;
}

export function parseYouTubeURL(value) {
  if (typeof value !== 'string' || value.length > 2048) throw new Error('Paste a YouTube video link, up to 2048 characters.');
  const input = value.trim();
  if (!input || /[\u0000-\u0020\\]/.test(input)) throw new Error('Paste a complete YouTube URL without spaces.');
  let url;
  try { url = new URL(input); } catch { throw new Error('Paste a complete https://youtube.com or https://youtu.be video link.'); }
  if (!['https:', 'http:'].includes(url.protocol) || !HOSTS.has(url.hostname.toLowerCase()) || url.username || url.password || url.port) {
    throw new Error('Only youtube.com and youtu.be video links are supported.');
  }
  const host = url.hostname.toLowerCase();
  const parts = url.pathname.split('/').filter(Boolean);
  let id;
  if (host === 'youtu.be' || host === 'www.youtu.be') {
    if (parts.length !== 1) throw new Error('The shortened YouTube link must contain one video ID.');
    id = parts[0];
  } else if (url.pathname === '/watch' || url.pathname === '/watch/') {
    if (url.searchParams.getAll('v').length !== 1) throw new Error('The YouTube watch link must contain one video ID.');
    id = url.searchParams.get('v');
  } else if (parts.length === 2 && ['embed', 'shorts', 'live'].includes(parts[0])) id = parts[1];
  else throw new Error('Use an individual YouTube video link; channel and playlist-only links are not supported.');
  if (!VIDEO_ID.test(id || '')) throw new Error('The link does not contain a valid 11-character YouTube video ID.');
  let time = url.searchParams.get('start') ?? url.searchParams.get('t');
  if (time === null && url.hash.startsWith('#t=')) time = url.hash.slice(3);
  const start = parseTime(time);
  const watch = new URL('https://www.youtube.com/watch');
  watch.searchParams.set('v', id);
  if (start) watch.searchParams.set('t', start + 's');
  return Object.freeze({id, start, watchURL: watch.href});
}

export function embedURL(video) {
  if (!video || !VIDEO_ID.test(video.id) || !Number.isSafeInteger(video.start) || video.start < 0 || video.start > 604800) throw new Error('Invalid video selection.');
  const url = new URL('https://www.youtube-nocookie.com/embed/' + video.id);
  url.searchParams.set('start', String(video.start));
  url.searchParams.set('autoplay', '0');
  url.searchParams.set('controls', '1');
  url.searchParams.set('playsinline', '1');
  url.searchParams.set('rel', '0');
  return url.href;
}

function timeLabel(seconds) {
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), secs = seconds % 60;
  return (hours ? hours + ':' + String(minutes).padStart(2, '0') : String(minutes)) + ':' + String(secs).padStart(2, '0');
}

export function mountCinema(options = {}) {
  if (typeof document === 'undefined') throw new Error('The cinema dock requires a browser document.');
  const ownerWindow = window;
  let hostDocument = options.document || document;
  // In the main GUI, mount above the persistent game iframe and work panels.
  if (!options.document && options.useParent !== false) {
    try { if (parent !== window && parent.location.origin === location.origin) hostDocument = parent.document; } catch {}
  }
  const hostWindow = hostDocument.defaultView;
  if (hostWindow.NexenCinema?.element?.isConnected) {
    ownerWindow.NexenCinema = hostWindow.NexenCinema;
    return hostWindow.NexenCinema;
  }
  const selectedDefault = parseYouTubeURL(options.defaultURL || DEFAULT_VIDEO_URL);
  const stylesheetURL = new URL('./cinema.css', import.meta.url);
  if (stylesheetURL.origin !== location.origin) throw new Error('Cinema styles must be served from the same origin.');
  if (!hostDocument.getElementById('nexen-cinema-style')) {
    const css = hostDocument.createElement('link'); css.id = 'nexen-cinema-style'; css.rel = 'stylesheet'; css.href = stylesheetURL.href; hostDocument.head.append(css);
  }
  const dock = hostDocument.createElement('section');
  dock.id = 'nexen-cinema'; dock.className = 'nx-cinema'; dock.hidden = true;
  dock.setAttribute('role', 'region'); dock.setAttribute('aria-label', 'WDR TV player');
  dock.innerHTML = `
    <header class="nx-cinema-head">
      <div class="nx-cinema-brand"><span aria-hidden="true" class="nx-cinema-light"></span><div><strong>WDR TV</strong><small data-tv-status>Ready when you are</small></div></div>
      <div class="nx-cinema-actions"><button type="button" data-tv-minimize aria-label="Minimize TV without unloading" title="Minimize; playback may continue">−</button><button type="button" data-tv-expand aria-label="Expand TV" title="Expand TV">↗</button><button type="button" data-tv-close aria-label="Close TV and unload the player" title="Close and stop the player">×</button></div>
    </header>
    <nav class="nx-cinema-tabs" role="tablist" aria-label="WDR screen mode"><button type="button" data-tv-mode="video" role="tab" aria-selected="true" aria-controls="nx-tv-video">YouTube</button><button type="button" data-tv-mode="games" role="tab" aria-selected="false" aria-controls="nx-tv-games" tabindex="-1">Game controls</button></nav>
    <div class="nx-cinema-body"><div id="nx-tv-video" data-tv-content role="tabpanel" aria-label="YouTube player">
      <div class="nx-cinema-stage" data-tv-stage><div class="nx-cinema-poster" data-tv-poster><span class="nx-cinema-chip">YOUR WORLD. YOUR SCREEN.</span><div class="nx-cinema-play" aria-hidden="true">▶</div><h2>Watch while you work.</h2><p>Your selected YouTube video starts at <b data-tv-start>8:54</b>.</p><button type="button" data-tv-load>Load YouTube player</button><small>The player loads only when you click. Press play in YouTube to begin.</small></div></div>
      <form class="nx-cinema-form" data-tv-form><label for="nexen-cinema-url">YouTube video link</label><div><input id="nexen-cinema-url" data-tv-input type="url" inputmode="url" autocomplete="off" spellcheck="false" maxlength="2048" required aria-describedby="nexen-cinema-help"><button type="submit">Load video</button></div></form>
      <p class="nx-cinema-message" data-tv-message role="status"></p>
      <footer class="nx-cinema-foot"><a data-tv-watch target="_blank" rel="noopener noreferrer">Watch on YouTube ↗</a><p id="nexen-cinema-help">Use the player's play, pause, volume and captions. YouTube links only; protected movie services are not supported.</p></footer>
    </div><div id="nx-tv-games" data-tv-games role="tabpanel" aria-label="Game controls" hidden></div></div>`;
  const launcher = hostDocument.createElement('button');
  launcher.id='nexen-tv-open'; launcher.className='nx-cinema-launcher'; launcher.type='button';
  launcher.innerHTML='<span aria-hidden="true">▣</span> WDR TV';launcher.setAttribute('aria-label','Open WDR TV');launcher.setAttribute('aria-controls',dock.id);launcher.setAttribute('aria-expanded','false');
  hostDocument.body.append(launcher,dock);
  const find = attr => dock.querySelector('[data-tv-'+attr+']');
  let selected=selectedDefault, iframe=null, minimized=false, expanded=false, mode='video';
  function emitFocus() {
    ownerWindow.dispatchEvent(new CustomEvent('nexen:cinema-focus'));
    if (hostWindow !== ownerWindow) hostWindow.dispatchEvent(new hostWindow.CustomEvent('nexen:cinema-focus'));
  }
  function message(text) { find('message').textContent=text; }
  const gameControls=mountGameControls(find('games'),{hostWindow,onFocus:emitFocus});
  function chooseMode(value) {
    mode=value==='games'?'games':'video';
    if(mode==='games')unload();
    find('content').hidden=mode!=='video';find('games').hidden=mode!=='games';
    dock.classList.toggle('nx-cinema-games',mode==='games');
    dock.querySelectorAll('[data-tv-mode]').forEach(button=>{const active=button.dataset.tvMode===mode;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
    gameControls.setVisible(!dock.hidden&&!minimized&&mode==='games');
    find('status').textContent=mode==='games'?'Your Windows games · local controls':iframe?'YouTube player loaded':'Ready when you are';emitFocus();
  }
  function syncSelection() {
    find('input').value=selected.watchURL;find('watch').href=selected.watchURL;
    find('start').textContent=timeLabel(selected.start);
  }
  function show() {
    dock.hidden=false; minimized=false;dock.classList.remove('nx-cinema-minimized');
    find('minimize').textContent='−';find('minimize').setAttribute('aria-label','Minimize TV without unloading');
    launcher.setAttribute('aria-expanded','true');emitFocus();
    gameControls.setVisible(mode==='games');
  }
  function minimize() {
    if(dock.hidden)return;
    minimized=!minimized;dock.classList.toggle('nx-cinema-minimized',minimized);
    find('minimize').textContent=minimized?'▣':'−';
    find('minimize').setAttribute('aria-label',minimized?'Restore TV':'Minimize TV without unloading');
    find('minimize').title=minimized?'Restore TV':'Minimize; playback may continue';
    find('status').textContent=minimized&&iframe?'Player kept open · restore to control':iframe?'YouTube player loaded':'Ready when you are';
    if(minimized)find('minimize').focus();
    gameControls.setVisible(!minimized&&mode==='games');
  }
  function expand() {
    show();expanded=!expanded;dock.classList.toggle('nx-cinema-expanded',expanded);
    find('expand').textContent=expanded?'↙':'↗';find('expand').setAttribute('aria-label',expanded?'Return TV to dock size':'Expand TV');
  }
  function unload() {
    if(iframe){iframe.src='about:blank';iframe.remove();iframe=null;}
    find('poster').hidden=false;find('status').textContent='Player unloaded';
  }
  function close() {
    unload();gameControls.setVisible(false);dock.hidden=true;launcher.setAttribute('aria-expanded','false');launcher.focus();
  }
  function load(value) {
    // Public calls may select a video, but only a trusted click/submit below loads it.
    selected=parseYouTubeURL(value);syncSelection();chooseMode('video');show();
    return selected;
  }
  function loadFromGesture(event) {
    event.preventDefault();
    if(!event.isTrusted){message('Click Load video to open the external player.');return;}
    try {
      const next=parseYouTubeURL(find('input').value);
      const src=embedURL(next);
      selected=next;syncSelection();show();
      if(iframe?.src===src){message('This video is already loaded. Use the player controls to play or pause.');return;}
      unload();
      iframe=hostDocument.createElement('iframe');iframe.title='YouTube video '+selected.id+' starting at '+timeLabel(selected.start);
      iframe.src=src;iframe.allow='encrypted-media; picture-in-picture; fullscreen';
      iframe.allowFullscreen=true;iframe.referrerPolicy='strict-origin-when-cross-origin';
      iframe.width='480';iframe.height='270';iframe.setAttribute('frameborder','0');
      find('stage').append(iframe);find('poster').hidden=true;
      find('status').textContent='YouTube player loaded';
      message('Press play in the player. If playback is restricted, use Watch on YouTube.');
    } catch(error) {message(error.message);find('input').setAttribute('aria-invalid','true');find('input').focus();}
  }
  launcher.onclick=()=>{show();(mode==='games'?dock.querySelector('[data-tv-mode="games"]'):find('input')).focus();};
  const openGames=()=>{chooseMode('games');show();dock.querySelector('[data-tv-mode="games"]').focus();};
  const gameButton=document.getElementById('games-button');gameButton?.addEventListener('click',openGames);
  dock.querySelectorAll('[data-tv-mode]').forEach(button=>{button.onclick=()=>chooseMode(button.dataset.tvMode);button.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();event.stopPropagation();chooseMode(event.key==='Home'?'video':event.key==='End'?'games':mode==='video'?'games':'video');dock.querySelector('[data-tv-mode="'+mode+'"]').focus();});});
  find('minimize').onclick=minimize;find('expand').onclick=expand;find('close').onclick=close;
  find('load').onclick=loadFromGesture;find('form').onsubmit=loadFromGesture;
  find('input').oninput=()=>find('input').removeAttribute('aria-invalid');
  dock.addEventListener('focusin',emitFocus);
  dock.addEventListener('pointerdown',emitFocus);
  // Do not let W/A/S/D, space, or editing keys bubble into world movement.
  dock.addEventListener('keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();if(!minimized)minimize();}});
  dock.addEventListener('keyup',event=>event.stopPropagation());
  syncSelection();
  const controller=Object.freeze({element:dock,open:show,openGames,select:load,minimize,expand,close,
    getState:()=>Object.freeze({visible:!dock.hidden,minimized,expanded,mode,loaded:!!iframe,videoId:selected.id,start:selected.start,autoplay:false,game:gameControls.getState()}),
    destroy:()=>{unload();gameControls.destroy();ownerWindow.removeEventListener('pagehide',ownerPagehide);gameButton?.removeEventListener('click',openGames);dock.remove();launcher.remove();delete hostWindow.NexenCinema;delete ownerWindow.NexenCinema;}});
  // The game iframe may unload while the parent dashboard remains open.
  // Cached pages keep their listeners; restoration does not re-run the module.
  const ownerPagehide=event=>event.persisted?close():controller.destroy();
  ownerWindow.addEventListener('pagehide',ownerPagehide);
  hostWindow.NexenCinema=controller;ownerWindow.NexenCinema=controller;
  return controller;
}

if(typeof window!=='undefined'&&typeof document!=='undefined') {
  const start=()=>mountCinema();
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
}
