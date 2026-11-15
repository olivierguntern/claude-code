# cyber-lab

Laboratoire d'entraînement à la cybersécurité, **local et éducatif**. Application web
volontairement vulnérable, à utiliser sur un réseau privé pour apprendre à repérer et
à corriger des failles courantes.

- **Aucune dépendance** : uniquement des modules intégrés à Node.js (v18+).
- **Écoute uniquement sur `127.0.0.1`** — n'expose rien sur le réseau.
- Deux modes : **vulnérable** (défaut) et **sécurisé** (`SAFE=1`) pour comparer avant/après.

## Lancer

```bash
cd cyber-lab
node server.js
# ouvrir http://127.0.0.1:3000
```

Mode corrigé : `SAFE=1 node server.js`. Autre port : `PORT=4000 node server.js`.

## Défis

| # | Faille | Page |
|---|--------|------|
| 1 | Injection | `/search` |
| 2 | XSS réfléchi | `/greet` |
| 3 | IDOR / contrôle d'accès | `/profile` |
| 4 | Traversée de chemin | `/notes` |

Comptes de test : `alice` / `password123`, `bob` / `qwerty`.

La marche à suivre, les indices et les solutions sont dans [`WORKBOOK.md`](./WORKBOOK.md).

## Avertissement

Ce projet contient des vulnérabilités **intentionnelles** à des fins pédagogiques. Ne le
déployez jamais sur un serveur accessible et n'appliquez ces techniques qu'à des systèmes
que vous possédez ou pour lesquels vous avez une autorisation écrite.
