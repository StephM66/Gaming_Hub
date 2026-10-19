# Sécurité

## Signaler une vulnérabilité

Ne pas ouvrir d'issue publique. Utiliser **Security → Report a vulnerability** sur
[GitHub](https://github.com/StephM66/Gaming_Hub/security/advisories/new) : le signalement
reste privé.

Indiquer la version de Gaming Hub, la console concernée et, si possible, les étapes pour
reproduire. Ne jamais joindre de jeton NPSSO, de clé d'appairage PS5 (`regist_key`, `rp_key`)
ni de code d'accès : les remplacer par `***` dans les journaux.

## Pas de garantie de correctif

Le projet est fourni en l'état (voir le README). Les signalements sont examinés au mieux, sans
délai ni correctif garantis.

## À savoir avant d'installer

- **Jeton NPSSO du PlayStation Network** : il donne accès au compte PSN. Home Assistant le
  conserve, comme ses autres identifiants, dans `.storage` (en clair) et dans ses sauvegardes :
  protéger l'accès à Home Assistant et aux sauvegardes. Pour le révoquer : se déconnecter de
  tous les appareils dans les paramètres du compte PlayStation.
- **Clés d'appairage PS5 et code d'accès PSN** : même stockage. Retirer la console dans
  Paramètres → Système → Lecture à distance → Appareils associés pour révoquer l'appairage.
- **webMAN MOD (PS3) et Switch Assistant (Switch) n'ont pas d'authentification** : tout appareil
  du réseau local, ou tout client du broker MQTT, peut piloter ces consoles, indépendamment de
  Gaming Hub. Protéger le broker (identifiants, droits par sujet) et, si possible, isoler les
  consoles dans un réseau dédié.
- **Jaquettes Switch** : elles viennent d'un service tiers (`tinfoil.media`), qui reçoit
  l'identifiant des jeux lancés. Désactivable dans les options.
- Les échanges avec les consoles restent sur le réseau local. Seuls le PlayStation Network et
  le service de jaquettes Switch sont joints sur Internet.

## Protections en place

- Tout ce qui vient du réseau est borné : pages webMAN (256 Kio, expressions régulières à
  temps linéaire), réponses Lecture à distance (64 Kio), champs DDP, valeurs MQTT (sujets
  connus seulement, 255 caractères).
- Une console interrogée n'est crue que si la réponse vient de son adresse (DDP, appairage).
- Les adresses transmises à Home Assistant sont contrôlées : jaquettes PSN en HTTPS
  uniquement, flux de l'écran Switch en `rtsp://` simple, identifiant de jeu Switch au format
  attendu.
- Les messages affichés sur la PS3 ne peuvent pas enchaîner d'autre commande webMAN.
- Aucune dépendance Python externe ; les secrets ne sont jamais écrits dans les journaux.
- `tests/test_security.py` vérifie ces points avec des données hostiles.
