/* Boss直聘 沟通页候选人收集器（页面内运行版）
 *
 * 为什么是页面内脚本：调试器接管的方案已被实验证实会被平台反自动化杀掉标签页
 * （2026-09-01）。页面内脚本就是网页自身的一部分，不存在那个检测面。
 *
 * 只做三件事：点会话、读文字、导出 CSV。不发请求、不改页面数据、不上传任何东西。
 */
(function () {
  "use strict";

  var VER = "v24";

  if (window.__bossPicker) {
    window.__bossPicker.show();
    return;
  }

  var CFG = {
    listSel: [".user-list", "[class*='user-list']", ".chat-list"],
    itemSel: ["[role='listitem']", "[class*='geek-item-wrap']"],
    nameSel: [".geek-name", "[class*='geek-name']"],
    jobSel: [".source-job", "[class*='source-job']"],
    sumSel: [".push-text", "[class*='push-text']"],
    timeSel: [".time", "[class*='time']"],
    /* 右侧整块。顶部那行"29岁 本科 期望…"不一定在 chat-conversation 里，
       所以从大往小找，谁的文字里有候选人信息就用谁。 */
    panelSel: [
      "[class*='chat-conversation']",
      "[class*='conversation-main']",
      "[class*='chat-content']",
      "[class*='geek-card']",
      "[class*='resume']",
    ],
    /* 三档速度。默认「慢」——被平台标记过之后，宁可慢也不要再触发。
       长休是 Python 版就有的机制，移植成书签时漏掉了，导致连续不断点击。 */
    speeds: {
      slow:   { min: 5000, max: 9000, every: 20, restMin: 120000, restMax: 300000, label: "慢速（推荐）" },
      normal: { min: 3000, max: 6000, every: 30, restMin: 60000,  restMax: 150000, label: "中速" },
      fast:   { min: 1500, max: 3000, every: 40, restMin: 30000,  restMax: 60000,  label: "快速（易被限制）" },
    },
    speedKey: "bossPickerSpeed",
    renderTimeout: 8000,
    scrollPause: 1200,
    scrollTries: 6,
    storeKey: "bossPickerRows",
  };

  var COLS = [
    "序号", "姓名", "年龄", "工作年限", "学历", "学校", "专业",
    "最近公司", "最近职位", "期望城市", "期望职位", "期望薪资",
    "沟通职位", "自我介绍", "有附件简历", "最后消息时间",
  ];

  var RE = {
    age: /(\d{1,2})\s*岁/,
    years: /(?<!\d)(\d{1,2})\s*年(?:工作经验|经验)?/,
    edu: /(博士|硕士|本科|大专|高中|中专|初中)/,
    salary: /(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk](?:\s*[·・]\s*\d+薪)?)/,
    expect: /(?:期望)\s*[:：]?\s*([^·・|\s\n]{2,12})\s*[·・|]\s*([^\n]*?)\s+(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*[Kk][^\s\n]*)/,
    comm: /(?:沟通职位)\s*[:：]?\s*([^\n]+)/,
    edu2: /([一-鿿A-Za-z()（）·\-]{2,40}(?:大学|学院|学校))\s*[·・|]\s*([^\n·・|]{1,30})/,
    /* 工作/教育都是"A · B"行。不靠关键词猜公司名（"艾迪咨询"这种会漏），
       改成取第一条 A 不是学校的行——实测三个真实档案都命中。 */
    pair: /^\s*([^\n·・|]{2,40})\s*[·・|]\s*([^\n]{1,60})$/gm,
    school: /([一-鿿A-Za-z()（）·\-]{2,40}(?:大学|学院|学校))/,
    time: /((?:今天|昨天)?\s*\d{1,2}:\d{2}|\d{1,2}月\d{1,2}日)/,
  };

  function q(root, sels) {
    for (var i = 0; i < sels.length; i++) {
      var el = root.querySelector(sels[i]);
      if (el) return el;
    }
    return null;
  }
  function qa(root, sels) {
    for (var i = 0; i < sels.length; i++) {
      var els = root.querySelectorAll(sels[i]);
      if (els.length) return Array.prototype.slice.call(els);
    }
    return [];
  }
  function txt(el) {
    return el ? (el.innerText || "").replace(/\s+/g, " ").trim() : "";
  }
  function pick(re, s, i) {
    var m = re.exec(s || "");
    return m ? (m[i || 1] || "").replace(/\s+/g, " ").trim() : "";
  }
  function sleep(ms) {
    return new Promise(function (r) { setTimeout(r, ms); });
  }
  function prof() { return CFG.speeds[speed]; }

  function rndWait() {
    var p = prof();
    return (p.min + Math.random() * (p.max - p.min)) * slowFactor;
  }

  function noteResult(ok) {
    /* 自适应：连续失败就成倍放慢并延长休息；连续成功再慢慢恢复。
       让脚本自己贴合这个站点当下的容忍度，不用人去猜数字。 */
    if (ok) {
      failStreak = 0;
      okStreak++;
      if (okStreak >= 12 && slowFactor > 1) {
        slowFactor = Math.max(1, slowFactor / 1.5);
        okStreak = 0;
      }
    } else {
      okStreak = 0;
      failStreak++;
      if (failStreak >= 2) {
        slowFactor = Math.min(8, slowFactor * 2);
        failStreak = 0;
        return true;   /* 需要立刻长休 */
      }
    }
    return false;
  }

  async function longRest(reason) {
    var p = prof();
    var ms = (p.restMin + Math.random() * (p.restMax - p.restMin)) * slowFactor;
    var until = Date.now() + ms;
    while (Date.now() < until && !stopped) {
      var left = Math.ceil((until - Date.now()) / 1000);
      say(reason + "，休息 " + left + " 秒（已收集 " + rows.length + " 人）");
      await sleep(1000);
    }
  }

  /* ---------- 状态 ---------- */
  var rows = [];
  var seen = {};
  var stopped = false;
  var running = false;
  var lastFail = "";
  var lastFingerprint = "";
  var speed = "slow";
  try { speed = localStorage.getItem(CFG.speedKey) || "slow"; } catch (e) {}
  if (!CFG.speeds[speed]) speed = "slow";
  var slowFactor = 1;      /* 自适应退避倍数 */
  var okStreak = 0;
  var failStreak = 0;
  var restCounter = 0;

  try {
    var saved = JSON.parse(localStorage.getItem(CFG.storeKey) || "[]");
    if (saved.length) {
      rows = saved;
      saved.forEach(function (r) { seen[r.__key] = 1; });
    }
  } catch (e) {}

  function save() {
    try { localStorage.setItem(CFG.storeKey, JSON.stringify(rows)); } catch (e) {}
  }

  /* ---------- 界面 ---------- */
  var box = document.createElement("div");
  box.style.cssText =
    "position:fixed;right:16px;bottom:16px;z-index:2147483647;width:290px;" +
    "background:#fff;border:1px solid #d8dde6;border-radius:10px;padding:14px;" +
    "box-shadow:0 8px 28px rgba(0,0,0,.18);font:13px/1.6 system-ui,sans-serif;color:#1b2733";
  box.innerHTML =
    '<div style="font-weight:600;margin-bottom:8px">候选人收集器 <span style="font-weight:400;color:#8b97a6;font-size:11px">v2</span></div>' +
    '<div id="bp-msg" style="min-height:44px;color:#4a5866">准备就绪。请确认左侧能看到候选人列表。</div>' +
    '<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">' +
    '<button id="bp-go" style="flex:1;padding:7px 0;border:0;border-radius:6px;background:#00bebd;color:#fff;font-weight:600;cursor:pointer">开始</button>' +
    '<button id="bp-stop" style="flex:1;padding:7px 0;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">停止</button>' +
    '</div>' +
    '<div style="margin-top:10px;display:flex;align-items:center;gap:8px">' +
    '<span style="color:#8b97a6;font-size:12px;white-space:nowrap">速度</span>' +
    '<select id="bp-speed" style="flex:1;padding:5px;border:1px solid #d8dde6;border-radius:6px;background:#fff;font-size:12px"></select>' +
    '</div>' +
    '<div style="margin-top:8px;display:flex;gap:8px">' +
    '<button id="bp-csv" style="flex:1;padding:7px 0;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">导出表格</button>' +
    '<button id="bp-diag" style="padding:7px 10px;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">诊断</button>' +
    '<button id="bp-clr" style="padding:7px 10px;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">清空</button>' +
    '</div>';
  document.body.appendChild(box);

  var speedEl = box.querySelector("#bp-speed");
  Object.keys(CFG.speeds).forEach(function (k) {
    var o = document.createElement("option");
    o.value = k;
    o.textContent = CFG.speeds[k].label;
    if (k === speed) o.selected = true;
    speedEl.appendChild(o);
  });
  speedEl.onchange = function () {
    speed = speedEl.value;
    slowFactor = 1;
    try { localStorage.setItem(CFG.speedKey, speed); } catch (e) {}
    stat();
  };

  var msgEl = box.querySelector("#bp-msg");
  function say(s) { msgEl.textContent = s; }
  function stat() {
    var p = prof();
    var per = ((p.min + p.max) / 2 / 1000) * slowFactor;
    var tempo = per.toFixed(0) + " 秒/人" + (slowFactor > 1 ? "（已自动放慢 " + slowFactor + " 倍）" : "");
    say(
      "已收集 " + rows.length + " 人" + (running ? "，正在继续……" : "。") +
      "\n节奏：" + tempo
    );
  }
  stat();

  /* ---------- 抓取 ---------- */
  function listEl() { return q(document, CFG.listSel); }

  function items() {
    var list = listEl();
    if (!list) return [];
    return qa(list, CFG.itemSel).filter(function (el) { return el.offsetParent !== null; });
  }

  function keyOf(el) {
    return (
      el.getAttribute("key") ||
      el.getAttribute("data-id") ||
      txt(q(el, CFG.nameSel)) + "|" + txt(q(el, CFG.timeSel))
    );
  }

  function panelRoot() {
    /* 关键：容器绝不能包含左侧会话列表。
       之前取得太宽，把整页都圈了进去，导致每个人都解析到同一段文字——
       CSV 里姓名在变、其余字段全同，就是这个 bug（2026-09-02）。 */
    var list = listEl();
    for (var i = 0; i < CFG.panelSel.length; i++) {
      var els = document.querySelectorAll(CFG.panelSel[i]);
      for (var j = 0; j < els.length; j++) {
        var el = els[j];
        if (el.offsetParent === null) continue;
        if (list && (el.contains(list) || el === list)) continue;
        if ((el.innerText || "").trim().length < 10) continue;
        return el;
      }
    }
    return null;
  }

  function panelText() {
    var root = panelRoot();
    return root ? (root.innerText || "").trim() : "";
  }

  function parsePanel(t) {
    var r = {};
    r["年龄"] = pick(RE.age, t);
    var y = pick(RE.years, t);
    r["工作年限"] = y ? y + "年" : "";
    r["学历"] = pick(RE.edu, t);
    r["期望薪资"] = pick(RE.salary, t).replace(/\s/g, "");
    r["沟通职位"] = pick(RE.comm, t);

    var m = RE.expect.exec(t);
    if (m) {
      r["期望城市"] = (m[1] || "").trim();
      r["期望职位"] = (m[2] || "").trim();
      r["期望薪资"] = (m[3] || "").replace(/\s/g, "");
    }
    var e = RE.edu2.exec(t);
    if (e) { r["学校"] = e[1].trim(); r["专业"] = e[2].trim(); }
    else { r["学校"] = pick(RE.school, t); }

    RE.pair.lastIndex = 0;
    var pm;
    while ((pm = RE.pair.exec(t)) !== null) {
      var left = pm[1].trim();
      if (/(大学|学院|学校)$/.test(left)) continue;   // 教育经历行，跳过
      if (/^(期望|沟通职位)/.test(left)) continue;     // 期望行，跳过
      /* 行首常带"2024.05-至今"这类日期，去掉后才是公司名 */
      r["最近公司"] = left.replace(/^\s*\d{4}[.\-/年]?\d{0,2}(?:\s*[-–—]\s*|\s*至\s*)(?:至今|今|\d{4}[.\-/年]?\d{0,2})?\s*/, "").trim();
      r["最近职位"] = pm[2].trim().split(/\s*[·・|]\s*/)[0];
      break;
    }

    r["有附件简历"] = /附件简历|\.pdf/i.test(t) ? "是" : "否";
    return r;
  }

  function firstMessage() {
    var nodes = document.querySelectorAll(
      "[class*='message-item'] [class*='text'],[class*='item-friend'] [class*='text']"
    );
    for (var i = 0; i < nodes.length; i++) {
      var s = txt(nodes[i]);
      if (s && s.length > 4) return s.slice(0, 300);
    }
    return "";
  }

  async function waitPanel(prev, name) {
    /* 判据是"面板里出现了这个人的名字"。
       不能用"文字变了"：当前已选中的那个人点了不会变，会被误判成失败
       （2026-09-01 实测第一个人永远抓不到）。 */
    var t0 = Date.now();
    while (Date.now() - t0 < CFG.renderTimeout) {
      var t = panelText();
      if (t && name && t.indexOf(name) !== -1 && t.length > 20) return t;
      if (t && !name && t !== prev) return t;
      await sleep(250);
    }
    return panelText();
  }


  function fireMouse(target, type, x, y) {
    var opts = {
      bubbles: true, cancelable: true, view: window,
      clientX: x, clientY: y, button: 0, buttons: type === "mousedown" ? 1 : 0,
    };
    try {
      target.dispatchEvent(
        type.indexOf("pointer") === 0
          ? new PointerEvent(type, Object.assign({ pointerId: 1, isPrimary: true }, opts))
          : new MouseEvent(type, opts)
      );
    } catch (e) {}
  }

  function clickLikeUser(el) {
    /* 只 dispatch 一个不带坐标的 click 是不够的——很多前端框架在
       pointerdown/mousedown 阶段就决定切换，且会读事件坐标。
       所以按真实鼠标的完整序列来，并且点"该点上真正最顶层的那个元素"。 */
    var rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    var x = Math.round(rect.left + rect.width / 2);
    var y = Math.round(rect.top + rect.height / 2);

    var target = document.elementFromPoint(x, y);
    if (!target || !el.contains(target)) target = el;

    ["pointerover", "mouseover", "pointermove", "mousemove",
     "pointerdown", "mousedown", "pointerup", "mouseup", "click"]
      .forEach(function (type) { fireMouse(target, type, x, y); });

    try { target.click(); } catch (e) {}
    return true;
  }

  async function grabOne(el) {
    var myKey = keyOf(el);
    var name = txt(q(el, CFG.nameSel));
    var job = txt(q(el, CFG.jobSel));
    var time = txt(q(el, CFG.timeSel));
    var prev = panelText();

    el.scrollIntoView({ block: "center" });
    await sleep(350);

    /* 虚拟列表会回收 DOM 节点：滚动之后手里这个元素可能已经换人了，
       必须按 key 重新定位一次再点（2026-09-02 数据串行的成因之一）。 */
    var fresh = null;
    var all = items();
    for (var ai = 0; ai < all.length; ai++) {
      if (keyOf(all[ai]) === myKey) { fresh = all[ai]; break; }
    }
    if (fresh) el = fresh;

    if (!clickLikeUser(el)) {
      lastFail = "点不动：" + (name || "?");
      return null;
    }

    /* 等这一条真的变成"选中"，说明页面确实切过去了 */
    var t0 = Date.now();
    while (Date.now() - t0 < 3000) {
      var cls = (el.getAttribute("class") || "") + " " +
                ((el.firstElementChild && el.firstElementChild.getAttribute("class")) || "");
      if (/selected|active|current/i.test(cls)) break;
      await sleep(150);
    }

    var t = await waitPanel(prev, name);
    if (!t || (name && t.indexOf(name) === -1)) {
      lastFail =
        "读取失败：面板里没出现『" + (name || "?") + "』｜面板字数 " +
        (t || "").length + "｜开头：" + (t || "").slice(0, 60).replace(/\n/g, " ");
      return null;
    }

    var row = parsePanel(t);
    /* 指纹相同 = 右侧根本没换人，宁可记失败也不写错数据 */
    var fp = [row["年龄"], row["学校"], row["最近公司"], row["期望薪资"], row["专业"]].join("|");
    if (fp !== "||||" && fp === lastFingerprint) {
      await sleep(1200);
      t = panelText();
      row = parsePanel(t);
      fp = [row["年龄"], row["学校"], row["最近公司"], row["期望薪资"], row["专业"]].join("|");
      if (fp === lastFingerprint) {
        lastFail = "跳过 " + name + "：右侧详情没有切换（与上一个人完全相同）";
        return null;
      }
    }
    lastFingerprint = fp;
    row["姓名"] = name || "";
    row["沟通职位"] = row["沟通职位"] || job;
    row["最后消息时间"] = time;
    row["自我介绍"] = firstMessage();
    return row;
  }

  async function loop() {
    if (running) return;
    if (!listEl()) { say("没找到候选人列表。请先点左侧「沟通」，看到列表后再开始。"); return; }
    running = true; stopped = false;
    var dry = 0;

    while (!stopped) {
      var list = items();
      var next = null;
      for (var i = 0; i < list.length; i++) {
        if (!seen[keyOf(list[i])]) { next = list[i]; break; }
      }

      if (next) {
        dry = 0;
        var k = keyOf(next);
        seen[k] = 1;
        try {
          say("正在读取：" + (txt(q(next, CFG.nameSel)) || "?") + "（已收集 " + rows.length + " 人）");
          var row = await grabOne(next);
          if (row && row["姓名"]) {
            row.__key = k;
            row["序号"] = String(rows.length + 1);
            rows.push(row);
            save();
          }
        } catch (err) {
          lastFail = "异常：" + (err && err.message ? err.message : String(err));
        }
        var gotOne = !!(row && row["姓名"]);
        var needRest = noteResult(gotOne);
        if (lastFail && !gotOne) say(lastFail);
        else stat();

        if (needRest) {
          await longRest("连续失败，自动放慢");
        } else if (gotOne && ++restCounter % prof().every === 0) {
          await longRest("已抓 " + rows.length + " 人，例行休息");
        } else {
          await sleep(rndWait());
        }
        continue;
      }

      // 当前可见的都抓完了，往下滚动加载更多
      var box2 = listEl();
      if (!box2) break;
      var before = box2.scrollTop;
      box2.scrollTop = Math.min(box2.scrollTop + box2.clientHeight * 0.85, box2.scrollHeight);
      await sleep(CFG.scrollPause);
      var grew = items().some(function (el) { return !seen[keyOf(el)]; });
      if (!grew && box2.scrollTop <= before + 2) dry++; else dry = 0;
      if (dry >= CFG.scrollTries) break;
    }

    running = false;
    say("完成：共 " + rows.length + " 人。点「导出表格」下载。");
  }

  /* ---------- 导出 ---------- */
  function csv() {
    var out = [COLS.join(",")];
    rows.forEach(function (r) {
      out.push(
        COLS.map(function (c) {
          var v = (r[c] == null ? "" : String(r[c])).replace(/"/g, '""');
          return '"' + v + '"';
        }).join(",")
      );
    });
    return "﻿" + out.join("\r\n");
  }

  function download() {
    if (!rows.length) { say("还没有数据。"); return; }
    var blob = new Blob([csv()], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "候选人.csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    say("已下载 候选人.csv（" + rows.length + " 人）");
  }

  box.querySelector("#bp-go").onclick = function () { loop(); };
  box.querySelector("#bp-stop").onclick = function () { stopped = true; say("已停止。已收集 " + rows.length + " 人。"); };
  box.querySelector("#bp-csv").onclick = download;
  box.querySelector("#bp-diag").onclick = function () {
    var list = listEl();
    var its = items();
    var first = its[0];
    var pt = panelText();
    var info =
      VER +
      " ｜列表容器:" + (list ? "有" : "无") +
      " ｜可见条目:" + its.length +
      " ｜首条姓名:" + (first ? txt(q(first, CFG.nameSel)) || "(空)" : "-") +
      " ｜首条key:" + (first ? String(keyOf(first)).slice(0, 20) : "-") +
      " ｜面板字数:" + pt.length +
      " ｜面板开头:" + pt.slice(0, 80).replace(/\n/g, " ") +
      " ｜上次失败:" + (lastFail || "无");
    say(info);
    try { navigator.clipboard.writeText(info); } catch (e) {}
  };
  box.querySelector("#bp-clr").onclick = function () {
    if (!confirm("清空已收集的 " + rows.length + " 人？")) return;
    rows = []; seen = {}; save(); stat();
  };

  window.__bossPicker = {
    show: function () { box.style.display = "block"; },
    rows: function () { return rows; },
  };
})();
