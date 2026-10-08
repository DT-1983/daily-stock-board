/* GEX 頁：K 線＋價位牆（Lightweight Charts v5）＋右側各履約價 GEX 長條（canvas，跟價格軸對齊）。
   資料 window.GEXDATA 由 gex_html.py 內嵌：m＝1 分 K [[秒,開,高,低,收,量]]（台北時間當 UTC 編碼）、d＝日 K、
   strikes＝[[履約價, GEX億, 買權口, 賣權口]]、spot/call_wall/put_wall/flip、colors。
   指標都在後端算好，這裡只畫。紅漲綠跌（台股慣例），陰線空心。 */
(function () {
  var D = window.GEXDATA, LC = window.LightweightCharts;
  var host = document.getElementById('gxk');
  if (!D || !LC || !host) return;
  var C = D.colors, UP = '#ff5277', DN = '#2ee6a8', BG = '#080E1A';
  var MONO = "'IBM Plex Mono',ui-monospace,monospace";
  var wd = ['日', '一', '二', '三', '四', '五', '六'];
  function p2(n) { return (n < 10 ? '0' : '') + n; }
  function fmt(t, withTime) {
    var d = new Date(t * 1000);
    var s = p2(d.getUTCMonth() + 1) + '/' + p2(d.getUTCDate());
    return withTime ? s + ' ' + p2(d.getUTCHours()) + ':' + p2(d.getUTCMinutes()) : s + '（' + wd[d.getUTCDay()] + '）';
  }
  var mode = 30;          // 分鐘數；0＝日 K

  var chart = LC.createChart(host, {
    autoSize: true,
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#9DB0C8', fontFamily: MONO, fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: '#0E1B2B' }, horzLines: { color: '#0E1B2B' } },
    rightPriceScale: { borderColor: '#16304A', scaleMargins: { top: 0.08, bottom: 0.08 } },
    timeScale: { borderColor: '#16304A', timeVisible: true, secondsVisible: false, rightOffset: 4 },
    crosshair: { mode: 0 },
    handleScroll: { vertTouchDrag: false },
    localization: { timeFormatter: function (t) { return fmt(t, mode !== 0); } }
  });
  var series = chart.addSeries(LC.CandlestickSeries, {
    upColor: UP, borderUpColor: UP, wickUpColor: UP,
    downColor: BG, borderDownColor: DN, wickDownColor: DN,
    priceLineVisible: false, lastValueVisible: false,
    priceFormat: { type: 'price', precision: 0, minMove: 1 }
  });

  function line(price, color, title, style) {
    series.createPriceLine({ price: price, color: color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title: title });
  }
  line(D.spot, '#DCE7F5', '收盤', 0);
  line(D.call_wall, C.pos, '買權牆', 0);
  line(D.put_wall, C.neg, '賣權牆', 0);
  if (D.flip) line(D.flip, C.flip, '翻轉點', 2);

  function agg(n) {
    var step = n * 60, out = [], cur = null;
    for (var i = 0; i < D.m.length; i++) {
      var b = D.m[i], k = Math.floor(b[0] / step) * step;
      if (!cur || cur.time !== k) {
        if (cur) out.push(cur);
        cur = { time: k, open: b[1], high: b[2], low: b[3], close: b[4] };
      } else {
        if (b[2] > cur.high) cur.high = b[2];
        if (b[3] < cur.low) cur.low = b[3];
        cur.close = b[4];
      }
    }
    if (cur) out.push(cur);
    return out;
  }
  function daily() {
    return D.d.map(function (r) { return { time: Date.parse(r[0] + 'T00:00:00Z') / 1000, open: r[1], high: r[2], low: r[3], close: r[4] }; });
  }

  var bars = [], VIS = { 5: 300, 15: 220, 30: 190, 60: 150, 0: 60 };
  function setMode(n) {
    mode = n;
    bars = n === 0 ? daily() : agg(n);
    series.setData(bars);
    chart.applyOptions({ timeScale: { timeVisible: n !== 0 } });
    var len = bars.length, vis = VIS[n];
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(-1, len - vis), to: len + 4 });
    var btns = document.querySelectorAll('#gxbtn button');
    for (var i = 0; i < btns.length; i++) btns[i].setAttribute('aria-pressed', String(+btns[i].getAttribute('data-n') === n));
    showBar(bars[len - 1], null);
  }

  // ───── 讀數列（高度寫死兩行，hover 不跳版）─────
  var rd1 = document.getElementById('gxr1'), rd2 = document.getElementById('gxr2');
  var nearK = null;
  function strikeNear(price) {
    var best = null, bd = 1e9;
    for (var i = 0; i < D.strikes.length; i++) {
      var d = Math.abs(D.strikes[i][0] - price);
      if (d < bd) { bd = d; best = D.strikes[i]; }
    }
    return best;
  }
  function showBar(b) {
    if (!b) return;
    var up = b.close >= b.open, col = up ? UP : DN;
    rd1.innerHTML = '<span class="dim">' + fmt(b.time, mode !== 0) + '</span>　開 <b>' + b.open.toLocaleString() + '</b>　高 <b>' + b.high.toLocaleString() +
      '</b>　低 <b>' + b.low.toLocaleString() + '</b>　收 <b style="color:' + col + '">' + b.close.toLocaleString() + '</b>';
  }
  function showStrike(s) {
    if (!s) { rd2.innerHTML = '&nbsp;'; return; }
    var pos = s[1] > 0, col = pos ? C.pos : C.neg;
    rd2.innerHTML = '<b>' + s[0].toLocaleString() + '</b>　<span style="color:' + col + '">' + (pos ? '避震器' : '油門') + ' ' + (s[1] > 0 ? '+' : '') + s[1].toFixed(2) +
      ' 億</span>　<span class="dim">買權 ' + s[2].toLocaleString() + ' 口 ／ 賣權 ' + s[3].toLocaleString() + ' 口</span>';
  }
  var defStrike = strikeNear(D.spot);
  chart.subscribeCrosshairMove(function (p) {
    if (!p.point || !p.time) { nearK = null; showBar(bars[bars.length - 1]); showStrike(defStrike); return; }
    var b = p.seriesData.get(series);
    if (b) showBar({ time: p.time, open: b.open, high: b.high, low: b.low, close: b.close });
    var price = series.coordinateToPrice(p.point.y);
    var s = price == null ? null : strikeNear(price);
    nearK = s ? s[0] : null;
    showStrike(s);
  });

  // ───── 右側各履約價 GEX 長條（canvas）─────
  var cv = document.getElementById('gxs'), ctx = cv.getContext('2d');
  var maxAbs = 0;
  D.strikes.forEach(function (s) { if (Math.abs(s[1]) > maxAbs) maxAbs = Math.abs(s[1]); });
  maxAbs = maxAbs || 1;
  function draw() {
    var dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var cx = Math.round(w * 0.5), plotH = h - 26, half = w * 0.5 - 4;
    ctx.strokeStyle = '#16304A'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(cx + .5, 0); ctx.lineTo(cx + .5, plotH); ctx.stroke();
    ctx.font = '10px ' + MONO; ctx.textBaseline = 'middle';
    ctx.fillStyle = C.neg; ctx.textAlign = 'left'; ctx.fillText('◀ 油門', 3, 8);
    ctx.fillStyle = C.pos; ctx.textAlign = 'right'; ctx.fillText('避震器 ▶', w - 3, 8);
    for (var i = 0; i < D.strikes.length; i++) {
      var s = D.strikes[i], y = series.priceToCoordinate(s[0]);
      if (y == null || y < 14 || y > plotH) continue;
      var y2 = series.priceToCoordinate(s[0] + 50), th = y2 == null ? 4 : Math.max(2, Math.abs(y2 - y) * 0.78);
      var len = Math.max(1, Math.abs(s[1]) / maxAbs * half);
      ctx.globalAlpha = (nearK === s[0]) ? 1 : 0.78;
      ctx.fillStyle = s[1] >= 0 ? C.pos : C.neg;
      ctx.fillRect(s[1] >= 0 ? cx + 1 : cx - len, y - th / 2, len, th);
    }
    ctx.globalAlpha = 1;
    [[D.call_wall, C.pos, '買權牆'], [D.put_wall, C.neg, '賣權牆']].forEach(function (a) {
      var y = series.priceToCoordinate(a[0]);
      if (y == null || y < 14 || y > plotH) return;
      ctx.fillStyle = a[1]; ctx.textAlign = a[0] === D.call_wall ? 'right' : 'left';
      ctx.fillText(a[0].toLocaleString() + ' ' + a[2], a[0] === D.call_wall ? w - 3 : 3, y - 9);
    });
  }
  var key = '';
  (function loop() {
    var a = series.priceToCoordinate(D.spot), b = series.priceToCoordinate(D.spot + 1000);
    var k = a + '|' + b + '|' + cv.clientWidth + '|' + cv.clientHeight + '|' + nearK;
    if (k !== key) { key = k; draw(); }
    requestAnimationFrame(loop);
  })();

  document.getElementById('gxbtn').addEventListener('click', function (e) {
    var n = e.target.getAttribute && e.target.getAttribute('data-n');
    if (n !== null && n !== undefined) setMode(+n);
  });
  showStrike(defStrike);
  setMode(30);
})();
