'use strict';

let data={jobs:[],sources:[],scan:{}},view='discover',tabView='arrivals',limit=30,activeId=null,toastTimer;

let displayMode='table';

try{if(localStorage.getItem('job-scout-layout')==='cards')displayMode='cards';}catch{}

const $=s=>document.querySelector(s);

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const safe=u=>{try{const x=new URL(u);return ['http:','https:'].includes(x.protocol)?x.href:'#';}catch{return '#';}};

const stamp=x=>x?new Date(x).toLocaleString([],{dateStyle:'medium',timeStyle:'short'}):'Not checked';

const day=x=>x?new Date(x).toLocaleDateString([],{dateStyle:'medium'}):'Date unknown';

const openEvidence=j=>['Application form found','Application steps found','Email applications listed'].includes(j.verification);

const closed=j=>['Closed','No longer listed'].includes(j.verification);

const badge=(text,type='')=>`<span class="badge ${type}">${esc(text)}</span>`;

const bookmarkIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4Z"/></svg>';

const available=j=>!['dismissed','applied'].includes(j.state);

async function api(path,body){
 if(window.scoutApi)return window.scoutApi(path,body);

 const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Scout-Token':data.token},body:JSON.stringify(body)}:{});

 const result=await response.json();if(!response.ok)throw new Error(result.error||result.message||'Request failed');return result;

}

function error(message){$('#error').textContent=message;$('#error').hidden=!message;}

function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},3200);}

async function load(){

 try{

  data=await api('/api/jobs');

  if(data.jobs.some(j=>!j.priority))throw new Error('The local server needs restarting to load the updated ranking.');

  $('#scan').disabled=!!data.scan.running;$('#scan').textContent=data.scan.running?'Checking sources…':window.SCOUT_PUBLIC?'Refresh jobs':'Search sources now';

  $('#scan-status').hidden=!data.scan.running;$('#scan-status').textContent=data.scan.message;

  updateRefreshStatus();

  const baseline=window.scoutReading.sync(data.jobs);
  $('#reading-notice').hidden=window.scoutReading.persistent&&!baseline;
  $('#reading-notice').textContent=window.scoutReading.persistent?(baseline?'Watching from today. Existing listings are your baseline; new arrivals will appear after a future refresh.':'New arrivals stay here until you open them. Viewed history stays in this browser. Listings that disappear and return keep their reading status.'):'Browser storage is unavailable. Reading history will be lost when you leave this page.';
  render();return true;

 }catch(e){error(e.message);return false;}

}

function updateRefreshStatus(){
 const finished=data.last_run?.finished,valid=finished&&Number.isFinite(Date.parse(finished));
 const time=valid?new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Karachi',dateStyle:'medium',timeStyle:'short'}).format(new Date(finished))+' PKT':'Not available';
 $('#last-scan').textContent=valid?'Last successful collection: '+time:'No successful collection recorded';
 if(valid)$('#last-scan').innerHTML='<span class="collection-label">Last successful collection:</span><time datetime="'+esc(finished)+'">'+esc(time)+'</time>';
 const pkParts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Karachi',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23',minute:'2-digit'}).formatToParts(new Date());
 const parts=Object.fromEntries(pkParts.map(p=>[p.type,p.value]));
 const today=parts.year+'-'+parts.month+'-'+parts.day;
 const date=valid?new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Karachi',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(finished)):'';
 const overdue=!valid||Date.now()-Date.parse(finished)>26*3600000||(Number(parts.hour)*60+Number(parts.minute)>=645&&date!==today);
 $('#last-scan').classList.toggle('overdue',overdue);
 if(overdue)$('#last-scan').innerHTML+='<span class="collection-overdue">Overdue</span>';
 $('#last-scan').title=window.SCOUT_PUBLIC?(overdue?'Morning update is overdue. Refresh jobs checks the published file; it cannot start the collector. Check the refresh run for failures.':'Morning collection: 7:23 AM Pakistan, with backup attempts at 9:23 and 10:23 AM. Refresh jobs loads the latest published results; it does not start a crawl.'):'This is the local collector. Automatic morning updates appear on the public site; Search sources now runs a local crawl.';
 $('#scan').title=window.SCOUT_PUBLIC?'Load the latest published jobs without calling job-feed APIs':'Fetch job feeds and check application pages';
}

const contexts={
 arrivals:'Newly discovered, unviewed roles dated within 30 days, with application evidence and Pakistan or flexible-location potential. New here does not mean newly posted.',

 promising:'Core design or product roles · dated within 30 days · application evidence · Pakistan or worldwide hiring advertised.',

 stretch:'Recent, listed roles where location or scope needs a judgement call. Read the catch before preparing an application.',

 review:'Application access or publication date needs confirmation. Undated roles are not treated as recent openings.',

 all:'Your monitored sources, not a worldwide job total. The complete research collection. Includes older, undated and closed jobs; finding a listing does not make it a recommendation.'

};

const designRole=j=>['Product design','Design engineering','Web / visual design'].includes(j.category);
function roleScope(j){const c=$('#category').value;return !c||(c==='design'?designRole(j):j.category===c);}
const arrival=j=>window.scoutReading.isNew(j.id)&&available(j)&&['promising','stretch'].includes(j.priority)&&!closed(j);
function readingChip(j){return window.scoutReading.isNew(j.id)?chip('New here','green'):window.scoutReading.isViewed(j.id)?chip('Viewed','neutral'):chip('Unviewed','blue');}
function matchesView(j){return view==='discover'?(tabView==='arrivals'?arrival(j):tabView==='all'||j.priority===tabView&&available(j)):j.state===view;}

function excerpt(j){return j.description.replace(/^(?:About(?: the)? (?:role|company)|Job description)[\s:–-]*/i,'').slice(0,420);}

function locationLabel(j){const value=j.location||'Not specified';return value.length>110?value.split(';').slice(0,3).join(' · ')+' + more countries':value;}

function saveControl(j){

 const saved=j.state==='saved';

 return `<button class="bookmark ${saved?'saved':''}" data-save="${esc(j.id)}" aria-label="${saved?'Unsave':'Save'} ${esc(j.title)} at ${esc(j.company)}" aria-pressed="${saved}">${bookmarkIcon}</button>`;

}

function applicationLabel(j){return j.verification==='Application form found'?'Form found':j.verification==='Application steps found'?'Multi-step form':j.verification==='Employer page listed'?'Page listed':j.verification==='Employer board listed'?'Board listed':j.verification==='Email applications listed'?'Email route listed':j.verification;}

function chip(text,tone='neutral'){return `<span class="scan-chip ${tone}">${esc(text)}</span>`;}

function eligibilityChip(j){return chip(j.eligibility,j.eligibility==='Pakistan listed'||j.eligibility==='Worldwide advertised'?'green':j.eligibility==='Restricted / review'?'rose':'amber');}

function freshnessChip(j){return chip(j.freshness==='Recent'?(j.age_days===0?'Today':`${j.age_days}d ago`):j.freshness==='Older'?'Older':j.freshness==='Unknown date'?'Undated':j.freshness,j.freshness==='Recent'?'blue':'neutral');}

function applicationChip(j){return chip(applicationLabel(j),j.verification==='Application form found'?'green':['Application steps found','Email applications listed'].includes(j.verification)?'teal':['Employer board listed','Employer page listed'].includes(j.verification)?'blue':closed(j)?'rose':'amber');}

function publicationLabel(j){return (j.date_basis||'').startsWith('Last published')?'Last published':j.date_basis.includes('Job-board')?'Job-board date':j.date_basis.includes('Application-page')?'Application-page date':'Listing date';}

function card(j){

 const reason=(j.opportunity_signals||[]).filter(x=>!x.endsWith(' role')).slice(0,2).join(' · ')||'Role title matches; hiring evidence needs checking.';

 return `<article class="opportunity-card"><div class="card-company"><span>${esc(j.company)}</span>${saveControl(j)}</div><button class="card-title" data-job="${esc(j.id)}">${esc(j.title)}</button><p class="card-location">${esc(j.location||'Location to confirm')}</p><p class="card-description">${esc(excerpt(j))}</p><p class="card-reason"><strong>Why look</strong> ${esc(reason)}</p><p class="card-catch"><strong>The catch</strong> ${esc(j.main_catch)}</p><div class="card-facts">${readingChip(j)}${applicationChip(j)}${freshnessChip(j)}</div><button class="card-open" data-job="${esc(j.id)}">View role & evidence <span aria-hidden="true">↗</span></button></article>`;

}

function table(jobs){

 return `<div class="table-scroll" role="region" aria-label="Opportunities table; scroll horizontally on small screens" tabindex="0"><table class="jobs-table"><caption class="sr-only">Opportunities with location, publication date, application evidence and trade-offs</caption><colgroup><col class="col-role"><col class="col-location"><col class="col-date"><col class="col-evidence"><col class="col-catch"><col class="col-save"></colgroup><thead><tr><th scope="col">Role & company</th><th scope="col">Location</th><th scope="col">Date</th><th scope="col">Application</th><th scope="col">Main consideration</th><th scope="col"><span class="sr-only">Save</span></th></tr></thead><tbody>${jobs.map(j=>`<tr><td><button class="table-title" data-job="${esc(j.id)}">${esc(j.title)}</button><span class="cell-secondary">${esc(j.company)}${j.state==='applied'?' · Applied':''}</span><span class="cell-category">${chip(j.category,"violet")}${readingChip(j)}</span></td><td><span>${esc(locationLabel(j))}</span><span class="cell-secondary">${eligibilityChip(j)}</span></td><td><span class="date-value">${j.published?day(j.published):'Unknown'}</span><span class="cell-secondary">${esc(j.published?publicationLabel(j):'Not supplied')}</span>${freshnessChip(j)}</td><td><span class="application-state ${openEvidence(j)?'available':closed(j)?'closed':'uncertain'}">${applicationChip(j)}</span><span class="cell-secondary">${j.checked_at?'Checked '+day(j.checked_at):'Not checked'}</span></td><td><p class="table-catch">${esc(j.main_catch)}</p><button class="table-details" data-job="${esc(j.id)}" aria-label="View evidence for ${esc(j.title)} at ${esc(j.company)}">View evidence ↗</button></td><td>${saveControl(j)}</td></tr>`).join('')}</tbody></table></div>`;

}

function arrivalsEmpty(){
 const sources=data.sources||[],worked=sources.filter(s=>['ok','cached','no_matches'].includes(s.status)).length;
 const failed=sources.filter(s=>s.status==='error').length,manual=sources.filter(s=>s.status==='manual').length,pending=sources.filter(s=>s.status==='pending').length;
 const ran=data.last_run?.finished;
 const when=ran?new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Karachi',dateStyle:'medium',timeStyle:'short'}).format(new Date(ran))+' PKT':'No completed search recorded';
 const report=data.collection_report,queue=data.jobs.filter(j=>arrival(j)&&roleScope(j)).length;
 const filters=queue>0;
 let reason=filters?'New arrivals exist, but your current filters hide them. Clear filters to see them.':'Existing jobs are not counted again. Opening a role removes it from New arrivals; your first visit establishes the existing collection as a baseline.';
 let outcome='';
 if(report?.comparison_available){
  outcome=`Compared with the previous collection: ${report.added_total} new listings across all roles, ${report.added_design} design roles, ${report.qualified_design} qualifying design roles.`;
  if(!filters&&report.qualified_design===0){
   const labels={older_or_closed:'older, closed or future-dated',undated:'without a confirmed recent posting date',application_unverified:'without a verified application route',other_review:'requiring further review'};
   const reasons=Object.entries(report.excluded||{}).filter(([,n])=>n>0).map(([key,n])=>`${n} ${labels[key]||'requiring review'}`);
   reason=report.added_design?`New design listings did not qualify: ${reasons.join('; ')}.`:'No newly discovered design roles were found in this collection. Existing jobs were not counted again.';
  }
 }else outcome='No previous-collection comparison is available yet; this is not evidence that no jobs exist elsewhere.';
 const coverage=sources.length?`${worked} of ${sources.length} sources worked`:'Source results unavailable';
 const gaps=[failed?`${failed} failed`:null,manual?`${manual} need manual checking`:null,pending?`${pending} not checked`:null].filter(Boolean).join(' · ');
 return `<div class="empty"><h2>${filters?'New arrivals are hidden by filters':'No new arrivals to show'}</h2><dl class="empty-search-report"><div><dt>Last completed search</dt><dd>${esc(when)}</dd></div><div><dt>Source coverage</dt><dd>${esc(coverage)}${gaps?`<small>${esc(gaps)}</small>`:''}</dd></div></dl><p>${esc(outcome)}</p><p>${esc(reason)}</p>${gaps?'<p class="coverage-gap">Coverage is incomplete. Failed or unreadable sources may contain jobs we missed.</p>':''}<button data-empty="promising">Browse best leads</button><button data-empty="review">Review unchecked leads</button>${filters?'<button data-empty="clear">Clear filters</button>':''}</div>`;
}

function render(){

 const discover=view==='discover',sources=view==='sources';

 $('#jobs-view').hidden=sources;$('#sources-view').hidden=!sources;$('#discovery-tabs').hidden=!discover;

 const names={discover:'Remote design jobs',saved:'Your saved opportunities',applied:'Your applications',dismissed:'Set aside',sources:'Follow the right companies'};

 const descriptions={discover:data.profile_loaded?'Prioritized for your product design, SaaS workflows and AI-assisted building experience.':'Find roles worth your time. Compare country requirements, posting dates and application checks.',saved:'The roles you want to come back to. Your notes stay with each opportunity.',applied:'Keep your applications and follow-up notes in one place.',dismissed:'Roles you have ruled out. They stay out of your discovery views.',sources:'Build a useful employer watchlist, rather than a bigger pile of listings.'};

 $('#view-title').textContent=names[view];$('#view-description').textContent=descriptions[view];$('#breadcrumb').textContent=discover?'Discover opportunities':names[view];

 $('#scope-note').textContent=discover?contexts[tabView]:view==='saved'?'Saved by you. Check the date and application evidence before applying.':view==='applied'?'Application status is recorded by you; Job Scout does not submit applications.':'Dismissed by you. You can restore a role from its details.';

 $('.selection-help').hidden=!discover;

 for(const name of ['saved','applied','dismissed'])$(`#${name}-count`).textContent=data.jobs.filter(j=>j.state===name).length;

 for(const name of ['promising','stretch','review'])$(`#${name}-count`).textContent=data.jobs.filter(j=>j.priority===name&&available(j)&&roleScope(j)).length;

 $('#arrivals-count').textContent=data.jobs.filter(j=>arrival(j)&&roleScope(j)).length;
 $('#all-count').textContent=data.jobs.filter(roleScope).length;

 document.querySelectorAll('[data-tab]').forEach(b=>{const selected=b.dataset.tab===tabView;b.classList.toggle('active',selected);b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});

 $('#scan').hidden=sources||!discover;
 if(sources){renderSources();return;}

 const query=$('#search').value.toLowerCase().trim(),category=$('#category').value,freshness=$('#freshness').value,eligibility=$('#eligibility').value;

 let jobs=data.jobs.filter(j=>matchesView(j)&&(!$('#reading-status').value||($('#reading-status').value==='viewed'?window.scoutReading.isViewed(j.id):!window.scoutReading.isViewed(j.id)))&&(!query||`${j.title} ${j.company} ${j.description} ${j.location}`.toLowerCase().includes(query))&&roleScope(j)&&(!eligibility||j.eligibility===eligibility)&&(!freshness||(freshness==='week'?j.age_days!==null&&j.age_days>=0&&j.age_days<=7:j.freshness===freshness)));

 const sort=$('#sort').value;jobs.sort((a,b)=>sort==='date'?(b.published||'').localeCompare(a.published||''):sort==='seen'?b.first_seen.localeCompare(a.first_seen):b.attention_rank-a.attention_rank);

 $('#visible-count').textContent=jobs.length;$('#result-label').textContent=jobs.length===1?'opportunity to consider':'opportunities to consider';

 $('#results-note').textContent=discover&&tabView==='all'?'Research collection · not recommendations':'Prioritized by evidence, not volume';

 const emptyTitle=discover&&tabView==='arrivals'?'You’re caught up on new arrivals.':discover&&tabView==='promising'?'No checked leads match this view.':'No roles match this view.';

 const emptyText=discover&&tabView==='arrivals'?'Existing listings are not counted again after a refresh. Check back after the morning update, or browse Best leads. New arrivals must also pass the recency, application and location checks.':discover&&tabView==='promising'?'The current collection has no recent core roles that meet the application and location checks together. Worth a chance has roles with trade-offs; Needs checking contains leads that still need verification.':'Try clearing your filters or exploring a different priority. Saved and applied roles are kept separately.';

 $('#results').className=jobs.length&&displayMode==='cards'?'card-grid':'';

 document.querySelectorAll('[data-layout]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.layout===displayMode)));

 $('#results').innerHTML=jobs.length?(displayMode==='table'?table(jobs.slice(0,limit)):jobs.slice(0,limit).map(card).join('')):discover&&tabView==='arrivals'?arrivalsEmpty():`<div class="empty"><h2>${data.jobs.length?emptyTitle:'Start with a fresh search.'}</h2><p>${data.jobs.length?emptyText:'Find recent remote design and product roles, then inspect the evidence before deciding where to apply.'}</p>${data.jobs.length?'<button data-empty="promising">Browse best leads</button><button data-empty="clear">Clear filters</button>':'<button data-empty="scan" class="primary">Find opportunities</button>'}</div>`;

 $('#more').hidden=jobs.length<=limit;

}

function changeView(next){view=next;limit=30;document.querySelectorAll('.nav').forEach(b=>{const active=b.dataset.view===view;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});render();window.scrollTo({top:0,behavior:'instant'});}

function changeTab(next){tabView=next;limit=30;render();}

function clearFilters(){for(const s of ['#search','#freshness','#eligibility','#reading-status'])$(s).value='';$('#category').value='design';render();}

function sourceName(name){return ({arbeitnow:'Arbeitnow · Europe',arbeitnow_uk:'Arbeitnow · United Kingdom',himalayas:'Himalayas · remote jobs',wwr:'We Work Remotely',remoteok:'Remote OK',jobicy:'Jobicy',remotive:'Remotive'})[name]||name.replace(/^ashby:/,'Ashby · ').replace(/^greenhouse:/,'Greenhouse · ').replace(/^workable:/,'Workable · ').replace(/^page:/,'Employer page · ');}
function renderSources(){$('.coverage-note p').textContent=window.SCOUT_PUBLIC?'Public source checks from the last collection. Failed checks are kept visible; they do not mean a company has stopped hiring.':'Follow smaller companies and inspect source checks. A failed check does not mean a company has stopped hiring.';$('#source-list').innerHTML=data.sources.map(s=>`<div class="source-row"><strong>${esc(sourceName(s.name))}</strong><span>${badge(s.status,s.status==='error'?'bad':['pending','manual'].includes(s.status)?'warn':'good')}</span><span>${esc(s.detail)}<br>Checked ${stamp(s.checked)}</span></div>`).join('')||'<p>No sources checked yet. Run a scan to begin.</p>';}

let refreshBusy=false;
async function startScan(){
 if(refreshBusy)return;
 refreshBusy=true;$('#scan').disabled=true;$('#scan').textContent=window.SCOUT_PUBLIC?'Refreshing…':'Starting search…';error('');
 const before=new Set(data.jobs.map(j=>j.id)),previous=data.last_run?.finished;
 try{
  await api('/api/scan',{});
  if(await load()){
   lastSnapshotCheck=Date.now();
   if(window.SCOUT_PUBLIC){const count=data.jobs.filter(j=>!before.has(j.id)&&arrival(j)&&roleScope(j)).length;toast(count?`${count} new qualifying ${count===1?'role':'roles'} loaded`:previous===data.last_run?.finished?'You have the latest published jobs. No newer collection yet.':'Latest collection loaded. No new qualifying design arrivals.');}
  }
 }catch(e){error(e.message);}finally{refreshBusy=false;$('#scan').disabled=!!data.scan.running;if(!data.scan.running)$('#scan').textContent=window.SCOUT_PUBLIC?'Refresh jobs':'Search sources now';}
}

async function quickSave(id,button){const j=data.jobs.find(j=>j.id===id);button.disabled=true;try{const state=j.state==='saved'?'new':'saved';await api('/api/job',{id,state,notes:j.notes});await load();toast(state==='saved'?'Opportunity saved':'Removed from saved opportunities');}catch(e){error(e.message);button.disabled=false;}}

$('#scan').addEventListener('click',startScan);

$('.rail nav').addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b)changeView(b.dataset.view);});

$('#discovery-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-tab]');if(b)changeTab(b.dataset.tab);});

$('#discovery-tabs').addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...document.querySelectorAll('[data-tab]')];const index=tabs.findIndex(x=>x.dataset.tab===tabView);const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;changeTab(tabs[next].dataset.tab);tabs[next].focus();});

$('#results').addEventListener('click',e=>{const save=e.target.closest('[data-save]'),job=e.target.closest('[data-job]'),empty=e.target.closest('[data-empty]');if(save)quickSave(save.dataset.save,save);else if(job)showJob(job.dataset.job);else if(empty){if(empty.dataset.empty==='scan')startScan();else if(empty.dataset.empty==='clear')clearFilters();else{clearFilters();changeTab(empty.dataset.empty);}}});

$('#close-detail').addEventListener('click',()=>$('#detail').close());
$('#detail').addEventListener('close',()=>{if(tabView==='arrivals')$('#results').focus();});

$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')&&e.offsetX<0)$('#detail').close();});

for(const s of ['#search','#category','#freshness','#eligibility','#reading-status','#sort'])$(s).addEventListener(s==='#search'?'input':'change',()=>{limit=30;render();});

$('#filter-toggle').addEventListener('click',()=>{const hidden=!$('#extra-filters').hidden;$('#extra-filters').hidden=hidden;$('#filter-toggle').setAttribute('aria-expanded',String(!hidden));});

$('#clear-filters').addEventListener('click',clearFilters);

$('#layout-toggle').addEventListener('click',e=>{const b=e.target.closest('[data-layout]');if(!b)return;displayMode=b.dataset.layout;try{localStorage.setItem('job-scout-layout',displayMode);}catch{}render();});

$('#more').addEventListener('click',()=>{limit+=30;render();});

$('#add-source').addEventListener('submit',async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await api('/api/source',Object.fromEntries(new FormData(e.target)));e.target.reset();await load();toast('Employer added. Run a scan to check its openings.');}catch(err){error(err.message);}finally{b.disabled=false;}});

$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')){const r=$('#detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('#detail').close();}});
load();setInterval(()=>{if(data.scan.running)load();},2500);


// Reopen a tab the next morning without leaving yesterday’s snapshot on screen.
let lastSnapshotCheck=Date.now();
document.addEventListener('visibilitychange',async()=>{
 if(!window.SCOUT_PUBLIC||document.visibilityState!=='visible'||Date.now()-lastSnapshotCheck<300000)return;
 lastSnapshotCheck=Date.now();
 try{await api('/api/scan',{});await load();}catch(e){error(e.message);}
});

setInterval(()=>{if(window.SCOUT_PUBLIC&&document.visibilityState==='visible'&&!refreshBusy&&Date.now()-lastSnapshotCheck>=1800000)startScan();},60000);
