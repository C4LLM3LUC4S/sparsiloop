const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const copy=value=>JSON.parse(JSON.stringify(value));
function element(tag='div') {
 return {tag,children:[],value:'',dataset:{},files:[],textContent:'',hidden:false,handlers:{},
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}},
  replaceChildren(...nodes){this.children=[];this.append(...nodes);},
  addEventListener(type,callback){this.handlers[type]=callback;},setAttribute(){},focus(){},scrollIntoView(){},
  querySelector(){return this.pre||(this.pre=element('pre'));},querySelectorAll(){return [];}};
}
function page() {
 const nodes=new Map(), get=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);};
 for(const selector of ['#controller-settings','#saved-policy-settings','#planned-settings','#planned-test-settings']) {
  get(selector).elements=new Proxy({}, {get(target,key){return target[key]||(target[key]=element('input'));}});
 }
 get('#controller-settings').elements.method.value='ilc';
 get('#saved-policy-settings').elements.seeds.value='9001';
 get('#planned-settings').elements.controller_kind.value='linear';
 const listeners={}, downloads=[];let response;
 const window={addEventListener(type,callback){(listeners[type]||(listeners[type]=[])).push(callback);},
  dispatchEvent(event){for(const callback of listeners[event.type]||[])callback(event);},
  labUI:{isBusy:()=>false,setBusy(){}}};
 const scope={window,document:{querySelector:get,createElement:element},TextEncoder,
  CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
  download:(name,content,type)=>downloads.push({name,content,type}),
  fetch:async(url,options)=>options?{ok:true,json:async()=>response}:{ok:true,json:async()=>url==='/api/planned/default'?{config:{}}:{mfac:{phi0:1,rho:1}}}};
 const context=vm.createContext(scope), folder=path.join(__dirname,'../event_control_lab/web');
 vm.runInContext(fs.readFileSync(path.join(folder,'policy-memory.js'),'utf8'),context);
 window.labUI.rememberPolicy=value=>{
  const result=window.labPolicyMemory.remember(value);
  window.dispatchEvent({type:'sparsiloop-policy-saved',detail:result.value});return result;
 };
 for(const script of ['controllers.js','planned.js'])vm.runInContext(fs.readFileSync(path.join(folder,script),'utf8'),context);
 return {get,downloads,
  async show(result){response=result;window.dispatchEvent({type:'sparsiloop-standalone-policy',detail:result.checkpoint});
   await get('#saved-policy-settings').handlers.submit({preventDefault(){}});},
  async showPlan(result){response=result;const file=get('#planned-test-settings').elements.selection;
   file.files=[{name:'selection.json',size:100,text:async()=>JSON.stringify(result.record.selection)}];
   await file.handlers.change();await get('#planned-test-settings').handlers.submit({preventDefault(){}});},
  async showSelection(result){await new Promise(resolve=>setImmediate(resolve));response=result;
   const input=get('#planned-settings').elements;
   for(const name of ['duration','budget','initial_position','initial_velocity','delay_steps','loss_probability',
    'measurement_noise','process_noise','heartbeat','threshold','kp','kd','input_limit','state_limit','rmse_limit'])input[name].value='1';
   input.absolute_thresholds.value='0.1';input.relative_thresholds.value='';
   input.selection_seeds.value='5001';input.test_seeds.value='6001';input.previously_used_seeds.value='';
   await get('#planned-settings').handlers.submit({preventDefault(){}});},
  text(selector){const visit=node=>[node,...node.children.flatMap(visit)];return visit(get(selector)).map(node=>node.textContent).join('\n');},
  find(selector,label){const visit=node=>[node,...node.children.flatMap(visit)];
   return visit(get(selector)).find(node=>node.tag==='button'&&node.textContent===label);}};
}
function checkpoint(ids=[1001]) {
 return {format:'sparsiloop-frozen-policy-v1',training_config:{plant:'scalar',dt:0.02,duration:0.2,input_limit:4},
  training_seeds:[101,102],source_sha256:{engine:'fixture'},table:{values:[0,1]},table_sha256:'fixture-table',
  training_statuses:['complete','complete'],selection:'final table',previous_evaluation_seeds:ids,
  evaluation_config:{plant:'scalar',duration:0.2,dt:0.02}};
}
function history(events) {return {format:'sparsiloop-policy-history-v2',origin:checkpoint(),
 checkpoint:checkpoint([1001,...events.flatMap(e=>e.seeds)]),events:copy(events)};}
function result(saved) {return {mode:'evaluation',specification:{duration:0.2,dt:0.02},rows:[],archive_base64:'',
 checkpoint:saved.format==='sparsiloop-frozen-policy-v1'?saved:saved.checkpoint,
 ...(saved.format==='sparsiloop-frozen-policy-v1'?{}:{policy_history:saved})};}
const plannedPhases=[{phase:'selection',seeds:[5001]},{phase:'test',seeds:[6001]}];
function plannedResult(saved) {
 const config={...checkpoint().training_config,initial_position:1,initial_velocity:0,budget:5};
 const selection={format:'sparsiloop-planned-policy-selection-v1',record_sha256:'fixture-selection',
  spec:{config,selection_seeds:[5001],test_seeds:[6001],rmse_limit:1},selected_id:null,
  selection_summaries:[],policy_before:{}};
 return {mode:'test',record:{selection,status:'not_run_no_eligible_choice',test_runs:[]},policy_history:saved,
  context:{},archive_base64:''};
}

test('the primary continuation download retains full phases; compatibility is secondary',async()=>{
 const p=page(), saved=history([{phase:'evaluation',seeds:[9001]}]);await p.show(result(saved));
 const primary=p.find('#saved-policy-output','保存完整历史，下次接着做');assert.ok(primary);
 primary.handlers.click();assert.equal(p.downloads[0].name,'policy-history.json');
 assert.deepEqual(JSON.parse(p.downloads[0].content),saved);
 const compatible=p.find('#saved-policy-output','保存兼容策略文件');assert.equal(compatible.parent.tag,'details');
 compatible.handlers.click();assert.deepEqual(JSON.parse(p.downloads[1].content),saved.checkpoint);
});
test('an older result downloads the retained later history without rewriting that result',async()=>{
 const p=page(), old=history(plannedPhases), later=history([...plannedPhases,{phase:'evaluation',seeds:[9004]}]);
 const replay=result(old), original=JSON.stringify(replay);await p.show(result(later));await p.show(replay);
 p.find('#saved-policy-output','保存完整历史，下次接着做').handlers.click();
 assert.deepEqual(JSON.parse(p.downloads[0].content),later);assert.equal(JSON.stringify(replay),original);
});
test('a checkpoint-only result stays a checkpoint and its old button stays bound to that result',async()=>{
 const p=page(), first=checkpoint();await p.show(result(first));
 const oldButton=p.find('#saved-policy-output','保存策略，下次开始测试');assert.ok(oldButton);
 assert.equal(p.find('#saved-policy-output','保存完整历史，下次接着做'),undefined);
 const another=checkpoint();another.table.values[0]=3;another.table_sha256='other';await p.show(result(another));
 oldButton.handlers.click();assert.equal(p.downloads[0].name,'policy-checkpoint.json');
 assert.deepEqual(JSON.parse(p.downloads[0].content),first);
});
test('a separate older branch cannot label a retained flat checkpoint as full history',async()=>{
 const p=page(), flat=checkpoint([2001]);await p.show(result(flat));await p.show(result(history(plannedPhases)));
 assert.equal(p.find('#saved-policy-output','保存完整历史，下次接着做'),undefined);
 p.find('#saved-policy-output','保存策略，下次开始测试').handlers.click();
 assert.deepEqual(JSON.parse(p.downloads[0].content),flat);
});
test('planned continuation download uses later page history while preserving the replay record',async()=>{
 const p=page(), later=history([...plannedPhases,{phase:'evaluation',seeds:[9004]}]);
 await p.show(result(later));const replay=plannedResult(history(plannedPhases)), original=JSON.stringify(replay);
 await p.showPlan(replay);const primary=p.find('#planned-test-output','保存完整历史，做下一个任务');assert.ok(primary);
 primary.handlers.click();assert.deepEqual(JSON.parse(p.downloads[0].content),later);
 assert.equal(JSON.stringify(replay),original);
 p.find('#planned-test-output','保存兼容策略文件（不含完整阶段顺序）').handlers.click();
 assert.deepEqual(JSON.parse(p.downloads[1].content),later.checkpoint);
});
test('planned fallback describes an existing checkpoint honestly without fabricating phases',async()=>{
 const p=page(), flat=checkpoint([2001]);await p.show(result(flat));await p.showPlan(plannedResult(history(plannedPhases)));
 assert.equal(p.find('#planned-test-output','保存完整历史，做下一个任务'),undefined);
 p.find('#planned-test-output','保存页面保留的策略文件').handlers.click();
 assert.equal(p.downloads[0].name,'policy-checkpoint.json');assert.deepEqual(JSON.parse(p.downloads[0].content),flat);
});
test('showing a recipe without a policy does not discard the reusable saved policy',async()=>{
 const p=page(), saved=history([{phase:'evaluation',seeds:[9001]}]);await p.show(result(saved));
 await p.show({mode:'recipes',specification:{config:{duration:0.2,dt:0.02}},rows:[],archive_base64:''});
 p.get('#use-latest-policy').handlers.click();
 assert.match(p.get('#saved-policy-source').textContent,/已载入本页最新/);
 assert.notEqual(p.get('#saved-policy-status').className,'error');
 assert.equal(p.find('#saved-policy-output','保存完整历史，下次接着做'),undefined);
});

function selectedResult(eligible=true) {
 const saved=history([{phase:'selection',selected_id:eligible?'event':null,plan:{test_seeds:[6001]},seeds:[5001]}]);
 const value=plannedResult(saved), choice=value.record.selection;
 choice.selected_id=eligible?'event':null;choice.selection_runs=[];
 choice.selection_summaries=eligible?[{id:'event',policy:'absolute',threshold:0.1,eligible:true,complete:1,requested:1}]:[];
 return {...value,mode:'selection',record:choice};
}

test('a pending selection keeps the original choice as the next action and withholds the standalone shortcut',async()=>{
 const p=page(), value=selectedResult();await p.showSelection(value);
 const choice=p.find('#planned-selection-output','保存选择记录，下次按原计划复核');assert.ok(choice);
 choice.handlers.click();assert.deepEqual(JSON.parse(p.downloads[0].content),value.record);
 assert.ok(p.find('#planned-selection-output','保存完整历史（还有待复核计划）'));
 assert.equal(p.find('#planned-selection-output','载入上方的单独测试'),undefined);
 assert.equal(p.find('#planned-selection-output','保存兼容策略文件（不含完整阶段顺序）'),undefined);
 assert.match(p.text('#planned-selection-output'),/完整历史不能代替/);
});

test('a selection with no eligible candidate does not invent a pending test',async()=>{
 const p=page();await p.showSelection(selectedResult(false));
 assert.ok(p.find('#planned-selection-output','保存完整历史，做下一个任务'));
 assert.equal(p.find('#planned-selection-output','保存完整历史（还有待复核计划）'),undefined);
 assert.match(p.text('#planned-selection-output'),/没有待运行的复核/);
});

test('replaying an old selection follows the retained completed history without replacing its saved choice',async()=>{
 const p=page(), selected=selectedResult();
 const completed=history([...selected.policy_history.events,{phase:'test',plan:{test_seeds:[6001]},seeds:[6001]}]);
 await p.show(result(completed));await p.showSelection(selected);
 p.find('#planned-selection-output','保存完整历史，做下一个任务').handlers.click();
 assert.deepEqual(JSON.parse(p.downloads[0].content),completed);
 assert.ok(p.find('#planned-selection-output','载入上方的单独测试'));
 p.find('#planned-selection-output','保存选择记录，下次按原计划复核').handlers.click();
 assert.deepEqual(JSON.parse(p.downloads[1].content),selected.record);
});

test('a later pending plan stays pending when an earlier completed result is shown again',async()=>{
 const p=page(), earlier=history(plannedPhases);
 const later=history([...plannedPhases,{phase:'selection',selected_id:'later',plan:{test_seeds:[6002]},seeds:[5002]}]);
 await p.show(result(later));await p.showPlan(plannedResult(earlier));
 const save=p.find('#planned-test-output','保存完整历史（还有待复核计划）');assert.ok(save);
 save.handlers.click();assert.deepEqual(JSON.parse(p.downloads[0].content),later);
 assert.equal(p.find('#planned-test-output','载入上方的单独测试'),undefined);
 assert.match(p.text('#planned-test-output'),/那次选择/);
});
