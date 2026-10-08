/* GEX 頁「進階」：到期日×履約價的熱力圖與 3D 曲面（Plotly，展開才載入）。
   到期日標籤直接寫在軸上（10/12（一）週選 …），滑鼠移上去會顯示「到期日／履約價／數值」。 */
(function () {
  var D = window.GEXDATA, M = D && D.matrix;
  var det = document.getElementById('gx3dwrap');
  if (!M || !det) return;
  var C = D.colors, loaded = false, cur = 'heat';
  var MONO = "'IBM Plex Mono',ui-monospace,monospace";
  var ex = M.expiries, yIdx = ex.map(function (_, i) { return i; });
  function sumRows(a, b) { return a.map(function (r, i) { return r.map(function (v, j) { return v + b[i][j]; }); }); }
  var oiAll = sumRows(M.oi_call, M.oi_put);
  var zmax = 0;
  M.gex.forEach(function (r) { r.forEach(function (v) { if (Math.abs(v) > zmax) zmax = Math.abs(v); }); });
  var DIV = [[0, C.neg], [0.5, '#1F4E6E'], [1, C.pos]];
  var LIN = function (c) { return [[0, '#16304A'], [1, c]]; };

  var spec = {
    heat: { title: 'GEX', unit: '億', z: M.gex, cs: DIV, sym: true, kind: 'heatmap' },
    gex: { title: 'GEX', unit: '億', z: M.gex, cs: DIV, sym: true, kind: 'surface' },
    oi: { title: '未平倉', unit: '口', z: oiAll, cs: LIN(C.pos), sym: false, kind: 'surface' },
    iv: { title: '隱含波動率', unit: '%', z: M.iv, cs: LIN(C.flip), sym: false, kind: 'surface' }
  };
  function render() {
    var s = spec[cur], el = document.getElementById('gx3d');
    if (!el.getAttribute('data-ready')) { el.textContent = ''; el.setAttribute('data-ready', '1'); }
    var cd = ex.map(function (l) { return M.strikes.map(function () { return l; }); });
    var tr = {
      type: s.kind, x: M.strikes, y: s.kind === 'heatmap' ? ex : yIdx, z: s.z, colorscale: s.cs, customdata: cd,
      hovertemplate: '到期 %{customdata}<br>履約價 %{x:,.0f}<br>' + s.title + ' %{z:,.2f} ' + s.unit + '<extra></extra>',
      connectgaps: true, colorbar: { thickness: 10, len: 0.8, tickfont: { color: '#9DB0C8', size: 10 }, title: { text: s.unit, font: { color: '#9DB0C8', size: 10 } } }
    };
    if (s.sym) { tr.zmin = -zmax; tr.zmax = zmax; tr.zmid = 0; }
    var font = { color: '#9DB0C8', family: MONO, size: 11 };
    var ax = { color: '#9DB0C8', gridcolor: '#16304A', zerolinecolor: '#2B4C6F', backgroundcolor: 'rgba(0,0,0,0)' };
    var layout = {
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: font, margin: { l: 10, r: 10, t: 10, b: 10 }, height: 480
    };
    if (s.kind === 'heatmap') {
      layout.margin = { l: 130, r: 10, t: 10, b: 50 }; layout.height = 360;
      layout.xaxis = { title: '履約價', gridcolor: '#16304A', color: '#9DB0C8' };
      layout.yaxis = { autorange: 'reversed', color: '#9DB0C8' };
    } else {
      layout.scene = {
        xaxis: Object.assign({ title: '履約價' }, ax),
        yaxis: Object.assign({ title: '到期日', tickvals: yIdx, ticktext: ex, autorange: 'reversed' }, ax),
        zaxis: Object.assign({ title: s.title + '（' + s.unit + '）' }, ax),
        camera: { eye: { x: 1.7, y: -1.7, z: 0.9 } }, aspectratio: { x: 1.8, y: 1.2, z: 0.8 }
      };
    }
    window.Plotly.react(el, [tr], layout, { displayModeBar: false, responsive: true });
  }
  function ensure(cb) {
    if (window.Plotly) return cb();
    var sc = document.createElement('script');
    sc.src = 'https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js';
    sc.onload = cb;
    sc.onerror = function () { document.getElementById('gx3d').textContent = '圖表函式庫載入失敗，請重新整理'; };
    document.head.appendChild(sc);
  }
  function go() { ensure(function () { loaded = true; render(); }); }
  det.addEventListener('toggle', function () { if (det.open && !loaded) go(); });
  document.getElementById('gx3dbtn').addEventListener('click', function (e) {
    var k = e.target.getAttribute && e.target.getAttribute('data-k');
    if (!k) return;
    cur = k;
    var bs = document.querySelectorAll('#gx3dbtn button');
    for (var i = 0; i < bs.length; i++) bs[i].setAttribute('aria-pressed', String(bs[i].getAttribute('data-k') === k));
    if (loaded) render(); else go();
  });
})();
