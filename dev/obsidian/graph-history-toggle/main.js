/* Obsidian のプラグイン: グラフを「いつもの見え方」と「すべてのファイル」でボタン 1 つで切り替える。
   すべてのファイル = 絞り込みの条件を外し、md 以外(html・画像など)も出す。いつもの見え方 = 押す前の条件と設定に戻す。
   ビルドなしの CommonJS。dev/plan_artifact.py --graph が保管庫の根の .obsidian/plugins/ へ写す。
   開いているグラフへの反映は Obsidian の非公開の口(dataEngine)を使う = Obsidian の更新で効かなくなったら、ここを直す */
const { Plugin, Notice } = require("obsidian");

// いつもの見え方の既定 = 経緯(状態が 済み・置き換え済み・取り下げ)を隠す。dev/plan_artifact.py の GRAPH_HIDE と同じ
const HIDE = "-[状態:済み] -[状態:置き換え済み] -[状態:取り下げ]";
// 前に dev/plan_artifact.py が入れていた「フォルダで隠す」条件。見つけたら HIDE に置き換える
const OLD = [
  /-path:"[^"]*\/docs\/worklog"\s+-path:"[^"]*\/docs\/design\/surveys"\s+-file:WORKLOG/,
  /-path:"[^"]*\/docs\/worklog"\s+-path:"[^"]*\/docs\/design"\s+-path:"[^"]*\/plan\/done"\s+-file:WORKLOG/,
  /-path:"[^"]*\/docs\/worklog"\s+-\(path:"[^"]*\/docs\/design"\s+-path:"[^"]*\/docs\/design\/reviews"\)\s+-path:"[^"]*\/plan\/done"\s+-file:WORKLOG/,
];

function migrate(search) {
  let s = search;
  for (const re of OLD) s = s.replace(re, HIDE);
  return s;
}

module.exports = class GraphAllToggle extends Plugin {
  async onload() {
    this.state = Object.assign({ all: false, search: HIDE, attachments: false }, await this.loadData());
    this.addRibbonIcon("layers", "グラフ: すべてのファイル / いつもの見え方", () => this.toggle());
    this.addCommand({ id: "toggle", name: "グラフ: すべてのファイル / いつもの見え方を切り替える", callback: () => this.toggle() });
    this.app.workspace.onLayoutReady(() => {
      const o = this.current();
      const s = migrate(o.search);
      if (!this.state.all && s !== o.search) this.set({ search: s });
    });
  }

  graph() {
    const p = this.app.internalPlugins && this.app.internalPlugins.getPluginById && this.app.internalPlugins.getPluginById("graph");
    return p && p.instance;
  }

  leaves() {
    return this.app.workspace.getLeavesOfType("graph");
  }

  current() {
    for (const leaf of this.leaves()) {
      const e = leaf.view && leaf.view.dataEngine;
      const o = e && e.getOptions && e.getOptions();
      if (o && typeof o.search === "string") return { search: o.search, attachments: !!o.showAttachments };
    }
    const g = this.graph();
    const o = (g && g.options) || {};
    return { search: typeof o.search === "string" ? o.search : "", attachments: !!o.showAttachments };
  }

  async toggle() {
    let n;
    if (this.state.all) {
      n = this.set({ search: this.state.search, showAttachments: this.state.attachments });
      this.state.all = false;
      new Notice("いつもの見え方に戻しました" + (n ? "" : "(グラフを開くと効きます)"));
    } else {
      const o = this.current();
      this.state.search = migrate(o.search);
      this.state.attachments = o.attachments;
      n = this.set({ search: "", showAttachments: true });
      this.state.all = true;
      new Notice("すべてのファイルを表示しました" + (n ? "" : "(グラフを開くと効きます)"));
    }
    await this.saveData(this.state);
  }

  /* 開いているグラフと、次に開くグラフ(graph.json)の両方に opts を当てる。当てられたグラフの数を返す */
  set(opts) {
    let n = 0;
    for (const leaf of this.leaves()) if (this.apply(leaf, opts)) n++;
    const g = this.graph();
    if (g && g.options) {
      Object.assign(g.options, opts);
      if (g.saveOptions) g.saveOptions();
    }
    return n;
  }

  apply(leaf, opts) {
    const e = leaf.view && leaf.view.dataEngine;
    if (!e) return false;
    try {
      if (e.getOptions && e.setOptions) {
        e.setOptions(Object.assign(e.getOptions(), opts));
        return true;
      }
    } catch (err) { console.error("graph-history-toggle", err); }
    try {
      const s = e.filterOptions && e.filterOptions.search;
      if (s && s.setValue && "search" in opts) {
        s.setValue(opts.search);
        if (e.requestUpdateSearch) e.requestUpdateSearch();
        return true;
      }
    } catch (err) { console.error("graph-history-toggle", err); }
    return false;
  }
};
