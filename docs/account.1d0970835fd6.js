'use strict';
window.scoutAccount=(()=>{
 const cfg=window.SCOUT_ACCOUNT_CONFIG||{},validId=id=>typeof id==='string'&&/^[a-f0-9]{20}$/.test(id);
 let client=null,database=null,user=null,profile=null,activities=new Map(),jobMap=new Map(),ready=Promise.resolve(),generation=0,problem='',signInError='',writes=Promise.resolve(),started=false;
 const configured=cfg.enabled===true;
 let settled=false,guest=false,oauthBusy=false;
 try{guest=sessionStorage.getItem('job-scout-guest-v1')==='1';}catch{}
 const emit=reset=>window.dispatchEvent(new CustomEvent('scout-account-change',{detail:{reset:!!reset}}));
 const element=id=>document.getElementById(id);
 const message=text=>{if(element('account-message'))element('account-message').textContent=text;};
 function guestChoice(value){guest=value;try{if(value)sessionStorage.setItem('job-scout-guest-v1','1');else sessionStorage.removeItem('job-scout-guest-v1');}catch{}}
 function welcome(){guestChoice(false);if(element('account-menu'))element('account-menu').open=false;render();element('welcome-title')?.focus?.();}
 function render(){
  if(!element('account-entry'))return;
  const enabled=configured&&!!window.SCOUT_PUBLIC,showWelcome=enabled&&!user&&!guest;
  if(settled||user||!enabled)document.body?.classList?.remove('public-entry-loading');
  if(element('welcome-screen'))element('welcome-screen').hidden=!showWelcome;
  if(element('dashboard-shell'))element('dashboard-shell').hidden=showWelcome;
  if(element('account-controls'))element('account-controls').hidden=!enabled;
  element('account-entry').hidden=!enabled||!!user;
  element('account-entry').textContent='Sign in';element('account-entry').title='Sign in or create your Job Scout account';
  if(element('account-menu')){element('account-menu').hidden=!enabled||!user;if(!user)element('account-menu').open=false;}
  const name=user?.user_metadata?.full_name||user?.user_metadata?.name||user?.email||'Your account';
  if(element('account-name'))element('account-name').textContent=name;
  if(element('account-avatar'))element('account-avatar').textContent=Array.from(name.trim())[0]?.toUpperCase()||'U';
  if(element('account-menu-email'))element('account-menu-email').textContent=user?.email||'';
  element('account-member').hidden=!user;
  element('account-email').textContent=user?.email||'';
  element('account-provider-label').textContent=cfg.provider==='github'?'Continue with GitHub':'Continue with Google';
  element('account-provider').disabled=!client||!settled||oauthBusy;
  element('browse-guest').disabled=!settled;
  if(element('welcome-status'))element('welcome-status').textContent=oauthBusy?'Opening sign-in…':!settled&&enabled?'Checking your session…':'';
  if(element('welcome-error')){element('welcome-error').hidden=!(signInError||problem);element('welcome-error').textContent=signInError||problem;}
  element('account-sync-state').textContent=problem?'Sync needs attention':profile?'Account up to date':'Loading account…';
  element('account-problem').hidden=!(problem||signInError);element('account-problem-text').textContent=problem||signInError;
  element('account-retry').textContent=signInError?'Try sign-in':'Retry sync';
  element('account-import').disabled=!profile||!!problem;
  element('account-export').disabled=!profile||!!problem;
  const label=document.querySelector('.storage-help>summary'),note=document.querySelector('.local-note');
  if(label)label.textContent=user?'Saved to your account':'Saved in this browser';
  if(note)note.textContent=user?'Your saves, notes and viewed history sync to your account. Other users cannot see them.':'Your saves, viewed history and notes stay here. Clearing browser data removes them.';
 }
 async function value(request){const result=await request;if(result.error)throw new Error('Account storage could not sync. Please retry.');return result.data;}
 function databaseFor(session){const token=session.access_token;return window.supabase.createClient(cfg.url,cfg.publishableKey,{accessToken:async()=>token});}
 async function readActivity(db,id){
  const rows=[];
  for(let offset=0;offset<20000;offset+=1000){
   const batch=await value(db.from('scout_activity').select('*').eq('user_id',id).order('job_id').range(offset,offset+999));
   rows.push(...batch);if(batch.length<1000)break;
   if(offset===19000)throw new Error('This account has too much history to load at once. Export your data or contact the owner.');
  }
  return rows;
 }
 async function activate(session){
  const incoming=session?.user||null;
  if(incoming?.id&&incoming.id===user?.id&&profile&&!problem)return;
  const current=++generation;
  user=incoming;database=session?databaseFor(session):null;profile=null;activities=new Map();problem='';render();emit(true);
  if(user)signInError='';
  if(!user)return;
  try{
   const id=user.id,db=database;
   await value(db.from('scout_profiles').upsert({id},{onConflict:'id',ignoreDuplicates:true}));
   const p=await value(db.from('scout_profiles').select('*').eq('id',id).single());
   const rows=await readActivity(db,id);
   if(current!==generation)return;
   profile=p;activities=new Map(rows.map(row=>[row.job_id,row]));
  }catch(e){if(current===generation)problem=e.message;}
  if(current===generation){render();emit(false);}
 }
 function start(){
  if(started)return ready;started=true;
  if(!configured){document.addEventListener('DOMContentLoaded',render);return ready;}
  ready=(async()=>{
   try{
    if(!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(cfg.url)||!cfg.publishableKey||cfg.publishableKey.startsWith('sb_secret_'))throw new Error('Account sign-in has not been configured correctly.');
    if(!['google','github'].includes(cfg.provider))throw new Error('Unsupported sign-in provider.');
    const callback=new URL(location.href),fragment=new URLSearchParams(callback.hash.slice(1));
    if(callback.searchParams.has('error')||fragment.has('error')){
     signInError='Sign-in could not finish. Try again; if it repeats, the app owner needs to check the sign-in configuration.';
     for(const key of ['error','error_code','error_description','code','sb'])callback.searchParams.delete(key);
     if(fragment.has('error'))callback.hash='';
     window.history?.replaceState(null,'',callback.pathname+callback.search+callback.hash);
    }
    client=window.supabase.createClient(cfg.url,cfg.publishableKey,{auth:{flowType:'pkce',persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
    const result=await client.auth.getSession();if(result.error)throw new Error('Your sign-in session could not be restored. Try signing in again.');
    await activate(result.data.session);
    client.auth.onAuthStateChange((event,session)=>{
     if(event==='SIGNED_OUT'){guestChoice(false);element('account-dialog')?.close?.();}
     if(session?.user?.id===user?.id&&profile&&!problem){database=databaseFor(session);return;}
     // Invalidate old-account writes synchronously; perform DB reads outside Auth's lock.
     generation++;user=session?.user||null;database=null;profile=null;activities=new Map();problem='';render();emit(true);
     setTimeout(()=>{ready=activate(session);},0);
    });
   }catch(e){problem=e.message;}
   finally{settled=true;render();}
  })();
  return ready;
 }
 function compactJob(j){
  if(!j)return {};
  const out={};for(const key of ['id','company','title','url','application_url','location','category','published','first_seen','salary'])if(j[key]!=null)out[key]=String(j[key]).slice(0,key==='location'?1000:1200);
  return out;
 }
 function overlay(jobs){
  jobMap=new Map(jobs.map(j=>[j.id,j]));
  if(!user)return jobs;
  const result=jobs.map(j=>({...j,state:activities.get(j.id)?.status||'new',notes:activities.get(j.id)?.notes||''}));
  for(const row of activities.values()){
   if(jobMap.has(row.job_id)||row.status==='new'&&!row.notes)continue;
   const s=row.job_snapshot||{};
   const archived={id:row.job_id,company:s.company||'Employer not in current collection',title:s.title||'Saved opportunity',url:s.url||'',application_url:s.application_url||s.url||'',location:s.location||'Not supplied',category:s.category||'Product design',published:s.published||null,first_seen:s.first_seen||row.updated_at,salary:s.salary||'',state:row.status,notes:row.notes,priority:'archive',attention_rank:0,description:'This job is no longer present in the published collection. Your personal history is retained; check the employer before applying.',verification:'Not in current collection',verification_evidence:'Saved history; this is not a current application check.',checked_at:null,eligibility:'Worth a chance',eligibility_evidence:'Eligibility needs confirmation.',freshness:'Unknown date',age_days:null,date_basis:'Saved listing date',match_reasons:[],sources:[],main_catch:'Not in the current collection. Check whether hiring continues.'};
   result.push(archived);jobMap.set(row.job_id,archived);
  }
  return result;
 }
 function enqueue(task){const next=writes.catch(()=>{}).then(task);writes=next;return next;}
 async function write(id,status,notes){
  const owner=user?.id,current=generation,db=database;
  if(!owner||!profile||problem)throw new Error('Account history is not ready. Retry sync before saving.');
  const snapshot=compactJob(jobMap.get(id));
  return enqueue(async()=>{
   if(user?.id!==owner||current!==generation)throw new Error('Your account changed. Please try again.');
   const row=await value(db.rpc('scout_set_activity',{p_job_id:id,p_action:'save',p_snapshot:snapshot,p_status:status,p_notes:String(notes||'').slice(0,10000)}));
   if(user?.id===owner&&current===generation)activities.set(id,Array.isArray(row)?row[0]:row);
   render();return {ok:true};
  });
 }
 function markViewed(id){
  if(!user||!profile||problem)return;
  const owner=user.id,current=generation,db=database,old=activities.get(id),snapshot=compactJob(jobMap.get(id));
  activities.set(id,{...old,job_id:id,status:old?.status||'new',notes:old?.notes||'',viewed:true,viewed_at:old?.viewed_at||new Date().toISOString(),marked_new:false,job_snapshot:snapshot});
  enqueue(async()=>{
   if(user?.id!==owner||current!==generation)return;
   const row=await value(db.rpc('scout_set_activity',{p_job_id:id,p_action:'view',p_snapshot:snapshot}));
   if(user?.id===owner&&current===generation){activities.set(id,Array.isArray(row)?row[0]:row);render();emit(false);}
  }).catch(()=>{
   if(user?.id!==owner||current!==generation)return;
   if(old)activities.set(id,old);else activities.delete(id);
   problem='Viewed history could not sync. Retry when your connection is available.';render();emit(false);
  });
 }
 async function refresh(){
  await ready;if(!client||!user&&!problem)return;
  await writes.catch(()=>{});
  const session=await client.auth.getSession();if(session.error)throw new Error('Your account session could not be refreshed. Try signing in again.');profile=null;
  ready=activate(session.data.session);await ready;
 }
 function guestItems(){
  let tracking={},reading={};
  try{tracking=JSON.parse(localStorage.getItem('job-scout-public-tracking-v1')||'{}')||{};reading=JSON.parse(localStorage.getItem('job-scout-reading-v1')||'{}')||{};}catch{}
  const viewed=new Set(Array.isArray(reading.viewed)?reading.viewed:[]),pending=new Set(Array.isArray(reading.pending)?reading.pending:[]);
  const ids=new Set([...Object.keys(tracking),...viewed,...pending]);
  return [...ids].filter(validId).map(id=>({job_id:id,status:['new','saved','applied','dismissed'].includes(tracking[id]?.state)?tracking[id].state:'new',notes:String(tracking[id]?.notes||'').slice(0,10000),viewed:viewed.has(id),viewed_at:typeof reading.viewedAt?.[id]==='string'&&Number.isFinite(Date.parse(reading.viewedAt[id]))?reading.viewedAt[id]:null,marked_new:pending.has(id),job_snapshot:compactJob(jobMap.get(id))}));
 }
 async function importGuest(){
  if(!user||!profile||problem)throw new Error('Sign in and finish syncing first.');
  const items=guestItems(),owner=user.id,current=generation,db=database;
  if(!items.length){message('No browser history to import.');return;}
  if(!confirm(`Copy ${items.length} browser activity records into ${user.email||'this account'}? Existing account records are kept. Browser data stays on this device.`))return;
  let added=0;
  for(let i=0;i<items.length;i+=500){
   if(user?.id!==owner||current!==generation)throw new Error('Account changed during import. Browser data was kept.');
   added+=await value(db.rpc('scout_import_activity',{p_items:items.slice(i,i+500)}));
  }
  await refresh();message(`${added} records imported. Existing account records and browser data were kept.`);emit(false);
 }
 async function exportData(){
  if(!user||!profile||problem)throw new Error('Sync your account before exporting.');
  await writes.catch(()=>{});
  const rows=await readActivity(database,user.id),blob=new Blob([JSON.stringify({version:1,exported_at:new Date().toISOString(),profile,activity:rows},null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='job-scout-account.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }
 async function signIn(){
  if(!client)throw new Error('Account sign-in is not ready.');
  signInError='';oauthBusy=true;render();
  try{
   const result=await client.auth.signInWithOAuth({provider:cfg.provider,options:{redirectTo:new URL('./',location.href).href}});
   if(result.error)throw new Error('Sign-in could not start. Please try again.');
  }finally{oauthBusy=false;render();}
 }
 async function signOut(){
  if(!client)return;
  await writes.catch(()=>{});
  const result=await client.auth.signOut({scope:'local'});
  if(result.error)throw new Error('Sign-out did not complete. Please retry.');
  guestChoice(false);element('account-dialog')?.close?.();
  ready=activate(null);await ready;
  element('welcome-title')?.focus?.();
 }
 async function deleteAccount(){
  if(!user)return;
  if(!confirm('Permanently delete your Job Scout account, saved jobs, application history and cloud notes? Browser-only data stays on this device. This cannot be undone.'))return;
  await value(database.rpc('scout_delete_account'));
  await signOut();element('account-dialog').close();
 }
 document.addEventListener('DOMContentLoaded',()=>{
  if(!element('account-entry'))return;
  element('account-entry').addEventListener('click',welcome);
  element('browse-guest').addEventListener('click',()=>{guestChoice(true);render();element('view-title')?.focus?.();});
  element('account-settings').addEventListener('click',()=>{element('account-menu').open=false;message('');render();element('account-dialog').showModal();});
  document.addEventListener('click',event=>{const menu=element('account-menu');if(menu?.open&&!menu.contains(event.target))menu.open=false;});
  document.addEventListener('keydown',event=>{const menu=element('account-menu');if(event.key==='Escape'&&menu?.open){menu.open=false;element('account-menu-trigger')?.focus?.();}});
  element('account-close').addEventListener('click',()=>element('account-dialog').close());
  for(const [id,action] of [['account-provider',signIn],['account-signout',signOut],['account-import',importGuest],['account-export',exportData],['account-retry',()=>signInError?signIn():refresh()],['account-delete',deleteAccount]]){
   element(id).addEventListener('click',async()=>{const button=element(id),isSignIn=id==='account-provider'||id==='account-retry'&&!!signInError;button.disabled=true;message('');try{await action();}catch(e){if(isSignIn)signInError=e.message;message(e.message);}finally{button.disabled=false;render();}});
  }
  render();
 });
 return {start,get ready(){return ready;},get active(){return !!user;},get configured(){return configured;},get problem(){return problem;},render,overlay,write,refresh,
  reading:{sync(jobs){for(const j of jobs)jobMap.set(j.id,j);return false;},isNew(id){const row=activities.get(id),j=jobMap.get(id);return !!profile&&!row?.viewed&&(!!row?.marked_new||Date.parse(j?.first_seen)>Date.parse(profile.baseline_at));},isViewed:id=>!!activities.get(id)?.viewed,viewedAt:id=>activities.get(id)?.viewed_at||null,markViewed}};
})();
