/* Obsidian のプラグイン: グラフで「経緯」= 状態が 済み・置き換え済み・取り下げ の文書の表示・非表示をボタン 1 つで切り替える(2026-10-13)。
   ビルドなしの CommonJS。dev/plan_artifact.py --graph が保管庫の根の .obsidian/plugins/ へ写す。
   グラフの絞り込みの欄に HIDE の条件を足す・外すだけ(ほかに書いた条件は残す)。
   開いているグラフへの反映は Obsidian の非公開の口(dataEngine)を使う = Obsidian の更新で効かなくなったら、ここを直す */
const { Plugin, Notice } = require("obsidian");

const HIDE = "-[状態:済み] -[状態:置き換え済み] -[状態:取り下げ]";
// 前に dev/plan_artifact.py が入れていた「フォルダで隠す」条件(これが残ると、ボタンを押しても経緯が出てこない)。見つけたら HIDE に置き換える
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

module.exports = class GraphHistoryToggle extends Plugin {
  async onload() {
    this.addRibbonIcon("history", "経緯(済んだ文書)の表示・非表示", () => this.toggle());
    this.addCommand({ id: "toggle", name: "経緯(済んだ文書)の表示・非表示を切り替える", callback: () => this.toggle() });
    this.app.workspace.onLayoutReady(() => this.migrateAll());
  }

  migrateAll() {
    const now = this.current();
    const next = migrate(now);
    if (next !== now) this.set(next);
  }

  set(query) {
    let n = 0;
    for (const leaf of this.leaves()) if (this.apply(leaf, query)) n++;
    const g = this.graph();   // 次に開くグラフも同じにする(graph.json)
    if (g && g.options) {
      g.options.search = query;
      if (g.saveOptions) g.saveOptions();
    }
    return n;
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
      if (o && typeof o.search === "string") return o.search;
    }
    const g = this.graph();
    return (g && g.options && typeof g.options.search === "string") ? g.options.search : "";
  }

  toggle() {
    const now = migrate(this.current());
    const wasHidden = now.includes(HIDE);
    const next = wasHidden ? now.replace(HIDE, "").replace(/\s+/g, " ").trim() : (now.trim() + " " + HIDE).trim();
    const n = this.set(next);
    new Notice((wasHidden ? "経緯を表示しました" : "経緯を隠しました") + (n ? "" : "(グラフを開くと効きます)"));
  }

  apply(leaf, query) {
    const e = leaf.view && leaf.view.dataEngine;
    if (!e) return false;
    try {
      if (e.getOptions && e.setOptions) {
        const o = e.getOptions();
        o.search = query;
        e.setOptions(o);
        return true;
      }
    } catch (err) { console.error("graph-history-toggle", err); }
    try {
      const s = e.filterOptions && e.filterOptions.search;
      if (s && s.setValue) {
        s.setValue(query);
        if (e.requestUpdateSearch) e.requestUpdateSearch();
        return true;
      }
    } catch (err) { console.error("graph-history-toggle", err); }
    return false;
  }
};
