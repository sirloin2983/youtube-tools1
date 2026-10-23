/* 友人のアプリの配色: ピンク(ui-kit のシンセウェーブ = 暗い・data-palette=synth)に固定する(配色 4 つの切り替えは 10-24 に無くした)。
   色は ui-kit のトークン(--bg・--panel・--ink・--accent など)だけ = 送る・受け取る・再生・設定・初回の準備・説明の全部が同じ変数を読む。
   ui-kit.js の直後に <script src="palette.js"></script>(defer なし)で読む = 描く前に色を決める(ちらつかない)。
   前に選んだ配色(友人の PC の <玄関>/palette.json)は読まない = 残っていてもピンクで出る */
(function () {
  'use strict';
  if (!window.UIKit || !UIKit.theme) return;
  UIKit.theme.palette('synth');
  var audit = false;   /* dev/ui_audit.py が明るい・暗いを自分で決めて確かめるとき(localStorage の ytt:palette-audit)は、明るい・暗いを変えない */
  try { audit = localStorage.getItem('ytt:palette-audit') === '1'; } catch (e) { audit = false; }
  if (!audit) UIKit.theme.set('dark');
})();
