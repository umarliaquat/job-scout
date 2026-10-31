'use strict';
// Private per-browser history, deliberately separate from published job data.
window.scoutReading=(()=>{
 const key='job-scout-reading-v1';
 let state={known:[],pending:[],viewed:[]},initialized=false,persistent=true;
 try{
  const saved=JSON.parse(localStorage.getItem(key)||'null');
  if(saved&&['known','pending','viewed'].every(k=>Array.isArray(saved[k])&&saved[k].every(x=>typeof x==='string'))){state=saved;initialized=true;}
 }catch{}
 const known=new Set(state.known),pending=new Set(state.pending),viewed=new Set(state.viewed);
 function save(){try{localStorage.setItem(key,JSON.stringify({known:[...known],pending:[...pending],viewed:[...viewed]}));persistent=true;}catch{persistent=false;}}
 return {
  sync(jobs){
   const baseline=!initialized;
   for(const job of jobs){if(!baseline&&!known.has(job.id)&&!viewed.has(job.id))pending.add(job.id);known.add(job.id);}
   initialized=true;save();return baseline;
  },
  isNew:id=>pending.has(id)&&!viewed.has(id),
  isViewed:id=>viewed.has(id),
  markViewed(id){viewed.add(id);pending.delete(id);save();},
  get persistent(){return persistent;}
 };
})();
