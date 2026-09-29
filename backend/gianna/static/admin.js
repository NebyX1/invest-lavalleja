'use strict';
(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  async function getJSON(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'X-CSRF-Token':csrf, ...(options.headers || {})}});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || 'No se pudo completar la solicitud.');
    return body;
  }
  const monitor = document.getElementById('job-monitor');
  if (monitor) {
    let timer;
    async function refresh() {
      try {
        const job = await getJSON(monitor.dataset.statusUrl);
        document.getElementById('job-message').textContent = job.message || 'En cola';
        document.getElementById('job-status').textContent = ({queued:'En cola',running:'En curso',done:'Finalizado',failed:'Falló',cancelled:'Cancelado'})[job.status] || job.status;
        const progress = document.getElementById('job-progress');
        progress.max = job.total || 1; progress.value = job.progress || 0;
        document.getElementById('job-count').textContent = `${job.progress} / ${job.total || 'Pendiente de calcular'}`;
        document.getElementById('job-error').textContent = job.error || '';
        if (['queued','running'].includes(job.status)) timer = setTimeout(refresh, 2500);
      } catch (error) { document.getElementById('job-error').textContent = error.message; }
    }
    refresh(); window.addEventListener('pagehide',()=>clearTimeout(timer));
  }
  document.querySelector('[data-models]')?.addEventListener('click',async(event)=>{
    const button=event.currentTarget;button.disabled=true;
    const status=document.getElementById('models-status');status.textContent='Consultando catálogo…';
    try {
      const result=await getJSON('/admin/api/models');const list=document.getElementById('model-list');list.replaceChildren();
      for(const model of result.models){const option=document.createElement('option');option.value=model;list.append(option);}
      status.textContent=`${result.models.length} modelos disponibles. Escribí o seleccioná el identificador exacto.`;
    } catch(error){status.textContent=error.message;} finally{button.disabled=false;}
  });
  document.querySelector('[data-diagnostics]')?.addEventListener('click',async(event)=>{
    const button=event.currentTarget;button.disabled=true;const out=document.getElementById('diagnostics-output');out.textContent='Comprobando…';
    try{out.textContent=JSON.stringify(await getJSON('/admin/api/diagnostics'),null,2);}catch(error){out.textContent=error.message;}finally{button.disabled=false;}
  });
  const plot=document.getElementById('chunk-plot');
  if(plot){
    getJSON(plot.dataset.pointsUrl).then(({points})=>{
      plot.replaceChildren();const ns='http://www.w3.org/2000/svg';
      if(!points.length){const text=document.createElementNS(ns,'text');text.setAttribute('x','30');text.setAttribute('y','40');text.textContent='La proyección aparece cuando termina la indexación.';plot.append(text);return;}
      const topics=[...new Set(points.map(p=>p.topic))];const legend=document.getElementById('plot-legend');
      topics.forEach((topic,index)=>{const el=document.createElement('span');el.className=`theme-${index%8}`;el.textContent=topic;legend.append(el);});
      points.forEach(point=>{
        const c=document.createElementNS(ns,'circle');c.setAttribute('cx',String(450+Number(point.x)*410));c.setAttribute('cy',String(195+Number(point.y)*160));c.setAttribute('r','5');c.setAttribute('class',`theme-${topics.indexOf(point.topic)%8}`);c.setAttribute('tabindex','0');c.setAttribute('role','button');c.setAttribute('aria-label',`${point.title}, ${point.topic}, ${point.token_count} tokens`);
        const title=document.createElementNS(ns,'title');title.textContent=`${point.title} · ${point.topic}`;c.append(title);
        const select=()=>{document.getElementById('plot-selection').textContent=`${point.title} | ${point.topic} | ${point.token_count} tokens | registro ${point.record_key}`;};
        c.addEventListener('click',select);c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}});plot.append(c);
      });
    }).catch(error=>{document.getElementById('plot-selection').textContent=error.message;});
  }
})();
