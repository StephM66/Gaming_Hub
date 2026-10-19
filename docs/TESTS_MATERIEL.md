# Essais sur console

Les tests automatiques couvrent les protocoles (consoles simulées), la logique et l'intégration
dans Home Assistant. Restent à valider sur du vrai matériel les points marqués ci-dessous.
Consoles disponibles : PS5, PS3, Switch première génération, aucune modifiée.

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
| 8 | Compte PSN (jeton NPSSO) à l'ajout | entrée créée ; identifiant de compte prérempli pour le PIN |
| 9 | Jeu en cours via le compte PSN | titre et jaquette sur le `media_player` du hub, moins d'une minute après le lancement |
| 10 | Trophées, PlayStation Plus, statut PSN | valeurs cohérentes avec l'application PlayStation |
| 11 | Jeton NPSSO invalidé (déconnexion de playstation.com) | notification de ré-authentification ; la console reste pilotable |
| 12 | Version du système | capteur au format `x.yy` (sinon, noter la valeur brute) |

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
| 8 | Quitter le jeu | retour au XMB, bouton indisponible ensuite |
| 9 | Mode du ventilateur (SYSCON, dynamique, manuel) | capteur cohérent avec le réglage webMAN |
| 10 | Mémoire, disque, allumée depuis, durée de la partie | valeurs cohérentes avec la page webMAN |

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
| 8 | Caméra « Écran » pendant un jeu | image en direct (le flux RTSP n'existe qu'en jeu) |
| 9 | Luminosité, volume, sortie audio, écran allumé | valeurs cohérentes avec la console |

## Nintendo Switch ou Switch 2 (compte Nintendo, sans modification)

Console associée à l'application Contrôle parental Nintendo Switch. Entité de présence : par
exemple l'entrée HDMI de la Sync Box (`linked` quand l'image arrive).

| # | Essai | Attendu |
|---|---|---|
| 1 | Ajout : lien de connexion, lien copié collé | console(s) du compte proposée(s) ; entrée créée, modèle Switch ou Switch 2 |
| 2 | Temps de jeu aujourd'hui, semaine, mois | mêmes valeurs que l'application Contrôle parental (à son délai près) |
| 3 | Lancer un jeu, console allumée (présence `on`) | `playing` avec titre et jaquette : **noter le délai** entre le lancement et l'affichage |
| 4 | Changer de jeu | nouveau titre affiché : noter le délai |
| 5 | Mettre la console en veille | `off` dès que l'entité de présence change |
| 6 | Sans entité de présence (option vidée) | `on` quand le temps de jeu augmente, `off` 30 min après la dernière minute ajoutée |
| 7 | Jeu Switch 2 | titre et jaquette présents (sinon, joindre les diagnostics) |
| 8 | Se déconnecter du compte Nintendo sur le site Nintendo | demande de reconnexion dans Home Assistant ; reconnexion par le même parcours |
| 9 | Redémarrage de Home Assistant en cours de jeu | pas de jeu affiché à tort ; temps de jeu inchangé |

Point sensible : le délai de synchronisation de la console vers Nintendo n'est pas connu. Les
essais 3, 4 et 6 le mesurent. S'il est long, le jeu en cours affiché arrive en retard.

## PlayStation 3 sans modification

| # | Essai | Attendu |
|---|---|---|
| 1 | Ajout avec l'entrée HDMI comme entité source, puis le compte PSN | entrée créée, modèle PlayStation 3 |
| 2 | PS3 allumée, sur le XMB | `on` d'après l'entité |
| 3 | PS3 connectée au PSN, en jeu | `playing` avec le titre et l'icône du jeu (compte PSN, moins de deux minutes) |
| 4 | PS3 éteinte | `off` dès que l'entité change |

## Contrôle parental et consommation (une console suffit)

| # | Essai | Attendu |
|---|---|---|
| 1 | Limite 10 min, préavis 2 min, action « éteindre » | avertissement à 8 min, extinction à 10 min, événements `warning` puis `enforced` |
| 2 | Rallumer après la limite | message, puis extinction au bout d'une minute |
| 3 | Plage 09:00–20:00, essai à 20:05 | blocage avec la raison `schedule` |
| 4 | Redémarrage de Home Assistant en cours de journée | temps de jeu conservé |
| 5 | Prise connectée associée dans les options | « Puissance » = valeur de la prise, « Énergie » augmente ; sans prise, ni l'un ni l'autre |
