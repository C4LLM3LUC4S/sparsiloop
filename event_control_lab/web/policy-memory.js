(() => {
 "use strict";
 const histories=new Map(), v2='sparsiloop-policy-history-v2';
 const clone=value=>JSON.parse(JSON.stringify(value));
 const ordered=value=>Array.isArray(value)?value.map(ordered):value && typeof value==='object'?
  Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])):value;
 const same=(left,right)=>JSON.stringify(ordered(left))===JSON.stringify(ordered(right));
 const checkpoint=value=>value.format==='sparsiloop-frozen-policy-v1'?value:value.checkpoint;
 function identity(value) {
  const saved=checkpoint(value);
  return JSON.stringify(ordered(Object.fromEntries(['training_config','training_seeds','source_sha256',
   'table','table_sha256','training_statuses','selection'].map(key=>[key,saved[key]]))));
 }
 function remember(value) {
  const key=identity(value), previous=histories.get(key);
  let advances=true;
  if(previous) {
   const used=new Set(checkpoint(value).previous_evaluation_seeds);
   advances=checkpoint(previous).previous_evaluation_seeds.every(seed=>used.has(seed));
   if(previous.format===v2)advances=advances && value.format===v2 && same(previous.origin,value.origin) &&
    previous.events.length<=value.events.length && previous.events.every((event,index)=>same(event,value.events[index]));
  }
  const kept=advances?clone(value):previous;
  histories.set(key,kept);
  return {value:clone(kept),retained:!advances,message:advances?'':
   '本次记录没有接在本页已有历史之后。复用按钮继续保留已有的后续历史；本次结果与下载仍按原记录保存。不同分支不会自动合并。'};
 }
 window.labPolicyMemory={remember};
})();
