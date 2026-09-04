#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aidlc.py — point d'entree du moteur deterministe du harness AI-DLC.

Toute la logique vit dans le paquet stdlib `_aidlc/` (meme repertoire) : un module par
concern (util, checks, maturity, scaffold, improve, hookslog, okf, selftest, commands,
cli). Ce fichier ne fait que mettre le repertoire sur sys.path et appeler
`_aidlc.cli.main` — il garde le chemin d'invocation stable que les hooks, les skills et
les consommateurs utilisent : ${CLAUDE_PLUGIN_ROOT}/scripts/aidlc.py.

Contrat public (inchange) : sorties machine en JSON sur stdout, messages humains sur
stderr ; sous-commandes log, guard, validate, score, gate, review-request, status,
scaffold, improve, check-okf (<dir>, --touched, --stop), plus --selftest.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _aidlc.cli import main  # apres l'ajout au sys.path (import volontairement tardif)

if __name__ == "__main__":
    sys.exit(main())
