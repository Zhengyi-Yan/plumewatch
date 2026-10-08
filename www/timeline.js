/* Metrics are calculated on the native grid; map images are previews. */
document.addEventListener('DOMContentLoaded',()=>{
  let data=null, maps=[], layers=[], timer=null, syncing=false, analysisPair=[0,1];
  const $=id=>document.getElementById(id);
  const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
  const format=value=>Number(value).toFixed(2);
  const dateText=(date,year=true)=>new Date(date+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'short',...(year?{year:'numeric'}:{}),timeZone:'UTC'});
  const plume=[215,239,144]; // Same visible-plume colour as the classification page.
  function el(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
  function stop(){if(timer)clearInterval(timer);timer=null;$('series-play').textContent='Play dates';$('series-play').setAttribute('aria-pressed','false');}
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
    for(let i=0;i<mask.length;i++)if(data.valid[i]&&colors[mask[i]])image.data.set(colors[mask[i]],i*4);
    context.putImageData(image,0,0);return canvas.toDataURL('image/png');
  }
  function replaceMap(j,index,mask,kind){
    layers[j].forEach(layer=>maps[j].removeLayer(layer));layers[j]=[];
    layers[j].push(L.imageOverlay(data.maps[index].rgb,data.bounds,{alt:'Sentinel-2 '+data.rows[index].date}).addTo(maps[j]));
    if(mask)layers[j].push(L.imageOverlay(overlay(mask,kind),data.bounds,{alt:kind==='change'?'Plume change between compared dates':kind==='frequency'?'Number of dates classified as plume':'Predicted plume footprint'}).addTo(maps[j]));
  }
  function paintMaps(){
    if(!data)return;
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);
    [a,b].forEach((index,j)=>replaceMap(j,index,$('series-show-plume').checked?data.maps[index].plume:null));
    [...$('series-observations').children].forEach((button,i)=>{
      button.classList.toggle('selected',i===b);button.setAttribute('aria-pressed',String(i===b));
      button.querySelector('.series-observation-state').textContent=i===a?(i===b?'Reference · Viewing':'Reference'):i===b?'Viewing':'View image →';
    });
    $('series-compare').disabled=a===b;
    $('series-compare-feedback').textContent=a===b?'Choose a different viewing date to compare changes.':'';
  }
  function legendKey(text,color){const key=el('span',text,'series-key');key.style.setProperty('--key-color',color);return key;}
  function paintAnalysis(){
    if(!data)return;
    const stats=$('series-change-stats'),legend=$('series-footprint-legend');stats.replaceChildren();legend.replaceChildren();
    if($('series-footprint-mode').value==='frequency'){
      replaceMap(2,data.rows.length-1,data.frequency,'frequency');
      $('series-change-description').textContent='Each colour shows how many of the '+data.rows.length+' uploaded dates that pixel was predicted as plume.';
      for(let n=1;n<=data.rows.length;n++){
        const t=(n-1)/(data.rows.length-1),color=n===data.rows.length?'#d7ef90':`rgb(${Math.round(169-168*t)},${Math.round(214-141*t)},${Math.round(229-105*t)})`;
        legend.append(legendKey(n+' of '+data.rows.length+' dates',color));
      }
      const any=Object.entries(data.frequency_km2).filter(([n])=>Number(n)>0).reduce((sum,[,v])=>sum+v,0);
      [['Plume on at least one date',any],['Plume on every date',data.frequency_km2[String(data.rows.length)]]].forEach(([label,value])=>{const block=el('div');block.append(el('span',label),el('strong',format(value)+' km²'));stats.append(block);});
      return;
    }
    const [low,high]=analysisPair,earlier=dateText(data.rows[low].date),later=dateText(data.rows[high].date);
    $('series-change-description').textContent=earlier+' compared with '+later+'. This comparison stays fixed until you click “Compare these dates” again.';
    legend.append(legendKey('Only '+dateText(data.rows[low].date),'#2a6f97'),legendKey('Only '+dateText(data.rows[high].date),'#ef8754'),legendKey('Plume on both dates','#d7ef90'));
    const change=new Uint8Array(data.width*data.height);
    for(let i=0;i<change.length;i++)change[i]=data.maps[low].plume[i]+2*data.maps[high].plume[i];
    replaceMap(2,high,change,'change');
    const pair=data.pairs[`${low}-${high}`];
    [['Only '+dateText(data.rows[low].date),pair.earlier_only_km2],['Only '+dateText(data.rows[high].date),pair.later_only_km2],['On both dates',pair.both_km2]].forEach(([label,value])=>{
      const block=el('div');block.append(el('span',label),el('strong',format(value)+' km²'));stats.append(block);
    });
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
    if(firstDisplay){analysisPair=[0,data.rows.length-1];$('series-change-section').open=false;$('series-footprint-mode').value='pair';}
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
    requestAnimationFrame(()=>{syncing=true;maps.slice(0,2).forEach(map=>{map.invalidateSize();map.fitBounds(data.bounds,{padding:[12,12],animate:false});});maps[2].setView(maps[0].getCenter(),maps[0].getZoom(),{animate:false});syncing=false;paintMaps();paintAnalysis();if(firstDisplay)$('series-results').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});});
    $('series_retry_weather').hidden=data.rows.every(r=>r.weather!==null);
  }
  ['series-left-date','series-right-date','series-show-plume'].forEach(id=>$(id).addEventListener('change',()=>{stop();paintMaps();}));
  $('series-footprint-mode').addEventListener('change',paintAnalysis);
  $('series-compare').addEventListener('click',()=>{
    if(!data)return;stop();
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);if(a===b)return;
    analysisPair=[Math.min(a,b),Math.max(a,b)];$('series-footprint-mode').value='pair';$('series-change-section').open=true;
    paintAnalysis();requestAnimationFrame(()=>{maps[2].invalidateSize();maps[2].setView(maps[0].getCenter(),maps[0].getZoom(),{animate:false});});
    $('series-change-section').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  });
  $('series-change-section').addEventListener('toggle',()=>{if(data&&$('series-change-section').open){maps[2].invalidateSize();maps[2].setView(maps[0].getCenter(),maps[0].getZoom(),{animate:false});}});
  $('series-play').addEventListener('click',()=>{
    if(timer){stop();return;}if(!data)return;
    $('series-play').textContent='Pause';$('series-play').setAttribute('aria-pressed','true');
    timer=setInterval(()=>{$('series-right-date').value=String((Number($('series-right-date').value)+1)%data.rows.length);paintMaps();},1800);
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
  Shiny.addCustomMessageHandler('series-result',install);
  Shiny.addCustomMessageHandler('series-progress',text=>{$('series_status').textContent=text;});
  Shiny.addCustomMessageHandler('series-controls',state=>{
    document.querySelectorAll('.series-setup input,.series-setup select,.series-setup button').forEach(e=>e.disabled=state.busy);
    $('series_run').disabled=state.busy||!state.ready;
    $('series_retry_weather').disabled=state.busy||!data||data.rows.every(r=>r.weather!==null);
    $('series-results').classList.toggle('series-busy',state.busy);
  });
});
