# Notices

Gaming Hub est publié sous CC0 1.0 (voir `LICENSE`), à l'exception des parties ci-dessous.

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

## Projets étudiés, sans code repris

- [ps5-mqtt](https://github.com/FunkeyFlo/ps5-mqtt) (MIT) : emplacement et format du fichier
  d'appairage `/config/ps5-mqtt/credentials.json`, que Gaming Hub sait relire.
- [ps3-home-assistant](https://github.com/SDR3078/ps3-home-assistant) (Apache 2.0) et
  [webMAN MOD](https://github.com/aldostools/webMAN-MOD) : commandes HTTP de webMAN et
  structure de la page `/cpursx.ps3`.
- [Switch Assistant](https://github.com/ErSeraph/switch-assistant) (MIT) : sujets MQTT publiés
  par le module système de la Switch.
