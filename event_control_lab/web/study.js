"use strict";
const studyForm = document.querySelector("#study-settings");
const studyStatus = document.querySelector("#study-status");
let trafficStudy = null;
const studyNumber = value => value === null ? "—" : Number(value).toFixed(5);
const studyNames = {absolute: "绝对变化", relative: "相对变化"};
const reasonNames = {
 event_failed: "事件运行未完成", reference_failed: "周期参考未完成",
 attempted_count_mismatch: "发送量未对齐", exogenous_trace_mismatch: "随机输入不同"
};

function staleStudy() {
 if (trafficStudy) {
  studyStatus.textContent = "设置已修改，仍显示上次扫描；请重新扫描";
  studyStatus.className = "";
 }
}
document.addEventListener("lab-config-edited", staleStudy);
studyForm.addEventListener("input", staleStudy);

function studyList(name) {
 const parts = studyForm.elements[name].value.split(",").map(value => value.trim());
 if (parts.some(value => value === "")) throw Error("列表中有空值，请用英文逗号分隔数字");
 const values = parts.map(Number);
 if (values.some(value => !Number.isFinite(value))) throw Error("列表只能填写有限数字");
 const label = name === "seeds" ? "随机种子" : "变化门槛";
 const maximum = name === "seeds" ? 5 : 8;
 if (values.length > maximum) throw Error(`${label}每次最多 ${maximum} 个`);
 if (new Set(values).size !== values.length) throw Error(`${label}不能重复填写`);
 if (name === "seeds" && values.some(value => !Number.isInteger(value) || value < 0 || value >= 4294967296))
  throw Error("随机种子必须是 0 到 4294967295 之间的整数");
 if (name === "thresholds" && values.some(value => value < 0 || value > 2))
  throw Error("变化门槛必须在 0 到 2 之间");
 return values;
}

studyForm.addEventListener("submit", async event => {
 event.preventDefault();
 if (window.labUI.isBusy()) return;
 const config = window.labUI.config();
 if (!config) return;
 try {
  const spec = {config, thresholds: studyList("thresholds"), seeds: studyList("seeds")};
  window.labUI.setBusy(true);
  studyStatus.textContent = "正在扫描与核对消息账本…";
  studyStatus.className = "";
  const response = await fetch("/api/study", {
   method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(spec)
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "扫描未完成");
  trafficStudy = result;
  document.querySelector("#study-output").hidden = false;
  renderStudy();
  studyStatus.textContent = "扫描完成，所有请求的案例均已保留";
 } catch (error) {
  studyStatus.textContent = `未完成：${error.message}${trafficStudy ? "；仍显示上次扫描" : ""}`;
  studyStatus.className = "error";
 } finally {
  window.labUI.setBusy(false);
 }
});

function studyRows() {
 return trafficStudy.pairs.map(pair => {
  const event = trafficStudy.runs[pair.event_run].result;
  const reference = trafficStudy.runs[pair.reference_run].result;
  return {pair, event, reference};
 });
}

function renderStudy() {
 const {config, seeds, thresholds} = trafficStudy.spec;
 document.querySelector("#study-scope").textContent =
  `扫描参数：${config.plant === "scalar" ? "一阶对象" : "位置—速度对象"}，${config.duration} 秒，每步 ${config.dt} 秒；事件发送上限 ${config.budget}，延迟 ${Math.round(config.delay_steps * config.dt * 1000)} ms，丢包 ${Math.round(config.loss_probability * 100)}%；门槛 ${thresholds.join(" / ")}，种子 ${seeds.join(" / ")}。`;
 const eligible = trafficStudy.pairs.filter(pair => pair.eligible).length;
 const failedEvents = trafficStudy.pairs.filter(pair => pair.unavailable_reasons.includes("event_failed")).length;
 const failedReferences = trafficStudy.pairs.filter(pair => pair.unavailable_reasons.includes("reference_failed")).length;
 const unmatched = trafficStudy.pairs.filter(pair => !pair.traffic_matched).length;
 document.querySelector("#study-counts").textContent =
  `共 ${trafficStudy.pairs.length} 项配对，${eligible} 项可比；事件未完成 ${failedEvents} 项，周期未完成 ${failedReferences} 项，发送量未对齐 ${unmatched} 项。这些计数可能重叠；不可比项的差值不可用。`;
 const summaryBody = document.querySelector("#study-summary");
 summaryBody.replaceChildren();
 for (const summary of trafficStudy.summaries) {
  const row = document.createElement("tr");
  const values = [studyNames[summary.policy], summary.threshold,
   `${summary.eligible_pairs} / ${summary.requested_pairs}`, studyNumber(summary.all_seed_mean_rmse_delta),
   `${summary.failed_event_runs} / ${summary.failed_reference_runs}`, summary.unmatched_traffic_pairs];
  for (const value of values) {
   const cell = document.createElement("td"); cell.textContent = String(value); row.append(cell);
  }
  if (summary.eligible_pairs !== summary.requested_pairs) row.classList.add("failed");
  summaryBody.append(row);
 }
 const body = document.querySelector("#study-pairs");
 body.replaceChildren();
 for (const {pair, event, reference} of studyRows()) {
  const row = document.createElement("tr");
  const values = [studyNames[pair.policy], pair.threshold, pair.seed,
   `${event.packets.attempted} / ${reference.packets.attempted}`,
   studyNumber(event.metrics.position_rmse), studyNumber(reference.metrics.position_rmse),
   studyNumber(pair.rmse_delta_event_minus_periodic),
   pair.eligible ? "完整时段，发送数相同" : pair.unavailable_reasons.map(reason => reasonNames[reason] || reason).join("；")];
  for (const value of values) {
   const cell = document.createElement("td");
   cell.textContent = String(value);
   row.append(cell);
  }
  if (!pair.eligible) row.classList.add("failed");
  body.append(row);
 }
 drawTraffic();
}

function drawTraffic() {
 if (!trafficStudy) return;
 const canvas = document.querySelector("#traffic-plot"), ctx = canvas.getContext("2d");
 const box = canvas.getBoundingClientRect(), scale = window.devicePixelRatio || 1;
 canvas.width = Math.round(box.width * scale); canvas.height = Math.round(box.height * scale);
 ctx.scale(scale, scale);
 const points = studyRows().flatMap(({pair, event, reference}) => [
  {run: event, color: pair.policy === "absolute" ? "#d59338" : "#34806a", hollow: false},
  {run: reference, color: "#326c91", hollow: true}
 ]).filter(point => point.run.metrics.position_rmse !== null);
 const maxX = Math.max(1, ...points.map(point => point.run.packets.attempted));
 const maxY = Math.max(0.1, ...points.map(point => point.run.metrics.position_rmse)) * 1.1;
 const x = value => 45 + (box.width - 63) * value / maxX;
 const y = value => 12 + (box.height - 44) * (1 - value / maxY);
 ctx.font = '10px "Segoe UI",sans-serif'; ctx.fillStyle = "#64736d"; ctx.lineWidth = 1;
 for (let index = 0; index <= 4; index++) {
  const value = maxY * index / 4;
  ctx.strokeStyle = "#e9ede7"; ctx.beginPath(); ctx.moveTo(45, y(value)); ctx.lineTo(box.width - 18, y(value)); ctx.stroke();
  ctx.fillText(value.toFixed(2), 3, y(value) + 3);
 }
 for (const tick of new Set(Array.from({length: 5}, (_, index) => Math.round(maxX * index / 4))))
  ctx.fillText(String(tick), x(tick) - 5, box.height - 10);
 for (const point of points) {
  ctx.beginPath(); ctx.arc(x(point.run.packets.attempted), y(point.run.metrics.position_rmse), 4, 0, 2 * Math.PI);
  ctx.fillStyle = point.hollow ? "#ffffff" : point.color; ctx.fill();
  ctx.strokeStyle = point.color; ctx.lineWidth = 1.5; ctx.stroke();
 }
 if (!points.length) ctx.fillText("没有完整时段指标；请查看下表的失败原因。", 55, 50);
}

document.querySelector("#study-json").addEventListener("click", () => {
 if (trafficStudy) download("event-control-traffic-study.json", JSON.stringify(trafficStudy, null, 2), "application/json");
});
document.querySelector("#study-csv").addEventListener("click", () => {
 if (!trafficStudy) return;
 const lines = ["pair_id,policy,seed,threshold,reference_budget,event_status,reference_status,event_attempted,reference_attempted,event_delivered,reference_delivered,event_dropped,reference_dropped,event_in_flight,reference_in_flight,event_rmse,reference_rmse,traffic_matched,eligible,rmse_delta_event_minus_periodic,unavailable_reasons"];
 for (const {pair, event, reference} of studyRows()) {
  lines.push([pair.id, pair.policy, pair.seed, pair.threshold, pair.reference_budget, event.status, reference.status,
   event.packets.attempted, reference.packets.attempted, event.packets.delivered, reference.packets.delivered,
   event.packets.dropped, reference.packets.dropped, event.packets.in_flight, reference.packets.in_flight,
   event.metrics.position_rmse ?? "", reference.metrics.position_rmse ?? "", pair.traffic_matched,
   pair.eligible, pair.rmse_delta_event_minus_periodic ?? "", pair.unavailable_reasons.join(";")].join(","));
 }
 download("event-control-traffic-pairs.csv", lines.join("\n") + "\n", "text/csv");
});
window.addEventListener("resize", drawTraffic);
