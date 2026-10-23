(() => {
 "use strict";
 const form=document.querySelector("#planned-settings"), testForm=document.querySelector("#planned-test-settings");
 const maximum=8*1024*1024, previous={selection:false,test:false};
 const bundleFormat="sparsiloop-planned-bundle-v1";
 let defaults=null, latest=null, loaded=null, fileVersion=0, reading=false;
 const number=v=>v===null || v===undefined ? "无法计算" : Number(v).toFixed(6);
 const count=v=>v===null || v===undefined ? "无法计算" : new Intl.NumberFormat("zh-CN",{maximumFractionDigits:2}).format(v);
 const candidate=r=>r.policy==="periodic" ? "周期发送" : `${r.policy==="absolute"?"绝对门槛":"相对系数"} ${r.threshold}`;
 const statuses={complete:"完整结束",state_limit:"状态超限，提前停止",controller_error:"控制器出错",plant_error:"模型出错"};
 function node(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
 function list(raw,name,limit,integer=false,empty=false) {
  if(!raw.trim() && empty)return [];
  const pieces=raw.split(",").map(x=>x.trim()), values=pieces.map(Number);
  if(pieces.some(x=>!x || (integer && !/^\d+$/.test(x))) || values.length>limit ||
   values.some(x=>!Number.isFinite(x) || x<0 || x>(integer?2**32-1:2) || (integer && !Number.isSafeInteger(x))) ||
   new Set(values).size!==values.length)
   throw Error(`${name}请用英文逗号分隔，最多 ${limit} 个不重复的${integer?"整数种子":"门槛（0 到 2）"}`);
  return values;
 }
 function numeric(name) {
  const raw=form.elements[name].value.trim(), value=Number(raw);
  if(!raw || !Number.isFinite(value))throw Error("请把数字填完整，不要填 NaN 或无穷大");return value;
 }
 function specification() {
  if(!defaults)throw Error("默认方案还没加载好，请稍后再试，或刷新页面");
  const spec=JSON.parse(JSON.stringify(defaults));spec.config.plant=form.elements.plant.value;
  for(const name of ["duration","budget","initial_position","initial_velocity","delay_steps","loss_probability",
   "measurement_noise","process_noise","heartbeat","threshold","kp","kd","input_limit","state_limit"])spec.config[name]=numeric(name);
  spec.rmse_limit=numeric("rmse_limit");
  for(const name of ["absolute_thresholds","relative_thresholds"])spec[name]=list(form.elements[name].value,"候选门槛",8,false,true);
  spec.selection_seeds=list(form.elements.selection_seeds.value,"选择种子",5,true);
  spec.test_seeds=list(form.elements.test_seeds.value,"复核种子",5,true);
  spec.previously_used_seeds=list(form.elements.previously_used_seeds.value,"已用种子",512,true,true);return spec;
 }
 function table(headers,rows) {
  const wrap=node("div",undefined,"table-scroll"), value=node("table"), head=node("thead"), tr=node("tr");
  wrap.tabIndex=0;wrap.setAttribute("aria-label","结果表，可左右滚动");
  for(const label of headers)tr.append(node("th",label));head.append(tr);value.append(head);
  const body=node("tbody");for(const cells of rows){const row=node("tr");for(const cell of cells)row.append(node("td",String(cell)));body.append(row);}
  value.append(body);wrap.append(value);return wrap;
 }
 function button(text,action){const b=node("button",text);b.type="button";b.addEventListener("click",action);return b;}
 function conditions(record,testing,ran=true) {
  const section=node("div"), spec=record.spec, c=spec.config;
  const state=c.plant==="scalar"?`一阶模型，初始位置 ${c.initial_position}`:`位置—速度模型，初始位置 ${c.initial_position}、初始速度 ${c.initial_velocity}`;
  section.append(node("p",`${state}，目标位置 0；每次 ${c.duration} 秒、每步 ${c.dt} 秒，尝试发送上限 ${c.budget}，每次完整时段的位置 RMSE 要不超过 ${spec.rmse_limit}。`,"scope"));
  const stage=testing?(ran?"本次运行的复核种子":"预留复核种子（本次未运行）"):"本次选择种子";
  section.append(node("p",`${stage}：${(testing?spec.test_seeds:spec.selection_seeds).join(", ")}。${testing?"选择记录保持原样。":"预留复核种子："+spec.test_seeds.join(", ")+"，这一步还没有运行。"}`,"scope"));
  const details=node("details");details.append(node("summary","查看完整条件和记录编号"),node("p",`记录摘要：${record.record_sha256}`,"hint"),node("pre",JSON.stringify(spec,null,2)));
  section.append(details);return section;
 }
 function source(record,message) {
  loaded=record;reading=false;const raw=record?.format===bundleFormat?record.result:record;
  const sha=typeof raw?.record_sha256==="string"?raw.record_sha256.slice(0,12):"待校验";
  const environment=record?.format===bundleFormat && record.context?.selection?.state==="recorded" ?
   "带有选择时的环境记录。" : "原文件没有选择时的环境，复核后也会保留未知。";
  document.querySelector("#planned-record-source").textContent=`${message} ${environment} 记录：${sha}。复核时会检查完整内容、版本和选择规则。`;
  if(previous.test){const status=document.querySelector("#planned-test-status");status.className="";status.textContent="当前载入的选择记录已更新，下方仍是上次复核结果；请核对结果自身的条件和记录编号。";}
 }
 function runtimeView(result) {
  const details=node("details");details.append(node("summary","查看选择、复核和生成报告时的环境"));
  const describe=value=>{
   if(value?.state!=="recorded")return {not_recorded:"未记录，不能从当前电脑反推",not_requested:"尚未开始复核",not_run:"这次未运行测试"}[value?.state]||"未记录";
   const r=value.runtime;return `${r.python_implementation} ${r.python_version}；${r.os_family} / ${r.python_pointer_bits} 位 Python；SparsiLoop ${r.sparsiloop_version}`;
  };
  for(const [label,value] of [["选择时",result.context?.selection],["复核时",result.context?.test],
   ["这次生成报告时",result.report_runtime?{state:"recorded",runtime:result.report_runtime}:null]])
   details.append(node("p",`${label}：${describe(value)}。`,"scope"));
  details.append(node("p","环境相同也不保证浮点逐位一致；这些是程序自行记录的信息，不是来源认证。完整环境和记录时间会随 ZIP 保存。","hint"));return details;
 }
 function output(mode,result) {
  const record=result.record, choice=mode==="selection"?record:record.selection;
  const saved=result.selection_context?{format:bundleFormat,result:choice,context:result.selection_context}:choice;
  const target=document.querySelector(`#planned-${mode}-output`);target.replaceChildren();target.hidden=false;
  const names=new Map(choice.selection_summaries.map(r=>[r.id,candidate(r)]));
  if(mode==="selection") {
   target.append(node("h3",choice.selected_id?`按原先的规则选定：${names.get(choice.selected_id)}`:"这次没有候选满足要求"),conditions(choice,false));
   target.append(table(["候选","完整运行","各次 RMSE 的最大值","平均 RMSE","平均尝试发送","选择情况"],choice.selection_summaries.map(r=>[
    candidate(r),`${r.complete} / ${r.requested}`,number(r.all_runs_max_rmse),number(r.all_runs_mean_rmse),count(r.all_requested_mean_attempts),
    r.id===choice.selected_id?"按规则选定":r.eligible?"满足条件":"未满足要求"])));
   const failures=choice.selection_runs.filter(r=>r.run.status!=="complete");
   if(failures.length){target.append(node("p","提前停止的消息数只统计停下之前发了多少条，不能当作完成整个任务的通信开销。","scope"));const d=node("details");d.append(node("summary",`查看 ${failures.length} 次提前停止`),table(["候选","种子","运行情况","停止时间（秒）","原因"],
    failures.map(r=>[names.get(r.candidate_id),r.seed,statuses[r.run.status]||r.run.status,r.run.duration_completed,r.run.error||"—"])));target.append(d);}
   target.append(node("p",choice.selected_id?"下一步可以直接点击下面的复核按钮。候选、种子和条件已经保存在记录里，上方再改参数也不会改动它。":
    "没有合格候选，复核不会运行任何测试种子。先看提前停止或误差超限的原因，保留记录；如果要改方案，请把已看过的种子列入历史，再另存一份。","scope"));
   latest=saved;source(saved,"已保留刚才生成的完整选择记录。");++fileVersion;testForm.elements.selection.value="";
   if(previous.test)document.querySelector("#planned-test-status").textContent="选择记录已更新，下方仍是上一份记录的复核结果；它的条件和下载文件保持原样。";
  } else {
   const messages={met_declared_tests:"所选方案在这次每个复核种子下都完整结束，而且位置误差达标。",
    did_not_meet_declared_tests:"所选方案没有通过这次全部要求，仍保留原来的选择，没有改选。",
    not_run_no_eligible_choice:"选择阶段没有合格候选，这次没有运行任何测试种子。"};
   target.append(node("h3",messages[record.status]),conditions(choice,true,record.test_runs.length>0));
   target.append(table(["用途","方案","种子","运行情况","位置 RMSE","尝试发送","到达","原因"],record.test_runs.map(r=>[
    r.roles.length===2?"所选方案 / 周期对照":r.roles.includes("selected")?"所选方案":"周期对照",names.get(r.candidate_id),r.seed,
    statuses[r.run.status]||r.run.status,number(r.run.metrics.position_rmse),r.run.packets.attempted,r.run.packets.delivered,r.run.error||"—"])));
   target.append(node("p",record.test_runs.length?"先看有没有跑完，再看每个种子是否达标，以及实际用了多少条消息。周期对照沿用相同上限，不会按事件策略的实际流量改预算。若据此调参，这批数据就成了开发数据，后续需要另定方案。":
    "请回到选择结果，先查提前停止或误差超限的原因。保留这份未运行记录；若决定修改方案，请记下已经看过的种子，再另存一份新方案。","scope"));
  }
  const downloads=node("div",undefined,"downloads");
  downloads.append(button("下载这一步的完整报告 ZIP",()=>download(`sparsiloop-planned-${mode}-${Date.now()}.zip`,
   Uint8Array.from(atob(result.archive_base64),x=>x.charCodeAt(0)),"application/zip")),
   button("另存选择记录和运行环境",()=>download(saved.format===bundleFormat?"selection-bundle.json":"selection.json",JSON.stringify(saved,null,2),"application/json")));
  target.append(runtimeView(result),downloads,node("p","完整解压 ZIP 后打开 report.html。原始结果、全部候选或测试、轨迹、失败、条件和环境都在里面；这里的小数只作简短显示。","hint"));previous[mode]=true;
 }
 function invalid(mode,error) {
  const s=document.querySelector(`#planned-${mode}-status`);s.className="error";
  s.textContent=`这次没有生成新结果：${error.message}${previous[mode]?" 下方仍是上次结果及其原条件。":""}`;
  const d=document.querySelector(`#planned-${mode}-error`);d.hidden=!error.detail;d.querySelector("pre").textContent=error.detail||"";
 }
 async function execute(mode,value) {
  const body=JSON.stringify(value);if(new TextEncoder().encode(body).length>maximum)throw Error("完整记录超过网页的 8 MiB 限制，请用命令行复核");
  const s=document.querySelector(`#planned-${mode}-status`);s.className="";document.querySelector(`#planned-${mode}-error`).hidden=true;
  s.textContent=mode==="selection"?"正在比较全部候选，只使用选择种子…":"正在核对选择记录，再按原计划复核；不会重新选方案…";
  window.labUI.setBusy(true);
  try {
   const response=await fetch(`/api/planned/${mode==="selection"?"select":"test"}`,{method:"POST",headers:{"Content-Type":"application/json"},body});
   const result=await response.json();if(!response.ok){const e=Error(result.error||"没能生成新结果");e.detail=result.detail;throw e;}
   output(mode,result);s.textContent="这一步的记录已生成。先看是否跑完和是否达标，再决定下一步。";
  } catch(e){invalid(mode,e instanceof TypeError?Error("没能连接到本地服务，请确认终端还在运行"):e);}
  finally{window.labUI.setBusy(false);}
 }
 form.addEventListener("input",()=>{if(previous.selection){const status=document.querySelector("#planned-selection-status");status.className="";status.textContent="上方设置改了，下方仍是保存好的选择；再次运行才会生成新记录。复核仍沿用保存时的条件。";}});
 form.addEventListener("submit",async e=>{e.preventDefault();if(window.labUI.isBusy())return;try{await execute("selection",{spec:specification()});}catch(e){invalid("selection",e);}});
 testForm.addEventListener("submit",async e=>{e.preventDefault();if(window.labUI.isBusy())return;try{if(reading)throw Error("选择记录还在读取，请稍后再复核");if(!loaded)throw Error("请先运行选择阶段，或载入完整 selection.json");await execute("test",{selection:loaded});}catch(e){invalid("test",e);}});
 document.querySelector("#planned-use-latest").addEventListener("click",()=>{if(!latest){invalid("test",Error("请先运行一次选择阶段"));return;}++fileVersion;testForm.elements.selection.value="";source(latest,"已载入刚才生成的完整选择记录。");});
 testForm.elements.selection.addEventListener("change",async()=>{
  const version=++fileVersion, file=testForm.elements.selection.files[0];reading=false;if(!file)return;reading=true;
  try{if(file.size>maximum)throw Error("文件超过网页的 8 MiB 限制，请用命令行复核");const value=JSON.parse(await file.text());if(version!==fileVersion)return;
   if(value?.format!=="sparsiloop-planned-selection-v1" && !(value?.format===bundleFormat && value.context?.phase==="selection"))
    throw Error("请选择 selection-bundle.json 或原始 selection.json，方案和测试记录不能代替选择");source(value,`已读取 ${file.name}，尚未完成校验。`);
  }catch(e){if(version===fileVersion)invalid("test",e);}finally{if(version===fileVersion)reading=false;}
 });
 fetch("/api/planned/default").then(r=>{if(!r.ok)throw Error("默认方案加载失败，请刷新页面");return r.json();})
  .then(v=>{defaults=v;document.querySelector("#planned-selection-status").textContent="先把条件定好，再点击“只运行选择阶段”。";}).catch(e=>invalid("selection",e));
})();
