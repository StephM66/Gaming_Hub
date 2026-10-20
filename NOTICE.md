# Notices

Gaming Hub est publié sous licence MIT-0 (MIT sans obligation d'attribution, voir `LICENSE`).
Les parties ci-dessous viennent de projets sous licences compatibles, dont les mentions sont
reproduites ici.

## playactor

Le protocole PS5 (`custom_components/gaming_hub/protocols/remoteplay.py`, `ddp.py`) et les
tables de `custom_components/gaming_hub/protocols/rp_keys.py` sont portés en Python depuis
[playactor](https://github.com/dhleong/playactor) 0.4.1 (`src/remoteplay/`, `src/discovery/`),
publié sous licence ISC (déclarée dans son `package.json`) :

```text
ISC License

Copyright (c) Daniel Leong

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## psn-api

Les adresses et paramètres d'authentification du PlayStation Network
(`custom_components/gaming_hub/protocols/psn.py`) suivent
[psn-api](https://github.com/achievements-app/psn-api) (MIT), utilisé aussi par PS5-MQTT.

## PSNAWP

La signature des adresses d'icônes des jeux PS3 (`ps3_icon_url` dans
`custom_components/gaming_hub/protocols/psn.py` : clé HMAC publique et format de l'adresse) vient
de [PSNAWP](https://github.com/isFakeAccount/psnawp), publié sous licence MIT :

```text
The MIT License (MIT)

Copyright (c) 2021 isFakeAccount

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Compte Nintendo

L'identifiant d'application, les adresses, les paramètres de connexion et les en-têtes de l'API
du contrôle parental Nintendo (`custom_components/gaming_hub/protocols/nintendo.py`) suivent
[pynintendoauth](https://github.com/pantherale0/pynintendoauth) (Apache 2.0) et
[pynintendoparental](https://github.com/pantherale0/pynintendoparental) (MIT), de pantherale0,
utilisés par l'intégration officielle Contrôle parental Nintendo Switch. Le client est écrit
séparément ; aucun code n'en est copié.

## Projets étudiés, sans code repris

- [ps5-mqtt](https://github.com/FunkeyFlo/ps5-mqtt) (MIT) : emplacement et format du fichier
  d'appairage `/config/ps5-mqtt/credentials.json`, que Gaming Hub sait relire.
- [ps3-home-assistant](https://github.com/SDR3078/ps3-home-assistant) (Apache 2.0) et
  [webMAN MOD](https://github.com/aldostools/webMAN-MOD) : commandes HTTP de webMAN et
  structure de la page `/cpursx.ps3`.
- [Switch Assistant](https://github.com/ErSeraph/switch-assistant) (MIT) : sujets MQTT publiés
  par le module système de la Switch.
