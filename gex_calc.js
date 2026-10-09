/* GEX 頁：選擇權損益試算器（到期當天的損益）。全在瀏覽器計算，不上傳、不儲存。
   報價 window.GEXDATA.quotes＝最近一場（夜盤或日盤）的買價／賣價／最後價；買進用賣價、賣出用買價，缺價時留空請手動填。
   單位：台指選擇權每點 50 元；微台每點 10 元。5 口微台＝1 口選擇權。 */
(function () {
  var D = window.GEXDATA, Q = D && D.quotes;
  var root = document.getElementById('pc_root');
  if (!D || !root) return;
  var $ = function (i) { return document.getElementById(i); };
  var C = D.colors;
  var MAXLEG = 4;
  var spot = Q ? Q.spot : D.spot;
  var months = Q ? Q.months : [];
  var curM = null;

  function fmt(n) { return Math.round(n).toLocaleString(); }
  function sgn(n) { return (n >= 0 ? '+' : '−') + fmt(Math.abs(n)); }

  // ───── 到期日、履約價選單 ─────
  var selExp = $('pc_exp');
  months.forEach(function (m, i) { var o = document.createElement('option'); o.value = i; o.textContent = m.label; selExp.appendChild(o); });
  function strikes() {
    return curM ? Object.keys(curM.q).map(Number).sort(function (a, b) { return a - b; }) : [];
  }
  function fillStrikes(sel, keep) {
    var cur = keep || sel.value, ks = strikes();
    sel.innerHTML = '';
    ks.forEach(function (k) { var o = document.createElement('option'); o.value = k; o.textContent = k.toLocaleString(); sel.appendChild(o); });
    if (cur && ks.indexOf(+cur) >= 0) sel.value = cur;
    else if (ks.length) { var best = ks.reduce(function (a, b) { return Math.abs(b - spot) < Math.abs(a - spot) ? b : a; }); sel.value = best; }
  }

  // ───── 每一腿 ─────
  var legsEl = $('pc_legs'), legs = [];
  function addLeg(side, cp, strike, qty) {
    if (legs.length >= MAXLEG) return;
    var id = legs.length, tr = document.createElement('tr');
    tr.innerHTML = '<td><select class="s">' + '<option value="B">買進</option><option value="S">賣出</option></select></td>' +
      '<td><select class="c"><option value="P">賣權</option><option value="C">買權</option></select></td>' +
      '<td><select class="k"></select></td><td><input class="q" type="number" min="0" value="1" inputmode="numeric"></td>' +
      '<td><input class="p" type="number" step="0.5" inputmode="decimal"><div class="qh dim"></div></td>' +
      '<td><button type="button" class="x" aria-label="刪除這一腿">✕</button></td>';
    legsEl.appendChild(tr);
    var leg = { tr: tr, manual: false };
    legs.push(leg);
    fillStrikes(tr.querySelector('.k'), strike);
    if (side) tr.querySelector('.s').value = side;
    if (cp) tr.querySelector('.c').value = cp;
    if (strike) tr.querySelector('.k').value = strike;
    if (qty != null) tr.querySelector('.q').value = qty;
    ['s', 'c', 'k'].forEach(function (c) { tr.querySelector('.' + c).addEventListener('change', function () { leg.manual = false; autoPrice(leg); calc(); }); });
    tr.querySelector('.q').addEventListener('input', calc);
    tr.querySelector('.p').addEventListener('input', function () { leg.manual = true; calc(); });
    tr.querySelector('.x').addEventListener('click', function () { legsEl.removeChild(tr); legs.splice(legs.indexOf(leg), 1); calc(); });
    autoPrice(leg);
  }
  function quoteOf(leg) {
    if (!curM) return null;
    var k = leg.tr.querySelector('.k').value, cp = leg.tr.querySelector('.c').value;
    var s = curM.q[k]; if (!s) return null;
    var off = cp === 'C' ? 0 : 3;
    return { bid: s[off], ask: s[off + 1], last: s[off + 2] };
  }
  function autoPrice(leg) {
    var q = quoteOf(leg), side = leg.tr.querySelector('.s').value, p = leg.tr.querySelector('.p'), h = leg.tr.querySelector('.qh');
    if (!q) { h.textContent = '無報價'; return; }
    if (!leg.manual) {
      var v = side === 'B' ? (q.ask != null ? q.ask : q.last) : (q.bid != null ? q.bid : q.last);
      p.value = v == null ? '' : v;
    }
    h.textContent = '買 ' + (q.bid == null ? '—' : q.bid) + ' ／ 賣 ' + (q.ask == null ? '—' : q.ask);
  }
  function refreshAll() { legs.forEach(function (l) { fillStrikes(l.tr.querySelector('.k')); autoPrice(l); }); }

  // ───── 計算 ─────
  function readLegs() {
    return legs.map(function (l) {
      var t = l.tr;
      return { side: t.querySelector('.s').value === 'B' ? 1 : -1, cp: t.querySelector('.c').value, K: +t.querySelector('.k').value,
               q: +t.querySelector('.q').value || 0, p: parseFloat(t.querySelector('.p').value) };
    });
  }
  function pnl(P, micro, lg) {
    var t = micro.dir * (P - micro.entry) * 10 * micro.lots;
    lg.forEach(function (g) {
      var intr = g.cp === 'C' ? Math.max(P - g.K, 0) : Math.max(g.K - P, 0);
      t += g.side * (intr - g.p) * 50 * g.q;
    });
    return t;
  }
  var lastTable = null;
  function calc() {
    var out = $('pc_res'), svg = $('pc_svg');
    var micro = { lots: +$('pc_ml').value || 0, dir: $('pc_md').value === 'L' ? 1 : -1, entry: +$('pc_me').value || spot };
    var lg = readLegs().filter(function (g) { return g.q > 0; });
    var miss = lg.filter(function (g) { return !(g.p >= 0); });
    if (!lg.length && !micro.lots) { out.innerHTML = '先按上面的範例，或自己加一腿。'; svg.innerHTML = ''; return; }
    if (miss.length) { out.innerHTML = '<span class="warnc">有一腿沒有報價（夜盤很多價位沒有人掛單），請在「價格」欄手動填入你看到的點數。</span>'; svg.innerHTML = ''; return; }
    var net = lg.reduce(function (a, g) { return a + g.side * g.p * 50 * g.q; }, 0);   // 正＝付出、負＝收到
    var lo = spot * 0.85, hi = spot * 1.15, step = 5, mn = 1e18, mx = -1e18, be = [], prev = null;
    for (var P = lo; P <= hi; P += step) {
      var v = pnl(P, micro, lg);
      if (v < mn) mn = v; if (v > mx) mx = v;
      if (prev !== null && ((prev.v < 0 && v >= 0) || (prev.v > 0 && v <= 0))) be.push(Math.round(prev.P + (P - prev.P) * (0 - prev.v) / (v - prev.v)));
      prev = { P: P, v: v };
    }
    var eps = 1e-6, sLo = (pnl(lo + 100, micro, lg) - pnl(lo, micro, lg)) / 100, sHi = (pnl(hi, micro, lg) - pnl(hi - 100, micro, lg)) / 100;
    var lossTxt = (sLo > eps || sHi < -eps) ? '沒有上限（價格往那個方向走，虧損會一直擴大）' : fmt(-mn) + ' 元';
    var gainTxt = (sHi > eps || sLo < -eps) ? '沒有上限' : fmt(mx) + ' 元';
    if (mn >= 0) lossTxt = '不會虧（在這個範圍內）';
    var hasSell = lg.some(function (g) { return g.side < 0; });
    out.innerHTML =
      '<b>' + (net >= 0 ? '一開始付出 ' + fmt(net) + ' 元' : '一開始收到 ' + fmt(-net) + ' 元') + '</b>（只算選擇權權利金）<br>' +
      '到期時最多虧：<b class="dn">' + lossTxt + '</b><br>最多賺：<b class="up">' + gainTxt + '</b><br>' +
      '損益兩平價：<b class="num">' + (be.length ? be.map(function (x) { return x.toLocaleString(); }).join('、') : '範圍內沒有') + '</b>' +
      (hasSell ? '<br><span class="warnc">⚠️ 有「賣出」的腿：需要保證金，風險可能很大，金額以期貨商為準。</span>' : '') +
      (micro.lots && lg.length && (micro.lots % 5) ? '<br><span class="warnc">微台口數不是 5 的倍數，沒辦法剛好對上 1 口選擇權。</span>' : '');
    // 表格
    var base = Math.round(spot / 500) * 500, rows = '', ps = [];
    for (var i = -4; i <= 4; i++) ps.push(base + i * 500);
    ps.sort(function (a, b) { return a - b; });
    ps.forEach(function (P) { var v = pnl(P, micro, lg); rows += '<tr><td>' + P.toLocaleString() + '</td><td class="' + (v >= 0 ? 'up' : 'dn') + '">' + sgn(v) + '</td></tr>'; });
    $('pc_tbl').innerHTML = '<tr><th>到期時指數</th><th style="text-align:right">損益（元）</th></tr>' + rows;
    // 損益曲線
    var W = 700, H = 220, L = 54, R = 10, T = 12, B = 26, x0 = spot * 0.93, x1 = spot * 1.07, pts = [], yl = 1e18, yh = -1e18;
    for (var X = x0; X <= x1; X += (x1 - x0) / 140) { var y = pnl(X, micro, lg); pts.push([X, y]); if (y < yl) yl = y; if (y > yh) yh = y; }
    yl = Math.min(yl, 0); yh = Math.max(yh, 0); var pad = (yh - yl) * 0.08 || 1; yl -= pad; yh += pad;
    var sx = function (v) { return L + (v - x0) / (x1 - x0) * (W - L - R); }, sy = function (v) { return T + (yh - v) / (yh - yl) * (H - T - B); };
    var z = sy(0), path = pts.map(function (p, i) { return (i ? 'L' : 'M') + sx(p[0]).toFixed(1) + ',' + sy(p[1]).toFixed(1); }).join(' ');
    var grid = '';
    [yl + pad, 0, yh - pad].forEach(function (v) { grid += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + sy(v) + '" y2="' + sy(v) + '" stroke="#0E1B2B"/><text x="' + (L - 6) + '" y="' + (sy(v) + 3) + '" text-anchor="end" fill="#5B6E8A" font-size="10">' + fmt(v) + '</text>'; });
    for (var t = Math.ceil(x0 / 500) * 500; t < x1; t += 500) grid += '<text x="' + sx(t) + '" y="' + (H - 8) + '" text-anchor="middle" fill="#5B6E8A" font-size="10">' + t.toLocaleString() + '</text>';
    svg.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" aria-label="到期損益曲線" style="font-family:\'IBM Plex Mono\',monospace">' + grid +
      '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + z + '" y2="' + z + '" stroke="#2B4C6F"/>' +
      '<line x1="' + sx(spot) + '" x2="' + sx(spot) + '" y1="' + T + '" y2="' + (H - B) + '" stroke="#DCE7F5" stroke-dasharray="4 3"/>' +
      '<text x="' + (sx(spot) + 4) + '" y="' + (T + 9) + '" fill="#DCE7F5" font-size="10">現價 ' + fmt(spot) + '</text>' +
      '<path d="' + path + '" fill="none" stroke="' + C.pos + '" stroke-width="2"/></svg>';
  }

  // ───── 範例 ─────
  function clearLegs() { legsEl.innerHTML = ''; legs = []; }
  function kUp() { var ks = strikes(), t = Math.ceil(spot / 1000) * 1000; return ks.indexOf(t) >= 0 ? t : ks.filter(function (k) { return k >= spot; })[0]; }
  function kDn() { var ks = strikes(), t = Math.floor(spot / 1000) * 1000; return ks.indexOf(t) >= 0 ? t : ks.filter(function (k) { return k <= spot; }).pop(); }
  function preset(name) {
    clearLegs();
    $('pc_md').value = 'L'; $('pc_me').value = Math.round(spot);
    var dn = kDn(), up = kUp(), lots = Math.max(1, Math.round((+$('pc_ml').value || 5) / 5));
    if (name === 'ins') { $('pc_ml').value = 5; addLeg('B', 'P', dn, 1); }
    if (name === 'collar') { $('pc_ml').value = 5; addLeg('B', 'P', dn, 1); addLeg('S', 'C', up, 1); }
    if (name === 'strangle') { $('pc_ml').value = 0; addLeg('B', 'P', dn, 1); addLeg('B', 'C', up, 1); }
    if (name === 'micro') { $('pc_ml').value = 5; }
    var bs = document.querySelectorAll('#pc_btn button');
    for (var i = 0; i < bs.length; i++) bs[i].setAttribute('aria-pressed', String(bs[i].getAttribute('data-k') === name));
    calc();
  }
  function setExp(i) { curM = months[i]; refreshAll(); }

  if (!months.length) {
    root.querySelector('.pc_body').innerHTML = '<div class="box warn">這次沒有取到選擇權報價，無法自動帶入。請之後再試，或到你的期貨商軟體看報價。</div>';
    return;
  }
  // 預設選第一個到期日；週選當天到期的剩幾小時，改預設到月選更貼近一般使用
  var def = 0;
  months.forEach(function (m, i) { if (m.label.indexOf('月選') >= 0 && def === 0) def = i; });
  selExp.value = def; setExp(def);
  selExp.addEventListener('change', function () { setExp(+selExp.value); calc(); });
  ['pc_ml', 'pc_md', 'pc_me'].forEach(function (i) { $(i).addEventListener('input', calc); });
  $('pc_add').addEventListener('click', function () { addLeg('B', 'P', null, 1); calc(); });
  $('pc_btn').addEventListener('click', function (e) { var k = e.target.getAttribute && e.target.getAttribute('data-k'); if (k) preset(k); });
  preset('ins');
})();
