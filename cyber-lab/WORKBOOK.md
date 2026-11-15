# Cahier d'exercices — cyber-lab

Laboratoire d'entraînement à la cybersécurité pour un **réseau privé**, en contexte
éducatif. L'application écoute uniquement sur `127.0.0.1`. Ne la déployez jamais sur
un réseau partagé et ne testez jamais ces techniques sur un système sans autorisation
écrite du propriétaire.

## Démarrage

```bash
cd cyber-lab
node server.js              # mode vulnérable (défaut)
# puis ouvrir http://127.0.0.1:3000
```

Pour comparer avec les versions corrigées :

```bash
SAFE=1 node server.js       # mode sécurisé
```

Changer de port si 3000 est occupé : `PORT=4000 node server.js`.

## Méthode pour chaque défi

1. **Observer** le comportement normal.
2. **Formuler une hypothèse** sur ce que le code fait avec votre entrée.
3. **Tester** une entrée inattendue.
4. **Expliquer** la cause racine.
5. **Corriger** (comparer avec le mode `SAFE=1`).

---

## Défi 1 — Injection (`/search`)

**Comportement attendu :** rechercher un compte par son nom.

**Cause de la faille :** l'entrée est interprétée comme une expression au lieu d'être
traitée comme une donnée. C'est le même principe qu'une injection SQL : la frontière
entre *code* et *données* n'est pas respectée.

**Détection :** saisir une valeur qui n'est pas un nom mais une condition toujours vraie.

<details><summary>Solution</summary>

Saisir `true` dans le champ de recherche : tous les comptes s'affichent, alors que la
fonction n'est censée filtrer que par nom.

</details>

**Remédiation (visible en `SAFE=1`) :** traiter l'entrée comme une chaîne littérale et
filtrer avec une comparaison sûre (`includes`). En base de données réelle : requêtes
paramétrées / préparées, jamais de concaténation de chaîne.

---

## Défi 2 — XSS réfléchi (`/greet`)

**Comportement attendu :** afficher « Bonjour, &lt;nom&gt; ».

**Cause de la faille :** le paramètre `name` est inséré dans le HTML sans échappement.
Le navigateur ne distingue plus le texte du balisage.

**Détection :** fournir une valeur contenant des balises HTML et vérifier si elles sont
interprétées.

<details><summary>Solution</summary>

Ouvrir `http://127.0.0.1:3000/greet?name=<b>test</b>` : le mot s'affiche en gras, donc
le HTML est interprété. Une charge utile `<script>...</script>` s'exécuterait de la même
manière — c'est la base d'un vol de session ou d'une action à l'insu de la victime.

</details>

**Remédiation (visible en `SAFE=1`) :** échapper toute donnée non fiable avant insertion
dans le HTML (`&`, `<`, `>`, `"`, `'`). En complément : en-tête `Content-Security-Policy`,
cookies `HttpOnly`.

---

## Défi 3 — IDOR / contrôle d'accès (`/profile`)

**Comportement attendu :** afficher le profil de l'utilisateur connecté.

**Cause de la faille :** l'identifiant de la ressource provient de l'URL (`?id=N`) et
aucun contrôle ne vérifie que la ressource appartient à l'utilisateur. C'est une
*référence directe d'objet non sécurisée* (IDOR).

**Détection :** se connecter avec un compte, puis modifier l'identifiant dans l'URL.

<details><summary>Solution</summary>

1. Se connecter : `alice` / `password123`.
2. Ouvrir `http://127.0.0.1:3000/profile?id=3` pour lire le secret du compte `admin`.

Le secret de l'administrateur est accessible sans en avoir le droit.

</details>

**Remédiation (visible en `SAFE=1`) :** dériver l'identité de la ressource depuis la
session authentifiée, jamais depuis un paramètre contrôlé par le client ; appliquer un
contrôle d'accès côté serveur pour chaque ressource.

---

## Défi 4 — Traversée de chemin (`/notes`)

**Comportement attendu :** lire un fichier du dossier `notes/`.

**Cause de la faille :** le nom de fichier fourni est concaténé au chemin sans
confinement. Des séquences `../` permettent de sortir du dossier prévu.

**Détection :** demander un fichier situé en dehors de `notes/`.

<details><summary>Solution</summary>

Ouvrir `http://127.0.0.1:3000/notes?file=../secret-hors-notes.txt` : le fichier placé
hors du dossier `notes/` est lu, ce qui révèle le drapeau.

</details>

**Remédiation (visible en `SAFE=1`) :** réduire l'entrée à un nom de fichier
(`path.basename`), résoudre le chemin absolu et vérifier qu'il reste **strictement**
à l'intérieur du dossier autorisé avant toute lecture.

---

## Durcissement de session (transversal)

En mode vulnérable, le cookie de session n'a pas d'attributs de protection. En mode
`SAFE=1`, il reçoit `HttpOnly`, `SameSite=Strict` et `Path=/`. Comparez les en-têtes
`Set-Cookie` dans les outils de développement du navigateur (onglet Réseau).

## Pour aller plus loin

- Outils d'observation : onglet « Réseau » et « Console » du navigateur suffisent ici.
- Associer chaque défi à sa catégorie OWASP Top 10 (A01 contrôle d'accès, A03 injection…).
- Rédiger, pour chaque faille, une courte fiche : *cause → impact → correction → test de non-régression*.

## Rappel éthique

Ces compétences servent à **défendre** des systèmes. Elles ne s'exercent que sur des
cibles que l'on possède ou pour lesquelles on dispose d'une autorisation explicite.
