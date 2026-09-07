from __future__ import annotations

import os
import sys
import unittest

from pathlib import Path

"""Suite de tests du moteur : decouverte unittest, un module par concern.

Ce paquet n'est **pas** un second point d'entree : il n'est atteignable que par
`aidlc.py test` (et son alias historique `aidlc.py --selftest`, que les hooks et la CI
appellent). `unittest` fait partie de la bibliotheque standard — la suite n'ajoute donc
aucune dependance et tourne chez n'importe quel consommateur avec `python3` seul.
"""

_HERE = Path(__file__).resolve().parent
#: Repertoire qui contient le paquet `_aidlc` — racine d'import de la decouverte.
_TOP_LEVEL = _HERE.parents[1]


def discover(pattern: str = "test_*.py") -> unittest.TestSuite:
    return unittest.defaultTestLoader.discover(
        str(_HERE), pattern=pattern, top_level_dir=str(_TOP_LEVEL))


def _select(suite: unittest.TestSuite, needle: str) -> unittest.TestSuite:
    """Filtre `-k` : garde les tests dont l'identifiant contient `needle`."""
    kept = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            sub = _select(item, needle)
            if sub.countTestCases():
                kept.addTest(sub)
        elif needle.lower() in item.id().lower():
            kept.addTest(item)
    return kept


#: Garde-fou de reentrance. `aidlc.py test` (et son alias `--selftest`) lance TOUTE la
#: suite ; or la suite invoque le CLI en sous-processus pour verifier son contrat. Sans
#: ce verrou, un seul test qui appelle `aidlc.py test` ou `aidlc.py coverage` relance la
#: suite entiere, indefiniment. Le verrou est une variable d'environnement parce que la
#: recursion passe justement par des sous-processus, qui l'heritent.
_REENTRANCY = "AIDLC_TEST_SUITE_RUNNING"


def run(select: str = None, verbosity: int = 1, failfast: bool = False) -> int:
    """Execute la suite. Renvoie 0 si tout passe, 1 sinon.

    Les messages vont sur **stderr** (comme tout message humain du moteur) : stdout
    reste reserve aux sorties machine.

    Une execution imbriquee (depuis un test) est refusee, pas executee : elle rend 0
    et le dit sur stderr. Un test qui veut verifier le routage du CLI vers la suite
    doit l'observer par substitution, jamais en relancant la suite.
    """
    if os.environ.get(_REENTRANCY):
        sys.stderr.write("Suite deja en cours : execution imbriquee ignoree.\n")
        return 0
    os.environ[_REENTRANCY] = "1"
    try:
        return _run(select, verbosity, failfast)
    finally:
        os.environ.pop(_REENTRANCY, None)


def _run(select: str, verbosity: int, failfast: bool) -> int:
    suite = discover()
    if select:
        suite = _select(suite, select)
        if not suite.countTestCases():
            sys.stderr.write(f"Aucun test ne correspond a -k {select!r}\n")
            return 1
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=verbosity,
                                     failfast=failfast).run(suite)
    total = result.testsRun
    if result.wasSuccessful():
        sys.stderr.write(f"OK: {total} tests\n")
        return 0
    sys.stderr.write(f"ECHEC: {len(result.failures)} echecs, {len(result.errors)} erreurs "
                     f"sur {total} tests\n")
    return 1
