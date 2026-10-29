/* RealChat - phần chính: đăng nhập, WebSocket, danh sách, khung chat. Cuộc gọi nằm ở calls.js */
"use strict";
const $ = id => document.getElementById(id);
const S = {
  token: localStorage.getItem("token"), me: null,
  rooms: [], users: [], online: new Set(), current: null,
  unread: {}, callStatus: {},          // callStatus[room_id] = {call_id, media, participants}
  ws: null, retry: 0, lost: false, hasMore: false, loadingOlder: false,
};
const PAGE = 30;
const MAX_IMG = 5 * 1024 * 1024;
const IMG_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

function toast(text, isErr = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = text;
  $("toasts").append(el);
  setTimeout(() => el.remove(), 4000);
}

/* ---------------- REST ---------------- */
async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(S.token && { Authorization: "Bearer " + S.token }) },
    body: body && JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && S.token) logout();
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : "Dữ liệu không hợp lệ");
  }
  return data;
}

/* ---------------- Đăng nhập / đăng ký / đăng xuất ---------------- */
async function auth(kind) {
  try {
    const d = await api("/api/auth/" + kind, "POST",
      { username: $("username").value.trim(), password: $("password").value });
    S.token = d.access_token; S.me = d.user;
    localStorage.setItem("token", S.token);
    $("err").textContent = ""; $("password").value = "";
    start();
  } catch (e) { $("err").textContent = e.message; }
}
$("authForm").onsubmit = e => { e.preventDefault(); auth("login"); };
$("registerBtn").onclick = () => auth("register");
$("logoutBtn").onclick = logout;

function logout() {
  if (typeof endCallLocal === "function") endCallLocal();
  if (S.ws) { S.ws.onclose = null; S.ws.close(); S.ws = null; }
  clearInterval(S.pingTimer); clearTimeout(S.pongTimer);
  S.token = null; S.me = null; S.current = null; S.rooms = []; S.users = [];
  localStorage.removeItem("token");
  $("app").classList.add("hidden");
  $("auth").classList.remove("hidden");
}

async function start() {
  S.unread = JSON.parse(localStorage.getItem("unread:" + S.me.id) || "{}");
  $("auth").classList.add("hidden");
  $("app").classList.remove("hidden");
  $("meName").textContent = S.me.username;
  connect();
  await refreshSidebar();
}

/* ---------------- WebSocket: kết nối, backoff, heartbeat ---------------- */
function connect() {
  if (!S.token) return;
  // Trang HTTPS thì buộc phải dùng wss:// (trình duyệt chặn ws:// trên trang https)
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(S.token)}`);
  S.ws = ws;
  ws.onopen = () => {
    S.retry = 0;
    $("status").textContent = "Đã kết nối";
    startHeartbeat();
    if (S.lost) { S.lost = false; refreshSidebar(); if (S.current) openRoom(S.current, true); } // đồng bộ tin bị lỡ
  };
  ws.onmessage = e => onEvent(JSON.parse(e.data));
  ws.onclose = e => {
    if (S.ws !== ws) return;
    clearInterval(S.pingTimer); clearTimeout(S.pongTimer);
    if (e.code === 4401) return logout();
    S.lost = true; S.online.clear(); renderSidebar();
    if (typeof endCallLocal === "function" && S.call) { endCallLocal(); toast("Mất kết nối - cuộc gọi đã kết thúc", true); }
    // Backoff tăng dần: 1s, 2s, 4s, 8s ... tối đa 15s
    const wait = Math.min(1000 * 2 ** S.retry++, 15000);
    $("status").textContent = `Mất kết nối, thử lại sau ${Math.round(wait / 1000)}s...`;
    setTimeout(connect, wait);
  };
}

// Heartbeat: gửi ping mỗi 20s; 10s không thấy pong thì coi như kết nối chết và đóng để tự kết nối lại
function startHeartbeat() {
  clearInterval(S.pingTimer);
  S.pingTimer = setInterval(() => {
    wsSend({ type: "ping" });
    clearTimeout(S.pongTimer);
    S.pongTimer = setTimeout(() => S.ws && S.ws.close(), 10000);
  }, 20000);
}

function wsSend(obj) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return false;
  S.ws.send(JSON.stringify(obj));
  return true;
}

async function onEvent(ev) {
  switch (ev.type) {
    case "pong": clearTimeout(S.pongTimer); break;
    case "presence.list": S.online = new Set(ev.users); renderSidebar(); break;
    case "presence.update":
      ev.status === "online" ? S.online.add(ev.user_id) : S.online.delete(ev.user_id);
      renderSidebar(); break;
    case "user.created":
      if (ev.user.id !== S.me.id && !S.users.some(u => u.id === ev.user.id)) { S.users.push(ev.user); renderSidebar(); }
      break;
    case "message.new": await onNewMessage(ev); break;
    case "group.created": case "group.updated": upsertRoom(ev.room); break;
    case "group.removed":
      S.rooms = S.rooms.filter(r => r.id !== ev.room_id);
      if (S.current && S.current.id === ev.room_id) closeChat();
      renderSidebar(); break;
    case "error": toast(ev.detail, true); if (typeof handleCallError === "function") handleCallError(ev); break;
    default: if (ev.type.startsWith("call.") || ev.type.startsWith("webrtc.")) handleCallEvent(ev);
  }
}

function upsertRoom(room) {
  const i = S.rooms.findIndex(r => r.id === room.id);
  if (i >= 0) S.rooms[i] = room; else S.rooms.push(room);
  if (S.current && S.current.id === room.id) { S.current = room; renderHeader(); }
  renderSidebar();
}

/* ---------------- Danh sách bên trái ---------------- */
async function refreshSidebar() {
  [S.rooms, S.users] = await Promise.all([api("/api/rooms"), api("/api/users")]);
  if (S.current) S.current = S.rooms.find(r => r.id === S.current.id) || null;
  renderSidebar();
}

function row(label, { active, dot, unread, live, onclick }) {
  const el = document.createElement("div");
  el.className = "item" + (active ? " active" : "");
  const left = document.createElement("span");
  left.className = "name";
  if (dot !== undefined) {
    const d = document.createElement("i");
    d.className = "dot" + (dot ? " on" : "");
    left.append(d);
  }
  left.append(label);
  el.append(left);
  if (live) { const l = document.createElement("span"); l.className = "live"; l.textContent = "\u{1F4DE}"; el.append(l); }
  if (unread) { const b = document.createElement("span"); b.className = "badge"; b.textContent = unread; el.append(b); }
  el.onclick = onclick;
  return el;
}

function note(text) { const d = document.createElement("div"); d.className = "empty"; d.textContent = text; return d; }

function dmRoomOf(userId) {
  return S.rooms.find(r => r.type === "dm" && r.members.some(m => m.id === userId));
}

function renderSidebar() {
  const groups = S.rooms.filter(r => r.type === "group");
  $("groups").replaceChildren(...groups.map(r => row("# " + r.name, {
    active: S.current && S.current.id === r.id, unread: S.unread[r.id],
    live: !!(S.callStatus[r.id] && S.callStatus[r.id].call_id), onclick: () => openRoom(r),
  })));
  const users = [...S.users].sort((a, b) =>
    (S.online.has(b.id) - S.online.has(a.id)) || a.username.localeCompare(b.username));
  $("users").replaceChildren(...(users.length ? users.map(u => {
    const dm = dmRoomOf(u.id);
    return row(u.username, {
      dot: S.online.has(u.id), active: dm && S.current && S.current.id === dm.id,
      unread: dm && S.unread[dm.id], onclick: () => openDM(u.id),
    });
  }) : [note("Chưa có người dùng khác. Mời bạn bè đăng ký nhé!")]));
  const n = S.users.filter(u => S.online.has(u.id)).length;
  $("onlineCount").textContent = `${n} đang online`;
}

async function openDM(userId) {
  try {
    const r = await api("/api/rooms/dm", "POST", { user_id: userId });
    upsertRoom(r);
    openRoom(r);
  } catch (e) { toast(e.message, true); }
}

/* ---------------- Khung chat ---------------- */
function renderHeader() {
  const r = S.current;
  if (!r) return;
  $("roomTitle").textContent = (r.type === "dm" ? "@ " : "# ") + r.name;
  if (r.type === "dm") {
    const other = r.members.find(m => m.id !== S.me.id);
    $("roomSub").textContent = other && S.online.has(other.id) ? "Đang online" : "Offline";
  } else {
    $("roomSub").textContent = r.members.length + " thành viên";
  }
  $("manageBtn").classList.toggle("hidden", r.type !== "group");
  const st = S.callStatus[r.id];
  const joinable = r.type === "group" && st && st.call_id && !(S.call && S.call.id === st.call_id);
  $("joinCallBtn").classList.toggle("hidden", !joinable);
  if (joinable) $("joinCallBtn").textContent = `Tham gia cuộc gọi (${st.participants.length})`;
  $("voiceBtn").classList.toggle("hidden", joinable);
  $("videoBtn").classList.toggle("hidden", joinable);
}

function closeChat() {
  S.current = null;
  $("chatHeader").classList.add("hidden"); $("composer").classList.add("hidden");
  $("msgs").replaceChildren(Object.assign(document.createElement("div"),
    { className: "placeholder", textContent: "Bạn không còn ở trong cuộc trò chuyện này." }));
  $("app").classList.remove("chat-open");
}
$("backBtn").onclick = () => { $("app").classList.remove("chat-open"); S.current = null; renderSidebar(); };

function saveUnread() { localStorage.setItem("unread:" + S.me.id, JSON.stringify(S.unread)); }

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

function msgEl(m) {
  const mine = m.sender.id === S.me.id;
  const el = document.createElement("div");
  el.className = "msg" + (mine ? " mine" : ""); el.dataset.id = m.id;
  if (!mine && S.current && S.current.type === "group") {
    const who = document.createElement("span"); who.className = "who"; who.textContent = m.sender.username; el.append(who);
  }
  const b = document.createElement("div");
  if (m.msg_type === "image") {
    b.className = "bubble img";
    const img = document.createElement("img");
    img.src = m.content; img.alt = "Ảnh"; img.loading = "lazy";
    img.onclick = () => window.open(m.content, "_blank", "noopener");
    img.onload = () => { if (el.dataset.stick) $("msgs").scrollTop = $("msgs").scrollHeight; };
    b.append(img);
  } else {
    b.className = "bubble";
    b.textContent = m.content; // textContent -> chống XSS
  }
  const t = document.createElement("time"); t.textContent = fmtTime(m.ts);
  el.append(b, t);
  return el;
}

function addMessage(m) {
  const box = $("msgs");
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const el = msgEl(m);
  if (near || m.sender.id === S.me.id) el.dataset.stick = "1";
  box.append(el);
  if (el.dataset.stick) box.scrollTop = box.scrollHeight;
}

async function onNewMessage(ev) {
  if (!S.rooms.some(r => r.id === ev.room_id)) await refreshSidebar(); // DM mới từ người khác
  if (S.current && S.current.id === ev.room_id) addMessage(ev);
  if (!S.current || S.current.id !== ev.room_id || document.hidden) {
    if (ev.sender.id !== S.me.id) { S.unread[ev.room_id] = (S.unread[ev.room_id] || 0) + 1; saveUnread(); renderSidebar(); }
  }
}

async function openRoom(room, keepScroll) {
  S.current = room;
  S.unread[room.id] = 0; saveUnread();
  $("app").classList.add("chat-open");
  $("chatHeader").classList.remove("hidden");
  $("composer").classList.remove("hidden");
  renderHeader();
  const list = await api(`/api/rooms/${room.id}/messages?limit=${PAGE}`);
  if (!S.current || S.current.id !== room.id) return; // người dùng đã chuyển phòng khác trong lúc chờ
  S.hasMore = list.length === PAGE;
  const box = $("msgs");
  box.replaceChildren(...(S.hasMore ? [note("Cuộn lên để tải tin cũ hơn")] : []), ...list.map(msgEl));
  if (S.hasMore) box.firstChild.className = "loadmore";
  box.querySelectorAll(".msg").forEach(e => (e.dataset.stick = "1"));
  box.scrollTop = box.scrollHeight;
  renderSidebar();
  if (!keepScroll && window.innerWidth > 720) $("text").focus();
}

// Cuộn lên đầu thì tải trang tin cũ hơn (cursor = id của tin đầu tiên đang hiển thị)
$("msgs").addEventListener("scroll", async () => {
  const box = $("msgs");
  if (box.scrollTop > 60 || !S.hasMore || S.loadingOlder || !S.current) return;
  const first = box.querySelector(".msg");
  if (!first) return;
  S.loadingOlder = true;
  const roomId = S.current.id;
  try {
    const list = await api(`/api/rooms/${roomId}/messages?limit=${PAGE}&before=${first.dataset.id}`);
    if (!S.current || S.current.id !== roomId) return;
    S.hasMore = list.length === PAGE;
    const oldH = box.scrollHeight;
    const anchor = box.querySelector(".loadmore");
    list.forEach(m => first.before(msgEl(m)));
    if (!S.hasMore && anchor) anchor.remove();
    box.scrollTop += box.scrollHeight - oldH; // giữ nguyên vị trí đang đọc
  } catch (e) { toast(e.message, true); }
  finally { S.loadingOlder = false; }
});

$("composer").onsubmit = e => {
  e.preventDefault();
  const content = $("text").value.trim();
  if (!content || !S.current) return;
  if (sendMessage("text", content)) $("text").value = "";
};

function sendMessage(msgType, content) {
  const ok = wsSend({
    type: "message.send", room_id: S.current.id, msg_type: msgType, content,
    client_id: Date.now() + "-" + Math.random().toString(36).slice(2),
  });
  if (!ok) toast("Chưa kết nối, đang thử lại...", true);
  return ok;
}

/* ---------------- Gửi ảnh ---------------- */
$("imgBtn").onclick = () => $("imgInput").click();
$("imgInput").onchange = async () => {
  const file = $("imgInput").files[0];
  $("imgInput").value = "";
  if (!file || !S.current) return;
  if (!IMG_TYPES.includes(file.type)) return toast("Chỉ hỗ trợ ảnh JPG, PNG, GIF, WEBP", true);
  if (file.size > MAX_IMG) return toast("Ảnh vượt quá 5MB", true);
  toast("Đang tải ảnh lên...");
  const fd = new FormData(); fd.append("file", file);
  try {
    const res = await fetch("/api/upload", { method: "POST", headers: { Authorization: "Bearer " + S.token }, body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Tải ảnh thất bại");
    sendMessage("image", data.url);   // upload xong mới gửi tin nhắn kiểu image qua WebSocket
  } catch (e) { toast(e.message, true); }
};

/* ---------------- Modal: tạo nhóm / quản lý nhóm ---------------- */
function openModal(...nodes) { $("dialog").replaceChildren(...nodes); $("modal").classList.remove("hidden"); }
function closeModal() { $("modal").classList.add("hidden"); }
$("modal").addEventListener("mousedown", e => { if (e.target === $("modal")) closeModal(); });

function el(tag, props = {}, ...kids) {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...kids);
  return n;
}

function checklist(users) {
  const box = el("div", { className: "checklist" });
  if (!users.length) box.append(el("div", { className: "empty", textContent: "Không có ai để chọn" }));
  users.forEach(u => {
    const cb = el("input", { type: "checkbox", value: u.id });
    box.append(el("label", {}, cb, u.username));
  });
  return box;
}
const checked = box => [...box.querySelectorAll("input:checked")].map(i => i.value);

$("newGroupBtn").onclick = () => {
  const name = el("input", { placeholder: "Tên nhóm", maxLength: 40 });
  const list = checklist(S.users);
  const create = el("button", { textContent: "Tạo nhóm" });
  create.onclick = async () => {
    try {
      const r = await api("/api/rooms/group", "POST", { name: name.value.trim(), member_ids: checked(list) });
      upsertRoom(r); closeModal(); openRoom(r);
    } catch (e) { toast(e.message, true); }
  };
  const cancel = el("button", { className: "ghost", textContent: "Hủy", onclick: closeModal });
  openModal(el("h3", { textContent: "Tạo nhóm chat" }), name, el("small", { className: "muted", textContent: "Chọn thành viên:" }),
    list, el("div", { className: "row" }, cancel, create));
};

$("manageBtn").onclick = () => {
  const r = S.current;
  if (!r || r.type !== "group") return;
  const isOwner = r.created_by === S.me.id && !r.is_default;
  const members = el("div", { className: "checklist" });
  r.members.forEach(m => {
    const row = el("div", { className: "memberRow" }, el("span", {
      textContent: m.username + (m.id === r.created_by ? " (người tạo)" : "") + (m.id === S.me.id ? " (bạn)" : ""),
    }));
    if (isOwner && m.id !== S.me.id) {
      row.append(el("button", { className: "danger small", textContent: "Xóa", onclick: async () => {
        try { upsertRoom(await api(`/api/rooms/${r.id}/members/${m.id}`, "DELETE")); $("manageBtn").onclick(); }
        catch (e) { toast(e.message, true); }
      } }));
    }
    members.append(row);
  });
  const nodes = [el("h3", { textContent: "# " + r.name }), members];
  if (isOwner) {
    const candidates = S.users.filter(u => !r.members.some(m => m.id === u.id));
    const list = checklist(candidates);
    nodes.push(el("small", { className: "muted", textContent: "Thêm thành viên:" }), list,
      el("button", { textContent: "Thêm đã chọn", onclick: async () => {
        const ids = checked(list);
        if (!ids.length) return;
        try { upsertRoom(await api(`/api/rooms/${r.id}/members`, "POST", { user_ids: ids })); $("manageBtn").onclick(); }
        catch (e) { toast(e.message, true); }
      } }));
  }
  const row = el("div", { className: "row" });
  if (!r.is_default) {
    row.append(el("button", { className: "danger", textContent: "Rời nhóm", onclick: async () => {
      if (!confirm("Bạn chắc chắn muốn rời nhóm này?")) return;
      try { await api(`/api/rooms/${r.id}/leave`, "POST"); closeModal(); } catch (e) { toast(e.message, true); }
    } }));
  }
  row.append(el("button", { className: "ghost", textContent: "Đóng", onclick: closeModal }));
  openModal(...nodes, row);
};

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && S.current) { S.unread[S.current.id] = 0; saveUnread(); renderSidebar(); }
});

/* ---------------- Khởi động ---------------- */
if (S.token) api("/api/auth/me").then(u => { S.me = u; start(); }).catch(() => {});
