/** Native game controls in the existing WDR TV dock. No game starts on page load. */
const IDS = ['halo','dolphin','playnite'];
const NAMES = {halo:'Halo Infinite',dolphin:'Dolphin',playnite:'Playnite'};
const SETUP = {halo:'https://store.steampowered.com/app/1240440/Halo_Infinite/',dolphin:'https://dolphin-emu.org/',playnite:'https://playnite.link/'};
const short = (value, limit=260) => typeof value === 'string' ? value.slice(0,limit) : '';

export function gameSnapshot(data) {
  if(!data || !Array.isArray(data.games)) throw Error('Game readiness is unavailable.');
  return {
    games:IDS.map(id=>{const candidates=data.games.filter(x=>x?.id===id),row=candidates.length===1?candidates[0]:{};
      return {id,name:NAMES[id],installed:row.installed===true,ready:row.launch_ready===true&&row.installed===true,
        blockers:Array.isArray(row.blockers)?row.blockers.filter(x=>typeof x==='string').slice(0,3).map(x=>short(x)):[],
        setup:row.setup_url===SETUP[id]?SETUP[id]:null};}),
    automations:[0,1].map(i=>{const row=data.automations?.[i];return {title:short(row?.title,80)||'Automation '+(i+1),
      status:short(row?.status,40)||'unavailable',detail:short(row?.detail)||'No verified activity was returned.'};}),
    foreground:{supported:data.foreground?.supported===true,halo:data.foreground?.halo_focused===true},
    pc2:{status:short(data.pc2?.status,40)||'unknown',detail:short(data.pc2?.detail)||'No current PC2 connection observation.'}
  };
}

export function windowPreview({mediaDevices,video,message,onState=()=>{}}) {
  let stream=null,generation=0,pending=false,disposed=false;
  const release=value=>value?.getTracks().forEach(track=>track.stop());
  function stop(note='Window preview stopped.') {
    generation++;pending=false;const previous=stream;stream=null;
    video.pause();video.srcObject=null;video.hidden=true;release(previous);onState(false,false);message(note);
  }
  async function start(event) {
    if(disposed||!event?.isTrusted||pending)return;
    if(!mediaDevices?.getDisplayMedia){message('Window preview is unavailable in this browser. Open the game normally.');return;}
    stop('Choose a game window in the browser sharing dialog.');
    pending=true;onState(false,true);const token=++generation;
    try {
      const selected=await mediaDevices.getDisplayMedia({video:{displaySurface:'window'},audio:false,monitorTypeSurfaces:'exclude',selfBrowserSurface:'exclude',surfaceSwitching:'exclude'});
      if(disposed||token!==generation){release(selected);return;}
      // Audio is never captured, even if a browser returns an unexpected audio track.
      selected.getAudioTracks().forEach(track=>{track.stop();selected.removeTrack(track);});
      if(selected.getVideoTracks().length!==1||selected.getVideoTracks()[0].getSettings?.().displaySurface!=='window'){
        release(selected);pending=false;onState(false,false);message('Choose an application window. Full-display and browser-tab sharing are not used for this preview.');return;
      }
      stream=selected;pending=false;video.muted=true;video.srcObject=selected;video.hidden=false;
      for(const track of selected.getVideoTracks())track.addEventListener('ended',()=>{if(stream===selected)stop('Window sharing ended.');},{once:true});
      await video.play();
      if(token!==generation)return;
      onState(true,false);message('Local window preview · muted · no recording or upload. Control the game in its own window.');
    }catch(error){
      if(token!==generation)return;
      stop(error?.name==='NotAllowedError'?'Window selection cancelled or permission declined.':
        'The window preview could not start. Your game is unchanged.');
    }
  }
  return {start,stop,destroy(){disposed=true;stop();},state:()=>({active:!!stream,pending})};
}

export function mountGameControls(container,{hostWindow=window,onFocus=()=>{}}={}) {
  const doc=container.ownerDocument;
  if(!doc.getElementById('nexen-game-controls-style')){
    const css=doc.createElement('link');css.id='nexen-game-controls-style';css.rel='stylesheet';css.href=new URL('./game-controls.css',import.meta.url).href;doc.head.append(css);
  }
  container.className='nx-game-controls';
  container.innerHTML=`<div class="nx-game-heading"><div><span class="nx-game-eyebrow">WINDOWS / YOUR GAMES</span><h2>Play. Keep your work in view.</h2><p>Open a game normally, or choose its window for the WDR screen.</p><a href="/continuity#phase-handoff" target="_top">Open phase handoff ↗</a></div><button type="button" data-game-refresh>Refresh</button></div>
    <div class="nx-game-grid"><section class="nx-game-library" aria-label="Installed game controls"><h3>Your game library</h3>${IDS.map(id=>`<article class="nx-native-card"><strong>${NAMES[id]}</strong><span class="nx-game-state" data-game-state-${id}>Checking readiness</span><p data-game-blocker-${id}>Waiting for a verified local check.</p><button type="button" data-game-launch-${id} disabled>Open ${NAMES[id]}</button><a data-game-setup-${id} hidden target="_blank" rel="noopener noreferrer">Setup details ↗</a></article>`).join('')}</section>
    <section class="nx-game-screen" aria-label="Game window preview"><div class="nx-game-screen-head"><span data-game-focus>NEXEN game screen</span><button type="button" data-game-fullscreen>Fullscreen preview</button></div><div class="nx-game-video-stage"><video data-game-video muted playsinline hidden aria-label="Your selected local game window"></video><div data-game-poster><span aria-hidden="true">▣</span><h3>Your game. Your screen.</h3><p>Choose a window to preview it here.<br>Play using the native game window.</p></div></div><div class="nx-game-preview-actions"><button type="button" data-game-preview>Choose game window</button><button type="button" data-game-stop disabled>Stop preview</button></div><p data-game-preview-message class="nx-game-note" role="status">Sharing stays on this PC. No recording, upload or remote control.</p><p class="nx-game-note">Halo fullscreen stays on its chosen Windows display. Keep NEXEN on another display to see your work.</p></section>
    <aside class="nx-game-work" aria-label="Two current automation summaries"><h3>Work beside your game</h3>${[0,1].map(i=>`<article class="nx-game-automation"><span data-game-auto-status-${i}>Waiting for status</span><h4 data-game-auto-title-${i}>Automation ${i+1}</h4><p data-game-auto-detail-${i}>No verified activity yet.</p></article>`).join('')}<div class="nx-game-pc2"><strong>PC2</strong><span data-game-pc2-state>Unknown</span><p data-game-pc2-detail>No current connection observation.</p></div></aside></div>
    <p data-game-message class="nx-game-note" role="status" aria-live="polite">Checking the local game controls does not start a game.</p>`;
  const el=name=>container.querySelector('[data-game-'+name+']');
  let visible=false,destroyed=false,loading=false,launching=false,packet=null,stale=true,interval=null,requestController=null;
  const tell=text=>{el('message').textContent=text;};
  const preview=windowPreview({mediaDevices:hostWindow.navigator?.mediaDevices,video:el('video'),message:text=>{el('preview-message').textContent=text;},
    onState:(active,pending)=>{el('poster').hidden=active;el('preview').disabled=pending;el('stop').disabled=!active&&!pending;}});
  function buttons(){for(const id of IDS)el('launch-'+id).disabled=!visible||stale||launching||!packet?.games.find(x=>x.id===id)?.ready;el('refresh').disabled=loading;}
  function render(data){
    packet=gameSnapshot(data);stale=false;
    for(const row of packet.games){
      el('state-'+row.id).textContent=row.ready?'Ready to open':row.installed?'Setup needed':'Not verified';
      el('state-'+row.id).dataset.ready=String(row.ready);
      el('blocker-'+row.id).textContent=row.blockers.join(' ')||(row.ready?'Opens a normal Windows application.':'The local launcher has not verified this application.');
      const link=el('setup-'+row.id);link.hidden=!row.setup;if(row.setup)link.href=row.setup;else link.removeAttribute('href');
    }
    packet.automations.forEach((row,i)=>{el('auto-title-'+i).textContent=row.title;el('auto-status-'+i).textContent=row.status.replaceAll('_',' ');el('auto-detail-'+i).textContent=row.detail;});
    el('focus').textContent=packet.foreground.supported?(packet.foreground.halo?'Halo has focus on Windows':'NEXEN game screen · Halo is not focused'):'NEXEN game screen · desktop focus unavailable';
    el('pc2-state').textContent=packet.pc2.status.replaceAll('_',' ');el('pc2-detail').textContent=packet.pc2.detail;
    tell('Local status checked '+new Date().toLocaleTimeString()+'. Automation summaries describe reported work, not game activity.');buttons();
  }
  async function api(path,body){
    const controller=new AbortController();requestController=controller;const timeout=hostWindow.setTimeout(()=>controller.abort(),10000);
    try{const response=await hostWindow.fetch(path,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:body?{'Content-Type':'application/json','X-Nexen-Action':'launch'}:{},...(body?{body:JSON.stringify(body)}:{})});
      if(response.status===401||response.redirected)throw Error('Sign in to NEXEN to use game controls.');
      if(!response.ok){let detail;try{detail=(await response.json()).detail;}catch{}throw Error(short(detail)||'Local game control unavailable ('+response.status+').');}
      return await response.json();
    }finally{hostWindow.clearTimeout(timeout);if(requestController===controller)requestController=null;}
  }
  async function refresh(){
    if(!visible||destroyed||loading||launching)return;loading=true;buttons();
    try{const data=await api('/api/game/native/status');if(visible&&!destroyed)render(data);}
    catch(error){if(!visible||destroyed)return;stale=true;for(const id of IDS)el('state-'+id).textContent='Status unavailable';
      for(const i of [0,1])el('auto-status-'+i).textContent='Stale · refresh needed';el('pc2-state').textContent='Unknown · status stale';el('focus').textContent='NEXEN game screen · focus unknown';
      tell(error.name==='AbortError'?'Local status timed out. Earlier details may be stale.':error.message);}
    finally{loading=false;if(!destroyed)buttons();}
  }
  for(const id of IDS)el('launch-'+id).onclick=async event=>{
    if(!event.isTrusted||!visible||stale||launching||!packet?.games.find(x=>x.id===id)?.ready)return;
    launching=true;buttons();tell('Requesting '+NAMES[id]+'…');
    try{const result=await api('/api/game/native/launch',{id});if(visible&&!destroyed)tell(result.status==='launch_requested'?'Windows launch requested. Check the '+NAMES[id]+' window to confirm it opened.':short(result.message)||'Request returned. Check the game window; launch completion is not verified.');}
    catch(error){if(visible&&!destroyed){stale=true;tell(error.name==='AbortError'?'Launch response timed out. Check the game window before retrying.':error.message);}}
    finally{launching=false;if(!destroyed)buttons();}
  };
  el('refresh').onclick=refresh;el('preview').onclick=event=>preview.start(event);el('stop').onclick=()=>preview.stop();
  el('fullscreen').onclick=async event=>{if(!event.isTrusted)return;try{if(!container.requestFullscreen)throw Error();await container.requestFullscreen();}catch{tell('Fullscreen preview is unavailable. You can expand the WDR TV dock instead.');}};
  container.addEventListener('focusin',onFocus);container.addEventListener('pointerdown',onFocus);
  function pagehide(){preview.stop();requestController?.abort();if(interval!==null)hostWindow.clearInterval(interval);interval=null;visible=false;stale=true;buttons();}
  hostWindow.addEventListener('pagehide',pagehide);
  return {setVisible(value){visible=!!value&&!destroyed;if(!visible){preview.stop();requestController?.abort();if(interval!==null)hostWindow.clearInterval(interval);interval=null;stale=true;buttons();return;}
      onFocus();refresh();if(interval===null)interval=hostWindow.setInterval(refresh,15000);},
    stopPreview:()=>preview.stop(),getState:()=>({visible,stale,...preview.state()}),
    destroy(){destroyed=true;pagehide();preview.destroy();hostWindow.removeEventListener('pagehide',pagehide);container.removeEventListener('focusin',onFocus);container.removeEventListener('pointerdown',onFocus);}};
}
