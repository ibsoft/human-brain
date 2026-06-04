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
function initThemeMode(){
  const key = "hb-theme-mode";
  const button = document.getElementById("themeModeToggle");
  const form = document.getElementById("defaultThemeForm");
  const apply = mode => {
    const normalized = mode === "light" ? "light" : "dark";
    document.documentElement.dataset.bsTheme = normalized;
    document.body.classList.toggle("theme-light", normalized === "light");
    document.body.classList.toggle("theme-dark", normalized !== "light");
    if(button){
      button.innerHTML = normalized === "light" ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
      button.title = normalized === "light" ? "Switch to dark mode" : "Switch to light mode";
      button.setAttribute("aria-label", button.title);
    }
  };
  const saved = localStorage.getItem(key) || "dark";
  apply(saved);
  if(button){
    button.addEventListener("click",()=>{
      const next = document.body.classList.contains("theme-light") ? "dark" : "light";
      localStorage.setItem(key, next);
      apply(next);
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
      const url = button.dataset.themeUrl;
      if(url){
        fetch(url,{
          method:"POST",
          headers:{"Content-Type":"application/x-www-form-urlencoded","X-CSRFToken":csrf},
          body:new URLSearchParams({default_theme:next}),
        }).catch(()=>{});
      }
    });
  }
  if(form){
    form.addEventListener("submit",()=>{
      const selected = form.querySelector('input[name="default_theme"]:checked')?.value || "dark";
      localStorage.setItem(key, selected);
    });
  }
}
function initMfaQrCode(){
  const target = document.getElementById("mfaQrCode");
  if(!target) return;
  const render = () => {
    if(target.dataset.rendered === "1") return;
    const uri = target.dataset.qrUri || "";
    target.innerHTML = "";
    if(!uri || typeof QRCode === "undefined"){
      target.innerHTML = '<div class="text-secondary small">QR code unavailable. Use the secret or URI below.</div>';
      return;
    }
    new QRCode(target,{text:uri,width:184,height:184,colorDark:"#06100c",colorLight:"#ffffff",correctLevel:QRCode.CorrectLevel.M});
    target.dataset.rendered = "1";
  };
  const modal = document.getElementById("profileSecurityModal");
  if(modal) modal.addEventListener("shown.bs.modal",render);
  render();
}
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
initThemeMode();
initMfaQrCode();
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
  initConfirmActionForms();
  initCopyButtons();
}
function openConfirmAction({title="Confirm action", message="This action cannot be undone.", confirmText="Delete", confirmClass="btn-danger", onConfirm}){
  const modalEl = document.getElementById("confirmActionModal");
  const titleEl = document.getElementById("confirmActionTitle");
  const messageEl = document.getElementById("confirmActionMessage");
  const button = document.getElementById("confirmActionButton");
  if(!modalEl || !button || !window.bootstrap){
    if(onConfirm) onConfirm();
    return;
  }
  titleEl.textContent = title;
  messageEl.textContent = message;
  button.textContent = confirmText;
  button.className = `btn ${confirmClass}`;
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  const nextButton = button.cloneNode(true);
  button.replaceWith(nextButton);
  nextButton.addEventListener("click",()=>{
    modal.hide();
    if(onConfirm) onConfirm();
  },{once:true});
  modal.show();
}
function initConfirmActionForms(){
  document.querySelectorAll("form[data-confirm-modal]").forEach(form=>{
    if(form.dataset.confirmReady === "1") return;
    form.dataset.confirmReady = "1";
    form.addEventListener("submit",event=>{
      if(form.dataset.confirmBypass === "1") return;
      event.preventDefault();
      hideGlobalSpinner();
      openConfirmAction({
        title: form.dataset.confirmTitle || "Confirm delete",
        message: form.dataset.confirmMessage || "This action cannot be undone.",
        confirmText: form.dataset.confirmText || "Delete",
        confirmClass: form.dataset.confirmClass || "btn-danger",
        onConfirm: ()=>{
          form.dataset.confirmBypass = "1";
          showGlobalSpinner();
          HTMLFormElement.prototype.submit.call(form);
        }
      });
    });
  });
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
    event.preventDefault();
    hideGlobalSpinner();
    openConfirmAction({
      title: "Delete selected memories",
      message: `Permanently delete ${ids.length} selected memories? This action cannot be undone.`,
      confirmText: "Delete selected",
      confirmClass: "btn-danger",
      onConfirm: ()=>{
        ids.slice(0,25).forEach(id=>{
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "memory_ids";
          input.value = id;
          input.dataset.bulkMemoryId = "1";
          form.appendChild(input);
        });
        showGlobalSpinner();
        HTMLFormElement.prototype.submit.call(form);
      }
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
  await copyTextWithButtonState(text, button);
}
async function copyTextWithButtonState(text, button){
  if(!text) return false;
  const original = button?.innerHTML;
  try{
    await copyTextToClipboard(text);
    if(button){
      button.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
      setTimeout(()=>{button.innerHTML = original;},1400);
    }
    return true;
  }catch(error){
    if(button){
      button.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Copy failed';
      setTimeout(()=>{button.innerHTML = original;},1800);
    }
    return false;
  }
}
async function copyTextToClipboard(text){
  if(navigator.clipboard?.writeText && window.isSecureContext){
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly","");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  textarea.style.left = "-1000px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try{
    if(!document.execCommand("copy")) throw new Error("execCommand copy failed");
  }finally{
    textarea.remove();
  }
}
function initCopyButtons(){
  document.querySelectorAll("[data-copy-target]").forEach(button=>{
    if(button.dataset.copyReady === "1") return;
    button.dataset.copyReady = "1";
    button.addEventListener("click",async ()=>{
      const target = document.getElementById(button.dataset.copyTarget);
      if(!target) return;
      const text = "value" in target ? target.value : target.textContent;
      await copyTextWithButtonState(text || "", button);
    });
  });
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
      const documentTypes = ".txt,.md,.markdown,.json,.csv,.log,.yaml,.yml,.py,.js,.html,.css,.xml,.pdf,.docx,.xlsx,.xlsm";
      const audioTypes = "audio/*,.mp3,.wav,.flac,.m4a,.aac,.ogg,.oga,.opus,.wma,.aiff,.aif";
      if(mode === "image"){
        upload.accept = "image/*";
      }else if(mode === "audio"){
        upload.accept = audioTypes;
      }else if(mode === "bulk"){
        upload.accept = `${documentTypes},image/*,${audioTypes}`;
      }else{
        upload.accept = documentTypes;
      }
      upload.multiple = true;
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
  const requestSpeedOptions={...chartOptions,scales:{...chartOptions.scales,x:{type:"linear",min:0,ticks:{color:"#98b9aa"},grid:{color:"rgba(128,230,178,.12)"}},y:{...chartOptions.scales.y,title:{display:true,text:"ms",color:"#98b9aa"}}}};
  const doughnutOptions={responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{color:"#dcecff",boxWidth:12}}}};
  const emptyPlugin={id:"emptyChart",afterDraw(chart){const values=chart.data.datasets.flatMap(dataset=>dataset.data||[]).map(value=>typeof value==="object"?value.y:value);if(values.some(value=>Number(value)>0)) return;const {ctx,chartArea}=chart;if(!chartArea) return;ctx.save();ctx.fillStyle="#74889e";ctx.font="13px system-ui";ctx.textAlign="center";ctx.fillText("No data yet",chartArea.left+chartArea.width/2,chartArea.top+chartArea.height/2);ctx.restore();}};
  const spikePlugin={id:"requestSpikes",afterDatasetsDraw(chart){if(chart.canvas.id!=="agentRequestSpeedChart") return;const {ctx,scales:{y}}=chart;const base=y.getPixelForValue(0);chart.data.datasets.forEach((dataset,datasetIndex)=>{const meta=chart.getDatasetMeta(datasetIndex);ctx.save();ctx.strokeStyle=dataset.borderColor;ctx.fillStyle=dataset.borderColor;ctx.lineWidth=2;meta.data.forEach(point=>{ctx.beginPath();ctx.moveTo(point.x,base);ctx.lineTo(point.x,point.y);ctx.stroke();ctx.beginPath();ctx.arc(point.x,point.y,2.4,0,Math.PI*2);ctx.fill();});ctx.restore();});}};
  const dataset=(key)=>dashboardCharts[key]||{labels:[],values:[]};
  const build=(id,type,key,label,options=chartOptions)=>{
    const target=document.getElementById(id);
    if(!target) return;
    const data=dataset(key);
    new Chart(target,{type,data:{labels:data.labels||[],datasets:[{label,data:data.values||[],borderColor:palette[0],backgroundColor:type==="line"?"rgba(56,232,143,.16)":palette,fill:type==="line",tension:.35}]},options,plugins:[emptyPlugin]});
  };
  const buildSpikeChart=(id,key,options=chartOptions)=>{
    const target=document.getElementById(id);
    if(!target) return;
    const data=dataset(key);
    const startMinute=Number(data.start_minute_of_day||0);
    const formatMinute=value=>{
      const total=(startMinute+Math.round(Number(value)||0)+1440*10)%1440;
      return `${String(Math.floor(total/60)).padStart(2,"0")}:${String(total%60).padStart(2,"0")}`;
    };
    const spikeOptions={...options,scales:{...options.scales,x:{...options.scales.x,max:Number(data.x_max||1440),ticks:{...options.scales.x.ticks,callback:formatMinute}}},plugins:{...options.plugins,tooltip:{callbacks:{title:items=>items.length?formatMinute(items[0].parsed.x):"",label:item=>`${item.dataset.label}: ${item.parsed.y} ms`}}}};
    const datasets=(data.datasets||[]).map((series,index)=>{
      const color=palette[index%palette.length];
      const points=series.points||((series.values||[]).map((value,valueIndex)=>{
        if(value===null||value===undefined||value==="") return null;
        const step=Number(data.x_max||1440)/Math.max((series.values||[]).length-1,1);
        return {x:Math.round(valueIndex*step*100)/100,y:Number(value)};
      }).filter(Boolean));
      return {label:series.label,data:points,borderColor:color,backgroundColor:color,pointRadius:0,pointHoverRadius:5,showLine:false};
    });
    new Chart(target,{type:"scatter",data:{datasets},options:spikeOptions,plugins:[emptyPlugin,spikePlugin]});
  };
  build("activityChart","line","activity","Memory writes");
  buildSpikeChart("agentRequestSpeedChart","agent_request_speed",requestSpeedOptions);
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
  const graphZoomIn=document.getElementById("graphZoomIn");
  const graphZoomOut=document.getElementById("graphZoomOut");
  const graphZoomReset=document.getElementById("graphZoomReset");
  const graphFullscreen=document.getElementById("graphFullscreen");
  if(graphNodeCount) graphNodeCount.textContent=data.nodes.length;
  if(graphEdgeCount) graphEdgeCount.textContent=data.edges.length;
  const ctx=canvas.getContext("2d");
  const colors={memory:"#48c4ff",agent:"#38e88f",workspace:"#f2c94c",session:"#d69cff",tag:"#ff8aa0",type:"#c8ffe3"};
  const viewport={scale:1,x:0,y:0};
  const galaxy={stars:[],started:performance.now()};
  let graphWidth=0;
  let graphHeight=620;
  const resize=()=>{const rect=canvas.getBoundingClientRect();graphWidth=rect.width;graphHeight=rect.height||620;canvas.width=rect.width*devicePixelRatio;canvas.height=graphHeight*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);galaxy.stars=Array.from({length:Math.max(80,Math.floor(graphWidth/6))},(_,i)=>({x:Math.random()*graphWidth,y:Math.random()*graphHeight,r:.3+Math.random()*1.05,a:.12+Math.random()*.32,twinkle:Math.random()*Math.PI*2,depth:.4+Math.random()*1.4}))};
  resize();
  const kindOffset={memory:0,agent:.6,workspace:1.2,session:1.8,tag:2.4,type:3};
  const goldenAngle=Math.PI*(3-Math.sqrt(5));
  const agents=data.nodes.filter(n=>n.kind==="agent");
  const agentCenterMap=Object.fromEntries(agents.map((agent,index)=>{
    const count=Math.max(agents.length,1);
    const angle=index*Math.PI*2/count;
    const radius=count===1?0:Math.min(46,18+count*5);
    return [agent.id,{x:graphWidth/2+Math.cos(angle)*radius,y:graphHeight/2+Math.sin(angle)*radius*.68}];
  }));
  const nodeMap=Object.fromEntries(data.nodes.map((n,index)=>{
    if(n.kind==="agent"){
      const center=agentCenterMap[n.id]||{x:graphWidth/2,y:graphHeight/2};
      return [n.id,{...n,x:center.x,y:center.y,vx:0,vy:0,orbit:index%7,pinned:true}];
    }
    const angle=index*goldenAngle+(kindOffset[n.kind]||0);
    const maxRadius=Math.max(120,Math.min(graphWidth,graphHeight)*.42);
    const baseRadius=n.kind==="memory"?28:52;
    const radius=Math.min(maxRadius,baseRadius+Math.sqrt(index+1)*12);
    const x=graphWidth/2+Math.cos(angle)*radius;
    const y=graphHeight/2+Math.sin(angle)*radius*.68;
    return [n.id,{...n,x:Math.max(26,Math.min(graphWidth-26,x)),y:Math.max(26,Math.min(graphHeight-26,y)),vx:0,vy:0,orbit:index%7}];
  }));
  const edges=data.edges.filter(e=>nodeMap[e.source]&&nodeMap[e.target]);
  if(!data.nodes.length){
    ctx.fillStyle="#74889e";
    ctx.font="14px system-ui";
    ctx.fillText("No graph data yet. Add memories to populate relationships.",24,42);
    return;
  }
  function visibleNodes(){
    const f=graphFilter ? graphFilter.value : "core";
    if(f==="all") return Object.values(nodeMap);
    if(f==="core") return Object.values(nodeMap).filter(n=>["memory","agent","workspace"].includes(n.kind));
    return Object.values(nodeMap).filter(n=>n.kind===f||n.kind==="memory");
  }
  function updateVisibleCounts(){
    const nodes=visibleNodes();
    if(graphNodeCount) graphNodeCount.textContent=nodes.length;
    if(graphEdgeCount) graphEdgeCount.textContent=edges.filter(e=>nodes.includes(nodeMap[e.source])&&nodes.includes(nodeMap[e.target])).length;
  }
  function screenToGraph(x,y){return {x:(x-viewport.x)/viewport.scale,y:(y-viewport.y)/viewport.scale}}
  function applyZoom(nextScale,centerX=graphWidth/2,centerY=graphHeight/2){
    const clamped=Math.max(.35,Math.min(3.5,nextScale));
    const graphPoint=screenToGraph(centerX,centerY);
    viewport.scale=clamped;
    viewport.x=centerX-graphPoint.x*viewport.scale;
    viewport.y=centerY-graphPoint.y*viewport.scale;
  }
  function zoomBy(factor,centerX,centerY){applyZoom(viewport.scale*factor,centerX,centerY)}
  function resetView(){viewport.scale=1;viewport.x=0;viewport.y=0}
  function tick(){
    const nodes=visibleNodes();
    const centerX=graphWidth/2,centerY=graphHeight/2;
    for(const a of nodes){
      for(const b of nodes){
        if(a===b)continue;
        const dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(dx*dx+dy*dy,260);
        const f=18/d2;
        a.vx+=dx*f;
        a.vy+=dy*f;
      }
    }
    for(const e of edges){
      const a=nodeMap[e.source],b=nodeMap[e.target];
      if(!nodes.includes(a)||!nodes.includes(b))continue;
      const dx=b.x-a.x,dy=b.y-a.y;
      const pull=a.kind==="memory"||b.kind==="memory"?.0018:.0012;
      if(a.kind!=="agent"){
        a.vx+=dx*pull;
        a.vy+=dy*pull;
      }
      if(b.kind!=="agent"){
        b.vx-=dx*pull;
        b.vy-=dy*pull;
      }
    }
    for(const n of nodes){
      if(n.kind==="agent"){
        const target=agentCenterMap[n.id]||{x:centerX,y:centerY};
        n.vx+=(target.x-n.x)*.08;
        n.vy+=(target.y-n.y)*.08;
      }else{
        n.vx+=(centerX-n.x)*.0009;
        n.vy+=(centerY-n.y)*.0009;
      }
      n.vx*=.82;
      n.vy*=.82;
      n.x=Math.max(36,Math.min(graphWidth-36,n.x+n.vx));
      n.y=Math.max(36,Math.min(graphHeight-36,n.y+n.vy));
    }
  }
  function drawSpace(time){
    const centerX=graphWidth/2,centerY=graphHeight/2;
    const bg=ctx.createRadialGradient(centerX,centerY,20,centerX,centerY,Math.max(graphWidth,graphHeight)*.72);
    bg.addColorStop(0,"rgba(56,232,143,.08)");
    bg.addColorStop(.22,"rgba(72,196,255,.045)");
    bg.addColorStop(.62,"rgba(8,13,24,.88)");
    bg.addColorStop(1,"rgba(1,3,8,1)");
    ctx.fillStyle=bg;
    ctx.fillRect(0,0,graphWidth,graphHeight);
    for(const star of galaxy.stars){
      const pulse=(Math.sin(time*.0016*star.depth+star.twinkle)+1)/2;
      ctx.fillStyle=`rgba(205,226,245,${star.a*(.35+pulse*.4)})`;
      ctx.beginPath();
      ctx.arc(star.x,star.y,star.r,0,Math.PI*2);
      ctx.fill();
    }
    ctx.save();
    ctx.translate(centerX,centerY);
    ctx.rotate(time*.000018);
    for(let arm=0;arm<4;arm++){
      ctx.strokeStyle=arm%2?"rgba(72,196,255,.045)":"rgba(56,232,143,.04)";
      ctx.lineWidth=.9;
      ctx.beginPath();
      for(let i=0;i<130;i++){
        const r=10+i*3.2;
        const a=arm*Math.PI/2+i*.105;
        const x=Math.cos(a)*r;
        const y=Math.sin(a)*r*.58;
        if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
    ctx.restore();
    for(let ring=0;ring<4;ring++){
      const radius=((time*.018+ring*155)%620)+30;
      ctx.strokeStyle=`rgba(72,196,255,${Math.max(0,.075-radius/1150)})`;
      ctx.lineWidth=1;
      ctx.beginPath();
      ctx.arc(centerX,centerY,radius,0,Math.PI*2);
      ctx.stroke();
    }
  }
  function drawNode(node,time){
    const base=node.kind==="memory"?7:10;
    const radius=base;
    const color=colors[node.kind]||"#fff";
    ctx.fillStyle=color;
    ctx.beginPath();
    ctx.arc(node.x,node.y,radius,0,Math.PI*2);
    ctx.fill();
    ctx.strokeStyle="rgba(255,255,255,.34)";
    ctx.lineWidth=.7;
    ctx.stroke();
    const shouldLabel = viewport.scale>1.15 || (viewport.scale>.72 && ["memory","agent","workspace"].includes(node.kind));
    if(shouldLabel){
      ctx.fillStyle="#dcecff";
      ctx.font=node.kind==="memory"?"12px system-ui":"600 12px system-ui";
      const label=node.label.length>38?`${node.label.slice(0,35)}...`:node.label;
      ctx.fillText(label,node.x+13,node.y+4);
    }
  }
  function draw(){
    const time=performance.now()-galaxy.started;
    tick();ctx.clearRect(0,0,canvas.width,canvas.height);drawSpace(time);const nodes=visibleNodes();
    ctx.save();
    ctx.translate(viewport.x,viewport.y);
    ctx.scale(viewport.scale,viewport.scale);
    ctx.globalCompositeOperation="lighter";
    ctx.lineWidth=.7;for(const e of edges){const a=nodeMap[e.source],b=nodeMap[e.target];if(!nodes.includes(a)||!nodes.includes(b))continue;const strength=Math.max(.025,Math.min(.13,Number(e.strength||.1)));ctx.strokeStyle=`rgba(125,211,252,${strength})`;ctx.beginPath();ctx.moveTo(a.x,a.y);const midX=(a.x+b.x)/2+(b.y-a.y)*.035,midY=(a.y+b.y)/2-(b.x-a.x)*.035;ctx.quadraticCurveTo(midX,midY,b.x,b.y);ctx.stroke()}
    for(const n of nodes){drawNode(n,time)}
    ctx.globalCompositeOperation="source-over";
    ctx.restore();
    requestAnimationFrame(draw);
  }
  canvas.addEventListener("wheel",ev=>{ev.preventDefault();const r=canvas.getBoundingClientRect();zoomBy(ev.deltaY<0?1.14:.88,ev.clientX-r.left,ev.clientY-r.top)},{passive:false});
  let dragging=false;
  let dragStart=null;
  let dragMoved=false;
  canvas.addEventListener("pointerdown",ev=>{dragging=true;dragMoved=false;dragStart={x:ev.clientX,y:ev.clientY,viewX:viewport.x,viewY:viewport.y};canvas.setPointerCapture(ev.pointerId)});
  canvas.addEventListener("pointermove",ev=>{if(!dragging||!dragStart)return;const dx=ev.clientX-dragStart.x,dy=ev.clientY-dragStart.y;if(Math.hypot(dx,dy)>3)dragMoved=true;viewport.x=dragStart.viewX+dx;viewport.y=dragStart.viewY+dy});
  canvas.addEventListener("pointerup",ev=>{dragging=false;dragStart=null;canvas.releasePointerCapture(ev.pointerId)});
  canvas.addEventListener("pointercancel",()=>{dragging=false;dragStart=null});
  canvas.addEventListener("click",ev=>{if(dragMoved){dragMoved=false;return;}const r=canvas.getBoundingClientRect();const point=screenToGraph(ev.clientX-r.left,ev.clientY-r.top);let found=null;for(const n of visibleNodes()){if(Math.hypot(n.x-point.x,n.y-point.y)<14)found=n}if(found&&graphDetails){const related=edges.filter(e=>e.source===found.id||e.target===found.id).length;graphDetails.classList.remove("empty");graphDetails.innerHTML=`<h3>${escapeHtml(found.label)}</h3><p><span class="badge text-bg-info">${escapeHtml(found.kind)}</span></p><pre>${escapeHtml(JSON.stringify(found.meta||{},null,2))}</pre><p class="text-secondary">${related} relationships</p>`}});
  if(graphZoomIn) graphZoomIn.addEventListener("click",()=>zoomBy(1.18));
  if(graphZoomOut) graphZoomOut.addEventListener("click",()=>zoomBy(.85));
  if(graphZoomReset) graphZoomReset.addEventListener("click",resetView);
  if(graphFullscreen){
    const panel=canvas.closest(".graph-panel");
    const updateFullscreenButton=()=>{
      const active=document.fullscreenElement===panel;
      graphFullscreen.innerHTML=active?'<i class="fa-solid fa-compress"></i>':'<i class="fa-solid fa-expand"></i>';
      graphFullscreen.title=active?"Exit fullscreen":"Fullscreen graph";
      graphFullscreen.setAttribute("aria-label", graphFullscreen.title);
      setTimeout(resize,80);
    };
    graphFullscreen.addEventListener("click",async()=>{
      if(!panel||!document.fullscreenEnabled) return;
      try{
        if(document.fullscreenElement===panel) await document.exitFullscreen();
        else await panel.requestFullscreen();
      }catch(error){
        console.warn("Could not toggle graph fullscreen", error);
      }
    });
    document.addEventListener("fullscreenchange",updateFullscreenButton);
  }
  window.addEventListener("resize",resize);
  updateVisibleCounts();
  if(graphFilter) graphFilter.addEventListener("change",updateVisibleCounts);
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
