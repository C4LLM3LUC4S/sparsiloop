const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'../event_control_lab/web/policy-memory.js'),'utf8');
const copy=value=>JSON.parse(JSON.stringify(value));
function memory(){const scope={window:{}};vm.runInNewContext(script,scope);return scope.window.labPolicyMemory;}
function checkpoint(seeds=[1001]) {
 return {format:'sparsiloop-frozen-policy-v1',training_config:{dt:0.02,duration:0.2,input_limit:4},
  training_seeds:[101,102],source_sha256:{engine:'fixture'},table:{values:[0,1]},table_sha256:'fixture-table',
  training_statuses:['complete','complete'],selection:'final table',previous_evaluation_seeds:seeds,
  evaluation_config:{delay_steps:2}};
}
function history(events,origin=checkpoint()) {
 return {format:'sparsiloop-policy-history-v2',origin:copy(origin),checkpoint:checkpoint([1001,...events.flatMap(e=>e.seeds)]),
  events:copy(events)};
}
const plan=[{phase:'selection',seeds:[5001]},{phase:'test',seeds:[6001]}];

test('repeating an original choice keeps the later evaluation available',()=>{
 const page=memory(), chosen=history(plan), later=history([...plan,{phase:'evaluation',seeds:[9004]}]);
 page.remember(chosen);page.remember(later);
 const replay=page.remember(chosen);
 assert.equal(replay.retained,true);
 assert.deepEqual(copy(replay.value),later);
 assert.match(replay.message,/不同分支不会自动合并/);
});
test('a completed new phase advances without modifying the supplied files',()=>{
 const page=memory(), previous=history(plan), later=history([...plan,{phase:'evaluation',seeds:[9004]}]);
 const original=JSON.stringify(previous);
 page.remember(previous);
 const result=page.remember(later);
 assert.equal(result.retained,false);
 result.value.events.length=0;
 assert.equal(page.remember(previous).value.events.length,3);
 assert.equal(JSON.stringify(previous),original);
});
test('branches with additional different IDs are preserved separately, never merged',()=>{
 const page=memory(), first=history([...plan,{phase:'evaluation',seeds:[9004]}]);
 page.remember(first);
 const branch=history([...plan,{phase:'evaluation',seeds:[9005]}]);
 const result=page.remember(branch);
 assert.equal(result.retained,true);
 assert.deepEqual(copy(result.value),first);
 assert.equal(result.value.checkpoint.previous_evaluation_seeds.includes(9005),false);
});
test('a flattened checkpoint cannot replace complete chronological history',()=>{
 const page=memory(), complete=history(plan);
 page.remember(complete);
 const result=page.remember(checkpoint([1001,5001,6001,9004]));
 assert.equal(result.retained,true);
 assert.deepEqual(copy(result.value),complete);
});
test('different clocks or tables have distinct page histories',()=>{
 const page=memory(), first=history(plan), other=history([{phase:'evaluation',seeds:[9004]}]);
 page.remember(first);
 other.checkpoint.table.values[1]=2;
 assert.equal(page.remember(other).retained,false);
 const clock=history([]);clock.checkpoint.training_config.dt=0.04;
 assert.equal(page.remember(clock).retained,false);
 assert.equal(page.remember(first).retained,false);
});
test('reordered JSON keys preserve identity, but rewritten chronology does not',()=>{
 const page=memory(), first=history(plan);
 page.remember(first);
 const reordered=copy(first);
 reordered.checkpoint.training_config={input_limit:4,duration:0.2,dt:0.02};
 assert.equal(page.remember(reordered).retained,false);
 const changed=history([{phase:'evaluation',seeds:[5001,6001]}]);
 assert.equal(page.remember(changed).retained,true);
 const newOrigin=history(plan);newOrigin.origin.previous_evaluation_seeds=[1001,1002];
 assert.equal(page.remember(newOrigin).retained,true);
});
test('changed evaluation network conditions do not invent a new training identity',()=>{
 const page=memory(), first=history(plan), next=history([...plan,{phase:'evaluation',seeds:[9004]}]);
 page.remember(first);next.checkpoint.evaluation_config.delay_steps=3;
 assert.equal(page.remember(next).retained,false);
});
