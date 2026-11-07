'use strict';
(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  async function getJSON(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'X-CSRF-Token':csrf, ...(options.headers || {})}});
    let body;
    try { body = await response.json(); }
    catch {
      const error = new Error(response.redirected ? 'La sesión venció. Volvé a iniciar sesión.' : 'El servidor no devolvió una actualización válida.');
      error.status = response.redirected ? 401 : response.status;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(body.error?.message || 'No se pudo completar la solicitud.');
      error.status = response.status;
      error.requestId = body.error?.request_id || response.headers.get('X-Request-ID');
      throw error;
    }
    return body;
  }
  const monitor = document.getElementById('job-monitor');
  if (monitor) {
    const labels = {queued:'En cola',running:'En curso',done:'Finalizado',failed:'Falló',cancelled:'Cancelado'};
    const workerLabels = {created:'Todavía no iniciado',blocked:'Bloqueado por una comprobación',disabled:'Deshabilitado',starting:'Iniciando',idle:'Disponible',running:'Procesando',waiting:'Esperando',waiting_for_lease:'Esperando el bloqueo del proceso anterior',stopped:'Detenido'};
    const date = new Intl.DateTimeFormat('es-UY', {dateStyle:'short',timeStyle:'medium',timeZone:'America/Montevideo'});
    const text = (id, value) => { const node=document.getElementById(id); if(node)node.textContent=String(value ?? '—'); };
    const when = (value) => value && Number.isFinite(Number(value)) ? date.format(new Date(Number(value)*1000)) : 'Sin registro';
    const connection = document.getElementById('monitor-connection');
    const refreshButton = document.getElementById('monitor-refresh');
    let timer, ticker, timeout, controller, inFlight=false, disposed=false;
    let failures=0, lastUpdated=0, lastJob=null, retryDeadline=0, historySignature='', requestSequence=0;
    function history(events) {
      const list=document.getElementById('job-events');
      if(!list || !Array.isArray(events))return;
      const signature=JSON.stringify(events);
      if(signature===historySignature)return;
      historySignature=signature;
      const items=events.map(item=>{
        const li=document.createElement('li');
        const heading=document.createElement('strong');
        heading.textContent=item.message || item.event || 'Evento registrado';
        const meta=document.createElement('small');
        meta.textContent=`${when(item.at || item.created_at)} · intento ${item.attempt ?? '—'}${item.stage ? ' · '+item.stage : ''}${item.code ? ' · '+item.code : ''}`;
        li.append(heading,meta);
        if(item.action){const p=document.createElement('p');p.textContent=item.action;li.append(p);}
        if(item.boot_id){const small=document.createElement('small');small.textContent='Arranque: '+item.boot_id;li.append(small);}
        if(item.details && Object.keys(item.details).length){
          const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Detalles técnicos';
          const pre=document.createElement('pre');pre.className='technical';pre.textContent=JSON.stringify(item.details,null,2);
          details.append(summary,pre);li.append(details);
        }
        return li;
      });
      if(!items.length){const li=document.createElement('li');li.textContent='Todavía no hay eventos registrados para este trabajo.';items.push(li);}
      list.replaceChildren(...items);
    }
    function waiting() {
      if(!lastJob)return;
      const worker=lastJob.worker || {};
      let message='';
      if(lastJob.status==='queued'){
        if(worker.state==='blocked')message='La instalación está bloqueada. Revisá la causa y la acción indicada antes de continuar.';
        else if(worker.enabled===false)message='El procesador de trabajos está deshabilitado; la cola no avanzará.';
        else if(worker.alive===false)message='El procesador de trabajos no está activo. Revisá el diagnóstico de la instalación.';
        else if(worker.state==='waiting_for_lease' && worker.blocking_job)message='Otro proceso conserva un trabajo hasta '+when(worker.blocking_job.lease_until)+'. El procesador lo revisará automáticamente al vencer ese bloqueo.';
        else if(retryDeadline>Date.now())message=`Próximo intento dentro de ${Math.max(1,Math.ceil((retryDeadline-Date.now())/1000))} s.`;
        else if(worker.current_job && worker.current_job!==lastJob.id)message='En espera: el procesador está ejecutando otro trabajo.';
        else message='Esperando asignación del procesador de trabajos.';
      } else if(lastJob.status==='running')message='El trabajo está en ejecución. Su etapa y último pulso aparecen abajo.';
      else if(lastJob.status==='failed')message='El trabajo se detuvo. Revisá la causa, la acción recomendada y el historial de intentos.';
      text('job-wait',message);
    }
    function update(job) {
      lastJob=job;
      monitor.dataset.status=job.status;
      retryDeadline=Date.now()+Math.max(0,Number(job.retry_in_seconds || 0))*1000;
      text('job-message',job.message || labels[job.status] || job.status);
      const status=document.getElementById('job-status');
      status.textContent=labels[job.status] || job.status;
      status.className='status status-'+(Object.hasOwn(labels,job.status) ? job.status : 'queued');
      const progress=document.getElementById('job-progress');
      const total=Number(job.total || 0);
      if(total>0){progress.max=total;progress.value=Math.max(0,Number(job.progress || 0));text('job-count',`${job.progress || 0} / ${total}`);}
      else {
        progress.removeAttribute('value');progress.removeAttribute('max');
        text('job-count',job.status==='done' ? 'Trabajo completado.' : job.status==='failed' ? 'El intento terminó sin un total calculado.' : job.status==='cancelled' ? 'El trabajo fue cancelado.' : 'Avance por etapas; todavía no hay un total calculado.');
      }
      progress.hidden=total<=0 && ['done','failed','cancelled'].includes(job.status);
      text('job-attempt',`${job.attempts || 0} / ${job.max_attempts || 3}`);
      text('job-stage',job.stage || 'Pendiente de asignar');
      text('job-code',job.error_code || 'Sin error registrado');
      text('job-heartbeat',when(job.heartbeat_at));
      text('job-last-attempt',when(job.last_attempt_at));
      text('job-boot',job.boot_id || 'Todavía no asignado');
      const worker=job.worker || {};
      text('job-worker',worker.enabled===false ? 'Deshabilitado' : workerLabels[worker.state] || worker.state || 'Sin información');
      text('job-worker-message',worker.last_error?.message || '');
      const cause=document.getElementById('job-cause');
      const showCause=!['done','cancelled'].includes(job.status) && Boolean(job.error || job.error_code || worker.last_error?.code);
      cause.hidden=!showCause;
      text('job-error-context',job.status==='failed' ? 'Causa del fallo' : 'Condición pendiente o fallo del intento anterior');
      text('job-error',job.error || worker.last_error?.message || (job.error_code ? 'Código: '+job.error_code : ''));
      text('job-action',job.action || worker.last_error?.action || 'Revisá el diagnóstico y los eventos antes de reintentar.');
      document.getElementById('job-cancel-form')?.toggleAttribute('hidden',!['queued','running'].includes(job.status) || job.kind==='delete');
      document.getElementById('job-retry-form')?.toggleAttribute('hidden',!['failed','cancelled'].includes(job.status));
      const installation=job.installation || {};
      text('job-installation-message',installation.message || 'Consultá el diagnóstico completo de la instalación.');
      text('job-report',installation.report_id || 'Sin informe');
      const result=document.getElementById('job-result');
      const resultSection=document.getElementById('job-result-section');
      if(job.result_json){
        let value=job.result_json;
        try{if(typeof value==='string')value=JSON.parse(value);}catch{/* Keep the recorded text without interpreting markup. */}
        result.textContent=typeof value==='string' ? value : JSON.stringify(value,null,2);resultSection.hidden=false;
      }else resultSection.hidden=true;
      history(job.events || []);waiting();
    }
    function schedule(delay) {
      clearTimeout(timer);
      if(!disposed)timer=setTimeout(refresh,delay);
    }
    async function refresh() {
      if(disposed || inFlight)return;
      clearTimeout(timer);inFlight=true;refreshButton.disabled=true;
      const sequence=++requestSequence;
      const requestController=new AbortController();controller=requestController;
      const requestTimeout=setTimeout(()=>requestController.abort(),15000);timeout=requestTimeout;
      try {
        const job=await getJSON(monitor.dataset.statusUrl,{signal:requestController.signal});
        if(disposed || sequence!==requestSequence)return;
        update(job);failures=0;lastUpdated=Date.now();
        connection.textContent='Última actualización: '+date.format(new Date(lastUpdated))+'.';
        connection.classList.remove('operational-stale');
        if(['queued','running'].includes(job.status))schedule(2500);
        else if(job.status==='failed')schedule(15000);
      } catch(error) {
        if(disposed || sequence!==requestSequence)return;
        failures++;
        const delay=Math.min(30000,2500*2**Math.min(failures,4));
        const previous=lastUpdated ? ' El estado mostrado es de '+date.format(new Date(lastUpdated))+'.' : ' Se conserva el estado recibido al abrir la página.';
        const reason=error.name==='AbortError' ? 'La actualización demoró demasiado.' : error.message;
        connection.textContent=reason+previous+(error.status===401 || error.status===403 ? ' Volvé a iniciar sesión para continuar.' : ` Volveremos a consultar en ${Math.round(delay/1000)} s.`)+(error.requestId ? ' Solicitud: '+error.requestId : '');
        connection.classList.add('operational-stale');
        if(error.status!==401 && error.status!==403)schedule(delay);
      } finally {
        clearTimeout(requestTimeout);
        if(sequence===requestSequence){inFlight=false;refreshButton.disabled=false;}
      }
    }
    function start(){disposed=false;clearInterval(ticker);ticker=setInterval(waiting,1000);refresh();}
    refreshButton.addEventListener('click',()=>{failures=0;refresh();});
    window.addEventListener('pagehide',()=>{disposed=true;requestSequence++;inFlight=false;clearTimeout(timer);clearTimeout(timeout);clearInterval(ticker);controller?.abort();});
    window.addEventListener('pageshow',event=>{if(event.persisted)start();});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden && !disposed)refresh();});
    start();
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
