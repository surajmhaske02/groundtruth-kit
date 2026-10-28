"""
viz — renders the groundtruth HTML report (used by `gt.py viz`).

One self-contained HTML file: no CDN, no server, works offline, light/dark mode, phone-friendly.
  Overview       entry points, AI hotspots, runtime-only spots, duplicates, risk by file
  Flow explorer  search any function; expand what it calls or who calls it; copy as Mermaid
  Agent runs     timeline (waterfall) of every LLM/tool/node step; first error; compare two runs
"""
import html
import json


def build_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(str(data.get("repo", "repo")))).replace("__DATA__", payload)


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>groundtruth · __TITLE__</title>
<style>
:root{--bg:#ffffff;--bg2:#f7f6f2;--bg3:#efede6;--fg:#1f1e1c;--fg2:#5f5e5a;--fg3:#8a8880;--bd:rgba(31,30,28,.12);--bd2:rgba(31,30,28,.22);
--acc:#185FA5;--acc-bg:#E6F1FB;--llm:#993556;--llm-bg:#FBEAF0;--llm-bar:#D4537E;--tool:#0F6E56;--tool-bg:#E1F5EE;--tool-bar:#1D9E75;
--gr:#534AB7;--gr-bg:#EEEDFE;--gr-bar:#7F77DD;--ret:#185FA5;--ret-bg:#E6F1FB;--ret-bar:#378ADD;--dyn:#854F0B;--dyn-bg:#FAEEDA;--dyn-bar:#EF9F27;
--err:#A32D2D;--err-bg:#FCEBEB;--err-bar:#E24B4A;--ok:#3B6D11;--ok-bg:#EAF3DE;--node:#5F5E5A;--node-bg:#F1EFE8;--node-bar:#B4B2A9;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;--r:8px}
@media (prefers-color-scheme:dark){:root{--bg:#1c1b1a;--bg2:#252422;--bg3:#2e2d2a;--fg:#ecebe6;--fg2:#b4b2a9;--fg3:#8a8880;--bd:rgba(255,255,255,.12);--bd2:rgba(255,255,255,.22);
--acc:#85B7EB;--acc-bg:#0C447C;--llm:#F4C0D1;--llm-bg:#72243E;--tool:#9FE1CB;--tool-bg:#085041;--gr:#CECBF6;--gr-bg:#3C3489;--ret:#B5D4F4;--ret-bg:#0C447C;
--dyn:#FAC775;--dyn-bg:#633806;--err:#F7C1C1;--err-bg:#791F1F;--ok:#C0DD97;--ok-bg:#27500A;--node:#D3D1C7;--node-bg:#444441;--node-bar:#888780}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
button{font:inherit;color:inherit;background:transparent;border:.5px solid var(--bd2);border-radius:var(--r);padding:6px 12px;cursor:pointer}
button:hover{background:var(--bg2)}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
input,select{font:inherit;color:inherit;background:var(--bg);border:.5px solid var(--bd2);border-radius:var(--r);padding:7px 10px}
code,.mono{font-family:var(--mono);font-size:12.5px}
.top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:.5px solid var(--bd);padding:10px 16px 0}
.brand{display:flex;gap:10px;align-items:center;margin-bottom:8px}
.logo{width:30px;height:30px;border-radius:8px;background:var(--gr-bg);color:var(--gr);display:flex;align-items:center;justify-content:center;font:600 13px var(--mono)}
.t1{font-weight:600}.t2{font-size:12px;color:var(--fg3)}
.tabs{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}
.tabs button{border:0;border-bottom:2px solid transparent;border-radius:0;padding:8px 10px;color:var(--fg2);white-space:nowrap}
.tabs button[aria-selected=true]{color:var(--fg);border-bottom-color:var(--acc)}.tabs button:hover{background:transparent;color:var(--fg)}
.count{font-size:11px;background:var(--bg3);border-radius:10px;padding:1px 7px;margin-left:4px}
main{max-width:1180px;margin:0 auto;padding:16px}
h2{font-size:16px;font-weight:600;margin:28px 0 10px}.lead{color:var(--fg2);margin:0 0 16px}.hint{color:var(--fg3);font-size:13px;margin:-4px 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.card{background:var(--bg2);border-radius:var(--r);padding:12px 14px;border:0;text-align:left;display:block;width:100%}
.card .l{font-size:12.5px;color:var(--fg2)}.card .v{font-size:24px;font-weight:600;line-height:1.3}.card .s{font-size:12px;color:var(--fg3)}
.card.warn .v{color:var(--dyn)}.card.bad .v{color:var(--err)}
.list{border:.5px solid var(--bd);border-radius:var(--r);overflow:hidden}
.li{display:flex;gap:10px;align-items:center;padding:9px 12px;border-top:.5px solid var(--bd);flex-wrap:wrap}.li:first-child{border-top:0}
.li .grow{flex:1;min-width:180px}.li .sub{font-size:12px;color:var(--fg3);font-family:var(--mono)}
.chip{display:inline-block;font-size:11.5px;font-weight:500;padding:1px 8px;border-radius:10px;white-space:nowrap;background:var(--node-bg);color:var(--node)}
.r-llm{background:var(--llm-bg);color:var(--llm)}.r-tool{background:var(--tool-bg);color:var(--tool)}.r-graph{background:var(--gr-bg);color:var(--gr)}
.r-ret{background:var(--ret-bg);color:var(--ret)}.r-dyn{background:var(--dyn-bg);color:var(--dyn)}.r-err{background:var(--err-bg);color:var(--err)}
.r-ok{background:var(--ok-bg);color:var(--ok)}.r-acc{background:var(--acc-bg);color:var(--acc)}
.link{border:0;padding:0;color:var(--acc);background:none;text-align:left}.link:hover{text-decoration:underline;background:none}
details{border:.5px solid var(--bd);border-radius:var(--r);margin:8px 0}summary{cursor:pointer;padding:10px 12px;font-weight:500}
details .inner{padding:0 12px 10px}.snip{display:block;font-family:var(--mono);font-size:12px;color:var(--fg2);white-space:pre-wrap;word-break:break-word}
.risk{display:grid;grid-template-columns:minmax(0,40%) minmax(0,1fr) 36px;gap:6px 10px;align-items:center;font-size:13px}
.risk .f{font-family:var(--mono);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left}
.bar{display:flex;height:12px;border-radius:3px;overflow:hidden;background:var(--bg3)}.bar span{display:block;height:100%}
.leg{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--fg2);margin:6px 0 12px}.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px}.controls label{font-size:13px;color:var(--fg2);display:flex;gap:6px;align-items:center}
.search{position:relative;flex:1 1 260px}.search input{width:100%}
.sugg{position:absolute;left:0;right:0;top:100%;margin-top:4px;background:var(--bg);border:.5px solid var(--bd2);border-radius:var(--r);z-index:4;max-height:340px;overflow:auto}
.sugg button{display:block;width:100%;text-align:left;border:0;border-radius:0;border-top:.5px solid var(--bd)}.sugg button:first-child{border-top:0}
.seg{display:inline-flex;border:.5px solid var(--bd2);border-radius:var(--r);overflow:hidden}.seg button{border:0;border-radius:0;padding:6px 12px}
.seg button[aria-pressed=true]{background:var(--acc-bg);color:var(--acc)}
.treehead{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0 8px}
.tree{border:.5px solid var(--bd);border-radius:var(--r);padding:6px 0;overflow-x:auto}
.row{display:flex;align-items:center;gap:6px;padding:4px 10px 4px calc(10px + var(--d,0) * 18px);min-height:32px;white-space:nowrap;position:relative}
.row:hover{background:var(--bg2)}.row.sel{background:var(--acc-bg)}
.row::before{content:"";position:absolute;left:calc(19px + (var(--d,0) - 1) * 18px);top:0;bottom:0;border-left:.5px solid var(--bd2);display:var(--guide,block)}
.car{width:22px;height:22px;padding:0;border:0;border-radius:4px;color:var(--fg2);flex:none;font-size:11px}.car[aria-expanded=true]{transform:rotate(90deg)}.sp{width:22px;flex:none}
.kb{width:18px;height:18px;border-radius:4px;background:var(--bg3);color:var(--fg2);font:600 10px var(--mono);display:inline-flex;align-items:center;justify-content:center;flex:none}
.nm{border:0;padding:0 2px;background:none;font-weight:500}.nm:hover{background:none;text-decoration:underline}
.loc{font-family:var(--mono);font-size:11.5px;color:var(--fg3)}.tag{font-size:11px;color:var(--fg3)}
.kids[hidden]{display:none}
.icard{margin:2px 12px 8px calc(12px + var(--d,0) * 18px);border:.5px solid var(--bd2);border-radius:var(--r);padding:10px 12px;background:var(--bg);white-space:normal}
.icard .q{font-weight:600;word-break:break-all}.icard .row2{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:13px;margin:8px 0}.kv dt{color:var(--fg3)}.kv dd{margin:0;word-break:break-word}
pre{font-family:var(--mono);font-size:12px;background:var(--bg2);border-radius:6px;padding:8px 10px;margin:4px 0 8px;white-space:pre-wrap;word-break:break-word;max-height:320px;overflow:auto}
.runsgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}
@media (min-width:980px){.runsgrid{grid-template-columns:300px minmax(0,1fr)}.runlist{position:sticky;top:110px;align-self:start;max-height:calc(100vh - 130px);overflow:auto}}
.runrow{display:flex;gap:10px;width:100%;text-align:left;border:0;border-top:.5px solid var(--bd);border-radius:0;padding:9px 12px;align-items:flex-start}
.runrow:first-child{border-top:0}.runrow[aria-current=true]{background:var(--acc-bg)}
.dot{width:9px;height:9px;border-radius:50%;margin-top:6px;flex:none;background:var(--ok-bar,#639922)}.dot.error{background:var(--err-bar)}.dot.unfinished{background:var(--dyn-bar)}
.callout{border:.5px solid var(--err);background:var(--err-bg);color:var(--err);border-radius:var(--r);padding:10px 12px;margin:10px 0;font-size:13.5px}
.callout.warn{border-color:var(--dyn);background:var(--dyn-bg);color:var(--dyn)}.callout.ok{border-color:var(--ok);background:var(--ok-bg);color:var(--ok)}
.callout b{font-weight:600}.callout code{color:inherit}
.wf{border:.5px solid var(--bd);border-radius:var(--r);overflow:hidden}
.wrow{display:grid;grid-template-columns:minmax(0,46%) minmax(0,1fr);align-items:center;border-top:.5px solid var(--bd);cursor:pointer;min-height:34px}
.wrow:first-child{border-top:0;cursor:default}.wrow:hover{background:var(--bg2)}.wrow.sel{background:var(--acc-bg)}
.wl{display:flex;gap:6px;align-items:center;padding:4px 8px 4px calc(8px + var(--d,0) * 14px);overflow:hidden;white-space:nowrap}.wl .n{overflow:hidden;text-overflow:ellipsis}
.wt{position:relative;height:34px;margin-right:10px}.wt .b{position:absolute;top:11px;height:12px;border-radius:3px;min-width:3px}
.wt .ev{position:absolute;top:12px;width:10px;height:10px;transform:rotate(45deg);background:var(--fg3);margin-left:-5px}
.wt .ms{position:absolute;top:24px;font-size:10.5px;color:var(--fg3);white-space:nowrap}
.scale{display:flex;justify-content:space-between;font-size:11px;color:var(--fg3);padding:0 10px 0 0}
.b-llm{background:var(--llm-bar)}.b-tool{background:var(--tool-bar)}.b-graph{background:var(--gr-bar)}.b-ret{background:var(--ret-bar)}.b-node{background:var(--node-bar)}
.b-err{background:var(--err-bar)}.b-unf{background:repeating-linear-gradient(45deg,var(--dyn-bar) 0 4px,transparent 4px 7px);border:1px solid var(--dyn-bar)}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}
.drow{display:flex;gap:8px;align-items:center;padding:5px 10px 5px calc(10px + var(--d,0) * 14px);border-top:.5px solid var(--bd);font-size:13px;cursor:default}
.drow .m{font-family:var(--mono);width:14px;text-align:center;flex:none}.drow.ne{background:var(--dyn-bg)}.drow.a{background:var(--err-bg)}.drow.b{background:var(--ok-bg)}.drow.ne{cursor:pointer}
.empty{border:.5px dashed var(--bd2);border-radius:var(--r);padding:20px;color:var(--fg2)}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:8px 14px;border-radius:var(--r);font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;z-index:9}
.toast.on{opacity:1}textarea{width:100%;min-height:160px;font-family:var(--mono);font-size:12px;background:var(--bg2);color:var(--fg);border:.5px solid var(--bd2);border-radius:var(--r);padding:8px}
@media (max-width:640px){.row{flex-wrap:wrap;white-space:normal;row-gap:0}.row .loc,.row .tag{font-size:11px}.tree{overflow-x:visible}
.wrow{grid-template-columns:minmax(0,1fr)}.wl{padding-top:6px}.wt{height:26px;margin:0 10px 4px calc(10px + var(--d,0) * 14px)}.wt .b{top:4px}.wt .ev{top:5px}.wt .ms{top:14px}
.wrow:first-child .wl{display:none}.scale{padding:6px 10px}}
#diff{margin-bottom:14px}.muted{color:var(--fg3)}.foot{color:var(--fg3);font-size:12px;margin:40px 0 10px;border-top:.5px solid var(--bd);padding-top:12px}
</style>
</head>
<body>
<header class="top">
  <div class="brand"><span class="logo">gt</span><div><div class="t1">__TITLE__</div><div class="t2" id="gen"></div></div></div>
  <nav class="tabs" role="tablist" aria-label="Report sections">
    <button role="tab" data-tab="overview" aria-selected="true">Overview</button>
    <button role="tab" data-tab="flow" aria-selected="false">Flow explorer</button>
    <button role="tab" data-tab="runs" aria-selected="false">Agent runs<span class="count" id="runcount"></span></button>
  </nav>
</header>
<main>
<section class="panel" id="p-overview">
  <p class="lead">Where requests start, where the AI is called, and where reading the code is not enough. Tap any function to explore its flow.</p>
  <div class="cards" id="cards"></div>
  <h2>Where to start</h2><div id="entries"></div>
  <h2>Risk by file</h2><p class="hint">Files with the most AI calls, runtime-only dispatch and duplicated code. Start reviews here.</p>
  <div class="leg"><span><i style="background:var(--llm-bar)"></i>AI hotspots</span><span><i style="background:var(--dyn-bar)"></i>Runtime-only</span><span><i style="background:var(--err-bar)"></i>Duplicates</span></div>
  <div id="risk"></div>
  <h2>Details</h2><div id="details"></div>
</section>
<section class="panel" id="p-flow" hidden>
  <div class="controls">
    <div class="search"><input id="q" type="search" placeholder="Search a function, e.g. handle_chat" autocomplete="off" aria-label="Search a function"><div id="sugg" class="sugg" hidden></div></div>
    <div class="seg" role="group" aria-label="Direction"><button data-mode="calls" aria-pressed="true">Calls</button><button data-mode="callers" aria-pressed="false">Called by</button></div>
    <label>Depth <select id="depth"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option><option>6</option></select></label>
    <label><input type="checkbox" id="lib" checked> AI and IO library calls</label>
  </div>
  <div class="leg"><span class="chip r-llm">LLM</span><span class="chip r-tool">Tool</span><span class="chip r-graph">Graph</span><span class="chip r-ret">Retrieval</span><span class="chip r-dyn">⚡ runtime only</span><span class="chip r-err">⚠ ambiguous</span><span class="muted">⇢ passed as callback · ~ guessed by name</span></div>
  <div id="treehead" class="treehead"></div>
  <div id="mmbox"></div>
  <div id="tree" class="tree"></div>
  <p class="hint" style="margin-top:10px">Static and name-based: it shows where code is defined and wired. Anything marked ⚡ or ⚠ must be confirmed by running it (see Agent runs).</p>
</section>
<section class="panel" id="p-runs" hidden>
  <div class="runsgrid"><div><div id="runlist" class="list"></div></div><div id="run"></div></div>
</section>
<p class="foot">Generated by groundtruth · <code>python tools/groundtruth/gt.py viz</code> · rerun after code changes or new agent runs.</p>
</main>
<div class="toast" id="toast" role="status"></div>
<script type="application/json" id="gt-data">__DATA__</script>
<script>
(function () {
"use strict";
var D = JSON.parse(document.getElementById("gt-data").textContent);
function $(s, el) { return (el || document).querySelector(s); }
function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
function esc(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function toast(t) { var x = $("#toast"); x.textContent = t; x.classList.add("on"); clearTimeout(x._t); x._t = setTimeout(function () { x.classList.remove("on"); }, 2200); }
function fmtMs(ms) { if (ms == null) return "?"; return ms < 1 ? ms.toFixed(1) + " ms" : ms < 1000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(2) + " s"; }
function pretty(v) { var s; try { s = typeof v === "string" ? v : JSON.stringify(v, null, 2); } catch (e) { s = String(v); } return s && s.length > 20000 ? s.slice(0, 20000) + "\n… (truncated)" : s; }
function brief(v, n) { if (v == null) return ""; var s; try { s = typeof v === "string" ? v : JSON.stringify(v); } catch (e) { s = String(v); } s = s.replace(/\s+/g, " "); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function copyText(text, label, box) {
  function fallback() { var b = $(box); b.innerHTML = '<p class="hint">Copy this:</p>'; var ta = el("textarea"); ta.value = text; b.appendChild(ta); ta.focus(); ta.select(); }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(function () { toast(label); }, fallback); else fallback();
}

var N = D.nodes.map(function (a, i) { return {id: i, qual: a[0], kind: a[1], file: a[2], line: a[3], role: a[4], doc: a[5], deco: a[6]}; });
var E = D.edges || {}, HID = D.hidden || {}, CALLERS = {};
Object.keys(E).forEach(function (src) { E[src].forEach(function (e) {
  if (e[1] >= 0) (CALLERS[e[1]] = CALLERS[e[1]] || []).push({src: +src, k: e[0], line: e[3]});
  (e[6] || []).forEach(function (c) { (CALLERS[c] = CALLERS[c] || []).push({src: +src, k: "a", line: e[3]}); });
}); });
function loc(n) { return n.file + ":" + n.line; }
var ROLE = {llm: ["LLM", "r-llm"], tool: ["Tool", "r-tool"], graph: ["Graph", "r-graph"], retrieval: ["Retrieval", "r-ret"]};
var TAGC = {LLM: "r-llm", INVOKE: "r-llm", TOOL: "r-tool", GRAPH: "r-graph", AGENT: "r-graph", RETRIEVAL: "r-ret", IO: "r-acc", PROMPT: "r-graph"};
function roleChip(r) { var x = ROLE[r]; return x ? '<span class="chip ' + x[1] + '">' + x[0] + "</span>" : ""; }
function kb(kind) { return '<span class="kb" title="' + esc(kind) + '">' + (kind === "class" ? "C" : kind === "module" ? "≡" : kind.indexOf("method") >= 0 ? "M" : kind === "interface" ? "I" : "F") + "</span>"; }

// ------------------------------------------------------------------ tabs
function show(tab) {
  $$("[data-tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === tab)); });
  $$(".panel").forEach(function (p) { p.hidden = p.id !== "p-" + tab; });
  try { history.replaceState(null, "", "#" + tab); } catch (e) {}
  window.scrollTo(0, 0);
}
$$("[data-tab]").forEach(function (b) { b.onclick = function () { show(b.dataset.tab); }; });

// ------------------------------------------------------------------ overview
var S = D.stats;
function pl(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
$("#gen").textContent = "Generated " + D.generated + " · " + S.files + " code files";
$("#runcount").textContent = S.runs;
var cards = [
  ["Entry points", S.entries, "where requests start", "", "entries"],
  ["Functions", S.functions, pl(S.classes, "class", "classes"), "", null],
  ["AI hotspots", S.hotspots, "LLM, tool, graph, prompt", "", "d-hot"],
  ["Runtime-only", S.dynamic, "chosen while running", S.dynamic ? "warn" : "", "d-dyn"],
  ["Duplicates", S.dups + S.clones, pl(S.dups, "name") + " · " + pl(S.clones, "clone"), S.dups + S.clones ? "warn" : "", "d-dup"],
  ["Agent runs", S.runs, S.run_errors + " with errors", S.run_errors ? "bad" : "", "runs"]
];
cards.forEach(function (c) {
  var b = el("button", "card " + c[3], '<div class="l">' + esc(c[0]) + '</div><div class="v">' + esc(c[1]) + '</div><div class="s">' + esc(c[2]) + "</div>");
  b.onclick = function () { if (c[4] === "runs") return show("runs"); var t = document.getElementById(c[4]); if (t) { if (t.tagName === "DETAILS") t.open = true; t.scrollIntoView({behavior: "smooth", block: "start"}); } };
  $("#cards").appendChild(b);
});
(function () {
  var box = $("#entries");
  if (!D.entries.length) { box.innerHTML = '<div class="empty">No entry points detected automatically. List them in AGENTS.md → Project facts, then search them in Flow explorer.</div>'; return; }
  var list = el("div", "list");
  D.entries.forEach(function (e) {
    var li = el("div", "li", '<span class="chip r-acc">' + esc(e[1]) + '</span><div class="grow"><code>' + esc(e[2]) + '</code><div class="sub">' + esc(e[0]) + "</div></div>");
    if (e[3] >= 0) { var b = el("button", "", "Explore flow"); b.onclick = function () { openFlow(e[3], "calls"); }; li.appendChild(b); }
    list.appendChild(li);
  });
  box.appendChild(list);
})();
(function () {
  var f = {};
  function add(file, key) { if (!file || file === "…") return; f[file] = f[file] || {ai: 0, dyn: 0, dup: 0}; f[file][key]++; }
  function fileOf(l) { return String(l).replace(/:\d+$/, ""); }
  Object.keys(D.hot).forEach(function (k) { D.hot[k].forEach(function (x) { add(fileOf(x[0]), "ai"); }); });
  Object.keys(D.dynamic).forEach(function (k) { D.dynamic[k].forEach(function (x) { add(fileOf(x[0]), "dyn"); }); });
  D.dups.forEach(function (d) { d[1].forEach(function (x) { add(fileOf(x[1]), "dup"); }); });
  D.clones.forEach(function (g) { g.forEach(function (x) { add(fileOf(x[1]), "dup"); }); });
  var rows = Object.keys(f).map(function (k) { var v = f[k]; return [k, v, v.ai + v.dyn + v.dup]; }).sort(function (a, b) { return b[2] - a[2]; }).slice(0, 12);
  if (!rows.length) { $("#risk").innerHTML = '<div class="empty">Nothing flagged.</div>'; return; }
  var max = rows[0][2], g = el("div", "risk");
  rows.forEach(function (r) {
    var w = function (n) { return (100 * n / max).toFixed(2) + "%"; };
    g.insertAdjacentHTML("beforeend", '<div class="f" title="' + esc(r[0]) + '">&lrm;' + esc(r[0]) + '&lrm;</div><div class="bar" role="img" aria-label="' + r[1].ai + " AI, " + r[1].dyn + " runtime-only, " + r[1].dup + ' duplicates"><span style="width:' + w(r[1].ai) + ';background:var(--llm-bar)"></span><span style="width:' + w(r[1].dyn) + ';background:var(--dyn-bar)"></span><span style="width:' + w(r[1].dup) + ';background:var(--err-bar)"></span></div><div class="muted" style="text-align:right">' + r[2] + "</div>");
  });
  $("#risk").appendChild(g);
})();
(function () {
  var box = $("#details");
  function group(id, title, obj, chip) {
    var keys = Object.keys(obj); if (!keys.length) return;
    var total = keys.reduce(function (a, k) { return a + obj[k].filter(function (x) { return x[0] !== "…"; }).length; }, 0);
    var d = el("details"); d.id = id; d.innerHTML = "<summary>" + esc(title) + ' <span class="muted">(' + total + ")</span></summary>";
    var inner = el("div", "inner");
    keys.forEach(function (k) {
      inner.insertAdjacentHTML("beforeend", '<p style="margin:10px 0 4px"><span class="chip ' + chip(k) + '">' + esc(k) + "</span></p>");
      var list = el("div", "list");
      obj[k].forEach(function (x) {
        var li = el("div", "li", '<div class="grow"><div class="sub">' + esc(x[0]) + '</div><span class="snip">' + esc(x[1]) + "</span></div>");
        if (x[2] >= 0) { var b = el("button", "", "Explore"); b.onclick = function () { openFlow(x[2], "calls"); }; li.appendChild(b); }
        list.appendChild(li);
      });
      inner.appendChild(list);
    });
    d.appendChild(inner); box.appendChild(d);
  }
  group("d-hot", "AI hotspots: LLM calls, tools, graphs, prompts, retrieval", D.hot, function (k) { return /LLM|invoke/.test(k) ? "r-llm" : /tool/.test(k) ? "r-tool" : /retrieval/.test(k) ? "r-ret" : "r-graph"; });
  group("d-dyn", "Runtime-only: static reading can't tell what runs here", D.dynamic, function () { return "r-dyn"; });
  if (D.dups.length || D.clones.length) {
    var d = el("details"); d.id = "d-dup"; d.innerHTML = "<summary>Duplicates and renamed clones <span class=\"muted\">(" + (D.dups.length + D.clones.length) + ")</span></summary>";
    var inner = el("div", "inner"), list = el("div", "list");
    function item(label, members) {
      var li = el("div", "li"); var g = el("div", "grow", label ? "<code>" + esc(label) + "</code>" : "");
      members.forEach(function (m, i) {
        var a = el("button", "link mono", esc(m[0]) + " <span class=\"muted\">" + esc(m[1]) + "</span>");
        a.style.display = "block"; if (m[2] >= 0) a.onclick = function () { openFlow(m[2], "callers"); };
        g.appendChild(a);
      });
      li.appendChild(g); list.appendChild(li);
    }
    D.dups.forEach(function (x) { item("same name in " + x[1].length + " files: " + x[0], x[1]); });
    D.clones.forEach(function (g) { item("same body, renamed", g); });
    inner.appendChild(el("p", "hint", "Tap one to see who calls it: fix the copy that actually runs, delete the other."));
    inner.appendChild(list); d.appendChild(inner); box.appendChild(d);
  }
  if (D.parse_errors.length) {
    var p = el("details"); p.innerHTML = "<summary>Files that failed to parse <span class=\"muted\">(" + D.parse_errors.length + ")</span></summary>";
    var pi = el("div", "inner"); D.parse_errors.forEach(function (x) { pi.insertAdjacentHTML("beforeend", '<div class="sub mono">' + esc(x[0]) + " — " + esc(x[1]) + "</div>"); });
    p.appendChild(pi); box.appendChild(p);
  }
  if (S.truncated) box.insertAdjacentHTML("beforeend", '<p class="hint">Large repo: the flow explorer includes the functions reachable from entry points and AI hotspots.</p>');
})();

// ------------------------------------------------------------------ flow explorer
var F = {root: null, mode: "calls", depth: 3, lib: true, open: null};
function callsOf(id) {
  var out = [];
  (E[id] || []).forEach(function (e) {
    var k = e[0];
    if (k === "d") out.push({t: "dyn", disp: e[2], line: e[3]});
    else if (k === "a") out.push({t: "amb", disp: e[2], line: e[3], cands: e[6] || []});
    else if (k === "x") { if (F.lib) out.push({t: "ext", disp: e[2], line: e[3], tag: e[5]}); }
    else out.push({t: "node", id: e[1], ref: k === "r", prob: e[4] === "probable", line: e[3], tag: e[5]});
  });
  return out;
}
function callersOf(id) {
  var seen = {}, out = [];
  (CALLERS[id] || []).forEach(function (c) { if (seen[c.src]) return; seen[c.src] = 1; out.push({t: "node", id: c.src, ref: c.k === "r", amb: c.k === "a", line: c.line}); });
  return out;
}
function kidsOf(item) {
  if (item.t === "amb") return item.cands.map(function (c) { return {t: "node", id: c, line: item.line, cand: true}; });
  if (item.t !== "node") return [];
  return F.mode === "calls" ? callsOf(item.id) : callersOf(item.id);
}
function hasKids(item) {
  if (item.t === "amb") return item.cands.length > 0;
  if (item.t !== "node") return false;
  return F.mode === "calls" ? callsOf(item.id).length > 0 || !!HID[item.id] : (CALLERS[item.id] || []).length > 0;
}
function rowHtml(item, anc) {
  if (item.t === "dyn") return '<span class="chip r-dyn">⚡ runtime only</span><code>' + esc(item.disp) + '</code><span class="tag">line ' + item.line + "</span>";
  if (item.t === "amb") return '<span class="chip r-err">⚠ ambiguous</span><code>' + esc(item.disp) + '</code><span class="tag">' + item.cands.length + " possible definitions</span>";
  if (item.t === "ext") return '<span class="chip ' + (TAGC[item.tag] || "") + '">' + esc(item.tag || "lib") + "</span><code>" + esc(item.disp) + '</code><span class="tag">library</span>';
  var n = N[item.id], bits = [];
  if (item.ref) bits.push(F.mode === "calls" ? "⇢ callback" : "⇢ passes it as callback");
  if (item.prob) bits.push("~ guessed by name");
  if (item.amb) bits.push("via an ambiguous name");
  if (item.cand) bits.push("candidate");
  if (anc && anc.indexOf(item.id) >= 0) bits.push("↻ recursive");
  if (item.line && item.t === "node" && item.depth) bits.push((F.mode === "calls" ? "called at L" : "calls it at L") + item.line);
  return kb(n.kind) + roleChip(n.role) + '<button class="nm" data-id="' + n.id + '">' + esc(n.qual) + '</button><span class="loc">' + esc(loc(n)) + "</span>" + (bits.length ? '<span class="tag">' + esc(bits.join(" · ")) + "</span>" : "");
}
function makeItem(item, depth, anc, seen, auto) {
  item.depth = depth;
  var wrap = el("div", "tn"), row = el("div", "row"); row.style.setProperty("--d", depth);
  if (depth === 0) row.style.setProperty("--guide", "none");
  var recursive = item.t === "node" && anc.indexOf(item.id) >= 0;
  var can = hasKids(item) && !recursive;
  var car = can ? el("button", "car", "▶") : el("span", "sp");
  if (can) { car.setAttribute("aria-expanded", "false"); car.setAttribute("aria-label", "Expand"); }
  row.appendChild(car); row.insertAdjacentHTML("beforeend", rowHtml(item, anc));
  var kids = el("div", "kids"); kids.hidden = true;
  wrap.appendChild(row); wrap.appendChild(kids);
  var filled = false;
  function fill(autoDepth) {
    if (filled) return; filled = true;
    var nanc = item.t === "node" ? anc.concat([item.id]) : anc;
    kidsOf(item).forEach(function (k) {
      var again = k.t === "node" && seen[k.id];
      if (k.t === "node") seen[k.id] = true;
      kids.appendChild(makeItem(k, depth + 1, nanc, seen, again ? 0 : autoDepth - 1));
      if (again) { var last = kids.lastChild.querySelector(".row"); last.insertAdjacentHTML("beforeend", '<span class="tag">· shown above</span>'); }
    });
    if (F.mode === "calls" && item.t === "node" && HID[item.id]) {
      var r = el("div", "row muted", '<span class="sp"></span><span class="tag">+' + HID[item.id] + " plain library calls not shown</span>"); r.style.setProperty("--d", depth + 1); kids.appendChild(r);
    }
  }
  function toggle(open) {
    if (!can) return; if (open) fill(0);
    kids.hidden = !open; car.setAttribute("aria-expanded", String(open)); car.setAttribute("aria-label", open ? "Collapse" : "Expand");
  }
  if (can) car.onclick = function () { toggle(kids.hidden); };
  if (can && auto > 0) { fill(auto); toggle(true); }
  return wrap;
}
function renderFlow() {
  var r = N[F.root]; if (!r) return;
  $$(".seg button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.mode === F.mode)); });
  var head = $("#treehead");
  head.innerHTML = '<div><span class="muted">' + (F.mode === "calls" ? "What it calls" : "Who calls it") + "</span> · <b>" + esc(r.qual) + '</b> <span class="loc">' + esc(loc(r)) + "</span></div>";
  var cm = el("button", "", "Copy as Mermaid"); cm.onclick = function () { copyText(mermaidFlow(F.root), "Mermaid copied: paste it into a ```mermaid block", "#mmbox"); };
  head.appendChild(cm); $("#mmbox").innerHTML = "";
  var tree = $("#tree"); tree.innerHTML = "";
  var seen = {}; seen[F.root] = true;
  tree.appendChild(makeItem({t: "node", id: F.root}, 0, [], seen, F.depth));
  F.open = null;
}
function openFlow(id, mode) { F.root = id; if (mode) F.mode = mode; $("#q").value = N[id].qual; show("flow"); renderFlow(); }
$("#tree").addEventListener("click", function (ev) {
  var b = ev.target.closest(".nm"); if (!b) return;
  var id = +b.dataset.id, row = b.closest(".row"), wrap = row.parentNode;
  $$(".row.sel").forEach(function (x) { x.classList.remove("sel"); });
  var old = $(".icard", $("#tree")); var same = old && old.previousSibling === row; if (old) old.remove();
  if (same) return;
  row.classList.add("sel");
  var card = infoCard(id); card.style.setProperty("--d", row.style.getPropertyValue("--d") || 0);
  wrap.insertBefore(card, row.nextSibling);
});
function infoCard(id) {
  var n = N[id], out = E[id] || [], calls = out.filter(function (e) { return e[1] >= 0 && e[0] !== "x"; }).length;
  var libs = out.filter(function (e) { return e[0] === "x"; }).length + (HID[id] || 0);
  var dyn = out.filter(function (e) { return e[0] === "d" || e[0] === "a"; }).length;
  var cs = callersOf(id);
  var c = el("div", "icard");
  c.innerHTML = '<div class="q">' + esc(n.qual) + "</div>" +
    '<dl class="kv"><dt>Where</dt><dd><code>' + esc(loc(n)) + "</code></dd><dt>Kind</dt><dd>" + esc(n.kind) + " " + roleChip(n.role) + "</dd>" +
    (n.deco ? "<dt>Decorator</dt><dd><code>@" + esc(n.deco) + "</code></dd>" : "") + (n.doc ? "<dt>Doc</dt><dd>" + esc(n.doc) + "</dd>" : "") +
    "<dt>Calls</dt><dd>" + calls + " functions · " + libs + " library calls" + (dyn ? ' · <span class="chip r-dyn">' + dyn + " runtime-only</span>" : "") + "</dd>" +
    "<dt>Called by</dt><dd>" + (cs.length ? cs.length + " functions" : '<span class="chip r-dyn">no static callers</span> <span class="muted">dead code, or called dynamically</span>') + "</dd></dl>";
  var r2 = el("div", "row2");
  var b1 = el("button", "", "Explore from here"); b1.onclick = function () { openFlow(id, "calls"); };
  var b2 = el("button", "", "Who calls this"); b2.onclick = function () { openFlow(id, "callers"); };
  var b3 = el("button", "", "Copy file:line"); b3.onclick = function () { copyText(loc(n), "Copied " + loc(n), "#mmbox"); };
  r2.appendChild(b1); r2.appendChild(b2); r2.appendChild(b3); c.appendChild(r2);
  return c;
}
function mmSafe(t, n) { t = String(t); n = n || 60; if (t.length > n) t = t.slice(0, n - 1) + "…"; return t.replace(/&/g, "#amp;").replace(/"/g, "#quot;").replace(/</g, "#lt;").replace(/>/g, "#gt;"); }
function mermaidFlow(rootId) {
  var ids = {}, decl = [], edges = [], cls = {}, count = 0;
  function node(key, label, k) { if (!(key in ids)) { ids[key] = "n" + (count++); decl.push("  " + ids[key] + '["' + label + '"]'); (cls[k] = cls[k] || []).push(ids[key]); } return ids[key]; }
  function lab(n) { return mmSafe(n.qual) + "<br/>" + mmSafe(loc(n)) + ""; }
  function k(n) { return {llm: "llm", tool: "tool", retrieval: "io"}[n.role] || "fn"; }
  var root = node("s" + rootId, lab(N[rootId]), "entry"), done = {};
  function rec(id, pid, d) {
    if (d >= F.depth || done[id]) return; done[id] = 1;
    var items = F.mode === "calls" ? callsOf(id) : callersOf(id);
    items.forEach(function (it) {
      var cid;
      if (it.t === "node") cid = node("s" + it.id, lab(N[it.id]), k(N[it.id]));
      else if (it.t === "dyn") cid = node("d" + pid + it.disp, "⚡ " + mmSafe(it.disp, 40) + "<br/>chosen at runtime", "dyn");
      else if (it.t === "amb") cid = node("a" + it.disp, "⚠ " + mmSafe(it.disp, 40) + "<br/>" + it.cands.length + " possible definitions", "amb");
      else cid = node("x" + it.disp, mmSafe((it.tag || "lib") + ": " + it.disp, 44), it.tag === "LLM" || it.tag === "INVOKE" ? "llm" : it.tag === "TOOL" ? "tool" : "io");
      var a = F.mode === "calls" ? pid : cid, b = F.mode === "calls" ? cid : pid;
      var line = "  " + a + (it.ref ? ' -. "callback" .-> ' : " --> ") + b;
      if (edges.indexOf(line) < 0) edges.push(line);
      if (it.t === "node") rec(it.id, cid, d + 1);
    });
  }
  rec(rootId, root, 0);
  var out = ["flowchart " + (F.mode === "calls" ? "TD" : "BT")].concat(decl, edges, [
    "  classDef entry fill:#EEEDFE,stroke:#534AB7,color:#26215C", "  classDef fn fill:#F1EFE8,stroke:#888780,color:#2C2C2A",
    "  classDef llm fill:#FBEAF0,stroke:#993556,color:#4B1528", "  classDef tool fill:#E1F5EE,stroke:#0F6E56,color:#04342C",
    "  classDef io fill:#E6F1FB,stroke:#185FA5,color:#042C53", "  classDef dyn fill:#FAEEDA,stroke:#854F0B,color:#412402,stroke-dasharray:4 3",
    "  classDef amb fill:#FCEBEB,stroke:#A32D2D,color:#501313,stroke-dasharray:4 3"]);
  Object.keys(cls).forEach(function (c) { out.push("  class " + cls[c].join(",") + " " + c); });
  return out.join("\n");
}
(function () {
  var q = $("#q"), sg = $("#sugg");
  function search() {
    var t = q.value.trim().toLowerCase(); if (!t) { sg.hidden = true; return; }
    var hits = [];
    for (var i = 0; i < N.length && hits.length < 400; i++) {
      var s = N[i].qual.toLowerCase(), last = s.split(".").pop();
      var score = s === t || last === t ? 0 : last.indexOf(t) === 0 ? 1 : s.indexOf(t) >= 0 ? 2 : N[i].file.toLowerCase().indexOf(t) >= 0 ? 3 : -1;
      if (score >= 0) hits.push([score, i]);
    }
    hits.sort(function (a, b) { return a[0] - b[0] || N[a[1]].qual.length - N[b[1]].qual.length; });
    sg.innerHTML = ""; hits.slice(0, 12).forEach(function (h) {
      var n = N[h[1]]; var b = el("button", "", kb(n.kind) + " " + roleChip(n.role) + " <b>" + esc(n.qual) + '</b> <span class="loc">' + esc(loc(n)) + "</span>");
      b.onmousedown = function (e) { e.preventDefault(); }; b.onclick = function () { sg.hidden = true; openFlow(n.id); };
      sg.appendChild(b);
    });
    if (!hits.length) sg.innerHTML = '<div class="li muted">No function matches “' + esc(q.value) + "”.</div>";
    sg.hidden = false;
  }
  q.addEventListener("input", search); q.addEventListener("focus", search);
  q.addEventListener("blur", function () { setTimeout(function () { sg.hidden = true; }, 150); });
  q.addEventListener("keydown", function (e) { if (e.key === "Enter") { var b = $("button", sg); if (b) b.click(); } if (e.key === "Escape") sg.hidden = true; });
  $$(".seg button").forEach(function (b) { b.onclick = function () { F.mode = b.dataset.mode; renderFlow(); }; });
  $("#depth").onchange = function () { F.depth = +this.value; renderFlow(); };
  $("#lib").onchange = function () { F.lib = this.checked; renderFlow(); };
  var first = D.entries.filter(function (e) { return e[3] >= 0; })[0];
  var start = first ? first[3] : -1;
  if (start < 0) { var best = -1; Object.keys(E).forEach(function (k) { if (best < 0 || E[k].length > E[best].length) best = +k; }); start = best; }
  if (start >= 0) { F.root = start; q.value = N[start].qual; renderFlow(); }
  else $("#tree").innerHTML = '<div class="empty" style="margin:10px">No call graph available (no Python functions found). Search still works for other languages.</div>';
})();

// ------------------------------------------------------------------ agent runs
var R = D.runs || [], CUR = null;
var KC = {llm: "llm", tool: "tool", retrieval: "ret", node: "graph", graph: "graph", agent: "graph"};
function kc(kind) { return KC[kind] || "node"; }
function prep(r) {
  if (r._p) return r._p;
  var kids = {}, all = r.spans.concat(r.events.map(function (e) { var x = {}; for (var k in e) x[k] = e[k]; x.kind = "event"; return x; }));
  all.forEach(function (n) { var p = n.parent || "_"; (kids[p] = kids[p] || []).push(n); });
  Object.keys(kids).forEach(function (k) { kids[k].sort(function (a, b) { return (a.ts || 0) - (b.ts || 0); }); });
  var flat = [];
  (function rec(pid, d) { (kids[pid] || []).forEach(function (n) { flat.push({d: d, n: n}); if (n.kind !== "event") rec(n.id, d + 1); }); })("_", 0);
  var t0 = r.ts || Infinity, t1 = 0;
  all.forEach(function (n) { t0 = Math.min(t0, n.ts || t0); t1 = Math.max(t1, n.ts_end || ((n.ts || 0) + (n.ms || 0) / 1000)); });
  var errs = r.spans.filter(function (s) { return s.status === "error"; }), fe = null;
  if (errs.length) {
    fe = errs.reduce(function (a, b) { return (a.ts || 0) <= (b.ts || 0) ? a : b; });
    for (;;) { var deeper = errs.filter(function (s) { return s.parent === fe.id; }); if (!deeper.length) break; fe = deeper.reduce(function (a, b) { return (a.ts || 0) <= (b.ts || 0) ? a : b; }); }
  }
  r._p = {kids: kids, flat: flat, t0: t0, total: Math.max(t1 - t0, 1e-6), firstErr: fe, errs: errs.length};
  return r._p;
}
function when(id) { var m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(id); return m ? m[1] + "-" + m[2] + "-" + m[3] + " " + m[4] + ":" + m[5] + ":" + m[6] : id; }
function renderRunList() {
  var box = $("#runlist");
  if (!R.length) {
    box.className = ""; box.innerHTML = '<div class="empty"><b>No agent runs recorded yet.</b><p>Add tracing to your LLM calls, tools and nodes, run the agent once, then regenerate this report:</p><pre>from tools.groundtruth import trace\n\n@trace(kind="llm")\ndef call_model(messages): ...\n\n@trace(kind="tool")\ndef search_docs(query): ...</pre><pre>python tools/groundtruth/gt.py viz</pre></div>';
    $("#run").innerHTML = ""; return;
  }
  box.innerHTML = "";
  R.forEach(function (r, i) {
    var p = prep(r);
    var b = el("button", "runrow", '<span class="dot ' + r.status + '"></span><div style="min-width:0"><div style="font-weight:500;overflow:hidden;text-overflow:ellipsis">' + esc(r.name) + '</div><div class="loc">' + esc(when(r.id)) + " · " + r.spans.length + " steps · " + fmtMs(r.ms) + (p.errs ? ' · <span style="color:var(--err)">' + p.errs + " errors</span>" : "") + "</div></div>");
    b.onclick = function () { selectRun(i); }; box.appendChild(b);
  });
  selectRun(0);
}
function selectRun(i) {
  CUR = i; $$(".runrow").forEach(function (b, k) { b.setAttribute("aria-current", String(k === i)); });
  var r = R[i], p = prep(r), box = $("#run");
  var st = r.status === "error" ? "r-err" : r.status === "ok" ? "r-ok" : "r-dyn";
  box.innerHTML = '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b style="font-size:16px">' + esc(r.name) + '</b><span class="chip ' + st + '">' + esc(r.status) + '</span><span class="muted">' + esc(when(r.id)) + " · " + fmtMs(r.ms) + " · " + r.spans.length + " steps</span></div>" +
    (r.input != null ? '<div class="loc" style="margin-top:4px">input: ' + esc(brief(r.input, 160)) + "</div>" : "");
  if (p.firstErr) {
    var e = p.firstErr.error || {};
    var c = el("div", "callout", "<b>First error</b> in <code>[" + esc(p.firstErr.kind) + "] " + esc(p.firstErr.name) + "</code><br>" + esc(e.type) + ": " + esc(e.msg) + "<br><span class=\"mono\">at " + esc(e.where) + (e.code ? ": " + esc(e.code) : "") + '</span><div style="margin-top:6px"><button class="link" id="goerr">Show this step</button></div>');
    box.appendChild(c);
  } else if (r.status === "ok") box.appendChild(el("div", "callout ok", "Completed without errors. If the answer is still wrong, read top-down and find the first step whose output is wrong for its input."));
  else box.appendChild(el("div", "callout warn", "This run never finished (crash, hang or timeout). The step marked ⏳ is where it stopped."));
  var tb = el("div", "toolbar");
  var sel = el("select"); sel.setAttribute("aria-label", "Compare with another run");
  sel.innerHTML = '<option value="">Compare with another run…</option>' + R.map(function (x, k) { return k === i ? "" : '<option value="' + k + '">' + esc(when(x.id)) + " · " + esc(x.name) + " · " + esc(x.status) + "</option>"; }).join("");
  sel.onchange = function () { var d = $("#diff"); d.innerHTML = ""; if (this.value !== "") diffRuns(R[i], R[+this.value], d); };
  var mm = el("button", "", "Copy as Mermaid sequence"); mm.onclick = function () { copyText(mermaidSeq(r), "Mermaid copied: paste it into a ```mermaid block", "#diff"); };
  tb.appendChild(sel); tb.appendChild(mm); box.appendChild(tb);
  box.appendChild(el("div", "", "")).id = "diff";
  box.appendChild(el("p", "hint", "Timeline: each bar is one step, placed when it started and as long as it took. Tap a step to see its input, output and error."));
  var wf = el("div", "wf");
  wf.innerHTML = '<div class="wrow"><div class="wl muted" style="font-size:12px">Step</div><div class="scale"><span>0</span><span>' + fmtMs(p.total * 500) + "</span><span>" + fmtMs(p.total * 1000) + "</span></div></div>";
  p.flat.forEach(function (x) {
    var n = x.n, row = el("div", "wrow"); row.style.setProperty("--d", x.d); row.tabIndex = 0; row.setAttribute("role", "button");
    var left = (100 * ((n.ts || p.t0) - p.t0) / p.total);
    if (n.kind === "event") {
      row.innerHTML = '<div class="wl"><span class="muted">•</span><span class="n muted">' + esc(n.name) + "</span></div><div class=\"wt\"><span class=\"ev\" style=\"left:" + left.toFixed(2) + '%"></span></div>';
    } else {
      var w = Math.max(100 * ((n.ms || 0) / 1000) / p.total, 0.6), bc = n.status === "error" ? "b-err" : n.status === "unfinished" ? "b-unf" : "b-" + kc(n.kind);
      var icon = n.status === "error" ? ' <span style="color:var(--err)">✗</span>' : n.status === "unfinished" ? " ⏳" : "";
      row.innerHTML = '<div class="wl"><span class="chip r-' + kc(n.kind) + '">' + esc(n.kind) + '</span><span class="n">' + esc(n.name) + "</span>" + icon + '</div><div class="wt"><span class="b ' + bc + '" style="left:' + Math.min(left, 99.4).toFixed(2) + "%;width:" + Math.min(w, 100 - Math.min(left, 99.4)).toFixed(2) + '%"></span><span class="ms" style="left:' + Math.min(left, 80).toFixed(2) + '%">' + fmtMs(n.ms) + "</span></div>";
    }
    row._n = n; wf.appendChild(row);
  });
  wf.addEventListener("click", function (ev) { var row = ev.target.closest(".wrow"); if (row && row._n) stepDetail(row); });
  wf.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { var row = ev.target.closest(".wrow"); if (row && row._n) stepDetail(row); } });
  box.appendChild(wf);
  var go = $("#goerr"); if (go) go.onclick = function () { var row = $$(".wrow", wf).filter(function (x) { return x._n === p.firstErr; })[0]; if (row) { stepDetail(row, true); row.scrollIntoView({behavior: "smooth", block: "center"}); } };
}
function stepDetail(row, forceOpen) {
  var n = row._n, nxt = row.nextSibling;
  if (nxt && nxt.classList && nxt.classList.contains("icard")) { nxt.remove(); row.classList.remove("sel"); if (!forceOpen) return; }
  $$(".wf .icard").forEach(function (x) { x.remove(); }); $$(".wrow.sel").forEach(function (x) { x.classList.remove("sel"); });
  row.classList.add("sel");
  var c = el("div", "icard"); c.style.margin = "4px 10px 10px";
  var h = '<div class="q">' + esc(n.kind === "event" ? "event · " + n.name : "[" + n.kind + "] " + n.name) + '</div><dl class="kv">';
  if (n.src) h += "<dt>Defined at</dt><dd><code>" + esc(n.src) + "</code></dd>";
  if (n.kind !== "event") h += "<dt>Status</dt><dd>" + esc(n.status) + "</dd><dt>Duration</dt><dd>" + fmtMs(n.ms) + "</dd>";
  h += "</dl>";
  if (n.error) h += '<div class="callout"><b>' + esc(n.error.type) + "</b>: " + esc(n.error.msg) + '<br><span class="mono">at ' + esc(n.error.where) + (n.error.code ? ": " + esc(n.error.code) : "") + "</span></div>" + (n.error.tb ? "<details><summary>Traceback</summary><div class=\"inner\"><pre>" + esc(n.error.tb) + "</pre></div></details>" : "");
  if (n.kind === "event") h += "<div class=\"muted\">Data</div><pre>" + esc(pretty(n.data)) + "</pre>";
  else {
    h += '<div class="muted">Input</div><pre>' + esc(pretty(n.input)) + "</pre>";
    if ("output" in n) h += '<div class="muted">Output</div><pre>' + esc(pretty(n.output)) + "</pre>";
    if (n.attrs) h += '<div class="muted">Attributes</div><pre>' + esc(pretty(n.attrs)) + "</pre>";
  }
  c.innerHTML = h; row.parentNode.insertBefore(c, row.nextSibling);
}
function same(a, b) { try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return false; } }
function diffRuns(A, B, box) {
  var fa = prep(A).flat, fb = prep(B).flat;
  function sig(x) { return x.d + "|" + x.n.kind + "|" + x.n.name; }
  var sa = fa.map(sig), sb = fb.map(sig), n = sa.length, m = sb.length, ops = [];
  if (n * m <= 4000000) {
    var W = m + 1, dp = new Uint16Array((n + 1) * W);
    for (var i = n - 1; i >= 0; i--) for (var j = m - 1; j >= 0; j--) dp[i * W + j] = sa[i] === sb[j] ? dp[(i + 1) * W + j + 1] + 1 : Math.max(dp[(i + 1) * W + j], dp[i * W + j + 1]);
    var x = 0, y = 0;
    while (x < n && y < m) { if (sa[x] === sb[y]) { ops.push(["=", x++, y++]); } else if (dp[(x + 1) * W + y] >= dp[x * W + y + 1]) ops.push(["-", x++]); else ops.push(["+", y++]); }
    while (x < n) ops.push(["-", x++]); while (y < m) ops.push(["+", y++]);
  } else { for (var k = 0; k < Math.max(n, m); k++) { if (k < n && k < m && sa[k] === sb[k]) ops.push(["=", k, k]); else { if (k < n) ops.push(["-", k]); if (k < m) ops.push(["+", k]); } } }
  var marks = [], rows = [], firstStruct = null;
  ops.forEach(function (o) {
    if (o[0] === "=") {
      var a = fa[o[1]], b = fb[o[2]], v = a.n.kind === "event" ? "data" : "output";
      var ea = a.n.error || {}, eb = b.n.error || {};
      var differs = !(same(a.n[v], b.n[v]) && a.n.status === b.n.status && ea.type === eb.type && ea.msg === eb.msg);
      marks.push({d: a.d, differs: differs, a: a.n, b: b.n, sameIn: same(a.n.input, b.n.input), v: v});
      rows.push({m: differs ? "≠" : "=", d: a.d, n: a.n, cls: differs ? "ne" : "", idx: marks.length - 1});
    } else {
      var z = o[0] === "-" ? fa[o[1]] : fb[o[1]];
      if (!firstStruct) firstStruct = {a: [], b: []};
      if (!firstStruct.closed) (o[0] === "-" ? firstStruct.a : firstStruct.b).push(z.n.name);
      marks.push({d: z.d, differs: true});
      rows.push({m: o[0] === "-" ? "−" : "+", d: z.d, n: z.n, cls: o[0] === "-" ? "a" : "b", note: o[0] === "-" ? "only in this run" : "only in the other run"});
    }
    if (firstStruct && o[0] === "=" && (firstStruct.a.length || firstStruct.b.length)) firstStruct.closed = true;
  });
  var fo = null;
  for (var q = 0; q < marks.length; q++) {
    var mk = marks[q]; if (!mk.differs || !mk.a) continue;
    var inner = false; for (var t = q + 1; t < marks.length && marks[t].d > mk.d; t++) if (marks[t].differs) { inner = true; break; }
    if (!inner) { fo = mk; break; }
  }
  var h = "";
  if (fo) {
    var why = fo.a.kind === "event" ? "The recorded decision differs. Look at the state that fed this decision." :
      fo.sameIn ? "<b>Same input, different result</b>: the variation is inside this step (LLM sampling, external data, time, cache). Pin temperature/seed, or record and replay this step." :
      "The inputs differ too, so the cause is upstream. Check the steps before this one.";
    h += '<div class="callout warn"><b>First different result</b>: <code>[' + esc(fo.a.kind) + "] " + esc(fo.a.name) + "</code>" + (fo.a.src ? ' <span class="mono">(' + esc(fo.a.src) + ")</span>" : "") +
      '<pre style="background:transparent;padding:4px 0;margin:4px 0">This run:  ' + esc(fo.a.status === "error" ? "ERROR " + (fo.a.error || {}).msg : brief(fo.a[fo.v], 140)) + "\nOther run: " + esc(fo.b.status === "error" ? "ERROR " + (fo.b.error || {}).msg : brief(fo.b[fo.v], 140)) + "</pre>" + why + "</div>";
  }
  if (firstStruct) h += '<div class="callout warn"><b>First different path</b>: this run did <code>' + esc(firstStruct.a.join(", ") || "nothing") + "</code>, the other did <code>" + esc(firstStruct.b.join(", ") || "nothing") + "</code>. The decision was made by the step just before (router or LLM tool choice).</div>";
  if (!fo && !firstStruct) h += '<div class="callout ok">The runs are identical in structure and recorded outputs.</div>';
  box.innerHTML = h;
  var list = el("div", "list");
  rows.forEach(function (r) {
    var d = el("div", "drow " + r.cls, '<span class="m">' + r.m + '</span><span class="chip r-' + kc(r.n.kind) + '">' + esc(r.n.kind) + "</span><span>" + esc(r.n.name) + "</span>" + (r.note ? '<span class="tag">' + r.note + "</span>" : ""));
    d.style.setProperty("--d", r.d);
    if (r.m === "≠") d.onclick = function () {
      var nx = d.nextSibling; if (nx && nx.classList && nx.classList.contains("icard")) { nx.remove(); return; }
      var mk2 = marks[r.idx], c = el("div", "icard");
      c.innerHTML = '<div class="muted">This run</div><pre>' + esc(pretty(mk2.a.status === "error" ? mk2.a.error : mk2.a[mk2.v])) + '</pre><div class="muted">Other run</div><pre>' + esc(pretty(mk2.b.status === "error" ? mk2.b.error : mk2.b[mk2.v])) + "</pre>" + (mk2.sameIn ? '<div class="muted">Inputs were identical.</div>' : '<div class="muted">Inputs differ:</div><pre>' + esc(brief(mk2.a.input, 300)) + "\n— vs —\n" + esc(brief(mk2.b.input, 300)) + "</pre>");
      d.parentNode.insertBefore(c, d.nextSibling);
    };
    list.appendChild(d);
  });
  box.appendChild(el("p", "hint", "Step-by-step comparison: = same · ≠ different result (tap) · − / + only in one run."));
  box.appendChild(list);
}
function seqSafe(t, n) { t = String(t == null ? "" : t).replace(/\s+/g, " "); n = n || 48; if (t.length > n) t = t.slice(0, n - 1) + "…"; return t.replace(/;/g, ",").replace(/#/g, "#35;").replace(/</g, "#lt;").replace(/>/g, "#gt;"); }
function seqText(v) { if (v == null) return ""; if (typeof v === "object" && !Array.isArray(v)) { return Object.keys(v).filter(function (k) { return k !== "self" && k !== "cls"; }).map(function (k) { return k + "=" + (typeof v[k] === "string" ? v[k] : brief(v[k], 60)); }).join(", "); } return typeof v === "string" ? v : brief(v, 80); }
function mermaidSeq(r) {
  var p = prep(r), names = {}, out = ["sequenceDiagram", "  autonumber", "  participant U as caller"], c = 0;
  function pid(n) { if (!(n.name in names)) { names[n.name] = "p" + (Object.keys(names).length + 1); out.push("  participant " + names[n.name] + " as " + seqSafe(n.name + " (" + n.kind + ")", 40).replace(/:/g, " ")); } return names[n.name]; }
  (function rec(parent, pp) {
    (p.kids[parent] || []).forEach(function (n) {
      if (c++ > 150) return;
      if (n.kind === "event") { out.push("  Note over " + pp + ": " + seqSafe(n.name + " " + seqText(n.data), 60)); return; }
      var me = pid(n); out.push("  " + pp + "->>+" + me + ": " + (seqSafe(seqText(n.input)) || seqSafe(n.name)));
      rec(n.id, me);
      if (n.status === "error") out.push("  " + me + "--x-" + pp + ": " + seqSafe((n.error || {}).type + ": " + (n.error || {}).msg));
      else if (n.status === "unfinished") out.push("  Note over " + me + ": did not finish", "  " + me + "--x-" + pp + ": (no return)");
      else out.push("  " + me + "-->>-" + pp + ": " + (seqSafe(seqText(n.output)) || "ok") + " (" + fmtMs(n.ms) + ")");
    });
  })("_", "U");
  return out.join("\n");
}
renderRunList();

var h0 = (location.hash || "").slice(1); if (h0 === "flow" || h0 === "runs") show(h0);
})();
</script>
</body>
</html>
"""
