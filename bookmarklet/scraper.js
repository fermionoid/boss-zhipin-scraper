/* Boss直聘 沟通页候选人收集器（页面内运行版）
 *
 * 为什么是页面内脚本：调试器接管的方案已被实验证实会被平台反自动化杀掉标签页
 * （2026-09-01）。页面内脚本就是网页自身的一部分，不存在那个检测面。
 *
 * 只做三件事：点会话、读文字、导出 CSV。不发请求、不改页面数据、不上传任何东西。
 */
(function () {
  "use strict";

  var VER = "v20";

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
    minWait: 1200,
    maxWait: 2600,
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
  function rndWait() {
    return CFG.minWait + Math.random() * (CFG.maxWait - CFG.minWait);
  }

  /* ---------- 状态 ---------- */
  var rows = [];
  var seen = {};
  var stopped = false;
  var running = false;
  var lastFail = "";

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
    '<div style="margin-top:8px;display:flex;gap:8px">' +
    '<button id="bp-csv" style="flex:1;padding:7px 0;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">导出表格</button>' +
    '<button id="bp-diag" style="padding:7px 10px;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">诊断</button>' +
    '<button id="bp-clr" style="padding:7px 10px;border:1px solid #d8dde6;border-radius:6px;background:#fff;cursor:pointer">清空</button>' +
    '</div>';
  document.body.appendChild(box);

  var msgEl = box.querySelector("#bp-msg");
  function say(s) { msgEl.textContent = s; }
  function stat() {
    say("已收集 " + rows.length + " 人" + (running ? "，正在继续……" : "。"));
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

  function panelText() {
    var parts = [];
    for (var i = 0; i < CFG.panelSel.length; i++) {
      var els = document.querySelectorAll(CFG.panelSel[i]);
      for (var j = 0; j < els.length && j < 3; j++) {
        var t = (els[j].innerText || "").trim();
        if (t && parts.indexOf(t) === -1) parts.push(t);
      }
    }
    return parts.join("\n");
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

  async function grabOne(el) {
    var name = txt(q(el, CFG.nameSel));
    var job = txt(q(el, CFG.jobSel));
    var time = txt(q(el, CFG.timeSel));
    var prev = panelText();

    el.scrollIntoView({ block: "center" });
    /* 点击处理函数挂在里层卡片上，点外层 [role=listitem] 可能不触发。
       从里往外找一个可点的目标，并派发会冒泡的真实鼠标事件。 */
    var target =
      el.querySelector("[class*='geek-item']") ||
      el.querySelector("[class*='figure']") ||
      q(el, CFG.nameSel) ||
      el;
    ["mousedown", "mouseup", "click"].forEach(function (type) {
      target.dispatchEvent(
        new MouseEvent(type, { bubbles: true, cancelable: true, view: window })
      );
    });
    var t = await waitPanel(prev, name);
    if (!t || (name && t.indexOf(name) === -1)) {
      lastFail =
        "读取失败：面板里没出现『" + (name || "?") + "』｜面板字数 " +
        (t || "").length + "｜开头：" + (t || "").slice(0, 60).replace(/\n/g, " ");
      return null;
    }

    var row = parsePanel(t);
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
        if (lastFail && !rows.length) say(lastFail);
        else stat();
        await sleep(rndWait());
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
