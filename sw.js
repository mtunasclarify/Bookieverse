// BookieVerse Service Worker — Push + Offline Shell
const CACHE = 'bv-v1';

// ── Install: cache the app shell ──────────────────────────────────────────────
self.addEventListener('install', e => {
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(clients.claim());
});

// ── Push: receive and display notifications ───────────────────────────────────
self.addEventListener('push', e => {
    let data = {};
    try { data = e.data ? e.data.json() : {}; } catch (_) {}

    const title = data.title || 'BookieVerse';
    const body  = data.body  || 'You have a new notification';
    const icon  = data.icon  || '/icon-192.png';
    const badge = data.badge || '/icon-192.png';
    const tag   = data.tag   || 'bv-general';
    const url   = data.url   || '/';

    const options = {
        body,
        icon,
        badge,
        tag,
        renotify: true,
        data: { url },
        vibrate: [100, 50, 100],
        actions: data.actions || []
    };

    e.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification click: focus or open the app ────────────────────────────────
self.addEventListener('notificationclick', e => {
    e.notification.close();
    const targetUrl = (e.notification.data && e.notification.data.url) || '/';

    e.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(wcs => {
            // If app is already open, focus it and navigate
            for (const wc of wcs) {
                if (wc.url.includes(self.location.origin)) {
                    wc.focus();
                    wc.postMessage({ type: 'PUSH_NAV', url: targetUrl });
                    return;
                }
            }
            // Otherwise open fresh
            return clients.openWindow(targetUrl);
        })
    );
});

// ── Push subscription change ──────────────────────────────────────────────────
self.addEventListener('pushsubscriptionchange', e => {
    // Re-subscribe and inform the server — handled by the app on next load
    e.waitUntil(Promise.resolve());
});
