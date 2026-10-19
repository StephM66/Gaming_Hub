# Sécurité

## Signaler une vulnérabilité

Ne pas ouvrir d'issue publique. Utiliser **Security → Report a vulnerability** sur
[GitHub](https://github.com/StephM66/Gaming_Hub/security/advisories/new) : le signalement
reste privé jusqu'à sa correction.

Indiquer la version de Gaming Hub, la console concernée et, si possible, les étapes pour
reproduire. Ne jamais joindre de jeton NPSSO, de clé d'appairage PS5 (`regist_key`, `rp_key`)
ni de code d'accès : les remplacer par `***` dans les journaux.

## Versions suivies

Seule la dernière version publiée reçoit des correctifs.

## Données sensibles manipulées

- Jeton NPSSO du compte PlayStation Network et jetons OAuth qui en découlent : stockés par Home
  Assistant (`.storage/core.config_entries` et `.storage/gaming_hub.*`), jamais journalisés.
- Clés d'appairage Lecture à distance de la PS5 et code d'accès PSN : stockés dans l'entrée de
  configuration.
- Les échanges avec les consoles restent sur le réseau local ; seuls les appels au PlayStation
  Network et au service de jaquettes Switch (désactivable) sortent sur Internet.
