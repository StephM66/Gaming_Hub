# Essais sur console

Les tests automatiques couvrent les protocoles (consoles simulées), la logique et l'intégration
dans Home Assistant. Restent à valider sur du vrai matériel les points marqués ci-dessous.
Consoles disponibles : PS5, PS3, Switch première génération.

Activer les journaux détaillés pendant les essais :

```yaml
logger:
  default: warning
  logs:
    custom_components.gaming_hub: debug
```

## PlayStation 5

| # | Essai | Attendu |
|---|---|---|
| 1 | Ajout : l'adresse est-elle proposée ? | IP de la PS5 préremplie (découverte DDP en diffusion) |
| 2 | Reprise de l'appairage PS5-MQTT | entrée créée sans PIN ; PS5-MQTT arrêté ensuite |
| 3 | Appairage par PIN (autre essai, après suppression de l'entrée) | entrée créée ; « Appareils associés » de la PS5 liste le client |
| 4 | États | allumée → `on`, mode repos → `standby`, débranchée → `off` en moins de 20 s |
| 5 | Allumer depuis le mode repos | PS5 allumée en moins de 30 s |
| 6 | Éteindre (mode repos) | PS5 en mode repos ; pas d'erreur `command_failed` |
| 7 | Éteindre avec un compte protégé par code d'accès | sans code : erreur `passcode_required` ; avec code : OK |
| 8 | Jeu en cours via PlayStation Network | titre et jaquette sur le `media_player` du hub |
| 9 | Version du système | capteur au format `x.yy` (sinon, noter la valeur brute) |

Point sensible : la mise en veille (essais 6 et 7) passe par le portage Python du canal de
contrôle Remote Play. Il est vérifié octet par octet contre playactor, mais pas encore face à
une vraie console. En cas d'échec, joindre le journal `debug` et, si possible, la sortie de
`playactor standby` avec `DEBUG=playactor:*` pour la même console.

## PlayStation 3 (webMAN MOD)

| # | Essai | Attendu |
|---|---|---|
| 1 | Ajout console allumée | entrée créée ; identifiant = adresse MAC |
| 2 | Sur le XMB | `on`, pas de jeu ; températures et ventilateur renseignés |
| 3 | En jeu (disque, ISO, PSN) | `playing`, titre sans numéro de version, icône |
| 4 | Jeu PS2/PS1/rétro | `playing` même sans titre, si webMAN le signale |
| 5 | Message à l'écran | notification affichée sur la TV |
| 6 | Redémarrer / Éteindre | console redémarrée / éteinte, puis `off` |
| 7 | Allumage par script (HDMI-CEC ou autre) | console allumée, puis `on` |

Pour fiabiliser l'analyse de la page webMAN, capturer deux pages réelles et les joindre (elles
remplaceront les pages reconstituées de `tests/fixtures/`) :

```sh
curl -s http://IP_PS3/cpursx.ps3 -o cpursx_xmb.html      # sur le XMB
curl -s http://IP_PS3/cpursx.ps3 -o cpursx_jeu.html      # en jeu
```

## Nintendo Switch (Switch Assistant)

| # | Essai | Attendu |
|---|---|---|
| 1 | Découverte MQTT | notification « Nouvel appareil détecté » pour la Switch |
| 2 | Accueil / en jeu | `on` / `playing` avec le titre |
| 3 | Jaquette | image du jeu (sinon, essayer un autre modèle d'URL dans les options) |
| 4 | Mise en veille | `off` environ 45 s après |
| 5 | Message à l'écran | popup affichée par la surcouche |
| 6 | Redémarrer / Éteindre | commande exécutée |
| 7 | Batterie, charge, manettes | valeurs cohérentes avec la console |

## Contrôle parental et consommation (une console suffit)

| # | Essai | Attendu |
|---|---|---|
| 1 | Limite 10 min, préavis 2 min, action « éteindre » | avertissement à 8 min, extinction à 10 min, événements `warning` puis `enforced` |
| 2 | Rallumer après la limite | message, puis extinction au bout d'une minute |
| 3 | Plage 09:00–20:00, essai à 20:05 | blocage avec la raison `schedule` |
| 4 | Redémarrage de Home Assistant en cours de journée | temps de jeu conservé |
| 5 | Prise connectée associée | « Puissance » = valeur de la prise, attribut `source: measured` |
