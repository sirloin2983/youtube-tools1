/* 見本のパターンの切り替え(?p=hud など)。見た目は patterns.css の html[data-pattern=…] */
(function () {
  'use strict';
  var NAMES = {
    hud: ['A 計器盤(HUD)', '細い線・角の括弧・目盛り。編集機材のモニターのような、静かで情報が主役の形'],
    terminal: ['B ターミナル', '全部を等幅の文字で。枠は破線、ボタンは [ ] 。コンソールの画面'],
    neon: ['C ネオン管', '丸い形と光る輪郭。配信の待機画面のような、やわらかく発光する形'],
    armor: ['D 装甲パネル', '角を斜めに切った板と太い帯。メカの操作盤のような、強く重い形'],
    blueprint: ['E 設計図', '方眼の地に、塗りのない線だけの部品。角に十字の印'],
    base: ['今の見た目(比べる用)', '今の ui-kit の暗いテーマ(色だけ紺とシアンに替えたもの)']
  };
  var p = (/[?&]p=([a-z]+)/.exec(location.search) || [])[1] || 'hud';
  if (!NAMES[p]) p = 'hud';
  document.documentElement.setAttribute('data-pattern', p);
  document.documentElement.setAttribute('data-theme', 'dark');
  var PAL = { cyan: 'ネオンシアン', magenta: 'シンセウェーブ', green: 'ターミナルグリーン(調整後)', amber: '琥珀の CRT', red: '警戒の赤',
              violet: '電子の紫', steel: '鋼の白(調整後)', dual: '二色(シアン + マゼンタ)', ice: 'アイスライト(調整後)' };
  var c = (/[?&]c=([a-z]+)/.exec(location.search) || [])[1];
  if (c && PAL[c] && c !== 'cyan') document.documentElement.setAttribute('data-palette', c);
  NAMES[p] = [NAMES[p][0] + (c && PAL[c] ? ' × ' + PAL[c] : ''), NAMES[p][1]];
  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('pbName').textContent = NAMES[p][0];
    document.getElementById('pbNote').textContent = NAMES[p][1];
    if (window.UIKit && UIKit.appnav) UIKit.appnav.setVersion('v0.15.0');
    if (/[?&]focus=1/.test(location.search)) document.getElementById('pbFocus').focus();
  });
})();
