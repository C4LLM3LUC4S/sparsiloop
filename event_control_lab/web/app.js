"use strict";
const names={periodic:"均匀周期发送",absolute:"绝对变化触发",relative:"相对变化触发"};
const colors={periodic:"#326c91",absolute:"#d59338",relative:"#34806a"};
const form=document.querySelector("#settings"), statusNode=document.querySelector("#status");
let experiment=null, defaults=null, busy=false;
const number=x=>x===null?"—":Number(x).toFixed(4);
function labels(){
 document.querySelector("#budget-value").textContent=`${form.elements.budget.value} 次`;
 document.querySelector("#delay-value").textContent=`${Math.round(Number(form.elements.delay_steps.value)*(defaults?.dt??0.02)*1000)} ms`;
 document.querySelector("#loss-value").textContent=`${Math.round(Number(form.elements.loss_probability.value)*100)}%`;
}
form.addEventListener("input",()=>{labels();if(experiment){statusNode.textContent="参数已修改，图表仍为上次运行";statusNode.className="";}document.dispatchEvent(new Event("lab-config-edited"));});
function currentConfig(){
 if(!defaults)return null;
 const config={...defaults};
 for(const [key,value] of new FormData(form))config[key]=key==="plant"?value:Number(value);
 return config;
}
function setBusy(value){
 busy=value;
 document.querySelectorAll("form input,form select,form button").forEach(node=>node.disabled=value || node.dataset.locked==="true");
}
function rememberPolicy(value) {
 const result=window.labPolicyMemory.remember(value);
 window.dispatchEvent(new CustomEvent('sparsiloop-policy-saved',{detail:result.value}));
 return result;
}
window.labUI={config:currentConfig,setBusy,isBusy:()=>busy,rememberPolicy};
async function run(event){
 if(event)event.preventDefault();
 if(!defaults||busy)return;
 const config=currentConfig();
 setBusy(true); statusNode.textContent="正在计算…";statusNode.className="";
 try{
  const response=await fetch("/api/compare",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(config)});
  const result=await response.json();if(!response.ok)throw Error(result.error||"运行失败");
  experiment=result;render();statusNode.textContent="结果已更新；请核对各策略是否跑完";
  document.querySelector("#download-json").disabled=false;document.querySelector("#download-csv").disabled=false;
 }catch(error){statusNode.textContent=`这次没有生成新结果：${error.message}${experiment?"。下方仍是上次结果":""}。请检查设置；连接中断时，确认终端仍在运行后刷新页面。`;statusNode.className="error";}
 finally{setBusy(false);}
}
function render(){
 const cfg=experiment.config;
 document.querySelector("#scope").textContent=`这次实验：最多 ${cfg.budget} 次发送，延迟 ${Math.round(cfg.delay_steps*cfg.dt*1000)} ms，丢包 ${Math.round(cfg.loss_probability*100)}%，种子 ${cfg.seed}。模拟 ${cfg.duration} 秒，三种策略使用相同的噪声和丢包随机数。发送上限相同，实际次数请看下方。`;
 const cards=document.querySelector("#cards"), ledger=document.querySelector("#ledger"), legend=document.querySelector("#legend");
 cards.replaceChildren();ledger.replaceChildren();legend.replaceChildren();
 for(const run of experiment.runs){
  const card=document.createElement("article");card.className="card";card.style.setProperty("--policy-color",colors[run.policy]);
  const title=document.createElement("div");title.className="card-title";title.textContent=names[run.policy];card.append(title);
  const metric=document.createElement("div");
  const label=document.createElement("div");label.className="metric-label";label.textContent="位置误差（RMSE）· 越小越好";
  const value=document.createElement("div");value.className="number";value.textContent=number(run.metrics.position_rmse);
  const caption=document.createElement("p");caption.className="card-caption";
  if(run.status!=="complete"){caption.textContent=`在 ${run.duration_completed.toFixed(2)} 秒停止，未纳入完整时段比较`;caption.classList.add("failed");}
  else caption.textContent=run.metrics.mean_observation_age===null?"全程没有收到有效测量":`收到第一条测量后，控制器所用测量平均已过去 ${(run.metrics.mean_observation_age*1000).toFixed(0)} ms`;
  metric.append(label,value,caption);card.append(metric);
  const count=document.createElement("div");count.className="card-count";
  const strong=document.createElement("strong");strong.textContent=String(run.packets.attempted);count.append(strong,` / ${cfg.budget} 次尝试发送（含丢包）`);
  const used=document.createElement("p");used.className="card-caption";used.textContent=`${run.metrics.requests_blocked_by_budget} 次请求因发送次数用完而未发出`;count.append(used);card.append(count);cards.append(card);
  const row=document.createElement("tr");
  for(const text of [names[run.policy],run.packets.attempted,run.packets.delivered,run.packets.dropped,run.packets.in_flight,run.metrics.controller_evaluations,run.metrics.norm_checks]){
   const cell=document.createElement("td");cell.textContent=String(text);row.append(cell);
  }ledger.append(row);
  const key=document.createElement("span");key.style.setProperty("--policy-color",colors[run.policy]);key.textContent=names[run.policy];legend.append(key);
 } draw();
}
function draw(){
 if(!experiment)return;
 const canvas=document.querySelector("#trajectory"), ctx=canvas.getContext("2d");
 const box=canvas.getBoundingClientRect(), ratio=window.devicePixelRatio||1;
 canvas.width=Math.round(box.width*ratio);canvas.height=Math.round(box.height*ratio);ctx.scale(ratio,ratio);
 const width=box.width,height=box.height,pad={left:48,right:15,top:15,bottom:32};
 const values=experiment.runs.flatMap(run=>run.trajectory.map(row=>row.state[0]));
 let lo=Math.min(0,...values),hi=Math.max(0.1,...values);const margin=(hi-lo)*.08;lo-=margin;hi+=margin;
 const x=t=>pad.left+(width-pad.left-pad.right)*t/experiment.config.duration;
 const y=value=>pad.top+(height-pad.top-pad.bottom)*(hi-value)/(hi-lo);
 ctx.font='10px "Segoe UI",sans-serif';ctx.lineWidth=1;ctx.fillStyle="#738078";
 for(let i=0;i<=4;i++){
  const value=lo+(hi-lo)*i/4,py=y(value);ctx.strokeStyle="#e9ede7";ctx.beginPath();ctx.moveTo(pad.left,py);ctx.lineTo(width-pad.right,py);ctx.stroke();ctx.fillText(value.toFixed(2),4,py+3);
 }
 for(let i=0;i<=4;i++){const t=experiment.config.duration*i/4;ctx.fillText(`${t.toFixed(0)} s`,x(t)-8,height-9);}
 ctx.setLineDash([4,4]);ctx.strokeStyle="#a9b3aa";ctx.beginPath();ctx.moveTo(pad.left,y(0));ctx.lineTo(width-pad.right,y(0));ctx.stroke();ctx.setLineDash([]);
 for(const run of experiment.runs){
  ctx.strokeStyle=colors[run.policy];ctx.lineWidth=2;ctx.beginPath();
  run.trajectory.forEach((row,i)=>{if(i===0)ctx.moveTo(x(row.t),y(row.state[0]));else ctx.lineTo(x(row.t),y(row.state[0]));});ctx.stroke();
 }
}
function download(name,content,type){
 const url=URL.createObjectURL(new Blob([content],{type}));const link=document.createElement("a");link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.querySelector("#download-json").addEventListener("click",()=>{if(experiment)download("event-control-experiment.json",JSON.stringify(experiment,null,2),"application/json");});
document.querySelector("#download-csv").addEventListener("click",()=>{
 if(!experiment)return;
 const lines=["policy,t_s,position,velocity,input,seen_position,observation_age_s,sent,dropped,delivered"];
 for(const run of experiment.runs)for(const row of run.trajectory)lines.push([run.policy,row.t,row.state[0],row.state[1]??"",row.input,row.controller_values?.[0]??"",row.observation_age??"",Number(row.sent),Number(row.dropped),row.delivered].join(","));
 download("event-control-trajectories.csv",lines.join("\n")+"\n","text/csv");
});
form.addEventListener("submit",run);window.addEventListener("resize",draw);
fetch("/api/default").then(response=>{if(!response.ok)throw Error("无法加载默认配置");return response.json();}).then(value=>{defaults=value;labels();run();}).catch(error=>{statusNode.textContent=`无法启动实验：${error.message}。请确认终端仍在运行，再刷新页面。`;statusNode.className="error";});
