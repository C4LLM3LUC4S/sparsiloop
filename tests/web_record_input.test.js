const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../event_control_lab/web/planned.js'),'utf8');
function element(){return {value:'',dataset:{},files:[],textContent:'',hidden:false,handlers:{},
 addEventListener(type,callback){this.handlers[type]=callback;},querySelector(){return this.pre||(this.pre=element());}};}
function setup() {
 const nodes=new Map(), get=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);};
 const form=get('#planned-settings'), testForm=get('#planned-test-settings');
 form.elements={controller_kind:element(),plant:element(),duration:element(),input_limit:element(),policy_file:element()};
 form.elements.controller_kind.value='linear';testForm.elements={selection:element()};
 const posts=[], scope={document:{querySelector:get},TextEncoder,
  window:{labUI:{isBusy:()=>false,setBusy(){}},addEventListener(){}},
  fetch:async(url,options)=>{
   if(options){posts.push(JSON.parse(options.body));return {ok:false,json:async()=>({error:'Fixture stops before backend execution'})};}
   return {ok:true,json:async()=>({})};
  }};
 vm.runInNewContext(source,scope);
 return {get,posts,file:testForm.elements.selection,
  async choose(file){testForm.elements.selection.files=file?[file]:[];await testForm.elements.selection.handlers.change();},
  async submit(){await testForm.handlers.submit({preventDefault(){}});}};
}
const record=id=>({format:'sparsiloop-planned-selection-v1',record_sha256:id});
const file=(id,body=JSON.stringify(record(id)))=>({name:id+'.json',size:body.length,text:async()=>body});

test('invalid replacement JSON does not submit the earlier active selection',async()=>{
 const page=setup();await page.choose(file('old'));
 page.get('#planned-test-output').textContent='retained earlier report';
 await page.choose(file('invalid','{invalid'));await page.submit();
 assert.equal(page.posts.length,0);
 assert.equal(page.get('#planned-test-output').textContent,'retained earlier report');
 assert.match(page.get('#planned-record-source').textContent,/尚未载入/);
});
test('an oversize replacement is refused without reading it or running the earlier selection',async()=>{
 const page=setup();await page.choose(file('old'));let read=false;
 await page.choose({name:'large.json',size:8*1024*1024+1,text:async()=>{read=true;return '{}';}});
 await page.submit();assert.equal(read,false);assert.equal(page.posts.length,0);
});
test('a slow replaced read cannot overwrite the newer selection; valid recovery uses the new record',async()=>{
 const page=setup();await page.choose(file('old'));let resolve;
 const pending=page.choose({name:'slow.json',size:20,text:()=>new Promise(done=>{resolve=done;})});
 await page.submit();assert.equal(page.posts.length,0);
 await page.choose(file('new'));resolve(JSON.stringify(record('slow')));await pending;
 await page.submit();assert.equal(page.posts.length,1);
 assert.equal(page.posts[0].selection.record_sha256,'new');
});
test('wrong file purpose clears active input and a later valid file can recover',async()=>{
 const page=setup();await page.choose(file('old'));
 await page.choose(file('test',JSON.stringify({format:'sparsiloop-policy-workflow-v1',phase:'test'})));
 await page.submit();assert.equal(page.posts.length,0);
 await page.choose(file('recovered'));await page.submit();
 assert.equal(page.posts.length,1);assert.equal(page.posts[0].selection.record_sha256,'recovered');
});
