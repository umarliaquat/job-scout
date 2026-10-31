const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('web/reading.js','utf8'),storage=new Map();
function open(blocked=false){const context={window:{},localStorage:{getItem:k=>storage.get(k)||null,setItem(k,v){if(blocked)throw Error('quota');storage.set(k,v);}}};vm.createContext(context);vm.runInContext(code,context);return context.window.scoutReading;}
let reader=open();
assert.equal(reader.sync([{id:'existing'}]),true);
assert.equal(reader.isNew('existing'),false,'Existing jobs establish a baseline');
assert.equal(reader.isViewed('existing'),false);
reader=open();reader.sync([{id:'existing',checked_at:'changed'},{id:'fresh'}]);
assert.equal(reader.isNew('existing'),false,'Refresh timestamps do not create arrivals');
assert.equal(reader.isNew('fresh'),true);
reader=open();reader.sync([{id:'existing'},{id:'fresh'}]);
assert.equal(reader.isNew('fresh'),true,'Unread arrivals survive reload');
reader.markViewed('fresh');assert.equal(reader.isNew('fresh'),false);assert.equal(reader.isViewed('fresh'),true);
reader=open();reader.sync([]);reader.sync([{id:'fresh'}]);
assert.equal(reader.isNew('fresh'),false,'A returning listing remains viewed');
reader.markViewed('existing');reader=open();assert.equal(reader.isViewed('existing'),true);
storage.set('job-scout-reading-v1','{"known":null}');reader=open();assert.equal(reader.sync([{id:'existing'}]),true);
reader=open(true);reader.sync([{id:'another'}]);assert.equal(reader.persistent,false,'Storage failure is exposed to the interface');
console.log('Reading history checks passed: baseline, arrivals, reloads, viewed, returning IDs, corrupt and blocked storage.');
const nodes=new Map();
function node(selector){if(!nodes.has(selector))nodes.set(selector,{value:selector==='#category'?'design':'',textContent:'',innerHTML:'',hidden:false,dataset:{},classList:{toggle(){}},setAttribute(){},addEventListener(){},focus(){}});return nodes.get(selector);}
const jobs=[{id:'baseline',title:'Designer',company:'Studio',category:'Product design',priority:'promising',state:'new',description:'Design products',verification:'Application form found',date_basis:'Listing date',freshness:'Recent',age_days:1,location:'Worldwide',eligibility:'Worldwide advertised',published:new Date().toISOString(),checked_at:new Date().toISOString(),first_seen:new Date().toISOString(),main_catch:'Check company',attention_rank:10}];
const uiStorage=new Map(),ui={window:{scoutApi:async()=>({jobs:structuredClone(jobs),sources:[],scan:{}})},document:{querySelector:node,querySelectorAll:()=>[],addEventListener(){}},localStorage:{getItem:k=>uiStorage.get(k)||null,setItem:(k,v)=>uiStorage.set(k,v)},setInterval(){},setTimeout(){},clearTimeout(){},Date,URL};
vm.createContext(ui);vm.runInContext(code,ui);vm.runInContext(fs.readFileSync('web/app.js','utf8'),ui);
(async()=>{
 await new Promise(setImmediate);
 assert.match(node('#results').innerHTML,/caught up/);
 jobs.push({...jobs[0],id:'arrival'});
 await vm.runInContext('load()',ui);
 assert.equal(node('#arrivals-count').textContent,1);
 assert.match(node('#results').innerHTML,/New here/);
 ui.window.scoutReading.markViewed('arrival');vm.runInContext('render()',ui);
 assert.equal(node('#arrivals-count').textContent,0);
 vm.runInContext("changeTab('all')",ui);
 assert.match(node('#results').innerHTML,/Viewed/);
 node('#reading-status').value='unviewed';vm.runInContext('render()',ui);
 assert.equal(node('#visible-count').textContent,1);
 console.log('Interface checks passed: baseline empty state, new queue, chips, viewed removal and unviewed filter.');
})().catch(e=>{console.error(e);process.exitCode=1});
