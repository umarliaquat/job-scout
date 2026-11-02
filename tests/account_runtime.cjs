const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
const id='abcdef0123456789abcd',second='bbbbbbbbbbbbbbbbbbbb';
const db={profiles:new Map(),activity:new Map()};
const rowKey=(owner,job)=>owner+':'+job;
db.activity.set(rowKey(a,id),{user_id:a,job_id:id,status:'saved',notes:'Only A',viewed:false,job_snapshot:{}});
db.activity.set(rowKey(b,id),{user_id:b,job_id:id,status:'applied',notes:'Only B',viewed:false,job_snapshot:{}});
let currentSession={user:{id:a,email:'a@example.com'},access_token:a},authCallback,failWrites=false;
const storage=new Map([['job-scout-public-tracking-v1',JSON.stringify({[second]:{state:'saved',notes:'Browser note'}})]]);
const nodes=new Map(),events=[];
function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,textContent:'',open:false,addEventListener(name,fn){this[name]=fn;},showModal(){this.open=true;},close(){this.open=false;}});return nodes.get(id);}
function databaseClient(ownerToken){
 async function owner(){return ownerToken?ownerToken():currentSession?.access_token;}
 return {
  from(table){
   let action='select',record,filter,single=false,start=0,end=999;
   const q={upsert(r){action='upsert';record=r;return q;},select(){return q;},eq(column,value){filter=[column,value];return q;},single(){single=true;return q;},order(){return q;},range(a,b){start=a;end=b;return q;},then(resolve,reject){return (async()=>{
    const uid=await owner();
    if(!uid)return {error:{message:'Unauthorized'}};
    if(table==='scout_profiles'){
     if(action==='upsert'){
      assert.equal(record.id,uid);if(!db.profiles.has(uid))db.profiles.set(uid,{id:uid,baseline_at:new Date(Date.now()-1000).toISOString()});
      return {data:null,error:null};
     }
     assert.deepEqual(filter,['id',uid]);return {data:single?db.profiles.get(uid):[db.profiles.get(uid)],error:null};
    }
    assert.deepEqual(filter,['user_id',uid]);return {data:[...db.activity.values()].filter(r=>r.user_id===uid).slice(start,end+1),error:null};
   })().then(resolve,reject);}};return q;
  },
  async rpc(name,args){
   const uid=await owner();if(!uid||failWrites)return {error:{message:'Write failed'}};
   assert.ok(!Object.hasOwn(args,'p_user_id'),'The server, never the client, chooses activity owner');
   if(name==='scout_set_activity'){
    const key=rowKey(uid,args.p_job_id),old=db.activity.get(key)||{user_id:uid,job_id:args.p_job_id,status:'new',notes:'',viewed:false};
    const next={...old,job_snapshot:args.p_snapshot};
    if(args.p_action==='save'){next.status=args.p_status;next.notes=args.p_notes;}
    if(args.p_action==='view'){next.viewed=true;next.viewed_at=old.viewed_at||new Date().toISOString();next.marked_new=false;}
    db.activity.set(key,next);return {data:next,error:null};
   }
   if(name==='scout_import_activity'){
    let added=0;for(const item of args.p_items){const key=rowKey(uid,item.job_id);if(!db.activity.has(key)){db.activity.set(key,{...item,user_id:uid});added++;}}
    return {data:added,error:null};
   }
   return {data:null,error:null};
  }
 };
}
const auth={async getSession(){return {data:{session:currentSession},error:null};},onAuthStateChange(fn){authCallback=fn;return {};},async signOut(){currentSession=null;authCallback('SIGNED_OUT',null);return {error:null};},async signInWithOAuth(){return {error:null};}};
const context={window:{SCOUT_PUBLIC:true,SCOUT_ACCOUNT_CONFIG:{enabled:true,url:'https://example.supabase.co',publishableKey:'sb_publishable_example',provider:'github'},supabase:{createClient(url,key,options){return options?.accessToken?databaseClient(options.accessToken):{auth,...databaseClient()};}},dispatchEvent:e=>events.push(e)},document:{getElementById:node,querySelector:node,addEventListener(event,fn){if(event==='DOMContentLoaded')context.onDom=fn;},createElement(){return {click(){}};}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},setTimeout,Date,URL,URLSearchParams,Blob,location:{href:'https://umarliaquat.github.io/job-scout/'},confirm:()=>true};
vm.createContext(context);vm.runInContext(fs.readFileSync('web/account.js','utf8'),context);
const account=context.window.scoutAccount;
const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
(async()=>{
 await account.start();context.onDom();
 const jobs=[{id,title:'Designer',company:'Studio',first_seen:new Date().toISOString()},{id:second,title:'Another designer',company:'Studio',first_seen:new Date().toISOString()}];
 assert.equal(account.active,true);
 assert.equal(account.overlay(jobs)[0].notes,'Only A');
 assert.equal(account.reading.isNew(second),true);
 await account.write(id,'applied','Updated A');
 assert.equal(db.activity.get(rowKey(a,id)).notes,'Updated A');
 account.reading.markViewed(id);await tick();
 assert.equal(account.reading.isViewed(id),true);
 assert.equal(db.activity.get(rowKey(a,id)).status,'applied','Viewing never overwrites saved/applied state');
 assert.equal(JSON.parse(storage.get('job-scout-public-tracking-v1'))[second].notes,'Browser note','Cloud writes do not contaminate guest data');
 currentSession={user:{id:b,email:'b@example.com'},access_token:b};authCallback('SIGNED_IN',currentSession);
 await assert.rejects(account.write(id,'saved','Must not leak A'),/not ready/);
 await tick();await account.ready;
 assert.equal(account.overlay(jobs)[0].notes,'Only B');assert.equal(account.reading.isViewed(id),false);
 assert.equal(db.activity.get(rowKey(a,id)).notes,'Updated A');
 await node('account-import').click();
 assert.equal(db.activity.get(rowKey(b,second)).notes,'Browser note');
 assert.equal(db.activity.get(rowKey(b,id)).notes,'Only B','Import keeps existing account records');
 failWrites=true;await assert.rejects(account.write(id,'saved','offline'),/could not sync/);failWrites=false;
 await node('account-signout').click();await tick();
 assert.equal(account.active,false);
 assert.ok(!JSON.stringify(account.overlay(jobs)).includes('Only B'));
 assert.equal(JSON.parse(storage.get('job-scout-public-tracking-v1'))[second].notes,'Browser note');
 assert.ok(events.some(e=>e.detail.reset));
 // OAuth failure parameters may contain codes or provider diagnostics. Show a
 // fixed message, remove the callback data, and keep the retry path functional.
 let cleanedUrl='',oauthCalls=0;
 const failed={...context,window:{...context.window,history:{replaceState(_state,_title,url){cleanedUrl=url;}}},location:{href:'https://umarliaquat.github.io/job-scout/?error=server_error&error_description=PRIVATE_CODE&category=design#error=server_error&error_description=PRIVATE_CODE'}};
 failed.document={...context.document,addEventListener(event,fn){if(event==='DOMContentLoaded')failed.onDom=fn;}};
 auth.signInWithOAuth=async()=>{oauthCalls++;return {error:null};};
 vm.createContext(failed);vm.runInContext(fs.readFileSync('web/account.js','utf8'),failed);
 await failed.window.scoutAccount.start();failed.onDom();
 assert.equal(failed.window.scoutAccount.active,false);
 assert.equal(node('account-problem').hidden,false);
 assert.ok(!node('account-problem-text').textContent.includes('PRIVATE_CODE'));
 assert.equal(cleanedUrl,'/job-scout/?category=design');
 assert.equal(node('account-retry').textContent,'Try sign-in');
 await node('account-retry').click();assert.equal(oauthCalls,1);
 console.log('Account runtime checks passed: account separation, bound credentials, cloud saves, views, migration, failures and sign-out.');
})().catch(e=>{console.error(e);process.exitCode=1});
