'use strict';

/*
 * cyber-lab — Laboratoire d'entraînement à la cybersécurité (usage privé / éducatif)
 * ---------------------------------------------------------------------------------
 * Application VOLONTAIREMENT vulnérable, destinée à l'apprentissage sur un réseau
 * privé. Elle n'écoute que sur 127.0.0.1 et n'utilise que des modules intégrés à
 * Node.js (aucune installation requise).
 *
 * Chaque défi expose une faille classique. Un commutateur « mode sécurisé » permet
 * de comparer la version vulnérable et la version corrigée. Le but pédagogique est
 * de comprendre la cause, la détection, puis la remédiation.
 *
 *   node server.js            -> démarre en mode vulnérable (défaut)
 *   SAFE=1 node server.js     -> démarre en mode sécurisé (corrections actives)
 *   PORT=4000 node server.js  -> change le port (défaut 3000)
 *
 * NE PAS exposer ce service sur un réseau non maîtrisé.
 */

const http = require('http');
const crypto = require('crypto');
const { URL } = require('url');
const path = require('path');
const fs = require('fs');

const HOST = '127.0.0.1';
const PORT = Number(process.env.PORT) || 3000;
const SAFE = process.env.SAFE === '1';

// --- Données de démonstration (en mémoire, réinitialisées à chaque lancement) ---
const users = [
  { id: 1, username: 'alice', password: 'password123', role: 'user', secret: 'Journal privé d\'Alice' },
  { id: 2, username: 'bob', password: 'qwerty', role: 'user', secret: 'Notes de Bob' },
  { id: 3, username: 'admin', password: 'S3cr3t-Adm1n!', role: 'admin', secret: 'DRAPEAU{idor_et_auth_faibles}' },
];

// Jetons de session très simples (en clair) — le point faible est volontaire.
const sessions = new Map(); // token -> userId

function makeToken(userId) {
  const token = crypto.randomBytes(16).toString('hex');
  sessions.set(token, userId);
  return token;
}

function parseCookies(req) {
  const header = req.headers.cookie || '';
  const out = {};
  header.split(';').forEach((p) => {
    const i = p.indexOf('=');
    if (i > -1) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}

function currentUser(req) {
  const token = parseCookies(req).session;
  if (!token || !sessions.has(token)) return null;
  return users.find((u) => u.id === sessions.get(token)) || null;
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, Object.assign({ 'Content-Type': 'text/html; charset=utf-8' }, headers));
  res.end(body);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function layout(title, inner) {
  const banner = SAFE
    ? '<span class="tag safe">MODE SÉCURISÉ</span>'
    : '<span class="tag vuln">MODE VULNÉRABLE</span>';
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} — cyber-lab</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body><header><a href="/" class="brand">cyber-lab</a>${banner}</header>
<main>${inner}</main>
<footer>Laboratoire éducatif — réseau privé uniquement. Ne jamais tester sur un système sans autorisation.</footer>
</body></html>`;
}

// ------------------------------------------------------------------
// Défi 1 — Injection (recherche d'utilisateur)
// Vulnérable : construction d'un filtre à partir d'une expression non validée
// évaluée dynamiquement. Corrigé : comparaison littérale sûre.
// ------------------------------------------------------------------
function challengeSearch(res, query) {
  const q = query.get('q') || '';
  let results = [];
  let note = '';
  if (q) {
    if (SAFE) {
      // Correction : filtrage simple, aucune interprétation de l'entrée.
      const needle = q.toLowerCase();
      results = users.filter((u) => u.username.toLowerCase().includes(needle));
    } else {
      // Faille : l'entrée est injectée dans un prédicat interprété.
      // Un attaquant peut écrire par ex.  true  pour tout révéler.
      try {
        // eslint-disable-next-line no-new-func
        const pred = new Function('u', `return (${q});`);
        results = users.filter((u) => {
          try { return pred(u); } catch { return false; }
        });
      } catch (e) {
        note = 'Expression invalide : ' + escapeHtml(e.message);
      }
    }
  }
  const rows = results
    .map((u) => `<tr><td>${u.id}</td><td>${escapeHtml(u.username)}</td><td>${escapeHtml(u.role)}</td></tr>`)
    .join('');
  send(res, 200, layout('Recherche', `
    <h1>Défi 1 — Injection</h1>
    <p>Recherche d'utilisateur par nom.</p>
    <form><input name="q" value="${escapeHtml(q)}" placeholder="nom..." autofocus>
    <button>Chercher</button></form>
    ${note ? `<p class="note">${note}</p>` : ''}
    <table><thead><tr><th>id</th><th>nom</th><th>rôle</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="hint">Objectif : afficher tous les comptes alors que le champ ne devrait
    permettre qu'une recherche par nom. ${SAFE ? 'En mode sécurisé, l\'entrée est traitée comme une simple chaîne.' : ''}</p>
  `));
}

// ------------------------------------------------------------------
// Défi 2 — XSS réfléchi (message de bienvenue)
// Vulnérable : le paramètre est inséré sans échappement.
// Corrigé : échappement systématique.
// ------------------------------------------------------------------
function challengeGreet(res, query) {
  const name = query.get('name') || 'visiteur';
  const rendered = SAFE ? escapeHtml(name) : name; // faille : pas d'échappement
  send(res, 200, layout('Bienvenue', `
    <h1>Défi 2 — XSS réfléchi</h1>
    <p>Bonjour, ${rendered} !</p>
    <form><input name="name" placeholder="votre nom" autofocus><button>Envoyer</button></form>
    <p class="hint">Objectif : faire exécuter du code dans la page via le paramètre
    <code>name</code>. ${SAFE ? 'En mode sécurisé, le contenu est échappé.' : ''}</p>
  `));
}

// ------------------------------------------------------------------
// Défi 3 — IDOR (accès direct à une ressource)
// Vulnérable : /profile?id=N ne vérifie pas la propriété.
// Corrigé : on ne sert que le profil de l'utilisateur authentifié.
// ------------------------------------------------------------------
function challengeProfile(req, res, query) {
  const me = currentUser(req);
  if (!me) {
    return send(res, 200, layout('Profil', `
      <h1>Défi 3 — IDOR</h1>
      <p>Vous devez être connecté. <a href="/login">Se connecter</a></p>
      <p class="hint">Identifiants de test : alice / password123</p>`));
  }
  let target;
  if (SAFE) {
    // Correction : l'identifiant de la cible vient de la session, pas de l'URL.
    target = me;
  } else {
    // Faille : l'identifiant vient directement de l'URL, sans contrôle d'accès.
    const id = Number(query.get('id') || me.id);
    target = users.find((u) => u.id === id);
  }
  if (!target) return send(res, 404, layout('Profil', '<h1>Introuvable</h1>'));
  send(res, 200, layout('Profil', `
    <h1>Défi 3 — IDOR</h1>
    <p>Connecté en tant que <strong>${escapeHtml(me.username)}</strong> (id ${me.id}).</p>
    <div class="card">
      <h2>Profil #${target.id} — ${escapeHtml(target.username)}</h2>
      <p>Secret : <code>${escapeHtml(target.secret)}</code></p>
    </div>
    <p class="hint">Objectif : lire le secret d'un autre compte (par ex. l'administrateur)
    ${SAFE ? '— impossible en mode sécurisé, seul votre propre profil est servi.' : 'en changeant le paramètre id dans l\'URL.'}</p>
  `));
}

// ------------------------------------------------------------------
// Défi 4 — Traversée de chemin (lecture de fichier de notes)
// Vulnérable : le nom de fichier n'est pas confiné au dossier notes/.
// Corrigé : normalisation + confinement.
// ------------------------------------------------------------------
const NOTES_DIR = path.join(__dirname, 'notes');
function challengeNotes(res, query) {
  const file = query.get('file') || 'bienvenue.txt';
  let content = '';
  let err = '';
  try {
    let target;
    if (SAFE) {
      // Correction : on retire tout composant de chemin et on confine au dossier.
      const base = path.basename(file);
      target = path.join(NOTES_DIR, base);
      const resolved = path.resolve(target);
      if (!resolved.startsWith(path.resolve(NOTES_DIR) + path.sep)) {
        throw new Error('Chemin hors du dossier notes');
      }
    } else {
      // Faille : concaténation directe, « ../ » permet de sortir du dossier.
      target = path.join(NOTES_DIR, file);
    }
    content = fs.readFileSync(target, 'utf8');
  } catch (e) {
    err = e.message;
  }
  send(res, 200, layout('Notes', `
    <h1>Défi 4 — Traversée de chemin</h1>
    <form><input name="file" value="${escapeHtml(file)}"><button>Lire</button></form>
    ${err ? `<p class="note">Erreur : ${escapeHtml(err)}</p>` : `<pre>${escapeHtml(content)}</pre>`}
    <p class="hint">Objectif : lire un fichier situé hors du dossier <code>notes/</code>
    ${SAFE ? '— bloqué en mode sécurisé.' : '(indice : séquences « ../ »).'}</p>
  `));
}

// ------------------------------------------------------------------
// Authentification (volontairement faible : cookie en clair, pas de durcissement)
// ------------------------------------------------------------------
function loginPage(res, message = '') {
  send(res, 200, layout('Connexion', `
    <h1>Connexion</h1>
    ${message ? `<p class="note">${escapeHtml(message)}</p>` : ''}
    <form method="post" action="/login">
      <input name="username" placeholder="utilisateur" autofocus>
      <input name="password" type="password" placeholder="mot de passe">
      <button>Entrer</button>
    </form>
    <p class="hint">Comptes de test : alice / password123 — bob / qwerty</p>
  `));
}

function handleLogin(req, res) {
  let body = '';
  req.on('data', (c) => { body += c; if (body.length > 1e4) req.destroy(); });
  req.on('end', () => {
    const params = new URLSearchParams(body);
    const username = params.get('username') || '';
    const password = params.get('password') || '';
    const user = users.find((u) => u.username === username && u.password === password);
    if (!user) return loginPage(res, 'Identifiants invalides.');
    const token = makeToken(user.id);
    // En mode sécurisé on ajoute les attributs de durcissement du cookie.
    const cookie = SAFE
      ? `session=${token}; HttpOnly; SameSite=Strict; Path=/`
      : `session=${token}; Path=/`;
    send(res, 302, '', { 'Set-Cookie': cookie, Location: '/profile' });
  });
}

// ------------------------------------------------------------------
// Fichiers statiques (CSS)
// ------------------------------------------------------------------
function serveStatic(res, name) {
  const safeName = path.basename(name);
  const file = path.join(__dirname, 'public', safeName);
  fs.readFile(file, (err, data) => {
    if (err) return send(res, 404, 'not found', { 'Content-Type': 'text/plain' });
    const type = safeName.endsWith('.css') ? 'text/css' : 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': type });
    res.end(data);
  });
}

function home(res) {
  send(res, 200, layout('Accueil', `
    <h1>cyber-lab</h1>
    <p>Laboratoire d'entraînement local. Chaque défi illustre une faille courante et sa correction.</p>
    <ol class="menu">
      <li><a href="/search">Défi 1 — Injection</a></li>
      <li><a href="/greet">Défi 2 — XSS réfléchi</a></li>
      <li><a href="/profile">Défi 3 — IDOR / contrôle d'accès</a></li>
      <li><a href="/notes">Défi 4 — Traversée de chemin</a></li>
    </ol>
    <p class="hint">Relancez avec <code>SAFE=1 node server.js</code> pour voir les versions corrigées.</p>
    <p>Consultez <code>WORKBOOK.md</code> pour la marche à suivre et les solutions.</p>
  `));
}

// ------------------------------------------------------------------
// Routage
// ------------------------------------------------------------------
const server = http.createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url, `http://${HOST}:${PORT}`);
  } catch {
    return send(res, 400, 'bad request', { 'Content-Type': 'text/plain' });
  }
  const p = url.pathname;
  const q = url.searchParams;

  if (p === '/') return home(res);
  if (p.startsWith('/static/')) return serveStatic(res, p.slice('/static/'.length));
  if (p === '/search') return challengeSearch(res, q);
  if (p === '/greet') return challengeGreet(res, q);
  if (p === '/profile') return challengeProfile(req, res, q);
  if (p === '/notes') return challengeNotes(res, q);
  if (p === '/login' && req.method === 'GET') return loginPage(res);
  if (p === '/login' && req.method === 'POST') return handleLogin(req, res);
  return send(res, 404, layout('Introuvable', '<h1>404</h1><p><a href="/">Accueil</a></p>'));
});

server.listen(PORT, HOST, () => {
  console.log(`cyber-lab — ${SAFE ? 'MODE SÉCURISÉ' : 'MODE VULNÉRABLE'}`);
  console.log(`En écoute sur http://${HOST}:${PORT}`);
  console.log('Arrêt : Ctrl+C');
});
