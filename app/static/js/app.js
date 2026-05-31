async function api(path, payload){
  showGlobalSpinner();
  const key = localStorage.getItem("humanBrainApiKey") || "";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const headers = {"Content-Type":"application/json"};
  if (path.startsWith("/api/")) headers["X-API-Key"] = key;
  if (!path.startsWith("/api/")) headers["X-CSRFToken"] = csrf;
  try{
    const res = await fetch(path,{method:"POST",headers,body:JSON.stringify(payload)});
    const text = await res.text();
    let data = {};
    try{
      data = text ? JSON.parse(text) : {};
    }catch(error){
      throw new Error(`HTTP ${res.status}: ${text.slice(0,160)}`);
    }
    if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }finally{
    hideGlobalSpinner();
  }
}
async function getJson(path){
  showGlobalSpinner();
  try{
    const res = await fetch(path,{headers:{"Accept":"application/json"}});
    const text = await res.text();
    let data = {};
    try{
      data = text ? JSON.parse(text) : {};
    }catch(error){
      throw new Error(`HTTP ${res.status}: ${text.slice(0,160)}`);
    }
    if(!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }finally{
    hideGlobalSpinner();
  }
}
function showGlobalSpinner(){document.getElementById("globalSpinner")?.removeAttribute("hidden")}
function hideGlobalSpinner(){document.getElementById("globalSpinner")?.setAttribute("hidden","")}
function initGlobalUx(){
  setTimeout(()=>document.querySelectorAll(".alert").forEach(alert=>alert.remove()),7000);
  document.querySelectorAll("form").forEach(form=>{
    form.addEventListener("submit",event=>{
      if(event.defaultPrevented) return;
      showGlobalSpinner();
    });
  });
}
function escapeHtml(value){
  return String(value ?? "").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
}
function initScrollMemory(){
  const key = `hb-scroll:${location.pathname}`;
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  const saved = sessionStorage.getItem(key);
  if(saved) requestAnimationFrame(()=>scrollTo(0, Number(saved)));
  const sidebar = document.querySelector(".sidebar");
  const sidebarKey = "hb-sidebar-scroll";
  if(sidebar){
    const sidebarSaved = sessionStorage.getItem(sidebarKey);
    if(sidebarSaved) requestAnimationFrame(()=>{sidebar.scrollTop = Number(sidebarSaved);});
    sidebar.addEventListener("scroll",()=>sessionStorage.setItem(sidebarKey, String(sidebar.scrollTop)),{passive:true});
  }
  let ticking=false;
  addEventListener("scroll",()=>{
    if(ticking) return;
    ticking=true;
    requestAnimationFrame(()=>{sessionStorage.setItem(key, String(scrollY)); ticking=false;});
  },{passive:true});
  document.querySelectorAll(".nav-link-item").forEach(link=>{
    if(link.pathname === location.pathname){
      link.classList.add("active");
      const collapse = link.closest(".accordion-collapse");
      if(collapse) sessionStorage.setItem("hb-nav-group", collapse.id);
    }
    link.addEventListener("click",()=>{
      if(sidebar) sessionStorage.setItem(sidebarKey, String(sidebar.scrollTop));
      const collapse = link.closest(".accordion-collapse");
      if(collapse) sessionStorage.setItem("hb-nav-group", collapse.id);
    });
  });
}
initScrollMemory();
initGlobalUx();
function initNavAccordionState(){
  const groups = Array.from(document.querySelectorAll(".nav-accordion .accordion-collapse"));
  if(!groups.length) return;
  const activeGroup = document.querySelector(".nav-link-item.active")?.closest(".accordion-collapse");
  const savedGroup = document.getElementById(sessionStorage.getItem("hb-nav-group") || "");
  const target = activeGroup || savedGroup || groups.find(group=>group.classList.contains("show")) || groups[0];
  groups.forEach(group=>{
    const shouldOpen = group === target;
    group.classList.toggle("show", shouldOpen);
    const button = document.querySelector(`[data-bs-target="#${group.id}"]`);
    if(button){
      button.classList.toggle("collapsed", !shouldOpen);
      button.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    }
    group.addEventListener("shown.bs.collapse",()=>{
      sessionStorage.setItem("hb-nav-group", group.id);
      groups.filter(other=>other !== group).forEach(other=>{
        if(window.bootstrap) bootstrap.Collapse.getOrCreateInstance(other,{toggle:false}).hide();
        else other.classList.remove("show");
      });
    });
  });
  if(target) sessionStorage.setItem("hb-nav-group", target.id);
}
initNavAccordionState();
function toggleSidebarMode(){
  document.body.classList.toggle("sidebar-compact");
  localStorage.setItem("hb-sidebar-compact", document.body.classList.contains("sidebar-compact") ? "1" : "0");
}
if(localStorage.getItem("hb-sidebar-compact")==="0") document.body.classList.remove("sidebar-compact");
else document.body.classList.add("sidebar-compact");
function toggleMobileSidebar(force){
  const open = typeof force === "boolean" ? force : !document.body.classList.contains("sidebar-open");
  document.body.classList.toggle("sidebar-open", open);
}
function initGlobalButtons(){
  document.getElementById("sidebarModeToggle")?.addEventListener("click",toggleSidebarMode);
  document.getElementById("mobileSidebarToggle")?.addEventListener("click",()=>toggleMobileSidebar());
  document.getElementById("sidebarBackdrop")?.addEventListener("click",()=>toggleMobileSidebar(false));
  document.getElementById("searchButton")?.addEventListener("click",demoSearch);
  document.getElementById("copySearchJson")?.addEventListener("click",copySearchJson);
  document.getElementById("copyContextJson")?.addEventListener("click",copyContextJson);
  document.getElementById("testRerankerButton")?.addEventListener("click",testReranker);
  document.getElementById("searchPrompt")?.addEventListener("keydown",event=>{
    if(event.key === "Enter"){
      event.preventDefault();
      demoSearch();
    }
  });
  document.getElementById("ctxBuildButton")?.addEventListener("click",buildContext);
  document.getElementById("ctxPrompt")?.addEventListener("keydown",event=>{
    if((event.ctrlKey || event.metaKey) && event.key === "Enter"){
      event.preventDefault();
      buildContext();
    }
  });
  document.querySelectorAll(".memory-row").forEach(row=>{
    row.addEventListener("click",event=>{
      if(event.target.closest("a,button,form,input,select,textarea,.row-actions")) return;
      openMemoryModal(row);
    });
  });
  initMemoryInputModes();
  initBulkMemoryActions();
}
function initBulkMemoryActions(){
  const form = document.getElementById("bulkMemoryDeleteForm");
  if(!form || form.dataset.bulkReady === "1") return;
  form.dataset.bulkReady = "1";
  const selectAll = document.getElementById("memorySelectAll");
  const checkboxes = Array.from(document.querySelectorAll(".memory-select"));
  const button = document.getElementById("bulkMemoryDeleteButton");
  const count = document.getElementById("bulkMemorySelectionCount");
  const selectedIds = () => checkboxes.filter(item=>item.checked).map(item=>item.value);
  const refresh = () => {
    const selected = selectedIds().length;
    if(button) button.disabled = selected === 0;
    if(count) count.textContent = `${selected} selected`;
    if(selectAll){
      selectAll.checked = selected > 0 && selected === checkboxes.length;
      selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
    }
  };
  selectAll?.addEventListener("change",()=>{
    checkboxes.forEach(item=>{ item.checked = selectAll.checked; });
    refresh();
  });
  checkboxes.forEach(item=>item.addEventListener("change",refresh));
  form.addEventListener("submit",event=>{
    form.querySelectorAll('input[data-bulk-memory-id="1"]').forEach(item=>item.remove());
    const ids = selectedIds();
    if(!ids.length){
      event.preventDefault();
      hideGlobalSpinner();
      refresh();
      return;
    }
    if(!confirm(`Permanently delete ${ids.length} selected memories?`)){
      event.preventDefault();
      hideGlobalSpinner();
      return;
    }
    ids.slice(0,25).forEach(id=>{
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "memory_ids";
      input.value = id;
      input.dataset.bulkMemoryId = "1";
      form.appendChild(input);
    });
  });
  refresh();
}
async function copySearchJson(){
  await copyJsonOutput("searchOutput","copySearchJson");
}
async function testReranker(){
  const button = document.getElementById("testRerankerButton");
  const output = document.getElementById("rerankerTestOutput");
  const original = button?.innerHTML;
  if(button){
    button.disabled = true;
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing...';
  }
  try{
    const data = await api("/settings/test-reranker",{});
    if(output) output.textContent = JSON.stringify(data,null,2);
  }catch(error){
    if(output) output.textContent = JSON.stringify({ok:false,error:String(error)},null,2);
  }finally{
    if(button){
      button.disabled = false;
      button.innerHTML = original;
    }
  }
}
async function copyContextJson(){
  await copyJsonOutput("ctxOutput","copyContextJson");
}
async function copyJsonOutput(outputId, buttonId){
  const button = document.getElementById(buttonId);
  const target = document.getElementById(outputId);
  const text = target?.textContent || "";
  if(!text.trim()) return;
  try{
    await navigator.clipboard.writeText(text);
    if(button){
      const original = button.innerHTML;
      button.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
      setTimeout(()=>{button.innerHTML = original;},1400);
    }
  }catch(error){
    if(button) button.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Copy failed';
  }
}
function initMemoryInputModes(){
  const modes = document.querySelectorAll('input[name="memory_input_mode"]');
  if(!modes.length) return;
  const upload = document.getElementById("memoryUploadInput");
  const apply = ()=>{
    const mode = document.querySelector('input[name="memory_input_mode"]:checked')?.value || "single";
    document.querySelectorAll(".memory-mode-field").forEach(field=>{
      field.hidden = !field.classList.contains(`mode-${mode}`);
    });
    if(upload){
      upload.accept = mode === "image" ? "image/*" : ".txt,.md,.markdown,.json,.csv,.log,.yaml,.yml,.py,.js,.html,.css,.pdf,.docx";
      upload.multiple = mode !== "image";
    }
  };
  modes.forEach(mode=>mode.addEventListener("change",apply));
  apply();
}
function initTableSearch(){
  document.querySelectorAll("table").forEach((table,index)=>{
    if(table.dataset.searchReady === "1") return;
    const tbody = table.querySelector("tbody");
    if(!tbody) return;
    table.dataset.searchReady = "1";
    const rows = Array.from(tbody.querySelectorAll("tr"));
    if(rows.length < 2) return;
    const toolbar = document.createElement("div");
    toolbar.className = "table-toolbar";
    toolbar.innerHTML = `
      <div class="table-search">
        <i class="fa-solid fa-magnifying-glass"></i>
        <input class="form-control form-control-sm" type="search" placeholder="Search this table">
      </div>
      <span class="table-count">${rows.length} rows</span>
    `;
    const wrapper = table.closest(".table-responsive") || table;
    wrapper.parentNode.insertBefore(toolbar, wrapper);
    const input = toolbar.querySelector("input");
    const count = toolbar.querySelector(".table-count");
    input.addEventListener("input",()=>{
      const query = input.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach(row=>{
        const match = !query || row.textContent.toLowerCase().includes(query);
        row.hidden = !match;
        if(match) visible += 1;
      });
      count.textContent = `${visible} of ${rows.length} rows`;
    });
  });
}
initTableSearch();
function initTableDetailRows(){
  document.querySelectorAll("table tbody tr:not(.memory-row)").forEach(row=>{
    if(row.children.length < 2) return;
    row.classList.add("table-detail-row");
    const openDetail = event=>{
      if(event.target.closest("a,button,form,input,select,textarea,.row-actions")) return;
      const table = row.closest("table");
      const headers = Array.from(table.querySelectorAll("thead th")).map(th=>th.textContent.trim());
      const cells = Array.from(row.children);
      if(cells.some(cell=>cell.colSpan && cell.colSpan > 1)) return;
      const body = document.getElementById("tableDetailBody");
      const actions = document.getElementById("tableDetailActions");
      const title = document.getElementById("tableDetailTitle");
      if(!body||!actions||!title) return;
      title.textContent = row.dataset.detailTitle || cells[1]?.textContent.trim() || cells[0]?.textContent.trim() || "Details";
      const json = row.querySelector(".row-detail-json")?.textContent;
      if(json){
        try{
          body.innerHTML = `<pre class="output">${escapeHtml(JSON.stringify(JSON.parse(json), null, 2))}</pre>`;
        }catch(error){
          body.innerHTML = `<pre class="output">${escapeHtml(json)}</pre>`;
        }
        actions.innerHTML = '<button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Close</button>';
        if(window.bootstrap) bootstrap.Modal.getOrCreateInstance(document.getElementById("tableDetailModal")).show();
        return;
      }
      const implicitActionCell = cells[cells.length - 1]?.querySelector("a,button,form") ? cells[cells.length - 1] : null;
      body.innerHTML = cells.map((cell,index)=>{
        if(cell.classList.contains("row-actions") || cell === implicitActionCell) return "";
        const label = headers[index] || `Field ${index + 1}`;
        if(!label) return "";
        return `<div class="detail-item"><span>${label}</span><strong>${cell.innerHTML}</strong></div>`;
      }).join("");
      const actionCell = row.querySelector(".row-actions") || implicitActionCell;
      actions.innerHTML = actionCell ? actionCell.innerHTML : '<button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">Close</button>';
      actions.querySelectorAll("form").forEach(form=>form.classList.add("d-inline"));
      if(window.bootstrap) bootstrap.Modal.getOrCreateInstance(document.getElementById("tableDetailModal")).show();
    };
    row.addEventListener("dblclick", openDetail);
  });
}
initTableDetailRows();
initGlobalButtons();
async function buildContext(){
  const el = id => document.getElementById(id);
  const button = el("ctxBuildButton");
  const prompt = el("ctxPrompt").value.trim();
  if(!prompt){
    el("ctxContextBlock").textContent = "Enter a prompt first.";
    el("ctxContextBlock").classList.add("empty");
    return;
  }
  const payload={
    agent_id:Number(el("ctxAgent").value),
    workspace_id:Number(el("ctxWorkspace").value),
    prompt,
    top_k:Number(el("ctxTopK").value),
    max_tokens:Number(el("ctxMaxTokens").value),
    sensitivity_policy:el("ctxSensitivity").value,
    include_correlations:true,
    correlation_limit:5
  };
  button.disabled = true;
  button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Building...';
  try{
    const data = await api("/web/context",payload);
    el("ctxOutput").textContent=JSON.stringify(data,null,2);
    el("ctxContextBlock").textContent=data.context || "No matching memories passed the current policy.";
    el("ctxContextBlock").classList.toggle("empty", !data.context);
    el("ctxPolicyLabel").textContent=`${data.policy.sensitivity_policy}, blocks ${data.policy.blocked_levels.join(", ") || "none"}`;
    el("ctxMemoryCount").textContent=`${data.memories.length} memories`;
    el("ctxMemoryList").innerHTML=data.memories.map(memory=>`<div class="context-memory"><b>#${memory.id}</b><span>score ${memory.score}</span></div>`).join("") || '<div class="text-secondary">No memories selected.</div>';
  }catch(error){
    el("ctxContextBlock").textContent = `Context build failed: ${error}`;
    el("ctxContextBlock").classList.add("empty");
  }finally{
    button.disabled = false;
    button.innerHTML = '<i class="fa-solid fa-code-branch"></i> Build Agent Context';
  }
}
async function demoSearch(){
  const el = id => document.getElementById(id);
  const query = el("searchPrompt").value.trim();
  if(!query){el("searchResults").innerHTML='<div class="context-block empty">Enter a search query first.</div>';return;}
  const button = el("searchButton");
  button.disabled=true;button.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> Searching...';
  try{
    const payload={
      agent_id:Number(el("searchAgent").value),
      workspace_id:Number(el("searchWorkspace").value),
      query,
      top_k:Number(el("searchTopK")?.value || 10),
      include_vector_details:true,
      include_correlations:true,
      correlation_limit:Number(el("searchCorrelationLimit")?.value || 5),
      include_timing:true
    };
    const data = await api("/web/search",payload);
    el("searchOutput").textContent=JSON.stringify(data,null,2);
    if(el("searchCount")){
      const ms = data.timing?.elapsed_ms;
      el("searchCount").textContent=ms !== undefined ? `${data.results.length} memories in ${ms} ms` : `${data.results.length} memories`;
    }
    if(el("searchRerankerStatus")){
      const timing = data.timing || {};
      const used = timing.reranker_used === true;
      const enabled = timing.reranker_enabled === true;
      const provider = timing.reranker_provider || "none";
      const model = timing.reranker_model || "none";
      const reason = timing.reranker_reason || "none";
      const error = timing.reranker_error || "";
      const rerankerMs = timing.reranker_ms ?? 0;
      const status = used ? "used" : (enabled ? "not used" : "disabled");
      el("searchRerankerStatus").innerHTML = `
        <span>reranker ${status}</span>
        <span>provider ${escapeHtml(provider)}</span>
        <span>model ${escapeHtml(model)}</span>
        <span>reason ${escapeHtml(reason)}</span>
        <span>reranker ${rerankerMs} ms</span>
        ${error ? `<span>error ${escapeHtml(error).slice(0,180)}</span>` : ""}
      `;
    }
    el("searchResults").innerHTML=data.results.map(result=>{
      const m=result.memory;
      const correlations=(result.correlations||[]).map(c=>`<a class="badge text-bg-dark border" href="/graph?memory_id=${m.id}">#${c.related_memory.id} ${escapeHtml(c.related_memory.title)} (${c.strength})</a>`).join(" ");
      const assets=(m.assets||[]).map(asset=>`<a class="badge text-bg-success" href="${asset.url}" target="_blank">${escapeHtml(asset.asset_type)}: ${escapeHtml(asset.original_filename)}</a>`).join(" ");
      const rerankerScore = result.reranker_score ?? "none";
      const finalScore = result.final_score ?? result.relevance_score;
      const retrievedBy = result.retrieved_by || "search";
      return `<div class="search-result rich-search-result">
        <div>
          <div class="result-title"><b>#${m.id} ${escapeHtml(m.title)}</b><span>${finalScore}</span></div>
          <p>${escapeHtml(m.summary||m.content).slice(0,700)}</p>
          <div class="score-strip">
            <span>${escapeHtml(retrievedBy)}</span><span>final ${finalScore}</span><span>semantic ${result.semantic_score}</span><span>reranker ${rerankerScore}</span><span>keyword ${result.explanation.keyword_match}</span><span>trust ${m.trust_score}</span><span>importance ${m.importance_score}</span>
          </div>
          <div class="mt-2"><span class="badge text-bg-info">${escapeHtml(m.memory_type)}</span> ${assets}</div>
          <div class="correlation-links mt-2">${correlations || '<span class="text-secondary">No direct correlations returned.</span>'}</div>
        </div>
      </div>`;
    }).join("") || '<div class="context-block empty">No matching memories found. Add memories or rebuild the FAISS index from System Health.</div>';
  }catch(error){
    el("searchResults").innerHTML=`<div class="context-block empty">Search failed: ${error}</div>`;
  }finally{
    button.disabled=false;button.innerHTML='<i class="fa-solid fa-magnifying-glass"></i> Search';
  }
}
if(document.getElementById("activityChart")){
  const dashboardDataEl=document.getElementById("dashboardChartsData");
  const dashboardCharts=dashboardDataEl ? JSON.parse(dashboardDataEl.textContent) : {};
  const palette=["#38e88f","#9cffcb","#f2c94c","#ff8aa0","#7dd3fc","#d69cff","#f59e0b","#22c55e"];
  const chartOptions={responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:"#dcecff"}}},scales:{x:{ticks:{color:"#98b9aa"},grid:{color:"rgba(128,230,178,.12)"}},y:{beginAtZero:true,ticks:{precision:0,color:"#98b9aa"},grid:{color:"rgba(128,230,178,.12)"}}}};
  const doughnutOptions={responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{color:"#dcecff",boxWidth:12}}}};
  const emptyPlugin={id:"emptyChart",afterDraw(chart){const values=chart.data.datasets.flatMap(dataset=>dataset.data||[]);if(values.some(value=>Number(value)>0)) return;const {ctx,chartArea}=chart;if(!chartArea) return;ctx.save();ctx.fillStyle="#74889e";ctx.font="13px system-ui";ctx.textAlign="center";ctx.fillText("No data yet",chartArea.left+chartArea.width/2,chartArea.top+chartArea.height/2);ctx.restore();}};
  const dataset=(key)=>dashboardCharts[key]||{labels:[],values:[]};
  const build=(id,type,key,label,options=chartOptions)=>{
    const target=document.getElementById(id);
    if(!target) return;
    const data=dataset(key);
    new Chart(target,{type,data:{labels:data.labels||[],datasets:[{label,data:data.values||[],borderColor:palette[0],backgroundColor:type==="line"?"rgba(56,232,143,.16)":palette,fill:type==="line",tension:.35}]},options,plugins:[emptyPlugin]});
  };
  build("activityChart","line","activity","Memory writes");
  build("typeChart","bar","types","Memories");
  build("sensitivityChart","doughnut","sensitivity","Memories",doughnutOptions);
  build("workspaceChart","bar","workspaces","Memories");
  build("trustChart","bar","trust","Memories");
  build("sourceChart","doughnut","sources","Memories",doughnutOptions);
}
function initMemoryGraph(){
  const canvas=document.getElementById("memoryGraphCanvas");
  const raw=document.getElementById("memoryGraphData");
  if(!canvas||!raw) return;
  const data=JSON.parse(raw.textContent);
  const graphNodeCount=document.getElementById("graphNodeCount");
  const graphEdgeCount=document.getElementById("graphEdgeCount");
  const graphFilter=document.getElementById("graphFilter");
  const graphDetails=document.getElementById("graphDetails");
  if(graphNodeCount) graphNodeCount.textContent=data.nodes.length;
  if(graphEdgeCount) graphEdgeCount.textContent=data.edges.length;
  const ctx=canvas.getContext("2d");
  const colors={memory:"#38e88f",agent:"#9cffcb",workspace:"#f2c94c",session:"#7dd3a8",tag:"#ff8aa0",type:"#c8ffe3"};
  const resize=()=>{const rect=canvas.getBoundingClientRect();canvas.width=rect.width*devicePixelRatio;canvas.height=620*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0)};
  resize();
  const nodeMap=Object.fromEntries(data.nodes.map(n=>[n.id,{...n,x:24+Math.random()*(canvas.width/devicePixelRatio-48),y:24+Math.random()*572,vx:0,vy:0}]));
  const edges=data.edges.filter(e=>nodeMap[e.source]&&nodeMap[e.target]);
  if(!data.nodes.length){
    ctx.fillStyle="#74889e";
    ctx.font="14px system-ui";
    ctx.fillText("No graph data yet. Add memories to populate relationships.",24,42);
    return;
  }
  function visibleNodes(){const f=graphFilter ? graphFilter.value : "";return Object.values(nodeMap).filter(n=>!f||n.kind===f||n.kind==="memory")}
  function tick(){
    const nodes=visibleNodes();
    for(const a of nodes){for(const b of nodes){if(a===b)continue;const dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(dx*dx+dy*dy,80);const f=80/d2;a.vx+=dx*f;a.vy+=dy*f}}
    for(const e of edges){const a=nodeMap[e.source],b=nodeMap[e.target];if(!nodes.includes(a)||!nodes.includes(b))continue;const dx=b.x-a.x,dy=b.y-a.y;a.vx+=dx*.002;a.vy+=dy*.002;b.vx-=dx*.002;b.vy-=dy*.002}
    for(const n of nodes){n.vx*=.86;n.vy*=.86;n.x=Math.max(24,Math.min(canvas.width/devicePixelRatio-24,n.x+n.vx));n.y=Math.max(24,Math.min(596,n.y+n.vy))}
  }
  function draw(){
    tick();ctx.clearRect(0,0,canvas.width,canvas.height);const nodes=visibleNodes();
    ctx.lineWidth=1;for(const e of edges){const a=nodeMap[e.source],b=nodeMap[e.target];if(!nodes.includes(a)||!nodes.includes(b))continue;ctx.strokeStyle="rgba(148,168,189,.18)";ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}
    for(const n of nodes){ctx.fillStyle=colors[n.kind]||"#fff";ctx.beginPath();ctx.arc(n.x,n.y,n.kind==="memory"?7:10,0,Math.PI*2);ctx.fill();ctx.fillStyle="#dcecff";ctx.font="12px system-ui";ctx.fillText(n.label,n.x+12,n.y+4)}
    requestAnimationFrame(draw);
  }
  canvas.addEventListener("click",ev=>{const r=canvas.getBoundingClientRect();const x=ev.clientX-r.left,y=ev.clientY-r.top;let found=null;for(const n of visibleNodes()){if(Math.hypot(n.x-x,n.y-y)<14)found=n}if(found&&graphDetails){const related=edges.filter(e=>e.source===found.id||e.target===found.id).length;graphDetails.classList.remove("empty");graphDetails.innerHTML=`<h3>${escapeHtml(found.label)}</h3><p><span class="badge text-bg-info">${escapeHtml(found.kind)}</span></p><pre>${escapeHtml(JSON.stringify(found.meta||{},null,2))}</pre><p class="text-secondary">${related} relationships</p>`}});
  if(graphFilter) graphFilter.addEventListener("change",()=>{});
  draw();
}
initMemoryGraph();
function openMemoryModal(row){
  const get = name => row.dataset[name] || "";
  const memoryId = get("id");
  const form = document.getElementById("memoryEditForm");
  if(!form) return;
  form.action = `/memories/${memoryId}/edit`;
  document.getElementById("memEditTitle").value = get("title");
  document.getElementById("memEditContent").value = get("content");
  document.getElementById("memEditSummary").value = get("summary");
  document.getElementById("memEditType").value = get("memoryType");
  document.getElementById("memEditTags").value = get("tags");
  document.getElementById("memEditImportance").value = get("importance");
  document.getElementById("memEditTrust").value = get("trust");
  document.getElementById("memEditSensitivity").value = get("sensitivity");
  document.getElementById("memEditVisibility").value = get("visibility");
  document.getElementById("memEditConfirmed").checked = get("confirmed") === "true";
  const graphLink = document.getElementById("memCorrelationGraphLink");
  if(graphLink) graphLink.href = `/graph?memory_id=${encodeURIComponent(memoryId)}`;
  loadMemoryCorrelations(memoryId);
  if(window.bootstrap) bootstrap.Modal.getOrCreateInstance(document.getElementById("memoryEditModal")).show();
}
async function loadMemoryCorrelations(memoryId){
  const target = document.getElementById("memCorrelationList");
  if(!target || !memoryId) return;
  target.innerHTML = '<div class="text-secondary">Loading correlations...</div>';
  try{
    const data = await getJson(`/memories/${memoryId}/correlations`);
    if(!data.correlations.length){
      target.innerHTML = '<div class="text-secondary">No correlations stored for this memory yet.</div>';
      return;
    }
    target.innerHTML = data.correlations.map(item=>{
      const tags = (item.related_tags || []).slice(0,5).map(tag=>`<span class="badge text-bg-dark border">${escapeHtml(tag)}</span>`).join(" ");
      return `<div class="memory-correlation-item">
        <div>
          <div class="correlation-title">#${item.related_memory_id} ${escapeHtml(item.related_title)}</div>
          <div class="correlation-meta">
            <span class="badge text-bg-success">${escapeHtml(item.related_type)}</span>
            <span class="badge text-bg-secondary">${escapeHtml(item.correlation_type)}</span>
            <span class="badge text-bg-info">strength ${item.strength}</span>
            ${tags}
          </div>
          <p>${escapeHtml(item.explanation || "No explanation stored.")}</p>
        </div>
      </div>`;
    }).join("");
  }catch(error){
    target.innerHTML = `<div class="text-danger">Could not load correlations: ${escapeHtml(error.message || error)}</div>`;
  }
}
