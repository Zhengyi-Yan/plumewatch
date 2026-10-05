function disagrees(a,b) { return a!==255 && b!==255 && a!==b; }
function plumeColor(score, soft) {
  const t=Math.max(0,Math.min(1,score/100));
  if (!soft) return [Math.round(57+158*t),Math.round(113+126*t),Math.round(121+23*t),225];
  const stops=[[0,[59,130,246]],[.35,[45,190,170]],[.65,[250,204,90]],[1,[239,103,63]]];
  const j=t<=.35 ? 0 : t<=.65 ? 1 : 2;
  const u=(t-stops[j][0])/(stops[j+1][0]-stops[j][0]);
  return [...stops[j][1].map((c,k)=>Math.round(c+u*(stops[j+1][1][k]-c))),Math.round(204*t)];
}
if (typeof module !== 'undefined') module.exports={disagrees,plumeColor};
/* Leaflet is display only. Areas and exports come from native-grid GeoTIFFs. */
document.addEventListener('DOMContentLoaded', () => {
  const map = L.map('map', {zoomControl:false, maxZoom:19, minZoom:2, zoomSnap:.1});
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);
  L.control.zoom({position:'topright'}).addTo(map);
  L.control.scale({position:'bottomright', imperial:false}).addTo(map);
  map.setView([-41.26,174.89],11);
  const caption = document.getElementById('map-caption');
  const inspector = document.getElementById('pixel-info');
  const canvas = document.createElement('canvas');
  const colors = {'0':[57,113,121],'1':[215,239,144],'3':[215,199,165]};
  let scene = null, rgb = null, overlay = null, results = null, view = 'overlay';
  let settings = {model:'rf', threshold:70, opacity:.58};
  const modelNames = {rf:'Random Forest', unet:'U-Net', svm:'SVM'};
  const swipe=document.getElementById('swipe-position');
  const scoreStyle=document.getElementById('score-style');
  scoreStyle.addEventListener('change',paint);
  const scoreSmoothing=document.getElementById('score-smoothing');
  scoreSmoothing.addEventListener('change',paint);
  const scoreStrength=document.getElementById('score-strength');
  scoreStrength.addEventListener('change',paint);
  const decode = value => Uint8Array.from(atob(value), character => character.charCodeAt(0));

  function chosen() { return results && results[settings.model]; }

  function otherResult() { return results && (settings.model==='rf' ? results.unet : results.rf); }

  function paint() {
    inspector.hidden=true;
    updateDetails();
    const result = chosen();
    if (!scene || !result) {
      if (overlay) overlay.setOpacity(0);
      if (rgb) rgb.setOpacity(1);
      inspector.hidden=true;
      updateView();
      if (scene) caption.textContent=modelNames[settings.model] + ' · classify to view';
      return;
    }
    canvas.width = result.width; canvas.height = result.height;
    const context = canvas.getContext('2d');
    const image = context.createImageData(canvas.width, canvas.height);
    for (let i=0; i<result.classes.length; i++) {
      const id = result.classes[i];
      if (id === 255) continue;
      let rgbColor = colors[id], alpha=225;
      if (view==='disagreement') {
        const other=otherResult();
        if (!other || !disagrees(id,other.classes[i])) continue;
        rgbColor=[235,102,73];
      } else if (view==='score') {
        const rgba=plumeColor((scoreSmoothing.checked ? result.smoothedPlumeScores[scoreStrength.value] : result.plumeScores)[i],scoreStyle.value==='soft');
        rgbColor=rgba.slice(0,3); alpha=rgba[3];
      } else if (result.scores[i] < settings.threshold) continue;
      if (!rgbColor) continue;
      image.data.set([...rgbColor, alpha], i*4);
    }
    context.putImageData(image,0,0);
    if (overlay) overlay.setUrl(canvas.toDataURL('image/png'));
    else overlay = L.imageOverlay(canvas.toDataURL('image/png'), scene.bounds, {
      interactive:false, alt:'Selected model classification overlay'
    }).addTo(map);
    caption.textContent = view==='score' ? (scoreStyle.value==='soft' ? 'Plume score · lower scores fade into the image · uncalibrated' : 'Plume score: dark 0% → lime 100% · uncalibrated') :
      view==='disagreement' ? (otherResult() ? 'Orange: RF vs ' + (settings.model==='svm' ? 'SVM' : 'U-Net') + ' · shared valid pixels' : 'Run RF + U-Net, or RF + SVM, to compare') :
      modelNames[settings.model] + ' · preview only';
    if(view==='score' && scoreSmoothing.checked) caption.textContent+=' · '+scoreStrength.selectedOptions[0].text+' · display only';
    updateView();
  }

  function updateView() {
    if (rgb) rgb.setOpacity(view === 'classes' && chosen() ? .17 : 1);
    if (overlay) overlay.setOpacity(!chosen() || view === 'original' ? 0 : ['classes','swipe','score'].includes(view) ? 1 : settings.opacity);
    document.getElementById('swipe-control').hidden=view!=='swipe' || !chosen();
    document.getElementById('score-controls').hidden=view!=='score';
    document.getElementById('disagreement-summary').hidden=view!=='disagreement';
    document.getElementById('score-legend').hidden=scoreStyle.value!=='soft';
    scoreStrength.disabled=!scoreSmoothing.checked;
    clipSwipe();
    document.querySelectorAll('[data-view]').forEach(button =>
      button.setAttribute('aria-pressed', String(button.dataset.view === view)));
  }

  function clipSwipe() {
    const position=Number(swipe.value);
    document.getElementById('swipe-divider').style.left=position+'%';
    document.getElementById('swipe-handle').style.left=position+'%';
    if (!overlay) return;
    const element=overlay.getElement();
    element.style.clipPath='';
    if (view!=='swipe') return;
    const left=map.latLngToContainerPoint(overlay.getBounds().getNorthWest()).x;
    const right=map.latLngToContainerPoint(overlay.getBounds().getSouthEast()).x;
    const cut=map.getSize().x*Number(swipe.value)/100;
    const pct=Math.max(0,Math.min(100,100*(cut-left)/(right-left)));
    element.style.clipPath=`inset(0 0 0 ${pct}%)`;
  }
  swipe.addEventListener('input',clipSwipe);
  map.on('move zoom resize',clipSwipe);

  function updateDetails() {
    const result=chosen();
    document.getElementById('scene-model-details').textContent=scene ?
      JSON.stringify({scene:scene.name, source_crs:scene.sourceCrs,
        source_dimensions:[scene.sourceWidth,scene.sourceHeight], bands:scene.bands,
        source_metadata:scene.sourceTags, model:result ? result.modelId : 'Not classified',
        excluded_km2:result ? result.excludedKm2 : null,
        preprocessing:settings.model==='svm' ? 'Saved StandardScaler; scaled reflectance' :
          settings.model==='unet' ? 'Saved training mean/std; scaled reflectance' : 'Scaled reflectance',
        screening:'SCL 2,4,5,6,7; available finite inputs only',
        acquisition_note:'Date/asset ID shown only when supplied in source metadata or filename.'},null,2) : 'Load a scene.';
  }
  function installScene(data) {
    scene = data; results = null; inspector.hidden = true;
    updateDetails();
    if (rgb) map.removeLayer(rgb);
    if (overlay) map.removeLayer(overlay);
    overlay = null;
    rgb = L.imageOverlay(data.rgb, data.bounds, {alt:'Sentinel-2 scene preview'}).addTo(map);
    map.fitBounds(data.bounds, {padding:[20,20]});
    caption.textContent = 'Sentinel-2 · quality-screened image';
    updateView();
  }

  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
    view = button.dataset.view; paint();
  }));
  map.on('click', event => {
    const result = chosen();
    if (!scene || !result) return;
    const point = L.CRS.EPSG3857.project(event.latlng);
    const [west,south,east,north] = scene.projectedBounds;
    const x = Math.floor((point.x-west)/(east-west)*scene.width);
    const y = Math.floor((north-point.y)/(north-south)*scene.height);
    if (x<0 || y<0 || x>=scene.width || y>=scene.height) { inspector.hidden=true; return; }
    const index = y*scene.width+x, id=result.classes[index], score=result.scores[index];
    const name = id===255 ? 'Excluded / no data' : score<settings.threshold && !['score','disagreement'].includes(view) ? 'Below display threshold' :
      id===1 ? 'Visible plume' : id===3 ? 'Land' : 'Normal water';
    inspector.replaceChildren();
    const heading=document.createElement('strong'); heading.textContent=name;
    const detail=document.createElement('span');
    detail.textContent=id===255 ? 'Quality screening excluded this preview pixel.' :
      `${modelNames[settings.model]} predicted-class score ${score}% · plume score ${result.plumeScores[index]}% · raw preview pixel${view==='score' && scoreSmoothing.checked ? ' (overlay smoothed)' : ''}`;
    inspector.append(heading,detail); inspector.hidden=false;
  });
  new ResizeObserver(() => map.invalidateSize()).observe(document.getElementById('map'));

  Shiny.addCustomMessageHandler('pw-scene', installScene);
  Shiny.addCustomMessageHandler('pw-result', data => {
    results = Object.fromEntries(Object.entries(data).map(([name, result]) => [name, {
      classes:decode(result.classes), scores:decode(result.scores), plumeScores:decode(result.plumeScores),
      smoothedPlumeScores:Object.fromEntries(Object.entries(result.smoothedPlumeScores).map(([strength,values])=>[strength,decode(values)])),
      modelId:result.modelId, excludedKm2:result.excludedKm2,
      width:result.width, height:result.height
    }]));
    paint();
  });
  Shiny.addCustomMessageHandler('pw-style', data => { settings=data; inspector.hidden=true; paint(); });
  Shiny.addCustomMessageHandler('pw-clear', _data => {
    if (rgb) map.removeLayer(rgb);
    if (overlay) map.removeLayer(overlay);
    rgb=overlay=scene=results=null; inspector.hidden=true;updateDetails();updateView();
    caption.textContent='Open a supported scene';
  });
  Shiny.addCustomMessageHandler('pw-controls', data => {
    document.getElementById('run').disabled=data.busy || !data.ready;
    document.getElementById('example').disabled=data.busy;
    document.getElementById('upload').disabled=data.busy;
    const exportArea=document.getElementById('export-actions');
    exportArea.classList.toggle('export-disabled', !data.download || data.busy);
    exportArea.inert=!data.download || data.busy;
    document.querySelector('.map-shell').classList.toggle('processing', data.busy);
  });
});
