'use strict';
// GitHub Pages serves a sanitized snapshot. Personal tracking stays in this browser.
window.SCOUT_PUBLIC=true;
const trackingKey='job-scout-public-tracking-v1';
let publicSnapshot;
function readTracking(){try{return JSON.parse(localStorage.getItem(trackingKey)||'{}');}catch{return {};}}
window.scoutApi=async function(path,body){
 if(path==='/api/jobs'){
  if(!publicSnapshot){const response=await fetch('./jobs.json',{cache:'no-store'});if(!response.ok)throw new Error('Listings could not load. Reload the page to try again.');publicSnapshot=await response.json();}
  const result=structuredClone(publicSnapshot),tracking=readTracking();
  for(const j of result.jobs){
   j.state=tracking[j.id]?.state||'new';j.notes=tracking[j.id]?.notes||'';
   if(j.checked_at&&Date.now()-Date.parse(j.checked_at)>86400000&&!['Closed','No longer listed'].includes(j.verification)){
    j.verification='Needs recheck';j.verification_evidence='This published application check is older than 24 hours. Open the employer listing before applying. '+j.verification_evidence;
    if(['promising','stretch'].includes(j.priority)){j.priority='review';j.main_catch='Application evidence is older than 24 hours; check the employer listing.';}
   }
   if(j.published){j.age_days=Math.floor((Date.now()-Date.parse(j.published))/86400000);if(j.age_days>30){j.freshness='Older';j.priority='archive';j.main_catch='Published more than 30 days ago. Confirm whether hiring continues.';}}
  }
  return result;
 }
 if(path==='/api/job'){
  if(!publicSnapshot?.jobs.some(j=>j.id===body.id))throw new Error('This listing is unavailable. Reload to update listings.');
  if(!['new','saved','applied','dismissed'].includes(body.state))throw new Error('Unknown application status.');
  const tracking=readTracking();tracking[body.id]={state:body.state,notes:String(body.notes||'').slice(0,10000)};
  try{localStorage.setItem(trackingKey,JSON.stringify(tracking));}catch{throw new Error('Browser storage is unavailable. Your changes could not be saved.');}
  return {ok:true};
 }
 if(path==='/api/scan'){publicSnapshot=null;return {ok:true};}
 throw new Error('Source management is available in the local collector.');
};
document.addEventListener('DOMContentLoaded',()=>{
 document.body.classList.add('public-mode');
 document.querySelector('.local-note').textContent='Public listings. Your saves and notes stay in this browser; clearing browser data removes them.';
 const form=document.querySelector('#add-source');form.hidden=true;
 document.querySelector('.selection-help>div').lastElementChild.textContent='These are research priorities, not response predictions. Check country requirements and employer identity. No resume data is published.';
 document.querySelector('.rail-bottom>a').addEventListener('click',async event=>{
  event.preventDefault();const data=await window.scoutApi('/api/jobs');
  const columns=['company','title','location','published','verification','url','state','notes'];
  const cell=value=>'"'+String(value??'').replace(/^[=+@\-\t\r]/,"'$&").replaceAll('"','""')+'"';
  const csv=[columns.join(','),...data.jobs.filter(j=>j.state!=='new').map(j=>columns.map(k=>cell(j[k])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='my-job-tracker.csv';a.click();URL.revokeObjectURL(url);
 });
});
