/* =========================================================
   REALCHAT - MAIN APPLICATION
   Authentication, WebSocket, Sidebar, Chat, Messages
   Voice/video calls are handled by calls.js
========================================================= */

"use strict";

/* ======================== CONFIG ======================== */

const $ = id => document.getElementById(id);

const PAGE = 30;
const MAX_IMG = 5 * 1024 * 1024;
const MAX_MEDIA = 5 * 1024 * 1024;
const MAX_AUDIO_SECONDS = 120;
const IMG_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];
const VIDEO_TYPES = ["video/mp4", "video/webm", "video/quicktime"];

const S = {
  token: localStorage.getItem("token"),
  me: null,
  rooms: [],
  users: [],
  online: new Set(),
  current: null,
  unread: {},
  callStatus: {},
  ws: null,
  retry: 0,
  lost: false,
  hasMore: false,
  loadingOlder: false,
  msgs: {},
};

const SIDEBAR_STORAGE_KEY = "realchat-sidebar-collapsed";

if (localStorage.getItem(SIDEBAR_STORAGE_KEY) === "true") {
  $("app").classList.add("sidebar-collapsed");
}

/* ======================== UTILITIES ======================== */

function toast(text, isErr = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = text;

  $("toasts").append(el);
  setTimeout(() => el.remove(), 4000);
}

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function dateKey(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function dateLabel(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);

  if (dateKey(d) === dateKey(today)) return "Hôm nay";
  if (dateKey(d) === dateKey(yesterday)) return "Hôm qua";

  return d.toLocaleDateString("vi-VN", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric"
  });
}

function dateDivider(ts) {
  const divider = document.createElement("div");
  divider.className = "date-divider";
  divider.dataset.date = dateKey(ts);

  const label = document.createElement("span");
  label.textContent = dateLabel(ts);

  divider.append(label);
  return divider;
}
function saveUnread() {
  if (!S.me) return;

  localStorage.setItem(
    "unread:" + S.me.id,
    JSON.stringify(S.unread)
  );
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

/* ======================== REST API ======================== */

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(S.token && {
        Authorization: "Bearer " + S.token,
      }),
    },
    body: body && JSON.stringify(body),
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    if (res.status === 401 && S.token) logout();

    const detail = data.detail;

    if (Array.isArray(detail)) {
      const messages = detail.map(error => {
        const field = error.loc?.at(-1);
        const label = field === "username"
          ? "Tên đăng nhập"
          : field === "password"
            ? "Mật khẩu"
            : "Dữ liệu";

        if (error.type === "string_too_short") {
          return `${label} phải có ít nhất ${error.ctx.min_length} ký tự`;
        }
        if (error.type === "string_too_long") {
          return `${label} không được quá ${error.ctx.max_length} ký tự`;
        }
        if (error.type === "string_pattern_mismatch" && field === "username") {
          return "Tên đăng nhập chỉ được gồm chữ không dấu, số và dấu gạch dưới";
        }
        if (error.type === "missing") {
          return `Thiếu ${label.toLowerCase()}`;
        }
        return `${label} không hợp lệ`;
      });

      throw new Error([...new Set(messages)].join(". "));
    }

    throw new Error(
      typeof detail === "string"
        ? detail
        : "Dữ liệu không hợp lệ"
    );
  }

  return data;
}

/* ======================== AUTHENTICATION ======================== */

async function auth(kind) {
  try {
    const data = await api("/api/auth/" + kind, "POST", {
      username: $("username").value.trim(),
      password: $("password").value,
    });

    S.token = data.access_token;
    S.me = data.user;

    localStorage.setItem("token", S.token);

    $("err").textContent = "";
    $("password").value = "";

    start();
  } catch (error) {
    $("err").textContent = error.message;
  }
}

$("authForm").onsubmit = event => {
  event.preventDefault();
  auth("login");
};

$("registerBtn").onclick = () => auth("register");
$("logoutBtn").onclick = logout;

function logout() {
  if (typeof endCallLocal === "function") {
    endCallLocal();
  }

  if (S.ws) {
    S.ws.onclose = null;
    S.ws.close();
    S.ws = null;
  }

  clearInterval(S.pingTimer);
  clearTimeout(S.pongTimer);

  S.token = null;
  S.me = null;
  S.current = null;
  S.rooms = [];
  S.users = [];

  localStorage.removeItem("token");

  $("app").classList.add("hidden");
  $("auth").classList.remove("hidden");
}

async function start() {
  S.unread = JSON.parse(
    localStorage.getItem("unread:" + S.me.id) || "{}"
  );

  $("auth").classList.add("hidden");
  $("app").classList.remove("hidden");
  renderAccountSidebar();

  connect();
  await refreshSidebar();
}

function updateAvatarElement(element, profile, imageUrl = profile.avatar_url) {
  if (imageUrl) {
    const image = el("img", {
      src: imageUrl,
      alt: "Ảnh đại diện",
    });
    element.replaceChildren(image);
  } else {
    element.textContent = (profile.display_name || profile.username).charAt(0).toUpperCase() || "?";
  }
}

function renderAccountSidebar() {
  $("meName").textContent = S.me.display_name || S.me.username;
  updateAvatarElement($("meAvatar"), S.me);
}

/* ======================== WEBSOCKET ======================== */

function connect() {
  if (!S.token) return;

  const protocol =
    location.protocol === "https:" ? "wss" : "ws";

  const ws = new WebSocket(
    `${protocol}://${location.host}/ws?token=${encodeURIComponent(S.token)}`
  );

  S.ws = ws;

  ws.onopen = () => {
    S.retry = 0;
    $("status").textContent = "Đã kết nối";

    startHeartbeat();

    if (S.lost) {
      S.lost = false;
      refreshSidebar();

      if (S.current) {
        openRoom(S.current, true);
      }
    }
  };

  ws.onmessage = event => {
    onEvent(JSON.parse(event.data));
  };

  ws.onclose = event => {
    if (S.ws !== ws) return;

    clearInterval(S.pingTimer);
    clearTimeout(S.pongTimer);

    if (event.code === 4401) {
      logout();
      return;
    }

    S.lost = true;
    S.online.clear();
    renderSidebar();

    if (
      typeof endCallLocal === "function" &&
      S.call
    ) {
      endCallLocal();
      toast("Mất kết nối - cuộc gọi đã kết thúc", true);
    }

    const wait = Math.min(
      1000 * 2 ** S.retry++,
      15000
    );

    $("status").textContent =
      `Mất kết nối, thử lại sau ${Math.round(wait / 1000)}s...`;

    setTimeout(connect, wait);
  };
}

function startHeartbeat() {
  clearInterval(S.pingTimer);

  S.pingTimer = setInterval(() => {
    wsSend({ type: "ping" });

    clearTimeout(S.pongTimer);

    S.pongTimer = setTimeout(() => {
      if (S.ws) S.ws.close();
    }, 10000);
  }, 20000);
}

function wsSend(data) {
  if (
    !S.ws ||
    S.ws.readyState !== WebSocket.OPEN
  ) {
    return false;
  }

  S.ws.send(JSON.stringify(data));
  return true;
}

/* ======================== WEBSOCKET EVENTS ======================== */

async function onEvent(event) {
  switch (event.type) {
    case "pong":
      clearTimeout(S.pongTimer);
      break;

    case "presence.list":
      S.online = new Set(event.users);
      renderSidebar();
      break;

    case "presence.update":
      if (event.status === "online") {
        S.online.add(event.user_id);
      } else {
        S.online.delete(event.user_id);
      }

      renderSidebar();
      break;

    case "user.created":
      if (
        event.user.id !== S.me.id &&
        !S.users.some(user => user.id === event.user.id)
      ) {
        S.users.push(event.user);
        renderSidebar();
      }
      break;

    case "message.new":
      await onNewMessage(event);
      break;

    case "message.edited":
      updateMessage({
        id: event.id,
        content: event.content,
        edited: true,
        edited_at: event.edited_at,
      });
      break;

    case "message.deleted":
    case "message.reaction":
      updateMessage(event);
      break;

    case "message.read": {
      if (event.user_id === S.me.id || !event.message_id) break;
      const message = S.msgs[event.message_id];
      if (message && !(message.read_by || []).includes(event.user_id)) {
        message.read_by = [...(message.read_by || []), event.user_id];
      }
      applySeen();
      break;
    }

    case "typing.start":
    case "typing.stop":
      onTyping(event);
      break;

    case "group.created":
    case "group.updated":
      upsertRoom(event.room);
      break;

    case "group.removed":
      S.rooms = S.rooms.filter(
        room => room.id !== event.room_id
      );

      if (
        S.current &&
        S.current.id === event.room_id
      ) {
        closeChat();
      }

      renderSidebar();
      break;

    case "error":
      toast(event.detail, true);

      if (typeof handleCallError === "function") {
        handleCallError(event);
      }
      break;

    default:
      if (
        event.type.startsWith("call.") ||
        event.type.startsWith("webrtc.")
      ) {
        handleCallEvent(event);
      }
  }
}

/* ======================== SIDEBAR DATA ======================== */

async function refreshSidebar() {
  [S.rooms, S.users] = await Promise.all([
    api("/api/rooms"),
    api("/api/users"),
  ]);

  if (S.current) {
    S.current =
      S.rooms.find(room => room.id === S.current.id) || null;
  }

  renderSidebar();
}

function upsertRoom(room) {
  const index = S.rooms.findIndex(
    item => item.id === room.id
  );

  if (index >= 0) {
    S.rooms[index] = room;
  } else {
    S.rooms.push(room);
  }

  if (
    S.current &&
    S.current.id === room.id
  ) {
    S.current = room;
    renderHeader();
  }

  renderSidebar();
}

function dmRoomOf(userId) {
  return S.rooms.find(room =>
    room.type === "dm" &&
    room.members.some(member => member.id === userId)
  );
}

function note(text) {
  return el("div", {
    className: "empty",
    textContent: text,
  });
}

/* ======================== SIDEBAR ITEMS ======================== */

function row(label, options = {}) {
  const {
    active,
    dot,
    unread,
    live,
    onclick,
  } = options;

  const item = el("div", {
    className: "item" + (active ? " active" : ""),
  });
  item.title = label;

  const left = el("span", {
    className: "name",
  });

  const cleanName = label.replace(/^[@#]\s*/, "").trim();

  const avatar = el("span", {
    className: "sidebar-avatar",
    textContent: cleanName.charAt(0).toUpperCase() || "?",
  });

  if (label.startsWith("#")) {
    avatar.classList.add("group-avatar");
  }

  const name = el("span", {
    className: "item-label",
    textContent: label,
  });

  left.append(avatar, name);

  if (dot !== undefined) {
    const status = el("i", {
      className: "dot" + (dot ? " on" : ""),
    });

    left.append(status);
  }

  item.append(left);

  if (live) {
    item.append(el("span", {
      className: "live",
      textContent: "\u{1F4DE}",
    }));
  }

  if (unread) {
    item.append(el("span", {
      className: "badge",
      textContent: unread,
    }));
  }

  item.onclick = onclick;

  return item;
}

function renderSidebar() {
  const keyword = (
    $("sidebarSearch")?.value || ""
  ).trim().toLowerCase();

  // Nhóm chat
  const groups = S.rooms.filter(room =>
    room.type === "group" &&
    room.name.toLowerCase().includes(keyword)
  );

  $("groups").replaceChildren(
    ...groups.map(room =>
      row("# " + room.name, {
        active:
          S.current &&
          S.current.id === room.id,

        unread: S.unread[room.id],

        live: !!(
          S.callStatus[room.id] &&
          S.callStatus[room.id].call_id
        ),

        onclick: () => openRoom(room),
      })
    )
  );

  // Người dùng
  const users = [...S.users]
    .filter(user =>
      user.username.toLowerCase().includes(keyword) ||
      (user.display_name || user.username).toLowerCase().includes(keyword)
    )
    .sort((a, b) =>
      (S.online.has(b.id) - S.online.has(a.id)) ||
      a.username.localeCompare(b.username)
    );

  const userItems = users.map(user => {
    const dm = dmRoomOf(user.id);

    return row(user.display_name || user.username, {
      dot: S.online.has(user.id),

      active:
        dm &&
        S.current &&
        S.current.id === dm.id,

      unread: dm && S.unread[dm.id],

      onclick: () => openDM(user.id),
    });
  });

  $("users").replaceChildren(
    ...(userItems.length
      ? userItems
      : [
          note(
            keyword
              ? "Không tìm thấy người dùng."
              : "Chưa có người dùng khác. Mời bạn bè đăng ký nhé!"
          ),
        ])
  );

  const onlineCount = S.users.filter(user =>
    S.online.has(user.id)
  ).length;

  $("onlineCount").textContent =
    `${onlineCount} đang online`;
}

/* ======================== SEARCH SIDEBAR ======================== */

const sidebarSearch = $("sidebarSearch");
const clearSearch = $("clearSearch");

if (sidebarSearch) {
  sidebarSearch.addEventListener(
    "input",
    renderSidebar
  );
}

if (clearSearch) {
  clearSearch.onclick = () => {
    if (!sidebarSearch) return;

    sidebarSearch.value = "";
    renderSidebar();
    sidebarSearch.focus();
  };
}

/* ======================== DIRECT MESSAGE ======================== */

async function openDM(userId) {
  try {
    const room = await api(
      "/api/rooms/dm",
      "POST",
      { user_id: userId }
    );

    upsertRoom(room);
    openRoom(room);
  } catch (error) {
    toast(error.message, true);
  }
}

/* ======================== CHAT HEADER ======================== */

function renderHeader() {
  const room = S.current;

  if (!room) return;

  $("roomTitle").textContent =
    (room.type === "dm" ? "@ " : "# ") + room.name;

  if (room.type === "dm") {
    const other = room.members.find(
      member => member.id !== S.me.id
    );

    $("roomSub").textContent =
      other && S.online.has(other.id)
        ? "Đang online"
        : "Offline";
  } else {
    $("roomSub").textContent =
      room.members.length + " thành viên";
  }

  $("manageBtn").classList.toggle(
    "hidden",
    room.type !== "group"
  );

  const status = S.callStatus[room.id];

  const joinable =
    room.type === "group" &&
    status &&
    status.call_id &&
    !(S.call && S.call.id === status.call_id);

  $("joinCallBtn").classList.toggle(
    "hidden",
    !joinable
  );

  if (joinable) {
    $("joinCallBtn").textContent =
      `Tham gia cuộc gọi (${status.participants.length})`;
  }

  $("voiceBtn").classList.toggle(
    "hidden",
    joinable
  );

  $("videoBtn").classList.toggle(
    "hidden",
    joinable
  );
}

/* ======================== OPEN / CLOSE CHAT ======================== */

function closeChat() {
  S.current = null;
  closeMobileSidebar();

  $("chatHeader").classList.add("hidden");
  $("composer").classList.add("hidden");

  $("msgs").replaceChildren(
    el("div", {
      className: "placeholder",
      textContent:
        "Bạn không còn ở trong cuộc trò chuyện này.",
    })
  );

  $("app").classList.remove("chat-open");
}

$("backBtn").onclick = () => {
  $("app").classList.remove("chat-open");
  $("app").classList.remove("mobile-sidebar-open");
  S.current = null;
  renderSidebar();
};

function closeMobileSidebar() {
  $("app").classList.remove("mobile-sidebar-open");
  $("sidebarMenuBtn").setAttribute("aria-expanded", "false");
}

$("sidebarMenuBtn").onclick = () => {
  $("app").classList.add("mobile-sidebar-open");
  $("sidebarMenuBtn").setAttribute("aria-expanded", "true");
};

$("sidebarBackdrop").onclick = closeMobileSidebar;

$("sidebarToggle").onclick = () => {
  const collapsed = $("app").classList.toggle("sidebar-collapsed");
  localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed));
  $("sidebarToggle").title = collapsed
    ? "Mở rộng danh sách"
    : "Thu gọn danh sách";
  $("sidebarToggle").setAttribute("aria-label", $("sidebarToggle").title);
  $("sidebarToggle").setAttribute("aria-expanded", String(!collapsed));
  $("sidebarToggle").textContent = collapsed ? "\u203A" : "\u2039";
};

if ($("app").classList.contains("sidebar-collapsed")) {
  $("sidebarToggle").title = "Mở rộng danh sách";
  $("sidebarToggle").setAttribute("aria-label", "Mở rộng danh sách");
  $("sidebarToggle").setAttribute("aria-expanded", "false");
  $("sidebarToggle").textContent = "\u203A";
}

/* ======================== MESSAGE DISPLAY ======================== */

function msgEl(message) {
  const mine = message.sender.id === S.me.id;

  const item = el("div", {
    className: "msg" + (mine ? " mine" : "")
  });

  item.dataset.id = message.id;
  item.dataset.date = dateKey(message.ts);

  // Avatar người gửi
  const avatar = el("span", {
    className: "message-avatar",
    textContent:
      (message.sender.username || "?")
        .charAt(0)
        .toUpperCase(),
  });

  // Nội dung tin nhắn
  const content = el("div", {
    className: "message-content",
  });

  // Tên người gửi trong nhóm
  if (
    !mine &&
    S.current &&
    S.current.type === "group"
  ) {
    content.append(
      el("span", {
        className: "who",
        textContent: message.sender.username,
      })
    );
  }

  S.msgs[message.id] = message;

  // Bong bóng tin nhắn
  const bubble = el("div");

  if (message.deleted) {
    bubble.className = "bubble deleted";
    bubble.textContent = "Tin nhắn đã được thu hồi";
  } else if (message.msg_type === "image") {
    bubble.className = "bubble img";
    const img = el("img", { src: message.content, alt: "Ảnh", loading: "lazy" });
    img.onclick = () => window.open(message.content, "_blank", "noopener");
    bubble.append(img);
  } else if (message.msg_type === "video") {
    bubble.className = "bubble media";
    const video = el("video", { src: message.content, controls: "", preload: "metadata", playsinline: "" });
    bubble.append(video);
    if (message.duration) bubble.append(el("span", { className: "media-duration", textContent: `Thời lượng ${formatDuration(message.duration)}` }));
  } else if (message.msg_type === "audio") {
    bubble.className = "bubble media audio";
    bubble.append(el("audio", { src: message.content, controls: "", preload: "metadata" }));
    bubble.append(el("span", { className: "media-duration", textContent: `Ghi âm · ${formatDuration(message.duration)}` }));
  } else {
    bubble.className = "bubble";
    bubble.append(...renderMentionParts(message.content));
  }

  // Thời gian
  const time = el("time", {
    textContent: fmtTime(message.ts),
  });

  content.append(bubble);

  const reactions = reactionsEl(message);
  if (reactions) content.append(reactions);

  const meta = el("div", { className: "msg-meta" }, time);
  if (message.edited && !message.deleted) {
    meta.append(el("span", { className: "edited", textContent: "đã chỉnh sửa" }));
  }
  if (mine && !message.deleted) {
    meta.append(el("span", { className: "seen", textContent: "Đã xem" }));
  }
  content.append(meta);

  if (!message.deleted) content.append(actionsEl(message, mine));

  if (mine) {
    item.append(content, avatar);
  } else {
    item.append(avatar, content);
  }

  return item;
}

const REACTIONS = ["❤️", "😂", "👍", "👎", "😍", "😢", "😮", "🙏", "🔥", "👏"];

function reactionsEl(message) {
  const entries = Object.entries(message.reactions || {})
    .filter(([, users]) => users.length);
  if (message.deleted || !entries.length) return null;

  const wrap = el("div", { className: "reactions" });
  entries.forEach(([emoji, users]) => {
    const chip = el("button", {
      type: "button",
      className: "reaction" + (users.includes(S.me.id) ? " mine" : ""),
      textContent: `${emoji} ${users.length}`,
    });
    chip.onclick = () => sendReaction(message.id, emoji);
    wrap.append(chip);
  });
  return wrap;
}

function actionsEl(message, mine) {
  const bar = el("div", { className: "msg-actions" });

  const react = el("button", {
    type: "button",
    title: "Thả cảm xúc",
    textContent: "😊",
  });
  react.onclick = event => {
    event.stopPropagation();
    toggleReactionPicker(bar, message.id);
  };
  bar.append(react);

  if (mine) {
    if (message.msg_type !== "image") {
      const edit = el("button", { type: "button", title: "Chỉnh sửa", textContent: "✏️" });
      edit.onclick = () => {
        const text = prompt("Chỉnh sửa tin nhắn", message.content);
        if (text === null) return;
        const trimmed = text.trim();
        if (!trimmed || trimmed === message.content) return;
        wsSend({
          type: "message.edit",
          room_id: message.room_id,
          message_id: message.id,
          content: trimmed,
        });
      };
      bar.append(edit);
    }

    const del = el("button", { type: "button", title: "Thu hồi", textContent: "🗑️" });
    del.onclick = () => {
      if (!confirm("Thu hồi tin nhắn này?")) return;
      wsSend({
        type: "message.delete",
        room_id: message.room_id,
        message_id: message.id,
      });
    };
    bar.append(del);
  }

  const pinned = (message.pinned_by || []).includes(S.me.id);
  const pin = el("button", {
    type: "button",
    title: pinned ? "Bỏ ghim" : "Ghim tin nhắn",
    textContent: pinned ? "📌" : "📍",
  });
  pin.onclick = () => wsSend({
    type: "message.pin",
    room_id: message.room_id,
    message_id: message.id,
  });
  bar.append(pin);

  return bar;
}

function toggleReactionPicker(bar, messageId) {
  const existing = bar.querySelector(".reaction-picker");
  document.querySelectorAll(".reaction-picker").forEach(p => p.remove());
  if (existing) return;

  const picker = el("div", { className: "reaction-picker" });
  REACTIONS.forEach(emoji => {
    const btn = el("button", { type: "button", textContent: emoji });
    btn.onclick = () => {
      picker.remove();
      sendReaction(messageId, emoji);
    };
    picker.append(btn);
  });
  bar.append(picker);
}

document.addEventListener("click", () => {
  document.querySelectorAll(".reaction-picker").forEach(p => p.remove());
});

function sendReaction(messageId, emoji) {
  if (!S.current) return;
  wsSend({
    type: "message.reaction",
    room_id: S.current.id,
    message_id: messageId,
    emoji,
  });
}

function updateMessage(patch) {
  const old = S.msgs[patch.id];
  if (!old) return;

  const message = { ...old, ...patch };
  const node = $("msgs").querySelector(`.msg[data-id="${patch.id}"]`);
  if (!node) {
    S.msgs[message.id] = message;
    return;
  }

  const fresh = msgEl(message);
  if (node.dataset.stick) fresh.dataset.stick = "1";
  node.replaceWith(fresh);
  applySeen();
}

// Đánh dấu "Đã xem" cho tin của mình từ đầu đến tin người khác đã đọc
function applySeen() {
  const items = [...$("msgs").querySelectorAll(".msg")];
  let lastRead = -1;
  items.forEach((item, index) => {
    const message = S.msgs[item.dataset.id];
    if (message && (message.read_by || []).some(id => id !== S.me.id)) {
      lastRead = index;
    }
  });

  let lastSeenMine = null;
  items.forEach((item, index) => {
    item.classList.remove("seen-last");
    if (index <= lastRead && item.classList.contains("mine")) {
      lastSeenMine = item;
    }
  });
  if (lastSeenMine) lastSeenMine.classList.add("seen-last");
}

function markCurrentRead() {
  if (!S.current || document.hidden) return;
  const items = $("msgs").querySelectorAll(".msg");
  const last = items[items.length - 1];
  if (!last) return;
  const message = S.msgs[last.dataset.id];
  if (!message || (message.read_by || []).includes(S.me.id)) return;

  message.read_by = [...(message.read_by || []), S.me.id];
  wsSend({
    type: "message.read",
    room_id: S.current.id,
    message_id: message.id,
  });
}

document.addEventListener("visibilitychange", markCurrentRead);

/* ---- Đang nhập ---- */

const typingUsers = {};

function renderTyping() {
  let node = $("typingIndicator");
  if (!node) {
    node = el("div", { id: "typingIndicator", className: "typing hidden" });
    $("composer").before(node);
  }
  const names = S.current
    ? Object.values(typingUsers[S.current.id] || {}).map(t => t.name)
    : [];
  node.textContent = names.length
    ? `${names.join(", ")} đang nhập...`
    : "";
  node.classList.toggle("hidden", !names.length);
}

function onTyping(event) {
  if (event.user_id === S.me.id) return;
  const room = (typingUsers[event.room_id] ||= {});
  clearTimeout(room[event.user_id]?.timer);

  if (event.type === "typing.start") {
    room[event.user_id] = {
      name: event.username,
      timer: setTimeout(() => {
        delete room[event.user_id];
        renderTyping();
      }, 5000),
    };
  } else {
    delete room[event.user_id];
  }
  renderTyping();
}

let typingSentAt = 0;
let typingStopTimer = null;

function sendTypingStop() {
  clearTimeout(typingStopTimer);
  typingStopTimer = null;
  if (typingSentAt && S.current) {
    wsSend({ type: "typing.stop", room_id: S.current.id });
  }
  typingSentAt = 0;
}

$("text").addEventListener("input", () => {
  if (!S.current) return;
  if (!$("text").value.trim()) return sendTypingStop();

  if (Date.now() - typingSentAt > 3000) {
    typingSentAt = Date.now();
    wsSend({ type: "typing.start", room_id: S.current.id });
  }
  clearTimeout(typingStopTimer);
  typingStopTimer = setTimeout(sendTypingStop, 2000);
});

function addMessage(message) {
  const box = $("msgs");

  const nearBottom =
    box.scrollHeight -
    box.scrollTop -
    box.clientHeight < 120;

  const currentDate = dateKey(message.ts);
  const messages = box.querySelectorAll(".msg");
  const lastMessage = messages[messages.length - 1];
  const lastDate = lastMessage?.dataset.date;
  if (currentDate && currentDate !== lastDate) {
    box.append(dateDivider(message.ts));
  }

  const item = msgEl(message);

  if (
    nearBottom ||
    message.sender.id === S.me.id
  ) {
    item.dataset.stick = "1";
  }

  box.append(item);

  if (item.dataset.stick) {
    box.scrollTop = box.scrollHeight;
  }
}

/* ======================== NEW MESSAGES ======================== */

async function onNewMessage(event) {
  showMessageNotification(event);

  if (!S.rooms.some(room => room.id === event.room_id)) {
    await refreshSidebar();
  }

  if (
    S.current &&
    S.current.id === event.room_id
  ) {
    addMessage(event);
    if (typingUsers[event.room_id]) {
      delete typingUsers[event.room_id][event.sender.id];
      renderTyping();
    }
    markCurrentRead();
  }

  if (
    !S.current ||
    S.current.id !== event.room_id ||
    document.hidden
  ) {
    if (event.sender.id !== S.me.id) {
      S.unread[event.room_id] =
        (S.unread[event.room_id] || 0) + 1;

      saveUnread();
      renderSidebar();
    }
  }
}

/* ======================== OPEN ROOM ======================== */

async function openRoom(room, keepScroll = false) {
  S.current = room;
  S.unread[room.id] = 0;
  closeMobileSidebar();

  saveUnread();

  $("app").classList.add("chat-open");
  $("chatHeader").classList.remove("hidden");
  $("composer").classList.remove("hidden");

  renderHeader();

  try {
    const list = await api(
      `/api/rooms/${room.id}/messages?limit=${PAGE}`
    );

    if (
      !S.current ||
      S.current.id !== room.id
    ) {
      return;
    }

    S.hasMore = list.length === PAGE;

    const box = $("msgs");
    const items = [];
    let previousDate = null;
    list.forEach(message => {
      const currentDate = dateKey(message.ts);
      if (currentDate && currentDate !== previousDate) {
        items.push(dateDivider(message.ts));
      }
      previousDate = currentDate;
      items.push(msgEl(message));
    });

    if (S.hasMore) {
      const loadMore = note("Cuộn lên để tải tin cũ hơn");
      loadMore.classList.add("loadmore");
      items.unshift(loadMore);
    }

    box.replaceChildren(...items);

    box.querySelectorAll(".msg").forEach(item => {
      item.dataset.stick = "1";
    });

    box.scrollTop = box.scrollHeight;

    renderSidebar();
    renderTyping();
    applySeen();
    markCurrentRead();
    renderPinnedBar();
    if (
      !keepScroll &&
      window.innerWidth > 720
    ) {
      $("text").focus();
    }
  } catch (error) {
    toast(error.message, true);
  }
}

/* ======================== LOAD OLDER MESSAGES ======================== */

$("msgs").addEventListener("scroll", async () => {
  const box = $("msgs");

  if (
    box.scrollTop > 60 ||
    !S.hasMore ||
    S.loadingOlder ||
    !S.current
  ) {
    return;
  }

  const first = box.querySelector(".msg");

  if (!first) return;

  S.loadingOlder = true;

  const roomId = S.current.id;

  try {
    const list = await api(
      `/api/rooms/${roomId}/messages?limit=${PAGE}&before=${first.dataset.id}`
    );

    if (
      !S.current ||
      S.current.id !== roomId
    ) {
      return;
    }

    S.hasMore = list.length === PAGE;

    const oldHeight = box.scrollHeight;
    const anchor = box.querySelector(".loadmore");
    const olderMessages = document.createDocumentFragment();
    let previousDate = first.dataset.date;

    list.forEach(message => {
      const currentDate = dateKey(message.ts);
      if (currentDate && currentDate !== previousDate) {
        olderMessages.append(dateDivider(message.ts));
      }
      previousDate = currentDate;
      olderMessages.append(msgEl(message));
    });

    first.before(olderMessages);

    if (!S.hasMore && anchor) {
      anchor.remove();
    }

    box.scrollTop +=
      box.scrollHeight - oldHeight;
  } catch (error) {
    toast(error.message, true);
  } finally {
    S.loadingOlder = false;
  }
});

/* ======================== SEND TEXT MESSAGE ======================== */

$("composer").onsubmit = event => {
  event.preventDefault();

  const content = $("text").value.trim();

  if (!content || !S.current) return;

  if (sendMessage("text", content)) {
    $("text").value = "";
    sendTypingStop();
  }
};

function sendMessage(msgType, content) {
  if (!S.current) return false;

  const success = wsSend({
    type: "message.send",
    room_id: S.current.id,
    msg_type: msgType,
    content,
    client_id:
      Date.now() +
      "-" +
      Math.random().toString(36).slice(2),
  });

  if (!success) {
    toast("Chưa kết nối, đang thử lại...", true);
  }

  return success;
}

/* ======================== SEND IMAGE / VIDEO ======================== */

$("imgBtn").onclick = () => $("imgInput").click();

$("imgInput").onchange = async () => {
  const file = $("imgInput").files[0];
  $("imgInput").value = "";
  if (!file || !S.current) return;
  if (!IMG_TYPES.includes(file.type)) return toast("Chỉ hỗ trợ ảnh JPG, PNG, GIF, WEBP", true);
  if (file.size > MAX_IMG) return toast("Ảnh vượt quá 5MB", true);
  await uploadMedia(file, "image", "Đang tải ảnh lên...");
};

$("videoMessageBtn").onclick = () => $("videoInput").click();
$("videoInput").onchange = async () => {
  const file = $("videoInput").files[0];
  $("videoInput").value = "";
  if (!file || !S.current) return;
  if (!VIDEO_TYPES.includes(file.type) && !/\.(mp4|webm|mov)$/i.test(file.name)) {
    return toast("Chỉ hỗ trợ video MP4, WebM hoặc MOV", true);
  }
  if (file.size > MAX_MEDIA) return toast("Video vượt quá 5MB", true);
  await uploadMedia(file, "video", "Đang tải video lên...");
};

async function uploadMedia(file, kind, statusText) {
  toast(statusText);
  const formData = new FormData();
  formData.append("file", file);
  formData.append("kind", kind);
  formData.append("room_id", S.current.id);

  try {
    const data = await uploadWithProgress("/api/upload", formData);
    let content = data.url;
    if (content.startsWith("/api/files/")) {
      content += (content.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(S.token);
    }
    const duration = kind === "video" ? await getVideoDuration(file) : undefined;
    sendMediaMessage(kind, content, duration);
  } catch (error) {
    toast(error.message || "Tải file thất bại", true);
  }
}

function sendMediaMessage(kind, content, duration) {
  wsSend({
    type: "message.send",
    room_id: S.current.id,
    msg_type: kind,
    content,
    duration,
    client_id: Date.now() + "-" + Math.random().toString(36).slice(2),
  });
}

function uploadWithProgress(url, formData) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Authorization", "Bearer " + S.token);
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) {
        toast(`Đang tải lên... ${Math.round(event.loaded / event.total * 100)}%`);
      }
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(typeof data.detail === "string" ? data.detail : "Tải file thất bại"));
    };
    xhr.onerror = () => reject(new Error("Mất kết nối khi tải file. Hãy thử lại."));
    xhr.send(formData);
  });
}

function getVideoDuration(file) {
  return new Promise(resolve => {
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      resolve(Number.isFinite(video.duration) ? Math.round(video.duration) : null);
      URL.revokeObjectURL(video.src);
    };
    video.onerror = () => resolve(null);
    video.src = URL.createObjectURL(file);
  });
}

/* ======================== RECORD AUDIO ======================== */

let mediaRecorder = null;
let audioStream = null;
let audioChunks = [];
let recorderTimer = null;
let recorderSeconds = 0;
let recordedBlob = null;
let recorderPreviewUrl = null;

function getAudioMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find(type => window.MediaRecorder && MediaRecorder.isTypeSupported(type)) || "";
}

function formatDuration(seconds) {
  const safe = Math.max(0, Math.round(seconds || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

function showRecorderPanel(preview = false) {
  let panel = $("recordPanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "recordPanel";
    $("composer").insertBefore(panel, $("text"));
  }
  panel.replaceChildren();
  panel.className = "record-panel";
  panel.append(el("span", {
    className: "record-status",
    textContent: preview ? `Tin ghi âm · ${formatDuration(recorderSeconds)}` : `Đang ghi · ${formatDuration(recorderSeconds)}`,
  }));

  if (preview && recorderPreviewUrl) {
    const audio = el("audio", { controls: "" });
    audio.src = recorderPreviewUrl;
    panel.append(audio);
  }

  const cancel = el("button", { type: "button", textContent: "Hủy" });
  cancel.onclick = stopAndCancelRecording;
  panel.append(cancel);

  if (preview) {
    const send = el("button", { type: "button", textContent: "Gửi", className: "record-send" });
    send.onclick = sendRecordedAudio;
    panel.append(send);
  } else {
    const stop = el("button", { type: "button", textContent: "Dừng", className: "record-send" });
    stop.onclick = stopRecording;
    panel.append(stop);
  }
}

async function startRecording() {
  if (!S.current) return;
  if (!window.isSecureContext) return toast("Ghi âm cần truy cập bằng HTTPS hoặc localhost", true);
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    return toast("Trình duyệt không hỗ trợ ghi âm", true);
  }

  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = getAudioMimeType();
    mediaRecorder = mimeType ? new MediaRecorder(audioStream, { mimeType }) : new MediaRecorder(audioStream);
    audioChunks = [];
    recorderSeconds = 0;
    recordedBlob = null;

    mediaRecorder.ondataavailable = event => {
      if (event.data.size) audioChunks.push(event.data);
    };
    mediaRecorder.onstop = () => {
      recordedBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      if (recordedBlob.size > MAX_MEDIA) {
        stopAndCancelRecording();
        toast("Tin ghi âm vượt quá 5MB", true);
        return;
      }
      if (recorderPreviewUrl) URL.revokeObjectURL(recorderPreviewUrl);
      recorderPreviewUrl = URL.createObjectURL(recordedBlob);
      showRecorderPanel(true);
      audioStream?.getTracks().forEach(track => track.stop());
    };

    mediaRecorder.start();
    showRecorderPanel(false);
    clearInterval(recorderTimer);
    recorderTimer = setInterval(() => {
      recorderSeconds += 1;
      showRecorderPanel(false);
      if (recorderSeconds >= 120) stopRecording();
    }, 1000);
  } catch (error) {
    const denied = error?.name === "NotAllowedError" || error?.name === "PermissionDeniedError";
    toast(denied ? "Bạn đã từ chối quyền micro. Hãy cấp quyền micro trong trình duyệt." : "Không thể mở micro. Kiểm tra thiết bị hoặc HTTPS.", true);
  }
}

function stopRecording() {
  clearInterval(recorderTimer);
  recorderTimer = null;
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
}

function stopAndCancelRecording() {
  clearInterval(recorderTimer);
  recorderTimer = null;
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.onstop = null;
    mediaRecorder.stop();
  }
  audioStream?.getTracks().forEach(track => track.stop());
  mediaRecorder = null;
  audioStream = null;
  recordedBlob = null;
  if (recorderPreviewUrl) URL.revokeObjectURL(recorderPreviewUrl);
  recorderPreviewUrl = null;
  $("recordPanel")?.remove();
}

async function sendRecordedAudio() {
  if (!recordedBlob || !S.current) return;
  const mimeType = recordedBlob.type || "audio/webm";
  const extension = mimeType.includes("mp4") ? "m4a" : "webm";
  const file = new File([recordedBlob], `voice-${Date.now()}.${extension}`, { type: mimeType });
  $("recordPanel")?.remove();

  const formData = new FormData();
  formData.append("file", file);
  formData.append("kind", "audio");
  formData.append("room_id", S.current.id);

  try {
    const data = await uploadWithProgress("/api/upload", formData);
    let content = data.url;
    if (content.startsWith("/api/files/")) {
      content += (content.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(S.token);
    }
    sendMediaMessage("audio", content, recorderSeconds);
  } catch (error) {
    toast(error.message || "Tải tin ghi âm thất bại", true);
  } finally {
    recordedBlob = null;
    if (recorderPreviewUrl) URL.revokeObjectURL(recorderPreviewUrl);
    recorderPreviewUrl = null;
  }
}

$("recordBtn").onclick = () => {
  if (mediaRecorder && mediaRecorder.state !== "inactive") stopRecording();
  else startRecording();
};

/* ======================== MODAL ======================== */

function openModal(...nodes) {
  $("dialog").replaceChildren(...nodes);
  $("modal").classList.remove("hidden");
}

function closeModal() {
  $("modal").classList.add("hidden");
  $("dialog").classList.remove("profile-dialog");
  $("dialog").removeAttribute("role");
  $("dialog").removeAttribute("aria-modal");
  $("dialog").removeAttribute("aria-labelledby");
}

$("modal").addEventListener("mousedown", event => {
  if (event.target === $("modal")) {
    closeModal();
  }
});

/* ======================== PERSONAL PROFILE ======================== */

function openProfile() {
  renderProfileView();
}

function profileHeading(title, onClose = closeModal) {
  const close = el("button", {
    className: "icon profile-close",
    type: "button",
    textContent: "×",
    title: "Đóng hồ sơ",
    onclick: onClose,
  });
  close.setAttribute("aria-label", "Đóng hồ sơ");
  return el("div", { className: "profile-heading" },
    el("h3", { id: "profileTitle", textContent: title }),
    close,
  );
}

function showProfileDialog(...nodes) {
  openModal(el("section", { className: "profile-card" }, ...nodes));
  $("dialog").classList.add("profile-dialog");
  $("dialog").setAttribute("role", "dialog");
  $("dialog").setAttribute("aria-modal", "true");
  $("dialog").setAttribute("aria-labelledby", "profileTitle");
}

function renderProfileView() {
  const isOnline = S.ws && S.ws.readyState === WebSocket.OPEN;
  const createdAt = S.me.created_at ? new Date(S.me.created_at) : null;
  const joinedLabel = createdAt && !Number.isNaN(createdAt.getTime())
    ? createdAt.toLocaleDateString("vi-VN", { day: "2-digit", month: "long", year: "numeric" })
    : "Chưa có dữ liệu";
  const avatar = el("div", { className: "profile-large-avatar" });
  updateAvatarElement(avatar, S.me);

  const identity = el("div", { className: "profile-identity" },
    avatar,
    el("div", {},
      el("h2", { textContent: S.me.display_name || S.me.username }),
      el("p", { className: "profile-handle", textContent: "@" + S.me.username }),
      el("span", {
        className: "profile-status" + (isOnline ? " online" : ""),
        textContent: isOnline ? "Đang online" : (S.lost ? "Ngoại tuyến" : "Đang kết nối"),
      }),
    ),
  );
  const about = el("section", { className: "profile-section" },
    el("h4", { textContent: "Giới thiệu" }),
    el("p", {
      className: "profile-about",
      textContent: S.me.about || "Chưa có nội dung giới thiệu.",
    }),
  );
  const edit = el("button", {
    type: "button",
    textContent: "Chỉnh sửa hồ sơ",
    onclick: renderProfileEditor,
  });
  const joined = el("p", {
    className: "profile-joined",
    textContent: "Tham gia " + joinedLabel,
  });

  showProfileDialog(profileHeading("Hồ sơ cá nhân"), identity, about, joined, edit);
}

function renderProfileEditor() {
  let previewUrl = null;
  const avatar = el("div", { className: "profile-large-avatar" });
  updateAvatarElement(avatar, S.me);
  const fileInput = el("input", {
    type: "file",
    accept: IMG_TYPES.join(","),
    className: "hidden",
  });
  const chooseImage = el("button", {
    type: "button",
    className: "ghost small",
    textContent: "Chọn ảnh",
    onclick: () => fileInput.click(),
  });
  const displayName = el("input", {
    type: "text",
    value: S.me.display_name === S.me.username ? "" : (S.me.display_name || ""),
    placeholder: S.me.username,
    maxLength: 40,
    autocomplete: "nickname",
  });
  const about = el("textarea", {
    value: S.me.about || "",
    maxLength: 280,
    rows: 4,
    placeholder: "Viết vài dòng giới thiệu về bạn...",
  });
  const form = el("form", { className: "profile-form" },
    profileHeading("Chỉnh sửa hồ sơ", () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      closeModal();
    }),
    el("div", { className: "profile-avatar-editor" },
      avatar,
      el("div", {},
        el("b", { textContent: "Ảnh đại diện" }),
        el("small", { className: "muted", textContent: "JPG, PNG, GIF hoặc WEBP · tối đa 5MB" }),
        chooseImage,
      ),
      fileInput,
    ),
    el("label", { className: "profile-field" },
      el("span", { textContent: "Tên hiển thị" }),
      displayName,
    ),
    el("p", { className: "profile-username" },
      el("span", { textContent: "Username" }),
      el("b", { textContent: "@" + S.me.username }),
    ),
    el("label", { className: "profile-field" },
      el("span", { textContent: "Giới thiệu" }),
      about,
    ),
    el("div", { className: "profile-actions" },
      el("button", {
        type: "button",
        className: "ghost",
        textContent: "Hủy",
        onclick: () => {
          if (previewUrl) URL.revokeObjectURL(previewUrl);
          renderProfileView();
        },
      }),
      el("button", { type: "submit", textContent: "Lưu" }),
    ),
  );

  fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (!file) return;
    if (!IMG_TYPES.includes(file.type)) {
      fileInput.value = "";
      toast("Chỉ hỗ trợ ảnh JPG, PNG, GIF, WEBP", true);
      return;
    }
    if (file.size > MAX_IMG) {
      fileInput.value = "";
      toast("Ảnh vượt quá 5MB", true);
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(file);
    updateAvatarElement(avatar, S.me, previewUrl);
  };

  form.onsubmit = async event => {
    event.preventDefault();
    const save = form.querySelector('button[type="submit"]');
    save.disabled = true;
    save.textContent = "Đang lưu...";

    try {
      const updates = {
        display_name: displayName.value.trim(),
        about: about.value.trim(),
      };
      const file = fileInput.files[0];
      if (file) {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetch("/api/upload", {
          method: "POST",
          headers: { Authorization: "Bearer " + S.token },
          body: formData,
        });
        const upload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof upload.detail === "string" ? upload.detail : "Tải ảnh đại diện thất bại");
        }
        updates.avatar_url = upload.url;
      }

      S.me = await api("/api/auth/me", "PATCH", updates);
      if (S.me.avatar_url) {
        updateAvatarElement($("meAvatar"), S.me);
      }
      closeModal();
      toast("Cập nhật hồ sơ thành công");
    } catch (error) {
      toast(error.message, true);
    } finally {
      save.disabled = false;
      save.textContent = "Lưu";
    }
  };
}
