/* Leaflet display only. Predictions and areas come from Python, never this canvas. */
document.addEventListener('DOMContentLoaded', () => {
  const map = L.map('map', {zoomControl:false, attributionControl:true, maxZoom:19, minZoom:2, zoomSnap:.1});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{
    maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.control.zoom({position:'topright'}).addTo(map);
  L.control.scale({position:'bottomright',imperial:false}).addTo(map);
  map.setView([-41.26,174.89],11);
  let rgb=null, overlay=null, scene=null, classes=null, scores=null, mode='overlay';
  let settings={layers:['1','uncertain'],opacity:.45,threshold:70};
  const canvas=document.createElement('canvas');
  const caption=document.getElementById('map-caption');
  const inspector=document.getElementById('pixel-info');
  const decode=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
  const colours={'0':[52,125,176],'1':[235,115,53],uncertain:[154,113,184]};

  function paint() {
    if (!scene || !classes) return;
    canvas.width=scene.width;canvas.height=scene.height;
    const ctx=canvas.getContext('2d'), image=ctx.createImageData(canvas.width,canvas.height);
    for(let i=0;i<classes.length;i++) {
      if(classes[i]===255) continue;
      const key=scores[i]<settings.threshold?'uncertain':String(classes[i]);
      if(!settings.layers.includes(key)) continue;
      image.data.set([...colours[key],235],i*4);
    }
    ctx.putImageData(image,0,0);
    const url=canvas.toDataURL('image/png');
    if(overlay) overlay.setUrl(url);
    else overlay=L.imageOverlay(url,scene.bounds,{interactive:false}).addTo(map);
    updateMode();
  }
  function updateMode() {
    if(rgb) rgb.setOpacity(mode==='classes' && classes?.length ? .18:1);
    if(overlay) overlay.setOpacity(mode==='original'?0:mode==='classes'?1:settings.opacity);
    document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===mode)));
  }
  function installScene(data) {
    scene=data;classes=null;scores=null;
    if(rgb) map.removeLayer(rgb);if(overlay) map.removeLayer(overlay);overlay=null;
    rgb=L.imageOverlay(data.rgb,data.bounds).addTo(map);
    map.fitBounds(data.bounds,{padding:[20,20]});
    document.documentElement.style.setProperty('--scene-bg',`url("${data.rgb}")`);
    inspector.hidden=true;caption.textContent='Sentinel-2 · quality-screened imagery';
    updateMode();
  }
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.view;updateMode();}));
  document.getElementById('fit-scene').onclick=()=>{if(scene)map.fitBounds(scene.bounds,{padding:[20,20]});};
  map.on('click',e=>{
    if(!scene || !classes)return;
    const p=L.CRS.EPSG3857.project(e.latlng), [w,s,ee,n]=scene.projectedBounds;
    const x=Math.floor((p.x-w)/(ee-w)*scene.width),y=Math.floor((n-p.y)/(n-s)*scene.height);
    if(x<0||y<0||x>=scene.width||y>=scene.height){inspector.hidden=true;return;}
    const i=y*scene.width+x, id=classes[i];
    const name=id===255?'Excluded / no data':scores[i]<settings.threshold?'Uncertain':id===1?'Plume class':'Normal-water class';
    inspector.replaceChildren();
    const heading=document.createElement('strong');heading.textContent=name;
    const detail=document.createElement('span');detail.textContent=id===255?'Quality mask rejected this preview pixel.':`Model score ${scores[i]}% · preview pixel`;
    inspector.append(heading,detail);inspector.hidden=false;
  });
  new ResizeObserver(()=>map.invalidateSize()).observe(document.getElementById('map'));
  function connect() {
    Shiny.addCustomMessageHandler('pw-scene',installScene);
    Shiny.addCustomMessageHandler('pw-result',data=>{
      scene=data;classes=decode(data.classes);scores=decode(data.scores);paint();
      caption.textContent='Pilot classification · no water mask';
    });
    Shiny.addCustomMessageHandler('pw-style',data=>{settings=data;paint();});
    Shiny.addCustomMessageHandler('pw-clear',data=>{
      if(rgb)map.removeLayer(rgb);if(overlay)map.removeLayer(overlay);
      rgb=overlay=scene=classes=scores=null;caption.textContent='Open a supported GEE scene';inspector.hidden=true;
    });
    Shiny.addCustomMessageHandler('pw-controls',data=>{
      document.getElementById('run').disabled=data.busy||!data.ready;
      document.getElementById('example').disabled=data.busy;
      document.getElementById('upload').disabled=data.busy;
      const link=document.getElementById('export-actions');
      link.classList.toggle('export-disabled',!data.download||data.busy);
      link.setAttribute('aria-disabled',String(!data.download||data.busy));
      link.inert=!data.download||data.busy;
      document.querySelector('.map-stage').classList.toggle('processing',data.busy);
    });
  }
  document.getElementById('export-actions').addEventListener('click',e=>{
    if(e.currentTarget.getAttribute('aria-disabled')==='true'){e.preventDefault();e.stopImmediatePropagation();}
  },true);
  // Shiny is loaded by the page dependencies before this deferred script runs.
  connect();
});
