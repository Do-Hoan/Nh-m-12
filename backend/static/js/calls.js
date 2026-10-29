/* RealChat - gọi thoại/video bằng WebRTC. WebSocket chỉ làm kênh signaling (xem docs/protocol.md).
 *
 * Quy ước mesh: người MỚI VÀO cuộc gọi tạo offer tới từng người ĐÃ Ở TRONG cuộc gọi.
 *   1-1:  A gọi -> B nghe máy -> B nhận danh sách [A] trong call.joined -> B offer tới A.
 *   Nhóm: D tham gia -> D offer tới A, B, C -> mỗi cặp người có đúng 1 RTCPeerConnection (mesh).
 */
"use strict";
let ICE = null;       // cấu hình ICE lấy từ server (STUN + TURN)
S.call = null;        // cuộc gọi đang diễn ra
S.pendingIn = null;   // cuộc gọi đến đang hiện popup
let ringTimer = null, audioCtx = null;

async function loadIce() {
  if (ICE) return ICE;
  try { ICE = (await api("/api/ice-servers")).iceServers; }
  catch { ICE = [{ urls: ["stun:stun.l.google.com:19302"] }]; }
  return ICE;
}

async function getMedia(media) {
  // getUserMedia chỉ có trên HTTPS (hoặc localhost)
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
    throw new Error("Trình duyệt không hỗ trợ gọi. Hãy mở trang bằng HTTPS.");
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: true, video: media === "video" ? { facingMode: "user" } : false });
  } catch {
    throw new Error(media === "video" ? "Không truy cập được camera/micro. Hãy cấp quyền cho trang." : "Không truy cập được micro. Hãy cấp quyền cho trang.");
  }
}

/* ---------------- Bắt đầu / tham gia cuộc gọi ---------------- */
async function startCall(media) {
  const room = S.current;
  if (!room) return;
  if (S.call || S.pendingIn) return toast("Bạn đang trong một cuộc gọi khác", true);
  let local;
  try { local = await getMedia(media); } catch (e) { return toast(e.message, true); }
  await loadIce();
  S.call = newCall({ roomId: room.id, media, isGroup: room.type === "group", local, title: room.name, status: "Đang gọi..." });
  showCallScreen();
  if (!wsSend({ type: "call.invite", room_id: room.id, media })) { toast("Chưa kết nối máy chủ", true); endCallLocal(); }
}
$("voiceBtn").onclick = () => startCall("audio");
$("videoBtn").onclick = () => startCall("video");

async function joinCall(callId, roomId, media, isGroup, title) {
  if (S.call) return;
  let local;
  try { local = await getMedia(media); } catch (e) { return toast(e.message, true); }
  await loadIce();
  S.call = newCall({ id: callId, roomId, media, isGroup, local, title, status: "Đang kết nối..." });
  showCallScreen();
  wsSend({ type: "call.accept", call_id: callId });   // server trả call.joined kèm danh sách người đang trong cuộc gọi
}
$("joinCallBtn").onclick = () => {
  const st = S.callStatus[S.current.id];
  if (st && st.call_id) joinCall(st.call_id, S.current.id, st.media, true, S.current.name);
};

function newCall(o) {
  return { id: null, joined: false, peers: new Map(), users: {}, connectedAt: null, tick: null, ...o };
}

/* ---------------- Cuộc gọi đến (popup) ---------------- */
function showIncoming(ev) {
  if (S.call || S.pendingIn) return wsSend({ type: "call.reject", call_id: ev.call_id });
  S.pendingIn = ev;
  $("inAvatar").textContent = ev.from.username[0].toUpperCase();
  $("inName").textContent = ev.is_group ? `# ${ev.room_name}` : ev.from.username;
  $("inText").textContent = (ev.is_group ? `${ev.from.username} đang gọi nhóm ` : "đang gọi ") + (ev.media === "video" ? "video" : "thoại");
  $("incoming").classList.remove("hidden");
  startRing();
}
function hideIncoming() { S.pendingIn = null; $("incoming").classList.add("hidden"); stopRing(); }

$("rejectBtn").onclick = () => { if (S.pendingIn) wsSend({ type: "call.reject", call_id: S.pendingIn.call_id }); hideIncoming(); };
$("acceptBtn").onclick = async () => {
  const ev = S.pendingIn;
  if (!ev) return;
  hideIncoming();
  await joinCall(ev.call_id, ev.room_id, ev.media, ev.is_group, ev.is_group ? ev.room_name : ev.from.username);
  if (!S.call) wsSend({ type: "call.reject", call_id: ev.call_id }); // không lấy được mic/camera -> từ chối
};

// Chuông đơn giản bằng WebAudio (có thể bị chặn nếu người dùng chưa tương tác với trang)
function startRing() {
  stopRing();
  const beep = () => {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.frequency.value = 880; g.gain.value = 0.08;
      o.connect(g); g.connect(audioCtx.destination);
      o.start(); o.stop(audioCtx.currentTime + 0.4);
    } catch { /* bỏ qua */ }
    if (navigator.vibrate) navigator.vibrate(300);
  };
  beep(); ringTimer = setInterval(beep, 1500);
}
function stopRing() { clearInterval(ringTimer); ringTimer = null; }

/* ---------------- Xử lý sự kiện cuộc gọi từ server ---------------- */
async function handleCallEvent(ev) {
  const c = S.call;
  switch (ev.type) {
    case "call.ringing":
      if (!c) return wsSend({ type: "call.end", call_id: ev.call_id }); // đã cúp trước khi server kịp trả lời
      c.id = ev.call_id; setStatus("Đang đổ chuông..."); break;
    case "call.busy": toast("Người này đang bận cuộc gọi khác", true); endCallLocal(); break;
    case "call.unavailable": toast("Người này đang offline, không thể gọi", true); endCallLocal(); break;
    case "call.incoming": showIncoming(ev); break;
    case "call.dismiss":
      if (S.pendingIn && S.pendingIn.call_id === ev.call_id) {
        hideIncoming();
        if (ev.reason === "timeout") toast("Bạn đã nhỡ một cuộc gọi");
        if (ev.reason === "cancelled") toast("Người gọi đã hủy cuộc gọi");
      }
      break;
    case "call.joined":
      if (!c) return;
      c.joined = true; setStatus("Đang kết nối...");
      for (const u of ev.participants) { c.users[u.id] = u; await sendOffer(makePeer(u)); }  // người mới vào chủ động offer
      break;
    case "call.participant_joined":
      if (!c) return;
      c.joined = true; c.users[ev.user.id] = ev.user;
      addPeerTile(ev.user); setStatus("Đang kết nối..."); break;   // chờ nhận offer từ người mới
    case "call.participant_left":
      if (!c) return;
      removePeer(ev.user.id); toast(`${ev.user.username} đã rời cuộc gọi`); break;
    case "call.rejected": toast(`${ev.user.username} đã từ chối cuộc gọi`); break;
    case "call.ended": {
      if (!c || c.id !== ev.call_id) return;
      const msg = { timeout: "Không có người trả lời", rejected: "Cuộc gọi bị từ chối", cancelled: "Cuộc gọi đã hủy" }[ev.reason] || "Cuộc gọi đã kết thúc";
      toast(msg); endCallLocal(); break;
    }
    case "call.status":
      if (ev.call_id) S.callStatus[ev.room_id] = ev; else delete S.callStatus[ev.room_id];
      renderHeader(); renderSidebar(); break;
    case "webrtc.offer": if (c && c.id === ev.call_id) await onOffer(ev); break;
    case "webrtc.answer": {
      const p = c && c.id === ev.call_id && c.peers.get(ev.from);
      if (p) { await p.pc.setRemoteDescription(ev.payload.sdp); await flushIce(p); }
      break;
    }
    case "webrtc.ice": {
      const p = c && c.id === ev.call_id && c.peers.get(ev.from);
      if (!p) break;
      if (p.pc.remoteDescription) p.pc.addIceCandidate(ev.payload.candidate).catch(() => {});
      else p.pending.push(ev.payload.candidate);   // chưa có remote description thì xếp hàng chờ
      break;
    }
  }
}

function handleCallError(ev) {
  // Lỗi khi mời/tham gia (đã đầy, không còn cuộc gọi...) -> đóng màn hình cuộc gọi vừa mở
  if (S.call && !S.call.joined && ["ALREADY_IN_CALL", "CALL_EXISTS", "CALL_FULL", "NO_CALL"].includes(ev.code)) endCallLocal();
}

/* ---------------- WebRTC peer ---------------- */
function makePeer(user) {
  const c = S.call;
  if (c.peers.has(user.id)) return c.peers.get(user.id);
  const pc = new RTCPeerConnection({ iceServers: ICE || [] });
  const p = { user, pc, pending: [], tile: addPeerTile(user) };
  c.peers.set(user.id, p);
  c.local.getTracks().forEach(t => pc.addTrack(t, c.local));
  pc.onicecandidate = e => {
    if (e.candidate) wsSend({ type: "webrtc.ice", call_id: c.id, to: user.id, payload: { candidate: e.candidate } });
  };
  pc.ontrack = e => { p.tile.video.srcObject = e.streams[0]; };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "connected") { p.tile.label.textContent = user.username; markConnected(); }
    if (pc.connectionState === "failed" || pc.connectionState === "disconnected") p.tile.label.textContent = user.username + " (mất kết nối)";
  };
  return p;
}

async function sendOffer(p) {
  const c = S.call;
  const offer = await p.pc.createOffer();
  await p.pc.setLocalDescription(offer);
  wsSend({ type: "webrtc.offer", call_id: c.id, to: p.user.id, payload: { sdp: p.pc.localDescription } });
}

async function onOffer(ev) {
  const c = S.call;
  const user = c.users[ev.from] || S.users.find(u => u.id === ev.from) || { id: ev.from, username: "Người dùng" };
  const p = makePeer(user);
  await p.pc.setRemoteDescription(ev.payload.sdp);
  await flushIce(p);
  const answer = await p.pc.createAnswer();
  await p.pc.setLocalDescription(answer);
  wsSend({ type: "webrtc.answer", call_id: c.id, to: ev.from, payload: { sdp: p.pc.localDescription } });
}

async function flushIce(p) {
  while (p.pending.length) await p.pc.addIceCandidate(p.pending.shift()).catch(() => {});
}

function removePeer(userId) {
  const c = S.call, p = c && c.peers.get(userId);
  if (!p) { const t = c && c.tiles && c.tiles.get(userId); if (t) { t.el.remove(); c.tiles.delete(userId); layoutTiles(); } return; }
  p.pc.close(); p.tile.el.remove(); c.peers.delete(userId); c.tiles.delete(userId); layoutTiles();
}

/* ---------------- Giao diện màn hình cuộc gọi ---------------- */
function makeTile(name, { local = false } = {}) {
  const el = document.createElement("div");
  el.className = "tile" + (local ? " local" : "") + (S.call.media === "audio" ? " audio" : "");
  const video = document.createElement("video");
  video.autoplay = true; video.playsInline = true;
  if (local) video.muted = true;   // tắt tiếng video local để không bị vọng lại
  const av = document.createElement("div"); av.className = "avatar"; av.textContent = name[0].toUpperCase();
  const label = document.createElement("span"); label.className = "label"; label.textContent = name;
  el.append(video, av, label);
  $("tiles").append(el);
  return { el, video, label };
}

function addPeerTile(user) {
  const c = S.call;
  c.tiles = c.tiles || new Map();
  if (c.tiles.has(user.id)) return c.tiles.get(user.id);
  const t = makeTile(user.username);
  t.label.textContent = user.username + " (đang kết nối...)";
  c.tiles.set(user.id, t);
  layoutTiles();
  return t;
}

function layoutTiles() {
  const n = $("tiles").children.length;
  const box = $("tiles");
  box.className = "n" + Math.min(n, 4) + (n === 2 && S.call && S.call.media === "video" ? " pip" : "");
}

function showCallScreen() {
  const c = S.call;
  $("callTitle").textContent = (c.isGroup ? "# " : "") + c.title + (c.media === "video" ? " - video" : " - thoại");
  $("tiles").replaceChildren();
  const t = makeTile("Bạn", { local: true });
  t.video.srcObject = c.local;
  if (c.media === "audio") t.el.classList.add("audio");
  c.tiles = new Map();
  $("camBtn").classList.toggle("hidden", c.media !== "video");
  $("micBtn").textContent = "Mic"; $("micBtn").classList.remove("off");
  $("camBtn").textContent = "Camera"; $("camBtn").classList.remove("off");
  setStatus(c.status);
  layoutTiles();
  $("callScreen").classList.remove("hidden");
  renderHeader();
}

function setStatus(text) { if (S.call && !S.call.connectedAt) $("callStatus").textContent = text; }

function markConnected() {
  const c = S.call;
  if (!c || c.connectedAt) return;
  c.connectedAt = Date.now();
  c.tick = setInterval(() => {
    const s = Math.floor((Date.now() - c.connectedAt) / 1000);
    $("callStatus").textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }, 1000);
}

function toggleTracks(kind, btn, onText, offText) {
  const tracks = S.call.local.getTracks().filter(t => t.kind === kind);
  const enable = !tracks.every(t => t.enabled);
  tracks.forEach(t => (t.enabled = enable));
  btn.textContent = enable ? onText : offText;
  btn.classList.toggle("off", !enable);
  if (kind === "video") S.call.tiles && $("tiles").querySelector(".tile.local").classList.toggle("nocam", !enable);
}
$("micBtn").onclick = () => S.call && toggleTracks("audio", $("micBtn"), "Mic", "Mic tắt");
$("camBtn").onclick = () => S.call && toggleTracks("video", $("camBtn"), "Camera", "Camera tắt");

// Cúp máy / hủy / rời cuộc gọi: đều gửi call.end, server tự quyết định kết thúc hay chỉ rời
$("hangBtn").onclick = () => {
  if (S.call && S.call.id) wsSend({ type: "call.end", call_id: S.call.id });
  endCallLocal();
};

function endCallLocal() {
  const c = S.call;
  S.call = null;
  if (!c) return;
  clearInterval(c.tick);
  c.peers.forEach(p => p.pc.close());
  c.local.getTracks().forEach(t => t.stop());
  $("tiles").replaceChildren();
  $("callStatus").textContent = "";
  $("callScreen").classList.add("hidden");
  renderHeader();
}

window.addEventListener("beforeunload", () => { if (S.call && S.call.id) wsSend({ type: "call.end", call_id: S.call.id }); });
