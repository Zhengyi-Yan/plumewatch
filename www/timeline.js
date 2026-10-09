/* Metrics are calculated on the native grid; map images are previews. */
document.addEventListener('DOMContentLoaded',()=>{
  let data=null, maps=[], layers=[], timer=null, syncing=false, analysisPair=[0,1], visibleChanges={1:true,2:true,3:false};
  const $=id=>document.getElementById(id);
  const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
  const format=value=>Number(value).toFixed(2);
  const dateText=(date,year=true)=>new Date(date+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',...(year?{year:'numeric'}:{}),timeZone:'UTC'});
  const plume=[215,239,144]; // Same visible-plume colour as the classification page.
  function el(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
  function stop(){if(timer)clearInterval(timer);timer=null;$('series-play').textContent='Play dates';$('series-play').setAttribute('aria-pressed','false');imageLabels();}
  function confirmationError(required){
    $('series-confirm-panel').classList.toggle('needs-confirmation',required);
    $('series-confirm-error').hidden=!required;
    $('series_confirm').setAttribute('aria-invalid',String(required));
    if(required){
      $('series_confirm').setAttribute('aria-describedby','series-confirm-error');
      $('series_confirm').focus({preventScroll:true});
      $('series-confirm-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'center'});
    }else $('series_confirm').removeAttribute('aria-describedby');
  }
  // Catch a missing confirmation before Shiny starts the task button's busy state.
  $('series_run').addEventListener('click',event=>{
    if(!$('series_confirm').checked){event.preventDefault();event.stopImmediatePropagation();confirmationError(true);}
  },true);
  $('series_confirm').addEventListener('change',()=>confirmationError(false));
  function scoreGuide(value){
    $('series-threshold-note').textContent=value===0?'0% · No filter. Start here to compare all predicted plume pixels.':
      value+'% · Keep only plume predictions scoring at least '+value+'%. Lower-score predictions are excluded; faint plume may also be removed.';
    const line=document.querySelector('.series-threshold-control .irs-line');
    if(line){
      line.setAttribute('role','slider');line.setAttribute('aria-labelledby','series_threshold-label');
      line.setAttribute('aria-describedby','series-threshold-note');
      line.setAttribute('aria-valuemin','0');line.setAttribute('aria-valuemax','95');
      line.setAttribute('aria-valuenow',String(value));line.setAttribute('aria-valuetext',value===0?'0 percent, no filter':value+' percent minimum model score');
      line.setAttribute('aria-disabled',String($('series_threshold').disabled));
    }
  }
  jQuery(document).on('shiny:inputchanged',event=>{
    if(event.name==='series_upload'||event.name==='series_confirm'&&event.value)confirmationError(false);
    if(event.name==='series_threshold')scoreGuide(Number(event.value));
  });
  Shiny.addCustomMessageHandler('series-date-confirmation',confirmationError);
  function initMaps(){
    if(maps.length)return;
    ['series-left-map','series-right-map','series-change-map'].forEach((id,index)=>{
      const map=L.map(id,{zoomControl:false,zoomSnap:.1,maxZoom:19,minZoom:2});
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
      L.control.zoom({position:'topright'}).addTo(map);L.control.scale({imperial:false}).addTo(map);
      maps.push(map);layers.push([]);
      new ResizeObserver(()=>map.invalidateSize()).observe($(id));
      map.on('moveend',()=>{
        if(index===2||syncing||!data)return;
        syncing=true;
        maps.slice(0,2).filter(other=>other!==map).forEach(other=>{
          if(other.getZoom()!==map.getZoom()||other.getCenter().distanceTo(map.getCenter())>.1)
            other.setView(map.getCenter(),map.getZoom(),{animate:false});
        });
        syncing=false;
      });
    });
  }
  function overlay(mask,kind){
    const canvas=document.createElement('canvas');canvas.width=data.width;canvas.height=data.height;
    const context=canvas.getContext('2d'),image=context.createImageData(data.width,data.height);
    const colors=kind==='change'?{1:[42,111,151,220],2:[239,135,84,220],3:[...plume,220]}:{1:[...plume,131]};
    if(kind==='frequency')for(let n=1;n<=data.rows.length;n++){
      const t=(n-1)/(data.rows.length-1);
      colors[n]=n===data.rows.length?[...plume,220]:[Math.round(169-168*t),Math.round(214-141*t),Math.round(229-105*t),220];
    }
    for(let i=0;i<mask.length;i++)if(data.valid[i]&&colors[mask[i]]&&(kind!=='change'||visibleChanges[mask[i]]))image.data.set(colors[mask[i]],i*4);
    context.putImageData(image,0,0);return canvas.toDataURL('image/png');
  }
  function replaceMap(j,index,mask,kind){
    layers[j].forEach(layer=>maps[j].removeLayer(layer));layers[j]=[];
    layers[j].push(L.imageOverlay(data.maps[index].rgb,data.bounds,{alt:'Sentinel-2 '+data.rows[index].date,className:j===2?'series-analysis-background':''}).addTo(maps[j]));
    if(mask)layers[j].push(L.imageOverlay(overlay(mask,kind),data.bounds,{alt:kind==='change'?'Plume change between compared dates':kind==='frequency'?'Number of dates classified as plume':'Predicted plume footprint'}).addTo(maps[j]));
  }
  function imageLabels(){
    if(!data)return;
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);
    if(!data.rows[a]||!data.rows[b])return;
    [['series-reference-stamp',a],['series-viewing-stamp',b]].forEach(([id,i])=>{
      $(id).textContent=dateText(data.rows[i].date);$(id).dateTime=data.rows[i].date;
    });
    $('series-viewing-position').textContent=(timer?'Playing · ':'Viewing · ')+'Image '+(b+1)+' of '+data.rows.length;
  }
  function paintMaps(){
    if(!data)return;
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);
    imageLabels();
    [a,b].forEach((index,j)=>replaceMap(j,index,$('series-show-plume').checked?data.maps[index].plume:null));
    [...$('series-observations').children].forEach((button,i)=>{
      button.classList.toggle('selected',i===b);button.setAttribute('aria-pressed',String(i===b));
      button.querySelector('.series-observation-state').textContent=i===a?(i===b?'Reference · Viewing':'Reference'):i===b?'Viewing':'View image →';
    });
    $('series-compare').disabled=a===b;
    $('series-compare-feedback').textContent=a===b?'Choose a different viewing date to compare changes.':'';
  }
  function layerCard(label,note,value,color,key){
    const card=el(key?'button':'div',undefined,'series-layer-card');
    card.style.setProperty('--key-color',color);
    const title=el('span',label,'series-layer-title');
    card.append(title,el('strong',format(value)+' km²','series-layer-value'),el('span',note,'series-layer-note'));
    if(key){
      card.type='button';card.dataset.layer=key;card.setAttribute('aria-pressed',String(visibleChanges[key]));
      card.append(el('span',visibleChanges[key]?'Shown on map':'Hidden · click to show','series-layer-state'));
      card.addEventListener('click',()=>{
        visibleChanges[key]=!visibleChanges[key];paintAnalysis();
        $('series-footprint-legend').querySelector(`[data-layer="${key}"]`).focus({preventScroll:true});
      });
    }
    return card;
  }
  function paintAnalysis(){
    if(!data)return;
    const legend=$('series-footprint-legend');legend.replaceChildren();
    if($('series-footprint-mode').value==='frequency'){
      replaceMap(2,data.rows.length-1,data.frequency,'frequency');
      $('series-change-title').textContent='How often was plume predicted here?';
      $('series-change-description').textContent=dateText(data.rows[0].date)+' to '+dateText(data.rows[data.rows.length-1].date)+' · '+data.rows.length+' acquisitions';
      $('series-change-instructions').textContent='Match each map colour to its count below. The area is where plume was predicted on exactly that many dates.';
      for(let n=1;n<=data.rows.length;n++){
        const t=(n-1)/(data.rows.length-1),color=n===data.rows.length?'#d7ef90':`rgb(${Math.round(169-168*t)},${Math.round(214-141*t)},${Math.round(229-105*t)})`;
        legend.append(layerCard(n+' of '+data.rows.length+' dates','Predicted plume on exactly '+n+(n===1?' date':' dates'),data.frequency_km2[String(n)]||0,color));
      }
      return;
    }
    const [low,high]=analysisPair,earlier=dateText(data.rows[low].date),later=dateText(data.rows[high].date),pair=data.pairs[`${low}-${high}`];
    const delta=pair.later_only_km2-pair.earlier_only_km2;
    $('series-change-title').textContent=Math.abs(delta)<.005?'No net change in predicted plume area':
      'Predicted plume '+(delta>0?'increased':'decreased')+' by '+format(Math.abs(delta))+' km²';
    $('series-change-description').textContent=earlier+' → '+later+' · Fixed comparison';
    $('series-change-instructions').textContent='Blue marks removed plume; orange marks added plume. Click a card to show or hide its map layer.';
    legend.append(layerCard('Removed plume','Predicted on '+earlier+' only',pair.earlier_only_km2,'#2a6f97','1'),
      layerCard('Added plume','Predicted on '+later+' only',pair.later_only_km2,'#ef8754','2'),
      layerCard('Unchanged plume','Predicted on both dates',pair.both_km2,'#d7ef90','3'));
    const change=new Uint8Array(data.width*data.height);
    for(let i=0;i<change.length;i++)change[i]=data.maps[low].plume[i]+2*data.maps[high].plume[i];
    replaceMap(2,high,change,'change');
  }
  function chart(id,field,unit,color){
    const values=data.rows.map(r=>r[field]),available=values.filter(v=>v!==null),largest=Math.max(...available,0);
    const raw=largest/4||.25,magnitude=10**Math.floor(Math.log10(raw));
    const step=[1,2,2.5,5,10].find(n=>n*magnitude>=raw)*magnitude;
    const max=Math.max(step,Math.ceil(largest/step)*step);
    const width=Math.max($(id).clientWidth,340),left=105,right=88,plot=width-left-right,top=24,rowHeight=52,axis=top+data.rows.length*rowHeight+8;
    const x=value=>left+value/max*plot;
    let html=`<svg viewBox="0 0 ${width} ${axis+44}" role="img" aria-label="${field==='plume_km2'?'Predicted plume area in square kilometres':'Rainfall in millimetres in the seven days before capture'}, one bar per acquisition">`;
    if(available.length)for(let n=0;n<=Math.round(max/step);n++){
      const value=n*step,xx=x(value),label=Number(value.toPrecision(5));
      html+=`<line x1="${xx}" x2="${xx}" y1="10" y2="${axis}" stroke="#e0edf3"/><text x="${xx}" y="${axis+23}" text-anchor="middle">${label}</text>`;
    }
    data.rows.forEach((r,i)=>{
      const y=top+i*rowHeight,value=values[i];
      html+=`<text x="${left-14}" y="${y+11}" text-anchor="end">${dateText(r.date,false)}</text><text class="series-chart-year" x="${left-14}" y="${y+27}" text-anchor="end">${r.date.slice(0,4)}</text>`;
      if(value===null)html+=`<text x="${left+8}" y="${y+19}">Unavailable</text>`;
      else{
        const digits=value>0&&value<.01?4:field==='plume_km2'?2:1;
        html+=`<rect x="${left}" y="${y}" width="${Math.max(value===0?0:2,x(value)-left)}" height="28" rx="5" fill="${color}"><title>${dateText(r.date)}: ${value.toFixed(digits)} ${unit}</title></rect><text class="series-chart-value" x="${x(value)+8}" y="${y+19}">${value.toFixed(digits)} ${unit}</text>`;
      }
    });
    html+='</svg>';$(id).innerHTML=html;
  }
  function charts(){chart('series-area-chart','plume_km2','km²','#014f86');chart('series-rain-chart','rainfall_7d_mm','mm','#61a5c2');}
  new ResizeObserver(()=>{if(data)charts();}).observe($('series-area-chart'));
  function table(){
    const table=el('table');table.className='series-data-table';
    const head=el('thead'),tr=el('tr');['Acquisition','Source file','Plume (km²)','Previous 7 days (mm)','Weather status'].forEach(t=>{const th=el('th',t);th.scope='col';tr.append(th);});head.append(tr);table.append(head);
    const body=el('tbody');data.rows.forEach(row=>{
      const tr=el('tr');[dateText(row.date),row.name,format(row.plume_km2),row.rainfall_7d_mm===null?'Unavailable':row.rainfall_7d_mm.toFixed(1),row.weather_error||'Available'].forEach(t=>tr.append(el('td',t)));body.append(tr);
    });table.append(body);$('series-table').replaceChildren(table);
  }
  function install(value){
    const firstDisplay=!data,previousLeft=$('series-left-date').value,previousRight=$('series-right-date').value;
    stop();data=value;$('series-results').hidden=!data;if(!data){$('series-change-section').open=false;return;}
    data.valid=decode(data.valid);data.frequency=decode(data.frequency);data.maps.forEach(m=>m.plume=decode(m.plume));
    if(firstDisplay){visibleChanges={1:true,2:true,3:false};analysisPair=[0,data.rows.length-1];$('series-change-section').open=false;$('series-footprint-mode').value='pair';}
    $('series-observations').replaceChildren();
    $('series-observations').style.setProperty('--observation-count',data.rows.length);
    data.rows.forEach((r,i)=>{
      const button=el('button');button.type='button';button.className='series-observation';
      const img=el('img');img.src=data.maps[i].rgb;img.alt='Sentinel-2 preview '+dateText(r.date);
      const info=el('div',undefined,'series-observation-info');
      info.append(el('strong',dateText(r.date)),el('span','Predicted plume','series-observation-label'),el('span',format(r.plume_km2)+' km²','series-observation-area'),el('span','View image →','series-observation-state'));
      button.append(img,info);
      button.addEventListener('click',()=>{stop();$('series-right-date').value=String(i);paintMaps();$('series-comparison-heading').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});});
      $('series-observations').append(button);
    });
    ['series-left-date','series-right-date'].forEach((id,j)=>{
      $(id).replaceChildren();data.rows.forEach((r,i)=>{const option=el('option',dateText(r.date));option.value=i;$(id).append(option);});
      $(id).value=firstDisplay?(j===0?'0':String(data.rows.length-1)):(j===0?previousLeft:previousRight);
    });
    $('series-coverage-note').textContent='Areas use '+format(data.shared_km2)+' km² valid on every date ('+data.coverage_percent.toFixed(1)+'% of the geographic overlap). Model: '+({rf:'Random Forest',unet:'U-Net',svm:'SVM'}[data.model])+'. Fixed score filter: '+Math.round(data.threshold*100)+'%. Adding a cloudy image can reduce this shared area.';
    charts();table();initMaps();
    requestAnimationFrame(()=>{syncing=true;maps.slice(0,2).forEach(map=>map.invalidateSize());maps[1].fitBounds(data.bounds,{padding:[12,12],animate:false});[maps[0],maps[2]].forEach(map=>map.setView(maps[1].getCenter(),maps[1].getZoom(),{animate:false}));syncing=false;paintMaps();paintAnalysis();if(firstDisplay)$('series-results').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});});
    $('series_retry_weather').hidden=data.rows.every(r=>r.weather!==null);
  }
  ['series-left-date','series-right-date','series-show-plume'].forEach(id=>$(id).addEventListener('change',()=>{stop();paintMaps();}));
  $('series-footprint-mode').addEventListener('change',paintAnalysis);
  $('series-compare').addEventListener('click',()=>{
    if(!data)return;stop();
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);if(a===b)return;
    analysisPair=[Math.min(a,b),Math.max(a,b)];visibleChanges={1:true,2:true,3:false};$('series-footprint-mode').value='pair';$('series-change-section').open=true;
    paintAnalysis();requestAnimationFrame(()=>{maps[2].invalidateSize();maps[2].setView(maps[0].getCenter(),maps[0].getZoom(),{animate:false});});
    $('series-change-section').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  });
  $('series-change-section').addEventListener('toggle',()=>{if(data&&$('series-change-section').open){maps[2].invalidateSize();maps[2].setView(maps[0].getCenter(),maps[0].getZoom(),{animate:false});}});
  $('series-play').addEventListener('click',()=>{
    if(timer){stop();return;}if(!data)return;
    $('series-play').textContent='Pause';$('series-play').setAttribute('aria-pressed','true');
    timer=setInterval(()=>{$('series-right-date').value=String((Number($('series-right-date').value)+1)%data.rows.length);paintMaps();},1800);imageLabels();
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  Shiny.addCustomMessageHandler('series-result',install);
  Shiny.addCustomMessageHandler('series-progress',text=>{$('series_status').textContent=text;});
  Shiny.addCustomMessageHandler('series-controls',state=>{
    document.querySelectorAll('.series-setup input,.series-setup select,.series-setup button').forEach(e=>e.disabled=state.busy);
    const scoreSlider=jQuery('#series_threshold').data('ionRangeSlider');
    if(scoreSlider){scoreSlider.update({disable:state.busy});scoreGuide(scoreSlider.result.from);}
    $('series_run').disabled=state.busy||!state.ready;
    $('series_retry_weather').disabled=state.busy||!data||data.rows.every(r=>r.weather!==null);
    $('series-results').classList.toggle('series-busy',state.busy);
  });
});
