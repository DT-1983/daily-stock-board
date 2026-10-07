# -*- coding: utf-8 -*-
"""戰情室「自選」分頁的前端（2026-10-08，Leo：自選＋XQ 匯入＋新增；手機左滑移除；漲跌色沿用站上的 .up/.dn）。

結構：第三個模式鈕「自選」→ #watchpane（跟列表模式的 .tablepane 同一個佔位邏輯）。
資料：GET/POST /room/watch（清單與增刪匯入，只有 Leo 本人）＋ GET /room/quote（即時價，15 秒一次，只在自選分頁開著時）。
另外：在左欄、列表表格、個股標題各塞一顆 ★，點一下加入／移除自選（同一份清單）。
⚠️ 家人帳號：模式鈕與面板整個隱藏，後端也 404（見 discord_bot._watch_ok）。
"""

WATCH_CSS = r"""
.watchpane{display:none;grid-column:1/-1;padding:8px 14px 26px}
.room.watch .tablepane{display:none}
.room.watch .watchpane{display:block}
.room.list.chat.watch .watchpane{grid-column:1;grid-row:1}
.wix{display:flex;gap:8px;margin:6px 0 10px}
.wix .wt{flex:1;border:1px solid #16304A;border-radius:6px;padding:6px 9px;background:#080E1A;min-width:0}
.wix .wt small{display:block;color:#6B84A3;font-size:11px;white-space:nowrap}
.wix .wt b{display:block;font-size:15px;font-weight:500;font-family:'IBM Plex Mono',ui-monospace,monospace}
.wtool{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0 8px}
.wtool .wtitle{font-size:14px;font-weight:600;margin-right:4px;white-space:nowrap}
.wtool input[type=text]{flex:1;min-width:140px;border:1px solid #16304A;border-radius:6px;padding:7px 9px;background:#04070E;color:#E6EDF7;font-size:14px}
.wtool button,.wtool select{border:1px solid #16304A;border-radius:6px;padding:7px 11px;background:#080E1A;color:#8FA8C8;font-size:13px}
.wtool button.go{border-color:#22D3EE;color:#22D3EE}
.wmsg{font-size:12.5px;color:#8FA8C8;min-height:18px;margin:2px 0 6px;line-height:1.5}
.wmsg b{color:#E6EDF7}
.wgrp{padding:6px 10px;background:#080E1A;color:#8FA8C8;font-size:12px;border:1px solid #16304A;border-bottom:none;margin-top:10px;border-radius:6px 6px 0 0}
.wgrp .lv{color:#22D3EE}
.wlist{border:1px solid #16304A;border-radius:0 0 6px 6px}
.wrow{position:relative;overflow:hidden;border-top:1px solid #0E1B2B;touch-action:pan-y}
.wrow:first-child{border-top:none}
.wbody{position:relative;background:#04070E;padding:9px 12px;cursor:pointer;transition:transform .18s;display:grid;
  grid-template-columns:1.6fr .9fr .8fr 1.1fr .9fr .8fr;gap:8px;align-items:center}
.wbody:hover{background:#08131F}
.wrow .wdel{position:absolute;right:0;top:0;bottom:0;width:88px;border:0;background:#B91C1C;color:#fff;font-size:14px;visibility:hidden}
.wrow.open .wdel{visibility:visible}
.wrow.open .wbody{transform:translateX(-88px)}
.wpq .wch{display:none}
.wrow .wx{display:none;position:absolute;right:8px;top:8px;border:1px solid #16304A;background:#04070E;color:#8FA8C8;border-radius:4px;padding:0 7px;font-size:13px}
@media(hover:hover){.wrow:hover .wx{display:block}}
.wh{display:grid;grid-template-columns:1.6fr .9fr .8fr 1.1fr .9fr .8fr;gap:8px;padding:5px 12px;color:#6B84A3;font-size:11px;border:1px solid #16304A;border-bottom:none;background:#060C16}
.wn b{font-size:14px}.wn span{color:#8FA8C8;font-size:12px;margin-left:6px}
.wp{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:15px}
.wp.lv::before{content:'●';color:#22D3EE;font-size:9px;margin-right:4px}
.wq{font-family:'IBM Plex Mono',ui-monospace,monospace}
.wr{color:#8FA8C8;font-size:12px}
.wsq i{display:inline-block;width:9px;height:9px;margin-right:2px;background:#22C55E}.wsq i.off{background:#1E2B42}
.wst{cursor:pointer;color:#475A74;margin-right:5px;font-size:14px;user-select:none}.wst.on{color:#FBBF24}
li.it .l1 .wst{order:0}
@media(max-width:700px){
 .watchpane{padding:6px 8px 24px}
 .wh{display:none}
 .wbody{grid-template-columns:1fr auto;gap:2px 8px;padding:10px 12px}
 .wbody .wn{grid-column:1}.wbody .wpq{grid-column:2;text-align:right}
 .wbody .wsq,.wbody .wt2,.wbody .wr{font-size:11.5px;color:#8FA8C8}
 .wbody .wsq{grid-column:1}.wbody .wr2{grid-column:2;text-align:right;font-size:11.5px;color:#8FA8C8}
 .wbody .wc,.wbody .wd{display:none}
 .wpq .wch{display:inline;margin-left:4px;font-size:13px}
 .wix .wt b{font-size:13.5px}
 .wrow .wx{display:none!important}
}
"""

WATCH_JS = r"""
<script>
(function(){
  var room=document.querySelector(".room"), pane=document.getElementById("watchpane"), mW=document.getElementById("mode-watch");
  if(!room||!pane||!mW) return;
  var items=[], quotes={}, loaded=false, shell=false, timer=null, sortKey="def", starSet={};
  var INDEX=[["^TWII","台股加權"],["^GSPC","S&P 500"],["^IXIC","那斯達克"],["^SOX","費半"]];
  function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; d=(d==null?2:d);
    return Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d}); }
  function cls(c){ return c>=0?"up":"dn"; }
  function sgn(c){ return (c>=0?"+":"")+c.toFixed(2)+"%"; }
  function post(b){ return fetch("/room/watch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})
    .then(function(r){ return r.ok?r.json():{error:"伺服器回應異常（"+r.status+"）"}; }).catch(function(){ return {error:"連不上伺服器"}; }); }
  function say(h){ var m=document.getElementById("wmsg"); if(m) m.innerHTML=h; }

  function buildShell(){
    pane.innerHTML='<div class="wix" id="windex"></div>'
      +'<div class="wtool"><span class="wtitle" id="wtitle">自選</span>'
      +'<input type="text" id="wadd" placeholder="代號或中文名：2330、NVDA、台積電（可一次貼多檔）" autocomplete="off" enterkeyhint="done">'
      +'<button class="go" id="waddb">＋ 新增</button>'
      +'<button id="wimpb">⇪ 匯入檔案</button><input type="file" id="wfile" accept=".dsl,.csv,.txt,text/plain" style="display:none">'
      +'<select id="wsort"><option value="def">排序：加入順序</option><option value="up">漲幅大→小</option><option value="dn">跌幅大→小</option><option value="lit">燈數多→少</option></select></div>'
      +'<div class="wmsg" id="wmsg">匯入支援 XQ 匯出的 .dsl、純文字／CSV；每列左滑（滑鼠移上去按 ✕）可移除。</div>'
      +'<div id="wlist"></div>';
    shell=true;
    var inp=document.getElementById("wadd");
    function doAdd(){ var q=inp.value.trim(); if(!q) return; say("新增中…");
      post({action:"add",q:q}).then(function(r){
        if(r.error){ say('<b style="color:#F87171">'+esc(r.error)+'</b>'); return; }
        var parts=[]; if(r.added&&r.added.length) parts.push("已新增 <b>"+esc(r.added.join("、"))+"</b>");
        if(r.already&&r.already.length) parts.push("本來就在清單："+esc(r.already.join("、")));
        if(r.skipped&&r.skipped.length) parts.push('<span style="color:#FBBF24">看不懂（沒加）：'+esc(r.skipped.join("、"))+"</span>");
        var c=r.candidates||{}; Object.keys(c).forEach(function(k){ parts.push("「"+esc(k)+"」有多個符合："+esc(c[k].join("、"))+"，請改輸入代號"); });
        say(parts.join("　｜　")||"沒有可新增的內容"); inp.value=""; refresh(true); }); }
    document.getElementById("waddb").addEventListener("click",doAdd);
    inp.addEventListener("keydown",function(e){ if(e.key==="Enter"){ e.preventDefault(); doAdd(); } });
    var fi=document.getElementById("wfile");
    document.getElementById("wimpb").addEventListener("click",function(){ fi.click(); });
    fi.addEventListener("change",function(){
      var f=fi.files&&fi.files[0]; if(!f) return; say("匯入「"+esc(f.name)+"」中…");
      var rd=new FileReader();
      rd.onload=function(){ var u8=new Uint8Array(rd.result), s="", i;
        for(i=0;i<u8.length;i+=8192) s+=String.fromCharCode.apply(null,u8.subarray(i,i+8192));
        post({action:"import",name:f.name,b64:btoa(s)}).then(function(r){
          fi.value="";
          if(r.error){ say('<b style="color:#F87171">'+esc(r.error)+'</b>'); return; }
          var p=["匯入完成：新增 <b>"+(r.added||[]).length+"</b> 檔"];
          if(r.already&&r.already.length) p.push("已在清單 "+r.already.length+" 檔");
          if(r.skipped&&r.skipped.length) p.push('<span style="color:#FBBF24">略過 '+r.skipped.length+" 個不支援的代號："+esc(r.skipped.slice(0,8).join("、"))+"</span>");
          p.push("目前共 "+r.total+" 檔"); say(p.join("　｜　")); refresh(true); }); };
      rd.readAsArrayBuffer(f); });
    document.getElementById("wsort").addEventListener("change",function(e){ sortKey=e.target.value; renderList(); });
    document.getElementById("wlist").addEventListener("click",function(e){
      var del=e.target.closest(".wdel,.wx"); var row=e.target.closest(".wrow"); if(!row) return;
      if(del){ var tk=row.dataset.tk; post({action:"remove",tk:tk}).then(function(){ say("已移除 <b>"+esc(tk)+"</b>（要加回去再輸入一次代號）"); refresh(true); }); return; }
      if(row.classList.contains("open")){ row.classList.remove("open"); return; }
      if(window.roomSearch){ window.roomSearch(row.dataset.tk); } });
    // 手機左滑：露出紅色「移除」
    var sx=0, sy=0, srow=null, moved=false;
    var L=document.getElementById("wlist");
    L.addEventListener("touchstart",function(e){ var t=e.touches[0]; sx=t.clientX; sy=t.clientY; moved=false; srow=e.target.closest(".wrow");
      L.querySelectorAll(".wrow.open").forEach(function(r){ if(r!==srow) r.classList.remove("open"); }); },{passive:true});
    L.addEventListener("touchmove",function(e){ if(!srow) return; var t=e.touches[0], dx=t.clientX-sx, dy=t.clientY-sy;
      if(Math.abs(dx)>Math.abs(dy)&&Math.abs(dx)>10){ moved=true; } },{passive:true});
    L.addEventListener("touchend",function(e){ if(!srow||!moved) return; var t=e.changedTouches[0], dx=t.clientX-sx;
      if(dx<-45){ srow.classList.add("open"); } else if(dx>25){ srow.classList.remove("open"); }
      e.preventDefault(); },{passive:false});
  }

  function stateOf(list){ var s=""; list.forEach(function(i){ var q=quotes[i.tk]; if(q&&q.state==="盤中") s="盤中"; else if(q&&!s) s=q.state||""; }); return s||"—"; }
  function renderIndex(){
    var h=""; INDEX.forEach(function(x){ var q=quotes[x[0]];
      h+='<div class="wt"><small>'+esc(x[1])+(q&&q.state==="盤中"?' <span style="color:#22D3EE">●</span>':'')+'</small><b>'+(q?fmt(q.px,0):"—")+'</b>'
        +(q&&q.chg!=null?'<span class="'+cls(q.chg)+'" style="font-size:12px">'+sgn(q.chg)+'</span>':'')+'</div>'; });
    document.getElementById("windex").innerHTML=h; }
  function rowHtml(i){
    var q=quotes[i.tk]||null, px=q?q.px:null, chg=q?q.chg:null;
    var sq=""; for(var k=0;k<4;k++) sq+='<i class="'+((i.lit!=null&&k<i.lit)?"":"off")+'"></i>';
    var tg=(i.target&&px)?((i.target/px-1)*100):null;
    var dist=tg==null?"—":('<span class="'+cls(tg)+'">'+(tg>=0?"+":"")+tg.toFixed(0)+"%</span>");
    var hl=q&&q.hi!=null?fmt(q.hi,i.mkt==="tw"?1:2)+" / "+fmt(q.lo,i.mkt==="tw"?1:2):"— / —";
    var lit=i.in_scan?(i.lit+"/4"):"不在掃描";
    return '<div class="wrow" data-tk="'+esc(i.tk)+'"><button class="wdel">移除</button><button class="wx" title="移除">✕</button>'
      +'<div class="wbody"><div class="wn"><b>'+esc(i.tk)+'</b><span>'+esc(i.name)+'</span></div>'
      +'<div class="wpq wq"><span class="wp'+(q&&q.state==="盤中"?" lv":"")+'">'+(px==null?"—":fmt(px,i.mkt==="tw"?1:2))+'</span> '
      +(chg==null?"":'<span class="wch '+cls(chg)+'">'+sgn(chg)+'</span>')+'</div>'
      +'<div class="wc wq '+(chg==null?"":cls(chg))+'">'+(chg==null?"—":sgn(chg))+'</div>'
      +'<div class="wd wr wt2">'+hl+'</div>'
      +'<div class="wsq" title="'+esc(lit)+'">'+sq+'</div>'
      +'<div class="wr2 wr">距目標 '+dist+'</div></div></div>'; }
  function renderList(){
    var L=document.getElementById("wlist"); if(!L) return;
    var arr=items.slice();
    var chgOf=function(i){ var q=quotes[i.tk]; return q&&q.chg!=null?q.chg:null; };
    if(sortKey==="up") arr.sort(function(a,b){ return (chgOf(b)==null?-999:chgOf(b))-(chgOf(a)==null?-999:chgOf(a)); });
    else if(sortKey==="dn") arr.sort(function(a,b){ return (chgOf(a)==null?999:chgOf(a))-(chgOf(b)==null?999:chgOf(b)); });
    else if(sortKey==="lit") arr.sort(function(a,b){ return (b.lit==null?-1:b.lit)-(a.lit==null?-1:a.lit); });
    var tw=arr.filter(function(i){return i.mkt==="tw";}), us=arr.filter(function(i){return i.mkt!=="tw";});
    var open=[]; L.querySelectorAll(".wrow.open").forEach(function(r){ open.push(r.dataset.tk); });
    var h="";
    function grp(name,list){ if(!list.length) return ""; var st=stateOf(list);
      return '<div class="wgrp">'+name+'　'+(st==="盤中"?'<span class="lv">● 盤中</span>':esc(st))+'　'+list.length+' 檔</div>'
        +'<div class="wh"><span>代號 名稱</span><span>現價</span><span>漲跌</span><span>今日高低</span><span>燈號</span><span>距目標</span></div>'
        +'<div class="wlist">'+list.map(rowHtml).join("")+'</div>'; }
    h=grp("美股",us)+grp("台股",tw);
    if(!h) h='<div class="wmsg" style="padding:24px 4px">還沒有自選股。用上面的框輸入代號，或按「匯入檔案」選 XQ 匯出的自選股。</div>';
    L.innerHTML=h;
    open.forEach(function(tk){ var r=L.querySelector('.wrow[data-tk="'+tk+'"]'); if(r) r.classList.add("open"); });
    var t=document.getElementById("wtitle"); if(t) t.textContent="自選 "+items.length+" 檔";
    renderIndex(); }

  function loadList(){ return fetch("/room/watch",{cache:"no-store"}).then(function(r){ return r.ok?r.json():{items:[]}; })
    .then(function(d){ items=d.items||[]; starSet={}; items.forEach(function(i){ starSet[i.tk]=1; }); loaded=true; paintStars(); }).catch(function(){}); }
  function fetchQuotes(){ var tks=items.map(function(i){return i.tk;}).concat(INDEX.map(function(x){return x[0];}));
    return fetch("/room/quote?tickers="+encodeURIComponent(tks.join(",")),{cache:"no-store"}).then(function(r){ return r.ok?r.json():{}; })
      .then(function(q){ quotes=q||{}; }).catch(function(){}); }
  function refresh(reload){ var p=reload?loadList():Promise.resolve(); return p.then(fetchQuotes).then(function(){ if(shell&&room.classList.contains("watch")) renderList(); }); }

  function show(){
    room.classList.add("list","watch");
    mW.classList.add("on"); var a=document.getElementById("mode-stock"), b=document.getElementById("mode-list");
    if(a) a.classList.remove("on"); if(b) b.classList.remove("on");
    if(!shell) buildShell();
    renderList(); refresh(true);
    clearInterval(timer); timer=setInterval(function(){ if(!document.hidden) refresh(false); },15000); }
  function hide(){ room.classList.remove("watch"); mW.classList.remove("on"); clearInterval(timer); timer=null; }
  mW.addEventListener("click",show);
  var s1=document.getElementById("mode-stock"), s2=document.getElementById("mode-list");
  if(s1) s1.addEventListener("click",hide); if(s2) s2.addEventListener("click",hide);

  // ★：左欄、列表表格、個股標題各一顆，點一下加入／移除自選
  function paintStars(){
    function mk(tk){ var s=document.createElement("span"); s.className="wst"+(starSet[tk]?" on":""); s.dataset.tk=tk; s.textContent=starSet[tk]?"★":"☆"; s.title=starSet[tk]?"移出自選":"加入自選"; return s; }
    function put(host,tk,before){ if(!host) return; var ex=host.querySelector(".wst");
      if(ex){ var on=!!starSet[tk]; if(ex.classList.contains("on")!==on){ ex.classList.toggle("on",on); ex.textContent=on?"★":"☆"; ex.title=on?"移出自選":"加入自選"; } return; }
      var s=mk(tk); if(before) host.insertBefore(s,host.firstChild); else host.appendChild(s); }
    document.querySelectorAll("li.it").forEach(function(li){ put(li.querySelector(".l1"),li.dataset.tk,true); });
    document.querySelectorAll("tr[data-tk]").forEach(function(tr){ var td=tr.querySelector("td"); put(td,tr.dataset.tk,true); });
    var t=document.querySelector(".dhead .tk"); if(t){ var tk=t.textContent.trim(); var host=t.parentElement; if(host) put(host,tk,true); } }
  document.addEventListener("click",function(e){
    var st=e.target.closest&&e.target.closest(".wst"); if(!st) return;
    e.stopPropagation(); e.preventDefault(); var tk=st.dataset.tk, on=!!starSet[tk];
    post(on?{action:"remove",tk:tk}:{action:"add",q:tk}).then(function(){ if(on) delete starSet[tk]; else starSet[tk]=1; paintStars();
      loadList().then(function(){ if(shell&&room.classList.contains("watch")) refresh(false); }); }); },true);
  var pend=null; function sched(){ clearTimeout(pend); pend=setTimeout(function(){ if(loaded) paintStars(); },350); }
  try{ new MutationObserver(sched).observe(document.querySelector(".room"),{childList:true,subtree:true}); }catch(e){}
  loadList();
})();
</script>
"""
