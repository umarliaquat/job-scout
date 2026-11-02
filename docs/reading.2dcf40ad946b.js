'use strict';
// Private per-browser history, deliberately separate from published job data.
window.scoutReading=(()=>{
 const key='job-scout-reading-v1';
 let state={known:[],pending:[],viewed:[]},initialized=false,persistent=true;
 try{
  const saved=JSON.parse(localStorage.getItem(key)||'null');
  if(saved&&['known','pending','viewed'].every(k=>Array.isArray(saved[k])&&saved[k].every(x=>typeof x==='string'))){state=saved;initialized=true;}
 }catch{}
 const known=new Set(state.known),pending=new Set(state.pending),viewed=new Set(state.viewed),viewedAt=Object.create(null);
 if(state.viewedAt&&typeof state.viewedAt==='object'&&!Array.isArray(state.viewedAt)){
  for(const [id,date] of Object.entries(state.viewedAt))if(viewed.has(id)&&typeof date==='string'&&Number.isFinite(Date.parse(date)))viewedAt[id]=date;
 }
 function save(){try{localStorage.setItem(key,JSON.stringify({known:[...known],pending:[...pending],viewed:[...viewed],viewedAt}));persistent=true;}catch{persistent=false;}}
 return {
  sync(jobs){
   if(window.scoutAccount?.active)return window.scoutAccount.reading.sync(jobs);
   const baseline=!initialized;
   for(const job of jobs){if(!baseline&&!known.has(job.id)&&!viewed.has(job.id))pending.add(job.id);known.add(job.id);}
   initialized=true;save();return baseline;
  },
  isNew:id=>window.scoutAccount?.active?window.scoutAccount.reading.isNew(id):pending.has(id)&&!viewed.has(id),
  isViewed:id=>window.scoutAccount?.active?window.scoutAccount.reading.isViewed(id):viewed.has(id),
  viewedAt:id=>window.scoutAccount?.active?window.scoutAccount.reading.viewedAt(id):viewedAt[id]||null,
  markViewed(id){if(window.scoutAccount?.active){window.scoutAccount.reading.markViewed(id);return;}viewed.add(id);pending.delete(id);if(!viewedAt[id])viewedAt[id]=new Date().toISOString();save();},
  get persistent(){return persistent;}
 };
})();
