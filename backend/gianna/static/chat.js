'use strict';
(() => {
  const form=document.getElementById('chat-form'), field=document.getElementById('question'), send=document.getElementById('send-chat');
  const messages=document.getElementById('messages'), status=document.getElementById('chat-status'), forget=document.getElementById('forget-chat');
  const captchaBox=document.getElementById('chat-captcha'), captchaQuestion=document.getElementById('captcha-question');
  const captchaAnswer=document.getElementById('captcha-answer'), refreshCaptcha=document.getElementById('refresh-captcha');
  // Token is a short-lived anonymous capability, not the Ollama key. No durable browser history.
  let token=null, challenge=null, busy=false;
  async function api(path,options={}){
    const response=await fetch(path,{credentials:'omit',...options,headers:{'Content-Type':'application/json',...(token?{'Authorization':`Bearer ${token}`}:{})}});
    const body=await response.json();if(!response.ok){if(response.status===401)token=null;const error=new Error(body.error?.message || 'La solicitud no pudo completarse.');error.code=body.error?.code;throw error;}return body;
  }
  async function newChallenge(){
    challenge=await api('/api/captcha');captchaQuestion.textContent=challenge.question;
    captchaAnswer.value='';captchaBox.hidden=false;send.textContent='Verificar y enviar →';
    status.textContent='Resolvé la suma para iniciar la conversación.';captchaAnswer.focus();
  }
  function text(tag,content,cls){const el=document.createElement(tag);el.textContent=content;if(cls)el.className=cls;return el;}
  function bubble(role,content){const el=text('article',content,`bubble ${role}`);messages.append(el);return el;}
  function answer(result){
    const el=bubble('assistant','');el.append(text('p',result.answer,'answer-text'));
    for(const cite of result.citations || []){
      const details=document.createElement('details');details.className='chunk';details.append(text('summary',`[${cite.id}] ${cite.title}`));details.append(text('p',cite.excerpt,'answer-text'));details.append(text('small',`${cite.evidence_type} · corte ${cite.cutoff_date || 'no especificado'}`));
      for(const source of cite.sources || []){
        try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))continue;
          const link=text('a',`${source.id} · ${source.title} ↗`);link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';const p=document.createElement('p');p.append(link);details.append(p);
        }catch{/* Invalid URLs are not rendered. */}
      }el.append(details);
    }
    const feedback=document.createElement('div');feedback.className='feedback';
    [[1,'Me resultó útil'],[-1,'Necesita mejorar']].forEach(([value,label])=>{
      const button=text('button',label);button.type='button';button.addEventListener('click',async()=>{
        try{await api(`/api/feedback/${encodeURIComponent(result.id)}`,{method:'POST',body:JSON.stringify({value})});feedback.replaceChildren(text('small','Gracias. Tu valoración quedó registrada.'));}catch(error){status.textContent=error.message;}
      });feedback.append(button);
    });el.append(feedback);
  }
  form.addEventListener('submit',async(event)=>{
    event.preventDefault();if(busy)return;const question=field.value.trim();if(!question)return;
    busy=true;send.disabled=true;forget.disabled=true;
    let userBubble=null;
    try{
      if(!token){
        if(!challenge){await newChallenge();return;}
        const captchaId=challenge.id;challenge=null;
        try{token=(await api('/api/sessions',{method:'POST',body:JSON.stringify({captcha_id:captchaId,captcha_answer:captchaAnswer.value.trim()})})).token;}
        catch(error){
          if(error.code==='captcha_invalid'){await newChallenge();status.textContent=error.message+' Intentá con la nueva suma.';}
          else status.textContent=error.message;
          return;
        }
        captchaBox.hidden=true;send.textContent='Enviar →';
      }
      status.textContent='Buscando en la guía y preparando una respuesta con fuentes…';
      userBubble=bubble('user',question);field.value='';
      const result=await api('/api/chat',{method:'POST',body:JSON.stringify({message:question})});answer(result);status.textContent='';
    }catch(error){status.textContent=error.message;field.value=question;if(userBubble)userBubble.remove();}
    finally{busy=false;send.disabled=false;forget.disabled=false;if(token)field.focus();}
  });
  refreshCaptcha.addEventListener('click',async()=>{
    if(busy || token)return;
    busy=true;refreshCaptcha.disabled=true;
    try{await newChallenge();}catch(error){status.textContent=error.message;}
    finally{busy=false;refreshCaptcha.disabled=false;}
  });
  captchaAnswer.addEventListener('keydown',(event)=>{
    if(event.key==='Enter'){event.preventDefault();form.requestSubmit();}
  });
  forget.addEventListener('click',async()=>{
    if(busy)return;
    try{if(token)await api('/api/sessions/current',{method:'DELETE'});token=null;challenge=null;captchaBox.hidden=true;send.textContent='Enviar →';messages.replaceChildren();status.textContent='Conversación borrada. Podés comenzar otra.';}catch(error){status.textContent=error.message;}
  });
  api('/api/config').then(cfg=>{
    document.getElementById('chat-name').textContent=cfg.name;document.getElementById('greeting').textContent=cfg.greeting;document.getElementById('chat-notice').textContent=cfg.notice;
    if(!cfg.enabled || !cfg.available)status.textContent='Gianna todavía no tiene una base disponible o está pausada.';
  }).catch(error=>{status.textContent=error.message;});
})();
