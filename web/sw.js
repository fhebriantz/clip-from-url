/* Service worker seadanya: menyimpan kerangka tampilan supaya aplikasi tetap
   terbuka rapi walau PC sedang mati, lalu menampilkan pesan yang jelas alih-alih
   layar galat browser.
   Catatan: hanya aktif di localhost atau HTTPS. Saat dibuka lewat alamat IP
   jaringan biasa (http://192.168.x.x), browser menolak mendaftarkannya. */

const VERSI = "cfu-v2";
const KERANGKA = ["/", "/style.css", "/app.js", "/manifest.json",
                  "/icons/icon-192.png", "/icons/icon-512.png",
                  "/icons/favicon-64.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSI).then((c) => c.addAll(KERANGKA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((k) => Promise.all(k.filter((n) => n !== VERSI).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  // Data selalu diambil langsung; hanya kerangka tampilan yang boleh dari cache.
  if (url.pathname.startsWith("/api/")) return;

  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const salinan = r.clone();
        caches.open(VERSI).then((c) => c.put(e.request, salinan));
        return r;
      })
      .catch(() => caches.match(e.request).then((c) => c || caches.match("/")))
  );
});
