(() => {
 "use strict";
 const form = document.querySelector("#controller-settings");
 const savedForm = document.querySelector("#saved-policy-settings");
 let defaults = null, latest = null, loaded = null, fileVersion = 0;
 const previous = {controller: false, "saved-policy": false};
 const stages = {online:"边运行边估计", trial:"重复执行任务", training:"训练过程",
  evaluation_trained:"测试：训练后的策略", evaluation_untrained:"测试：未训练的策略",
  evaluation_linear_feedback:"测试：固定反馈控制"};
 const policies = {periodic:"周期发送", absolute:"绝对变化触发", relative:"相对变化触发"};
 const statuses = {complete:"完整结束", state_limit:"状态超限，提前停止", controller_error:"控制器出错", plant_error:"模型出错"};
 const numeric = name => {
  const raw = form.elements[name].value.trim(), value = Number(raw);
  if (!raw || !Number.isFinite(value)) throw Error("请把数字填完整，不要使用 NaN 或无穷大");
  return value;
 };
 function seeds(raw) {
  const pieces = raw.split(",").map(x=>x.trim());
  if (pieces.some(x=>!/^\d+$/.test(x))) throw Error("种子要填非负整数，用英文逗号分隔，中间不要留空项");
  const result = pieces.map(Number);
  if (result.length < 1 || result.length > 5 || result.some(x=>!Number.isSafeInteger(x) || x >= 2**32) || new Set(result).size !== result.length)
   throw Error("一次请填 1–5 个不同的种子，范围是 0 到 4294967295");
  return result;
 }
 function showMethod() {
  for (const group of form.querySelectorAll("[data-method]")) {
   group.hidden = form.elements.method.value !== "all" && form.elements.method.value !== group.dataset.method;
   group.disabled = group.hidden;
  }
 }
 function stale(prefix) {
  if (previous[prefix]) {
   const status = document.querySelector(`#${prefix}-status`);
   status.textContent = "设置已修改，下方仍是上次成功生成的结果；再次运行后才会更新。";
   status.className = "";
  }
 }
 form.addEventListener("input",()=>{showMethod();stale("controller");});
 savedForm.addEventListener("input",()=>stale("saved-policy"));
 showMethod();

 function specification() {
  const spec = JSON.parse(JSON.stringify(defaults));
  spec.config.duration = numeric("duration");
  spec.config.budget = Math.round(spec.config.duration / spec.config.dt);
  spec.config.initial_position = numeric("initial_position");
  const method = form.elements.method.value;
  if (method === "all" || method === "mfac") {spec.mfac.phi0 = numeric("phi0"); spec.mfac.rho = numeric("rho");}
  if (method === "all" || method === "ilc") {spec.ilc_trials = numeric("ilc_trials"); spec.ilc_gain = numeric("ilc_gain");}
  if (method === "all" || method === "rl") {
  const start = numeric("training_start"), count = numeric("training_count");
  if (!Number.isInteger(start) || start < 0 || !Number.isInteger(count) || count < 1 || count > 128 || start + count > 2**32)
   throw Error("训练种子数量要在 1 到 128 之间，起始编号及生成的编号也要在种子范围内");
  spec.training_seeds = Array.from({length:count},(_,i)=>start+i);
  spec.evaluation_seeds = seeds(form.elements.evaluation_seeds.value);
  spec.evaluation_config = {...spec.config,
   budget:Math.floor(spec.config.budget * numeric("budget_fraction")),
   delay_steps:numeric("delay_steps"), loss_probability:numeric("loss_probability"),
   measurement_noise:0.005, process_noise:0.01};
  }
  return spec;
 }
 function element(tag, text, className) {
  const node = document.createElement(tag); if (text !== undefined) node.textContent = text;
  if (className) node.className = className; return node;
 }
 function resultTable(rows) {
  const wrapper = element("div", undefined, "table-scroll"); wrapper.tabIndex = 0;
  const table = element("table"), head = element("thead"), header = element("tr");
  for (const label of ["方法","阶段","轮次 / 种子","发送策略","运行情况","位置误差 RMSE","尝试发送","到达","停止时间 / 原因"])
   header.append(element("th", label));
  head.append(header); table.append(head); const body = element("tbody");
  for (const row of rows) {
   const tr = element("tr");
   if (row.status !== "complete") tr.className = "failed";
   for (const value of [row.method.toUpperCase(), stages[row.stage] || row.stage, row.trial_or_seed,
    policies[row.policy], statuses[row.status] || row.status,
    row.position_rmse === null ? "无法计算" : Number(row.position_rmse).toFixed(6),
    row.packets.attempted, row.packets.delivered,
    row.status === "complete" ? "—" : `${row.duration_completed} 秒；${row.error || row.status}`])
    tr.append(element("td", String(value)));
   body.append(tr);
  }
  table.append(body); wrapper.append(table); return wrapper;
 }
 function button(label, action) {
  const node = element("button", label); node.type="button"; node.addEventListener("click", action); return node;
 }
 function display(prefix, result) {
  const output = document.querySelector(`#${prefix}-output`); output.replaceChildren(); output.hidden = false;
  const training = result.rows.filter(row=>row.stage==="training"), shown = result.rows.filter(row=>row.stage!=="training");
  const failures = result.rows.filter(row=>row.status!=="complete").length;
  const config = result.mode === "recipes" ? result.specification.config : result.specification;
  output.append(element("h3",result.mode === "recipes" ? "这次运行得到什么？" : "保存的策略，在新种子下表现怎样？"));
  output.append(element("p",`这份结果每次模拟 ${config.duration} 秒，每步 ${config.dt} 秒；共有 ${training.length} 次训练、${shown.length} 条运行或测试结果，${failures} 项没有跑完。失败项保留，不能算的分数也没有填零。`,"scope"));
  output.append(resultTable(shown));
  if (training.length) {
   const details = element("details"); details.append(element("summary",`查看全部 ${training.length} 次训练（不是测试成绩）`),resultTable(training)); output.append(details);
  }
  const downloads = element("div", undefined, "downloads");
  downloads.append(button("下载完整报告 ZIP",()=>{
   const bytes = Uint8Array.from(atob(result.archive_base64),x=>x.charCodeAt(0));
   download(`sparsiloop-${prefix}-${Date.now()}.zip`,bytes,"application/zip");
  }));
  if (result.checkpoint) downloads.append(button("另存策略，留到下次测试",()=>download("policy-checkpoint.json",JSON.stringify(result.checkpoint,null,2),"application/json")));
  output.append(downloads, element("p","ZIP 要完整解压，再打开 report.html。设置、每轮轨迹、失败和原始结果都在里面；下载后可以关掉网页再阅读。","hint"));
  output.append(element("p",failures ? "下一步先看哪些运行没跑完，以及停止时间和原因。改条件后另存一份结果，保留这次失败。" :
   "先在同一种方法、同一组条件下比较误差和实际消息数。ILC 可以看前后轮次；强化学习要看测试阶段，训练成绩不能代替测试，也不要把不同方法直接排成总榜。","scope"));
  latest = result.checkpoint || null;
  if(prefix === "saved-policy" && result.checkpoint) {
   loaded=result.checkpoint;
   document.querySelector("#saved-policy-source").textContent="当前页面已记住这次用过的测试种子。下次打开网页时要接着用，请另存新版策略。";
  }
  previous[prefix] = true;
 }
 async function execute(prefix,path,payload) {
  const status = document.querySelector(`#${prefix}-status`);
  const details = document.querySelector(`#${prefix}-error`); details.hidden=true;
  window.labUI.setBusy(true); status.className="";
  status.textContent = prefix === "controller" ? "正在运行实验并整理报告，请稍等…" : "正在加载保存的策略并测试；这次不会训练…";
  try {
   const response = await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
   const result = await response.json();
   if (!response.ok) {const error=Error(result.error || "实验没能生成结果");error.detail=result.detail;throw error;}
   display(prefix,result); status.textContent="新结果已生成。先核对有没有没跑完的项目，再看分数。";
  } catch (error) {
   const message=error instanceof TypeError ? "没能连接到本地服务，请确认终端还在运行" : error.message;
   status.textContent=`这次没有生成新结果：${message}${previous[prefix] ? " 下方仍是上次结果。" : ""}`;
   details.hidden=!error.detail;details.querySelector("pre").textContent=error.detail || "";
   status.className="error";
  } finally {window.labUI.setBusy(false);}
 }
 function invalid(prefix,error) {
  document.querySelector(`#${prefix}-error`).hidden=true;
  const node=document.querySelector(`#${prefix}-status`); node.className="error";
  node.textContent=`还没有开始运行：${error.message}。${previous[prefix] ? "下方仍是上次结果。" : ""}`;
 }
 form.addEventListener("submit",async event=>{
  event.preventDefault(); if(window.labUI.isBusy())return;
  try {if(!defaults)throw Error("默认设置还没有加载好，请刷新页面再试");
   await execute("controller","/api/controllers",{method:form.elements.method.value,spec:specification()});
  } catch(error){invalid("controller",error);}
 });
 savedForm.elements.checkpoint.addEventListener("change",async()=>{
  const version=++fileVersion;
  loaded=null; const node=document.querySelector("#saved-policy-source"), file=savedForm.elements.checkpoint.files[0];
  if(!file){node.textContent="还没有选择策略文件。";return;}
  try {
   if(file.size > 2*1024*1024)throw Error("文件超过网页的 2 MiB 限制，请用命令行加载");
   const value=JSON.parse(await file.text());
   if(version!==fileVersion)return;
   if(value?.format!=="sparsiloop-frozen-policy-v1")throw Error("请选择完整的 policy-checkpoint.json，旧的原始 Q 表不够");
   loaded=value; node.textContent=`已选择 ${file.name}。运行前还会检查参数、来源摘要和种子。`;
  } catch(error){if(version!==fileVersion)return;node.textContent="这个文件还不能用于测试。";invalid("saved-policy",error);}
 });
 document.querySelector("#use-latest-policy").addEventListener("click",()=>{
  if(!latest){invalid("saved-policy",Error("请先运行一次强化学习，或选择保存好的策略文件"));return;}
  ++fileVersion;loaded=latest; savedForm.elements.checkpoint.value="";stale("saved-policy");
  document.querySelector("#saved-policy-source").textContent="已载入刚才成功实验保存的策略，包括已用过的测试种子。";
 });
 savedForm.addEventListener("submit",async event=>{
  event.preventDefault();if(window.labUI.isBusy())return;
  try {if(!loaded)throw Error("请先选择一个完整策略文件");
   await execute("saved-policy","/api/evaluate-policy",{checkpoint:loaded,seeds:seeds(savedForm.elements.seeds.value)});
  } catch(error){invalid("saved-policy",error);}
 });
 fetch("/api/controllers/default").then(r=>{if(!r.ok)throw Error("默认设置没有加载成功");return r.json();}).then(value=>{
  defaults=value; form.elements.phi0.value=value.mfac.phi0;form.elements.rho.value=value.mfac.rho;
  document.querySelector("#controller-status").textContent="选好方法和参数后，点击运行即可。";
 }).catch(error=>invalid("controller",error));
})();
