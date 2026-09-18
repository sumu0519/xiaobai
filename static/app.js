/* QQ 机器人控制台前端逻辑 */
const FIELDS = [
  "agnes_base_url", "agnes_model", "temperature", "max_tokens", "system_prompt",
  "max_reply_chars", "reply_private", "reply_group_at",
  "search_enabled", "search_max_results", "search_hints",
  "image_enabled", "image_model", "video_enabled", "video_model",
  "ws_host", "ws_port", "history_len", "history_ttl",
  "admin_qq", "rate_limit_per_min", "whitelist", "keyword_rules",
  "welcome_new_member", "welcome_text",
];
const SECRET_FIELDS = ["agnes_api_key", "tavily_api_key", "access_token"];

function toast(msg, type = "") {
  const box = document.getElementById("toast-box");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const resp = await fetch(path, opt);
  if (!resp.ok && resp.status !== 400) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function setField(id, v) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.type === "checkbox") el.checked = !!v;
  else el.value = v ?? "";
}

function getField(id) {
  const el = document.getElementById(id);
  if (!el) return undefined;
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number" || el.type === "range") return parseFloat(el.value) || 0;
  return el.value.trim();
}

async function loadConfig() {
  try {
    const { config: cfg } = await api("/api/config");
    FIELDS.forEach((f) => setField(f, cfg[f]));
    document.getElementById("agnes_key_masked").textContent = cfg.agnes_api_key_masked ? `已配置（…${cfg.agnes_api_key_masked.slice(-4)}）` : "未配置";
    document.getElementById("tavily_key_masked").textContent = cfg.tavily_api_key_masked ? `已配置（…${cfg.tavily_api_key_masked.slice(-4)}）` : "未配置";
    document.getElementById("token_masked").textContent = cfg.access_token ? "已配置" : "未配置";
  } catch (e) {
    toast("加载配置失败：" + e.message, "err");
  }
}

async function saveConfig() {
  const data = {};
  FIELDS.forEach((f) => (data[f] = getField(f)));
  SECRET_FIELDS.forEach((f) => (data[f] = getField(f) || "")); // 空 = 不修改
  try {
    const r = await api("/api/config", data);
    toast(r.ok ? "配置已保存并生效 ✅" : "保存失败", r.ok ? "ok" : "err");
    if (r.ok) loadConfig();
  } catch (e) {
    toast("保存失败：" + e.message, "err");
  }
}

async function resetConfig() {
  if (!confirm("确定恢复全部默认配置？API Key 也会被清除（回到 .env）。")) return;
  try {
    const r = await api("/api/config/reset", {});
    toast(r.ok ? "已恢复默认" : "重置失败", r.ok ? "ok" : "err");
    if (r.ok) { SECRET_FIELDS.forEach((f) => setField(f, "")); loadConfig(); }
  } catch (e) {
    toast("重置失败：" + e.message, "err");
  }
}

async function testAgnes() {
  toast("正在测试 AI 连接…");
  try {
    const r = await api("/api/test/agnes", {});
    toast(r.ok ? `AI 连接成功，回复：${r.message}` : `AI 连接失败：${r.message}`, r.ok ? "ok" : "err");
  } catch (e) { toast("测试失败：" + e.message, "err"); }
}

async function testTavily() {
  toast("正在测试 Tavily…");
  try {
    const r = await api("/api/test/tavily", {});
    toast(r.ok ? `Tavily 连接成功：${r.message}` : `Tavily 失败：${r.message}`, r.ok ? "ok" : "err");
  } catch (e) { toast("测试失败：" + e.message, "err"); }
}

async function testSend() {
  const qq = document.getElementById("test-qq").value.trim();
  if (!qq) return toast("请输入 QQ 号", "err");
  try {
    const r = await api("/api/test/send", { qq });
    toast(r.message, r.ok ? "ok" : "err");
  } catch (e) { toast("发送失败：" + e.message, "err"); }
}

async function testImage() {
  toast("正在测试图像模型（会真实生成一张图，约10-30秒）…");
  try {
    const r = await api("/api/test/image", {});
    toast(r.ok ? `图像模型正常 ✅ ${r.message}` : `图像模型失败：${r.message}`, r.ok ? "ok" : "err");
  } catch (e) { toast("测试失败：" + e.message, "err"); }
}

async function testVideo() {
  toast("正在测试视频模型（创建任务验证，约10秒）…");
  try {
    const r = await api("/api/test/video", {});
    toast(r.ok ? `视频模型正常 ✅ ${r.message}` : `视频模型失败：${r.message}`, r.ok ? "ok" : "err");
  } catch (e) { toast("测试失败：" + e.message, "err"); }
}

async function fetchModels() {
  toast("正在获取云端模型列表…");
  try {
    const r = await api("/api/models");
    if (!r.ok) return toast("获取失败：" + r.message, "err");
    const dl = document.getElementById("model-list");
    dl.innerHTML = "";
    r.models.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m;
      dl.appendChild(opt);
    });
    toast(`已获取 ${r.models.length} 个云端模型，点击模型输入框即可下拉选择 ✅`, "ok");
  } catch (e) { toast("获取失败：" + e.message, "err"); }
}

async function refreshStatus() {
  try {
    const r = await api("/api/status");
    const badge = document.getElementById("status-badge");
    const text = document.getElementById("status-text");
    if (r.bot_connected) {
      badge.className = "badge on";
      text.textContent = `已连接${r.qq ? " · QQ " + r.qq : ""}`;
    } else {
      badge.className = "badge off";
      text.textContent = "NapCat 未连接";
    }
  } catch (e) { /* 静默 */ }
}

loadConfig();
refreshStatus();
setInterval(refreshStatus, 10000);
