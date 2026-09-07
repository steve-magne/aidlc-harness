#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""aidlc-dev — les portes de CE depot, hors du plugin que consomment les projets.

`test`, `coverage`, `selfscore` et `ratchet` notent, mesurent et figent le harnais
lui-meme. Elles n'ont aucun sens dans un projet consommateur, qui n'a pas a savoir
comment le moteur est maintenu : elles vivent donc ici, a la racine du depot auteur, et
`aidlc --help` ne les montre plus.

Le moteur, lui, reste unique : ce point d'entree appelle le meme `_aidlc.cli.main`, en
lui demandant simplement d'exposer les sous-commandes de maintenance.
"""

import os
import sys

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "plugins", "aidlc", "scripts")
sys.path.insert(0, os.path.abspath(ENGINE))

from _aidlc.cli import main  # apres l'ajout au sys.path (import volontairement tardif)

if __name__ == "__main__":
    sys.exit(main(dev=True))
