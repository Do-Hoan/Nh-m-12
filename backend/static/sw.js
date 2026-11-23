self.addEventListener("push", event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch {}
  event.waitUntil(self.registration.showNotification(data.title || "Tin nhắn mới - RealChat", {
    body: data.body || "Bạn có tin nhắn mới",
    icon: "/favicon.ico",
    badge: "/favicon.ico",
    tag: data.tag || "realchat",
    data: { url: data.url || "/" },
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    const existing = list.find(client => client.url.includes(location.origin));
    if (existing) return existing.focus();
    return clients.openWindow(event.notification.data?.url || "/");
  }));
});
