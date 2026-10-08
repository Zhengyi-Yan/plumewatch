/* All quantities come from native-grid server calculations; maps are previews. */
document.addEventListener('DOMContentLoaded',()=>{
  let data=null, maps=[], layers=[], timer=null, syncing=false;
  const $=id=>document.getElementById(id);
  const names={rf:'Random Forest',unet:'U-Net',svm:'SVM'};
  const decode=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
  const format=value=>Number(value).toFixed(2);
  function el(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
  function stop(){if(timer)clearInterval(timer);timer=null;$('series-play').textContent='Play sequence';}
  function initMaps(){
    if(maps.length)return;
    ['series-left-map','series-right-map','series-change-map'].forEach(id=>{
      const map=L.map(id,{zoomControl:false,zoomSnap:.1,maxZoom:19,minZoom:2});
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
      L.control.zoom({position:'topright'}).addTo(map);L.control.scale({imperial:false}).addTo(map);
      maps.push(map);layers.push([]);
      new ResizeObserver(()=>map.invalidateSize()).observe($(id));
      map.on('moveend',()=>{
        if(syncing||!data)return;
        syncing=true;
        maps.filter(other=>other!==map).forEach(other=>{
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
    const colors=kind==='change'?{1:[42,111,151,220],2:[239,135,84,220],3:[137,194,217,220]}:{1:[169,214,229,205]};
    if(kind==='frequency')for(let n=1;n<=data.rows.length;n++){const t=(n-1)/(data.rows.length-1);colors[n]=[Math.round(169-168*t),Math.round(214-141*t),Math.round(229-105*t),220];}
    for(let i=0;i<mask.length;i++){if(data.valid[i]&&colors[mask[i]])image.data.set(colors[mask[i]],i*4);}
    context.putImageData(image,0,0);return canvas.toDataURL('image/png');
  }
  function paint(){
    if(!data)return;
    const a=Number($('series-left-date').value),b=Number($('series-right-date').value);
    [a,b].forEach((index,j)=>{
      layers[j].forEach(layer=>maps[j].removeLayer(layer));layers[j]=[];
      layers[j].push(L.imageOverlay(data.maps[index].rgb,data.bounds,{alt:'Sentinel-2 '+data.rows[index].date}).addTo(maps[j]));
      if($('series-show-plume').checked)layers[j].push(L.imageOverlay(overlay(data.maps[index].plume),data.bounds,{alt:'Predicted plume footprint'}).addTo(maps[j]));
    });
    layers[2].forEach(layer=>maps[2].removeLayer(layer));layers[2]=[];
    const low=Math.min(a,b),high=Math.max(a,b);
    layers[2].push(L.imageOverlay(data.maps[high].rgb,data.bounds,{alt:'Later observation'}).addTo(maps[2]));
    const stats=$('series-change-stats');stats.replaceChildren();
    const legend=$('series-footprint-legend');legend.replaceChildren();
    if($('series-footprint-mode').value==='frequency'){
      layers[2].push(L.imageOverlay(overlay(data.frequency,'frequency'),data.bounds,{alt:'Number of dates classified as plume'}).addTo(maps[2]));
      legend.append(el('span','Light blue: 1 date · dark blue: all '+data.rows.length+' dates'));
      const any=Object.entries(data.frequency_km2).filter(([n])=>Number(n)>0).reduce((sum,[n,v])=>sum+v,0);
      stats.append(el('p','All '+data.rows.length+' acquisitions'));
      [['Plume on at least one date',any],['Plume on every date',data.frequency_km2[String(data.rows.length)]]].forEach(([label,value])=>{const block=el('div');block.append(el('span',label),el('strong',format(value)+' km²'));stats.append(block);});
      return;
    }
    [['Earlier only','earlier'],['Later only','later'],['Both dates','both']].forEach(([text,cls])=>legend.append(el('span',text,'series-key '+cls)));
    if(a===b){stats.append(el('p','Select two different dates to see change.'));return;}
    const change=new Uint8Array(data.width*data.height);
    for(let i=0;i<change.length;i++)change[i]=data.maps[low].plume[i]+2*data.maps[high].plume[i];
    layers[2].push(L.imageOverlay(overlay(change,'change'),data.bounds,{alt:'Earlier only, later only and shared plume classifications'}).addTo(maps[2]));
    const pair=data.pairs[`${low}-${high}`];
    stats.append(el('p',`${data.rows[low].date} → ${data.rows[high].date}`));
    [['Earlier only',pair.earlier_only_km2],['Later only',pair.later_only_km2],['Both dates',pair.both_km2]].forEach(([label,value])=>{
      const block=el('div');block.append(el('span',label),el('strong',`${format(value)} km²`));stats.append(block);
    });
  }
  function chart(id,field,unit,color){
    const rows=data.rows,values=rows.map(r=>r[field]);
    const dates=rows.map(r=>Date.parse(r.date+'T00:00:00Z'));
    const start=Math.min(...dates),span=Math.max(...dates)-start||1;
    const max=Math.max(...values.filter(v=>v!==null),1)*1.15;
    const width=Math.max($(id).clientWidth,240);
    const x=i=>48+(dates[i]-start)/span*(width-72),y=v=>176-v/max*130;
    let html=`<svg viewBox="0 0 ${width} 245" role="img" aria-label="${field==='plume_km2'?'Mapped plume extent':'Seven-day preceding rainfall'} by acquisition date">`;
    [0,.5,1].forEach(t=>{const yy=y(max*t);html+=`<line x1="48" x2="${width-12}" y1="${yy}" y2="${yy}" stroke="#d8ebf2"/><text x="38" y="${yy+4}" text-anchor="end">${(max*t).toFixed(1)}</text>`;});
    html+=`<text x="48" y="24">${unit}</text>`;
    rows.forEach((r,i)=>{
      if(values[i]===null){html+=`<text x="${x(i)}" y="160" text-anchor="middle">N/A</text>`;}
      else if(field==='plume_km2'){html+=`<circle cx="${x(i)}" cy="${y(values[i])}" r="6" fill="${color}"><title>${r.date}: ${format(values[i])} ${unit}</title></circle>`;}
      else{html+=`<rect x="${x(i)-9}" y="${y(values[i])}" width="18" height="${176-y(values[i])}" rx="4" fill="${color}"><title>${r.date}: ${values[i].toFixed(1)} ${unit}</title></rect>`;}
      if(i===0||i===rows.length-1||((x(i)-x(i-1)>65)&&(x(rows.length-1)-x(i)>65))) html+=`<text x="${x(i)}" y="209" text-anchor="middle">${r.date.slice(5)}</text><text x="${x(i)}" y="225" text-anchor="middle">${r.date.slice(0,4)}</text>`;
    });
    html+='</svg>';$(id).innerHTML=html;
  }
  new ResizeObserver(()=>{if(data){chart('series-area-chart','plume_km2','km²','#014f86');chart('series-rain-chart','rainfall_7d_mm','mm','#61a5c2');}}).observe($('series-area-chart'));
  function table(){
    const table=el('table');table.className='series-data-table';
    const head=el('thead'),tr=el('tr');['Acquisition','Source file','Plume (km²)','Previous 7 days (mm)','Weather status'].forEach(t=>{const th=el('th',t);th.scope='col';tr.append(th);});head.append(tr);table.append(head);
    const body=el('tbody');data.rows.forEach(row=>{
      const tr=el('tr');[row.date,row.name,format(row.plume_km2),row.rainfall_7d_mm===null?'Unavailable':row.rainfall_7d_mm.toFixed(1),row.weather_error||'Available'].forEach(t=>tr.append(el('td',t)));body.append(tr);
    });table.append(body);$('series-table').replaceChildren(table);
  }
  function install(value){
    const firstDisplay=!data;stop();data=value;$('series-results').hidden=!data;if(!data)return;
    data.valid=decode(data.valid);data.frequency=decode(data.frequency);data.maps.forEach(m=>m.plume=decode(m.plume));
    $('series-summary').replaceChildren();
    const facts=[names[data.model],`${data.rows.length} observations`,`${format(data.shared_km2)} km² comparable`,`${data.coverage_percent.toFixed(1)}% of overlap valid`,`${Math.round(data.threshold*100)}% score filter`];
    facts.forEach(t=>$('series-summary').append(el('span',t)));
    $('series-observations').replaceChildren();
    data.rows.forEach((r,i)=>{
      const button=el('button');button.type='button';button.className='series-observation';
      const img=el('img');img.src=data.maps[i].rgb;img.alt='Observation '+r.date;
      button.append(img,el('strong',r.date),el('span',format(r.plume_km2)+' km²'));
      button.addEventListener('click',()=>{stop();$('series-right-date').value=String(i);paint();});$('series-observations').append(button);
    });
    ['series-left-date','series-right-date'].forEach((id,j)=>{
      $(id).replaceChildren();data.rows.forEach((r,i)=>{const option=el('option',r.date);option.value=i;$(id).append(option);});$(id).value=j===0?'0':String(data.rows.length-1);
    });
    chart('series-area-chart','plume_km2','km²','#014f86');chart('series-rain-chart','rainfall_7d_mm','mm','#61a5c2');table();initMaps();
    requestAnimationFrame(()=>{maps.forEach(map=>{map.invalidateSize();map.fitBounds(data.bounds,{padding:[12,12],animate:false});});paint();if(firstDisplay)$('series-results').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});});
    $('series_retry_weather').disabled=data.rows.every(r=>r.weather!==null);
  }
  ['series-left-date','series-right-date','series-show-plume','series-footprint-mode'].forEach(id=>$(id).addEventListener('change',()=>{stop();paint();}));
  $('series-play').addEventListener('click',()=>{
    if(timer){stop();return;}if(!data)return;
    $('series-play').textContent='Pause';timer=setInterval(()=>{$('series-right-date').value=String((Number($('series-right-date').value)+1)%data.rows.length);paint();},1400);
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
