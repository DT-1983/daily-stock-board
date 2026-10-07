# -*- coding: utf-8 -*-
"""戰情室「自選」（2026-10-08；Leo：「自選股放左邊、頁面放右邊，像個股一樣」＋「可自行上下移動」＋「選台股／美股」＋「新增匯入做小一點或浮動視窗」）

呈現方式＝**個股模式的版面**：左欄換成「自選清單」，點一檔 → 中間載入那一檔的完整頁面（燈號、技術圖、軍師）。
手機＝清單在上、頁面在下。模式鈕「個股｜列表｜自選」：自選＝個股版面＋左欄切成自選（class .watch 蓋在 .room 上，
不動原本的左欄 DOM，只是藏起來）。
左欄結構（由上到下）：大盤一行小字 → 標題列（自選 N 檔｜＋小鈕｜排序小選單）→ 全部／台股／美股 篩選籤 → 美台分區的報價卡。
「＋」開浮動小視窗：新增（代號／中文名／多檔）與匯入檔案（XQ .dsl／CSV／文字）都在裡面，平常不佔版面。
排序選「加入順序」時，每列左邊出現 ⠿ 把手，按住上下拖曳＝調整順序（存在伺服器，手機電腦同一份）。
資料：GET/POST /room/watch（清單與增刪匯入排序，只有 Leo 本人）＋ GET /room/quote（即時價，15 秒，只在自選模式開著時）。
另外在左欄、列表表格、個股標題各塞一顆 ★，點一下加入／移除自選（同一份清單）。
手機左滑露出「移除」；電腦滑鼠移上去按 ✕。漲跌色沿用站上的 .up/.dn。
⚠️ 家人帳號：模式鈕整個隱藏，後端也 404（見 discord_bot._watch_ok）。
"""

WATCH_CSS = r"""
.wleft{display:none}
.room.watch .pane.left>*{display:none}
.room.watch .pane.left>.grip{display:block}
.room.watch .pane.left{overflow-x:hidden}
.wleft,#wlist{min-width:0;overflow-x:hidden}
.room.watch .pane.left>.wleft{display:flex;flex-direction:column;min-height:0;height:100%;padding:8px 10px 12px;position:relative}
.wix{display:flex;flex-wrap:wrap;gap:2px 12px;font-size:11.5px;color:#8FA8C8;margin:0 0 6px;line-height:1.5}
.wix .wt b{font-weight:500;color:#E6EDF7;font-family:'IBM Plex Mono',ui-monospace,monospace;margin:0 3px}
.whead{display:flex;align-items:center;gap:6px;margin:0 0 6px}
.whead .wtitle{font-size:14px;font-weight:600;margin-right:auto;white-space:nowrap}
.whead button,.whead select{border:1px solid #16304A;border-radius:6px;background:#080E1A;color:#8FA8C8;font-size:13px;height:28px;padding:0 9px}
.whead button.plus{border-color:#22D3EE;color:#22D3EE;font-size:16px;line-height:1;padding:0 10px}
.whead select{width:92px;padding:0 4px;font-size:12px}
.wchips{display:flex;gap:6px;margin:0 0 6px}
.wchips button{border:1px solid #16304A;border-radius:14px;background:#080E1A;color:#8FA8C8;font-size:12px;padding:2px 11px}
.wchips button.on{border-color:#22D3EE;color:#22D3EE;background:#0E3A52}
.wpop{display:none;position:absolute;left:8px;right:8px;top:40px;z-index:6;background:#0C1524;border:1px solid #22D3EE;border-radius:8px;padding:10px 10px 8px;box-shadow:0 8px 24px #000a}
.wpop.show{display:block}
.wpop .ph{display:flex;align-items:center;margin-bottom:6px;font-size:13px;color:#E6EDF7;font-weight:600}
.wpop .ph button{margin-left:auto;border:0;background:none;color:#8FA8C8;font-size:16px}
.wpop input[type=text]{width:100%;box-sizing:border-box;border:1px solid #16304A;border-radius:6px;padding:8px 9px;background:#04070E;color:#E6EDF7;font-size:14px}
.wpop .pb{display:flex;gap:6px;margin-top:6px}
.wpop .pb button{flex:1;border:1px solid #16304A;border-radius:6px;padding:7px 8px;background:#080E1A;color:#8FA8C8;font-size:13px}
.wpop .pb button.go{border-color:#22D3EE;color:#22D3EE}
.wxq{margin-top:8px;padding-top:8px;border-top:1px solid #16304A}
.wxq .xh{display:flex;align-items:center;font-size:13px;color:#E6EDF7;font-weight:600;margin-bottom:4px}
.wxq .xh label{margin-left:auto;font-weight:400;font-size:12px;color:#8FA8C8;display:flex;align-items:center;gap:4px}
.wxq .xl{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12.5px;color:#8FA8C8;margin-bottom:6px}
.wxq .xl label{display:flex;align-items:center;gap:4px;white-space:nowrap}
.wxq .xl label.off{opacity:.45}
.wxq .xb{display:flex;gap:6px;align-items:center}
.wxq .xb button,.wxq .xb a{flex:1;text-align:center;border:1px solid #16304A;border-radius:6px;padding:6px 8px;background:#080E1A;color:#8FA8C8;font-size:12.5px;text-decoration:none}
.wxq .xs{font-size:11.5px;color:#6B84A3;margin-top:5px;line-height:1.5}
.wmsg{font-size:12px;color:#8FA8C8;min-height:0;margin:6px 0 0;line-height:1.5}
.wmsg b{color:#E6EDF7}
.wtoast{font-size:12px;color:#8FA8C8;margin:0 0 4px;line-height:1.4;min-height:0}
.wtoast b{color:#E6EDF7}
#wlist{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch}
.wgrp{padding:5px 8px;background:#080E1A;color:#8FA8C8;font-size:12px;border:1px solid #16304A;border-bottom:none;margin-top:6px;border-radius:6px 6px 0 0;position:sticky;top:0;z-index:1}
.wgrp .lv{color:#22D3EE}
.wlist{border:1px solid #16304A;border-radius:0 0 6px 6px}
.wrow{position:relative;overflow:hidden;border-top:1px solid #0E1B2B;touch-action:pan-y}
.wrow:first-child{border-top:none}
.wbody{position:relative;background:#04070E;padding:8px 10px;cursor:pointer;transition:transform .18s;display:grid;
  grid-template-columns:1fr auto;gap:2px 8px;align-items:center}
.wbody:hover{background:#08131F}
.wrow.sel .wbody{background:#0B2A3A;box-shadow:inset 3px 0 0 #22D3EE}
.wrow.drag .wbody{background:#123B52;opacity:.85}
.wrow .wdel{position:absolute;right:0;top:0;bottom:0;width:88px;border:0;background:#B91C1C;color:#fff;font-size:14px;visibility:hidden}
.wrow.open .wdel{visibility:visible}
.wrow.open .wbody{transform:translateX(-88px)}
.wrow .wx{display:none;position:absolute;right:6px;top:6px;border:1px solid #16304A;background:#04070E;color:#8FA8C8;border-radius:4px;padding:0 6px;font-size:12px;z-index:2}
@media(hover:hover){.wrow:hover .wx{display:block}}
.wgrip{display:none;cursor:grab;touch-action:none;color:#6B84A3;padding:0 8px 0 0;font-size:16px;line-height:1;user-select:none}
.wmanual .wgrip{display:inline-block}
.wn{grid-column:1;display:flex;align-items:baseline;min-width:0}.wn b{font-size:14px}.wn span.nm{color:#8FA8C8;font-size:12px;margin-left:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wpq{grid-column:2;text-align:right;font-family:'IBM Plex Mono',ui-monospace,monospace}
.wp{font-size:14.5px}
.wp.lv::before{content:'●';color:#22D3EE;font-size:9px;margin-right:4px}
.wpq .wch{margin-left:4px;font-size:12.5px}
.wsq{grid-column:1;font-size:11.5px;color:#8FA8C8}
.wsq i{display:inline-block;width:9px;height:9px;margin-right:2px;background:#22C55E}.wsq i.off{background:#1E2B42}
.wr2{grid-column:2;text-align:right;font-size:11.5px;color:#8FA8C8}
.wst{cursor:pointer;color:#475A74;margin-right:5px;font-size:14px;user-select:none}.wst.on{color:#FBBF24}
li.it .l1 .wst{order:0}
"""

WATCH_JS = r"""
<script>
(function(){
  var room=document.querySelector(".room"), left=document.querySelector(".pane.left"), mW=document.getElementById("mode-watch");
  if(!room||!left||!mW) return;
  var box=document.createElement("div"); box.className="wleft"; box.id="wleft"; left.appendChild(box);
  var items=[], quotes={}, loaded=false, shell=false, timer=null, sortKey="def", fil="all", starSet={}, selTk="", toastT=null;
  try{ fil=localStorage.getItem("wfil")||"all"; sortKey=localStorage.getItem("wsort")||"def"; }catch(e){}
  var INDEX=[["^TWII","台股加權"],["^GSPC","S&P"],["^IXIC","那指"],["^SOX","費半"]];
  function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function fmt(n,d){ if(n==null||isNaN(n)) return "—"; d=(d==null?2:d);
    return Number(n).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d}); }
  function cls(c){ return c>=0?"up":"dn"; }
  function sgn(c){ return (c>=0?"+":"")+c.toFixed(2)+"%"; }
  function post(b){ return fetch("/room/watch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})
    .then(function(r){ return r.ok?r.json():{error:"伺服器回應異常（"+r.status+"）"}; }).catch(function(){ return {error:"連不上伺服器"}; }); }
  function say(h){ var m=document.getElementById("wmsg"); if(m) m.innerHTML=h; }
  function toast(h){ var t=document.getElementById("wtoast"); if(!t) return; t.innerHTML=h; clearTimeout(toastT); toastT=setTimeout(function(){ t.innerHTML=""; },7000); }
  function popShow(on){ var p=document.getElementById("wpop"); if(!p) return; p.classList.toggle("show",on); if(on){ if(window._wxqLoad) window._wxqLoad(); var i=document.getElementById("wadd"); if(i) setTimeout(function(){ i.focus(); },50); } }

  function buildShell(){
    box.innerHTML='<div class="wix" id="windex"></div>'
      +'<div class="whead"><span class="wtitle" id="wtitle">自選</span>'
      +'<button class="plus" id="wplus" title="新增／匯入">＋</button>'
      +'<select id="wsort" title="排序"><option value="def">我的順序</option><option value="up">漲幅大→小</option><option value="dn">跌幅大→小</option><option value="lit">燈數多→少</option></select></div>'
      +'<div class="wchips" id="wchips"><button data-f="all">全部</button><button data-f="tw">台股</button><button data-f="us">美股</button></div>'
      +'<div class="wtoast" id="wtoast"></div>'
      +'<div id="wlist"></div>'
      +'<div class="wpop" id="wpop"><div class="ph">新增／匯入自選股<button id="wclose" title="關閉">✕</button></div>'
      +'<input type="text" id="wadd" placeholder="代號或中文名：2330、NVDA、台積電（可多檔）" autocomplete="off" enterkeyhint="done">'
      +'<div class="pb"><button class="go" id="waddb">＋ 新增</button><button id="wimpb">⇪ 匯入檔案</button></div>'
      +'<input type="file" id="wfile" accept=".dsl,.csv,.txt,text/plain" style="display:none">'
      +'<div class="wmsg" id="wmsg">匯入支援 XQ 匯出的 .dsl、純文字／CSV。手機左滑那一列可移除；電腦滑鼠移上去按 ✕。</div>'
      +'<div class="wxq" id="wxq"><div class="xh">與 XQ 同步<label><input type="checkbox" id="wxauto">自動</label></div>'
      +'<div class="xl" id="wxl">讀取中…</div>'
      +'<div class="xb"><button id="wxsync">立即同步</button><a id="wxexp" href="/room/watch/export" download="watchlist_for_xq.txt">匯出給 XQ</a></div>'
      +'<div class="xs" id="wxs"></div></div></div>';
    shell=true;
    document.getElementById("wsort").value=sortKey;
    document.getElementById("wplus").addEventListener("click",function(){ popShow(!document.getElementById("wpop").classList.contains("show")); });
    document.getElementById("wclose").addEventListener("click",function(){ popShow(false); });
    document.addEventListener("keydown",function(e){ if(e.key==="Escape") popShow(false); });
    document.addEventListener("click",function(e){ var p=document.getElementById("wpop"); if(p&&p.classList.contains("show")&&!e.target.closest("#wpop,#wplus")) popShow(false); });
    document.getElementById("wchips").addEventListener("click",function(e){ var b=e.target.closest("button[data-f]"); if(!b) return;
      fil=b.dataset.f; try{ localStorage.setItem("wfil",fil); }catch(x){} renderList(); });
    // ── XQ 同步（單向 XQ→自選；只讀 XQ 的檔）──
    var xqLists=[], xqSel=[];
    function xqRender(st){
      var L=document.getElementById("wxl"), S=document.getElementById("wxs"); if(!L) return;
      if(!st||!st.available){ L.textContent="找不到 XQ 的自選股檔（這台電腦沒裝 XQ，或還沒建立自選股）。"; document.getElementById("wxsync").disabled=true; return; }
      xqLists=st.lists||[]; xqSel=st.selected||[]; document.getElementById("wxauto").checked=!!st.auto;
      L.innerHTML=xqLists.map(function(x){ var off=x.count===0;
        return '<label class="'+(off?"off":"")+'"><input type="checkbox" data-n="'+esc(x.name)+'"'+(xqSel.indexOf(x.name)>=0?" checked":"")+(off?" disabled":"")+'>'+esc(x.name)+" "+x.count+"</label>"; }).join("");
      S.textContent=(st.last?("上次同步 "+st.last.time+"：新增 "+st.last.added+"、移除 "+st.last.removed+"。"):"尚未同步。")
        +" XQ 拿掉的會同步拿掉，自己手動加的不會動。"; }
    function xqLoad(){ fetch("/room/xq",{cache:"no-store"}).then(function(r){ return r.ok?r.json():null; }).then(xqRender).catch(function(){}); }
    window._wxqLoad=xqLoad;
    function xqPost(b){ return fetch("/room/xq",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}).then(function(r){ return r.ok?r.json():null; }); }
    function xqDone(r){ if(!r) { say('<b style="color:#F87171">同步失敗</b>'); return; } xqRender(r.status);
      var x=r.result||{}; if(x.error){ say('<b style="color:#F87171">'+esc(x.error)+"</b>"); return; }
      var msg="XQ 同步完成：新增 <b>"+(x.added||[]).length+"</b>、移除 <b>"+(x.removed||[]).length+"</b>，共 "+x.total+" 檔"
        +((x.removed||[]).length?"（移除："+esc(x.removed.slice(0,6).join("、"))+((x.removed||[]).length>6?"…":"")+"）":"");
      say(msg); toast(msg); refresh(true); }
    document.getElementById("wxl").addEventListener("change",function(){
      var sel=[]; document.querySelectorAll("#wxl input[type=checkbox]:checked").forEach(function(c){ sel.push(c.dataset.n); });
      say("同步中…"); xqPost({action:"config",lists:sel,auto:document.getElementById("wxauto").checked}).then(xqDone); });
    document.getElementById("wxauto").addEventListener("change",function(e){ xqPost({action:"config",auto:e.target.checked}).then(xqDone); });
    document.getElementById("wxsync").addEventListener("click",function(){ say("同步中…"); xqPost({action:"sync"}).then(xqDone); });
    var inp=document.getElementById("wadd");
    function doAdd(){ var q=inp.value.trim(); if(!q) return; say("新增中…");
      post({action:"add",q:q}).then(function(r){
        if(r.error){ say('<b style="color:#F87171">'+esc(r.error)+'</b>'); return; }
        var parts=[]; if(r.added&&r.added.length) parts.push("已新增 <b>"+esc(r.added.join("、"))+"</b>");
        if(r.already&&r.already.length) parts.push("本來就在："+esc(r.already.join("、")));
        if(r.skipped&&r.skipped.length) parts.push('<span style="color:#FBBF24">看不懂（沒加）：'+esc(r.skipped.join("、"))+"</span>");
        var c=r.candidates||{}; Object.keys(c).forEach(function(k){ parts.push("「"+esc(k)+"」有多個符合："+esc(c[k].join("、"))+"，請改輸入代號"); });
        var msg=parts.join("　｜　")||"沒有可新增的內容"; say(msg); inp.value=""; refresh(true);
        if(r.added&&r.added.length&&!(r.skipped&&r.skipped.length)&&!Object.keys(c).length){ toast(msg); popShow(false); } }); }
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
          p.push("共 "+r.total+" 檔"); var msg=p.join("　｜　"); say(msg); toast(msg); refresh(true); }); };
      rd.readAsArrayBuffer(f); });
    document.getElementById("wsort").addEventListener("change",function(e){ sortKey=e.target.value; try{ localStorage.setItem("wsort",sortKey); }catch(x){} renderList(); });
    var Lst=document.getElementById("wlist");
    Lst.addEventListener("click",function(e){
      if(e.target.closest(".wgrip")) return;
      var del=e.target.closest(".wdel,.wx"); var row=e.target.closest(".wrow"); if(!row) return;
      if(del){ var tk=row.dataset.tk; post({action:"remove",tk:tk}).then(function(){ toast("已移除 <b>"+esc(tk)+"</b>（要加回去：點「＋」再輸入代號）"); refresh(true); }); return; }
      if(row.classList.contains("open")){ row.classList.remove("open"); return; }
      selTk=row.dataset.tk; markSel(); if(window.roomSearch){ window.roomSearch(selTk); } });
    // 手機左滑：露出紅色「移除」
    var sx=0, sy=0, srow=null, moved=false;
    Lst.addEventListener("touchstart",function(e){ if(e.target.closest(".wgrip")) { srow=null; return; } var t=e.touches[0]; sx=t.clientX; sy=t.clientY; moved=false; srow=e.target.closest(".wrow");
      Lst.querySelectorAll(".wrow.open").forEach(function(r){ if(r!==srow) r.classList.remove("open"); }); },{passive:true});
    Lst.addEventListener("touchmove",function(e){ if(!srow) return; var t=e.touches[0], dx=t.clientX-sx, dy=t.clientY-sy;
      if(Math.abs(dx)>Math.abs(dy)&&Math.abs(dx)>10){ moved=true; } },{passive:true});
    Lst.addEventListener("touchend",function(e){ if(!srow||!moved) return; var t=e.changedTouches[0], dx=t.clientX-sx;
      if(dx<-45){ srow.classList.add("open"); } else if(dx>25){ srow.classList.remove("open"); }
      e.preventDefault(); },{passive:false});
    // 拖曳調整順序（只在「我的順序」時有 ⠿ 把手；手機電腦都用 Pointer Events）
    var dragRow=null, dragPid=null, lastY=0, asTimer=null;
    function autoScroll(){ if(!dragRow) return; var r=Lst.getBoundingClientRect(), m=48;           // 拖到清單上下緣 → 自動捲動
      if(lastY<r.top+m) Lst.scrollTop-=14; else if(lastY>r.bottom-m) Lst.scrollTop+=14; }
    Lst.addEventListener("pointerdown",function(e){ var g=e.target.closest(".wgrip"); if(!g) return;
      dragRow=g.closest(".wrow"); dragPid=e.pointerId; dragRow.classList.add("drag"); lastY=e.clientY;
      clearInterval(asTimer); asTimer=setInterval(autoScroll,40);
      try{ g.setPointerCapture(e.pointerId); }catch(x){} e.preventDefault(); });
    Lst.addEventListener("pointermove",function(e){ if(!dragRow||e.pointerId!==dragPid) return; lastY=e.clientY;
      var el=document.elementFromPoint(e.clientX,e.clientY), tgt=el&&el.closest?el.closest(".wrow"):null;
      if(!tgt||tgt===dragRow||tgt.parentElement!==dragRow.parentElement) return;
      var r=tgt.getBoundingClientRect(), after=(e.clientY>r.top+r.height/2);
      var par=dragRow.parentElement; par.insertBefore(dragRow,after?tgt.nextSibling:tgt); });
    function endDrag(e){ if(!dragRow||(e&&e.pointerId!==dragPid)) return; clearInterval(asTimer); dragRow.classList.remove("drag"); dragRow=null;
      var order=[]; document.querySelectorAll("#wlist .wrow").forEach(function(r){ order.push(r.dataset.tk); });
      post({action:"reorder",order:order}).then(function(){ loadList().then(function(){ renderList(); }); }); }
    Lst.addEventListener("pointerup",endDrag); Lst.addEventListener("pointercancel",endDrag);
  }

  function markSel(){ document.querySelectorAll("#wlist .wrow").forEach(function(r){ r.classList.toggle("sel",r.dataset.tk===selTk); }); }
  function stateOf(list){ var s=""; list.forEach(function(i){ var q=quotes[i.tk]; if(q&&q.state==="盤中") s="盤中"; else if(q&&!s) s=q.state||""; }); return s||"—"; }
  function renderIndex(){
    var h=""; INDEX.forEach(function(x){ var q=quotes[x[0]];
      h+='<span class="wt">'+esc(x[1])+(q&&q.state==="盤中"?'<span style="color:#22D3EE">●</span>':'')+'<b>'+(q?fmt(q.px,0):"—")+'</b>'
        +(q&&q.chg!=null?'<span class="'+cls(q.chg)+'">'+sgn(q.chg)+'</span>':'')+'</span>'; });
    var w=document.getElementById("windex"); if(w) w.innerHTML=h; }
  function rowHtml(i){
    var q=quotes[i.tk]||null, px=q?q.px:null, chg=q?q.chg:null;
    var sq=""; for(var k=0;k<4;k++) sq+='<i class="'+((i.lit!=null&&k<i.lit)?"":"off")+'"></i>';
    var tg=(i.target&&px)?((i.target/px-1)*100):null;
    var dist=tg==null?"—":('<span class="'+cls(tg)+'">'+(tg>=0?"+":"")+tg.toFixed(0)+"%</span>");
    var lit=i.in_scan?(i.lit+"/4"):"不在燈號掃描";
    return '<div class="wrow'+(i.tk===selTk?" sel":"")+'" data-tk="'+esc(i.tk)+'"><button class="wdel">移除</button><button class="wx" title="移除">✕</button>'
      +'<div class="wbody"><div class="wn"><span class="wgrip" title="按住上下拖曳調整順序">⠿</span><b>'+esc(i.tk)+'</b><span class="nm">'+esc(i.name)+'</span></div>'
      +'<div class="wpq"><span class="wp'+(q&&q.state==="盤中"?" lv":"")+'">'+(px==null?"—":fmt(px,i.mkt==="tw"?1:2))+'</span>'
      +(chg==null?"":'<span class="wch '+cls(chg)+'">'+sgn(chg)+'</span>')+'</div>'
      +'<div class="wsq" title="'+esc(lit)+'">'+sq+(i.in_scan?"":' <span style="color:#6B84A3">'+esc(lit)+"</span>")+'</div>'
      +'<div class="wr2">距目標 '+dist+'</div></div></div>'; }
  function renderList(){
    var L=document.getElementById("wlist"); if(!L) return;
    var arr=items.slice(); var chgOf=function(i){ var q=quotes[i.tk]; return q&&q.chg!=null?q.chg:null; };
    if(sortKey==="up") arr.sort(function(a,b){ return (chgOf(b)==null?-999:chgOf(b))-(chgOf(a)==null?-999:chgOf(a)); });
    else if(sortKey==="dn") arr.sort(function(a,b){ return (chgOf(a)==null?999:chgOf(a))-(chgOf(b)==null?999:chgOf(b)); });
    else if(sortKey==="lit") arr.sort(function(a,b){ return (b.lit==null?-1:b.lit)-(a.lit==null?-1:a.lit); });
    var tw=arr.filter(function(i){return i.mkt==="tw";}), us=arr.filter(function(i){return i.mkt!=="tw";});
    var open=[]; L.querySelectorAll(".wrow.open").forEach(function(r){ open.push(r.dataset.tk); });
    var top=L.scrollTop;
    function grp(name,list){ if(!list.length) return ""; var st=stateOf(list);
      return '<div class="wgrp">'+name+'　'+(st==="盤中"?'<span class="lv">● 盤中</span>':esc(st))+'　'+list.length+' 檔</div>'
        +'<div class="wlist">'+list.map(rowHtml).join("")+'</div>'; }
    var h=(fil==="tw"?"":grp("美股",us))+(fil==="us"?"":grp("台股",tw));
    if(!h) h='<div class="wmsg" style="padding:18px 4px">'+(items.length?"這個市場沒有自選股。":"還沒有自選股。點右上「＋」輸入代號，或匯入 XQ 匯出的自選股。")+'</div>';
    L.innerHTML=h; L.scrollTop=top;
    L.classList.toggle("wmanual",sortKey==="def");
    open.forEach(function(tk){ var r=L.querySelector('.wrow[data-tk="'+tk+'"]'); if(r) r.classList.add("open"); });
    var t=document.getElementById("wtitle"); if(t) t.textContent="自選 "+items.length+" 檔";
    var cn={all:items.length,tw:tw.length,us:us.length}, names={all:"全部",tw:"台股",us:"美股"};
    document.querySelectorAll("#wchips button").forEach(function(b){ b.classList.toggle("on",b.dataset.f===fil); b.textContent=names[b.dataset.f]+" "+cn[b.dataset.f]; });
    renderIndex(); }

  function loadList(){ return fetch("/room/watch",{cache:"no-store"}).then(function(r){ return r.ok?r.json():{items:[]}; })
    .then(function(d){ items=d.items||[]; starSet={}; items.forEach(function(i){ starSet[i.tk]=1; }); loaded=true; paintStars(); }).catch(function(){}); }
  function fetchQuotes(){ var tks=items.map(function(i){return i.tk;}).concat(INDEX.map(function(x){return x[0];}));
    return fetch("/room/quote?tickers="+encodeURIComponent(tks.join(",")),{cache:"no-store"}).then(function(r){ return r.ok?r.json():{}; })
      .then(function(q){ quotes=q||{}; }).catch(function(){}); }
  function refresh(reload){ var p=reload?loadList():Promise.resolve(); return p.then(fetchQuotes).then(function(){ if(shell&&room.classList.contains("watch")&&!document.querySelector(".wrow.drag")) renderList(); }); }

  function show(){
    var s1=document.getElementById("mode-stock"); if(s1) s1.click();          // 先切到個股版面（左清單＋中頁面）
    room.classList.add("watch"); mW.classList.add("on");
    if(s1) s1.classList.remove("on"); var b=document.getElementById("mode-list"); if(b) b.classList.remove("on");
    if(!shell) buildShell();
    renderList();
    refresh(true).then(function(){
      var emp=document.querySelector("#mid-body .empty");               // 中間還是空的「左邊選一檔」→ 自動點第一檔
      if(items.length && (emp || !selTk) && window.roomSearch){ var f=document.querySelector("#wlist .wrow"); if(f){ selTk=f.dataset.tk; markSel(); window.roomSearch(selTk); } } });
    clearInterval(timer); timer=setInterval(function(){ if(!document.hidden) refresh(false); },15000); }
  function hide(){ room.classList.remove("watch"); mW.classList.remove("on"); clearInterval(timer); timer=null; popShow(false); }
  try{ var ms=document.getElementById("mode-stock");
    new MutationObserver(function(){ if(room.classList.contains("watch")&&ms.classList.contains("on")) ms.classList.remove("on"); })
      .observe(ms,{attributes:true,attributeFilter:["class"]}); }catch(e){}
  mW.addEventListener("click",function(e){ if(e.isTrusted===false && room.classList.contains("watch")) return; show(); });
  var s1=document.getElementById("mode-stock"), s2=document.getElementById("mode-list");
  if(s1) s1.addEventListener("click",function(e){ if(room.classList.contains("watch") && e.isTrusted===false) return; hide(); });
  if(s2) s2.addEventListener("click",hide);

  // ★：左欄、列表表格、個股標題各一顆，點一下加入／移除自選
  function paintStars(){
    function mk(tk){ var s=document.createElement("span"); s.className="wst"+(starSet[tk]?" on":""); s.dataset.tk=tk; s.textContent=starSet[tk]?"★":"☆"; s.title=starSet[tk]?"移出自選":"加入自選"; return s; }
    function put(host,tk){ if(!host) return; var ex=host.querySelector(".wst");
      if(ex){ var on=!!starSet[tk]; if(ex.classList.contains("on")!==on){ ex.classList.toggle("on",on); ex.textContent=on?"★":"☆"; ex.title=on?"移出自選":"加入自選"; } return; }
      host.insertBefore(mk(tk),host.firstChild); }
    document.querySelectorAll("li.it").forEach(function(li){ put(li.querySelector(".l1"),li.dataset.tk); });
    document.querySelectorAll("tr[data-tk]").forEach(function(tr){ put(tr.querySelector("td"),tr.dataset.tk); });
    var t=document.querySelector(".dhead .tk");
    if(t){ var tk=t.textContent.trim(), nx=t.nextElementSibling;
      if(nx&&nx.classList.contains("wst")){ var on=!!starSet[tk]; if(nx.classList.contains("on")!==on){ nx.classList.toggle("on",on); nx.textContent=on?"★":"☆"; } }
      else { var st=mk(tk); st.style.marginLeft="6px"; t.insertAdjacentElement("afterend",st); } } }
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
