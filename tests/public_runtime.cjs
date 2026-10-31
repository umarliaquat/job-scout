const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const storage=new Map();
const snapshot={jobs:[{id:'one',title:'Product Designer',state:'new',notes:'',priority:'promising',published:new Date().toISOString(),checked_at:new Date().toISOString(),verification:'Application form found',verification_evidence:'Form found.'}],sources:[],scan:{running:false}};
let fetched;
const context={window:{},document:{addEventListener(){}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},structuredClone,Date,URL,Blob,fetch:async path=>{fetched=path;return {ok:true,json:async()=>structuredClone(snapshot)}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/public.js','utf8'),context);
(async()=>{
 const api=context.window.scoutApi;
 assert.equal((await api('/api/jobs')).jobs[0].state,'new');assert.equal(fetched,'./jobs.json');
 await api('/api/job',{id:'one',state:'saved',notes:'Private browser note'});
 assert.equal((await api('/api/jobs')).jobs[0].notes,'Private browser note');
 assert.equal(snapshot.jobs[0].notes,'');
 await assert.rejects(api('/api/job',{id:'missing',state:'saved'}),/unavailable/);
 snapshot.jobs[0].checked_at='2020-01-01T00:00:00Z';await api('/api/scan');
 let current=await api('/api/jobs');assert.equal(current.jobs[0].verification,'Needs recheck');assert.equal(current.jobs[0].priority,'review');
 snapshot.jobs[0].published='2020-01-01T00:00:00Z';await api('/api/scan');
 assert.equal((await api('/api/jobs')).jobs[0].priority,'archive');
 console.log('Public runtime checks passed: relative fetch, browser-only tracking, stale checks, archive and errors.');
})().catch(e=>{console.error(e);process.exitCode=1});
