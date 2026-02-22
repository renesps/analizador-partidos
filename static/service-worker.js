/* ══════════════════════════════════════════════════════════════════════════
   Service Worker — Analizador de Partidos PWA
   Estrategia:
   - Shell (HTML + iconos + manifest) → Cache First (siempre offline)
   - Google Fonts → Cache First con fallback sin fuente
   - Sofascore / OpenRouter / The Odds API → Network Only (necesitan red)
   - /sf proxy, /odds → Network Only
   - Todo lo demás → Network First con fallback al cache
══════════════════════════════════════════════════════════════════════════ */

const CACHE_NAME  = 'analizador-v1';
const SHELL_CACHE = 'analizador-shell-v1';

// Recursos del app shell — se cachean al instalar
const SHELL_URLS = [
  '/',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-144.png',
  '/static/icons/icon-96.png',
];

// Dominios que SIEMPRE van a la red (nunca cachear)
const NETWORK_ONLY_HOSTS = [
  'api.sofascore.com',
  'api.openrouter.ai',
  'api.the-odds-api.com',
  'api.scraperapi.com',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

// Rutas del propio servidor que van a la red (datos en tiempo real)
const NETWORK_ONLY_PATHS = ['/sf', '/odds', '/historial'];

// ── Install: cachear el shell ─────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(cache => {
      return cache.addAll(SHELL_URLS).catch(err => {
        console.warn('[SW] Shell cache parcial:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: limpiar caches viejos ──────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== SHELL_CACHE)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: estrategia híbrida ─────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // Solo manejar GET
  if (req.method !== 'GET') return;

  // Network-only: dominios externos
  if (NETWORK_ONLY_HOSTS.some(h => url.hostname.includes(h))) {
    return; // dejar pasar sin interceptar
  }

  // Network-only: rutas de API propias
  if (NETWORK_ONLY_PATHS.some(p => url.pathname.startsWith(p))) {
    return; // dejar pasar sin interceptar
  }

  // Cache-first para el shell (raíz y recursos estáticos)
  if (url.pathname === '/' || url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then(cached => {
        if (cached) return cached;
        return fetch(req).then(resp => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(SHELL_CACHE).then(c => c.put(req, clone));
          }
          return resp;
        }).catch(() => {
          // Offline fallback: si piden '/' y no hay red, devolver el shell cacheado
          if (url.pathname === '/') return caches.match('/');
        });
      })
    );
    return;
  }

  // Network-first para todo lo demás
  event.respondWith(
    fetch(req)
      .then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE_NAME).then(c => c.put(req, clone));
        }
        return resp;
      })
      .catch(() => caches.match(req))
  );
});

// ── Mensaje: forzar actualización desde el cliente ────────────────────────
self.addEventListener('message', event => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
