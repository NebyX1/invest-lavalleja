/* Driven by the opt-in Python test; uses only its isolated Flask/SQL instance. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const config=JSON.parse(await new Promise(resolve=>{
  let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>resolve(input));
}));
const engines=await import(pathToFileURL(config.playwright_module).href);
const {expect}=await import(pathToFileURL(path.join(path.dirname(config.playwright_module),'test.mjs')).href);
const profiles=[];
await fs.mkdir(config.artifacts,{recursive:true});
for(const name of ['chromium','webkit']){
  const browser=await engines[name].launch();
  try{
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    await context.addCookies([{name:'gianna_admin',value:config.cookie,url:config.origin+'/admin/'}]);
    const page=await context.newPage();const errors=[];let polls=0,holdNext=false,held=false,release;
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/admin/api/jobs/**',async route=>{
      polls++;
      if(polls===1)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'Fallo temporal de red de prueba.'}})});
      if(holdNext){holdNext=false;held=true;await new Promise(resolve=>release=resolve);try{return await route.continue();}catch{return;}}
      return route.continue();
    });
    const state=async value=>{const result=await fetch(config.origin+'/__isolated_monitor_test__/'+value,{method:'POST'});assert.equal(result.status,200);};
    await state('queued');
    await page.goto(config.origin+'/admin/jobs/'+config.job_id);
    await expect(page.locator('#monitor-connection')).toContainText('Volveremos a consultar');
    await expect(page.locator('#job-progress')).not.toHaveAttribute('value');
    await expect(page.locator('#monitor-connection')).toContainText('Última actualización',{timeout:12000});
    assert.ok(polls>=2,'Polling must resume automatically after the failed fetch');
    await state('failed');await page.locator('#monitor-refresh').click();
    await expect(page.locator('#job-status')).toHaveText('Falló');
    await expect(page.locator('#job-retry-form')).toBeVisible();
    await expect(page.locator('#job-cancel-form')).toBeHidden();
    await expect(page.locator('#job-code')).toHaveText('storage_not_mounted');
    await expect(page.locator('#job-error')).toContainText('<img src=x');
    await expect(page.locator('#job-events')).toContainText('<script>');
    assert.equal(await page.evaluate(()=>globalThis.monitorXSS),undefined);
    assert.equal(await page.locator('#job-events script,#job-error img').count(),0);
    for(const width of [390,1280]){
      await page.setViewportSize({width,height:900});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await page.screenshot({path:path.join(config.artifacts,`${name}-job-${width}.png`),fullPage:true});
    }
    await state('running');
    if(name==='chromium')await expect(page.locator('#job-status')).toHaveText('En curso',{timeout:18000});
    else{await page.locator('#monitor-refresh').click();await expect(page.locator('#job-status')).toHaveText('En curso');}
    await expect(page.locator('#job-cancel-form')).toBeVisible();
    await expect(page.locator('#job-retry-form')).toBeHidden();
    await expect(page.locator('#job-progress')).toHaveAttribute('value','1');
    await state('done');await page.locator('#monitor-refresh').click();
    await expect(page.locator('#job-status')).toHaveText('Finalizado');
    await expect(page.locator('#job-result-section')).toBeVisible();
    await expect(page.locator('#job-result')).toContainText('"verified": true');
    const completedPolls=polls;await page.waitForTimeout(2800);assert.equal(polls,completedPolls,'Completed jobs must stop automatic polling');
    await state('queued');holdNext=true;const beforeRestore=polls;
    await page.locator('#monitor-refresh').click();
    await expect.poll(()=>held).toBe(true);
    await page.evaluate(()=>{
      window.dispatchEvent(new PageTransitionEvent('pagehide'));
      window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
    });
    await expect(page.locator('#monitor-refresh')).toBeEnabled();
    assert.equal(polls,beforeRestore+2,'Restoring a page must start exactly one new status request');
    release();
    await state('done');await page.locator('#monitor-refresh').click();
    await expect(page.locator('#job-status')).toHaveText('Finalizado');
    await page.goto(config.origin+'/admin/diagnostics');
    await expect(page.getByRole('heading',{name:'Diagnóstico de la instalación',exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Plan según el estado encontrado'})).toBeVisible();
    await page.setViewportSize({width:390,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(config.artifacts,`${name}-diagnostics-390.png`),fullPage:true});
    assert.deepEqual(errors,[]);
    profiles.push(name);
  }finally{await browser.close();}
}
const report={profiles,scenarios:['real Flask/SQL SSR','HTTP 503 polling resumed','unknown progress indeterminate','cause and attempts visible','XSS text escaped','dynamic cancel/retry actions','failed job automatically observed after recovery','terminal result and polling stopped','pagehide abort and pageshow resume without duplicate requests','390/1280 layouts'],provider_calls:0};
await fs.writeFile(path.join(config.artifacts,'browser-validation.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
