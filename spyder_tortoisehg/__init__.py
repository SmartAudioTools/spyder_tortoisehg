# -*- coding: utf-8 -*-
"""Greffon Spyder « Mercurial », bati sur le RepoWidget de TortoiseHg.

Ce module ne fait qu'une chose : rendre importable la copie de TortoiseHg livree avec le
greffon, sous _vendor/. Elle y est parce qu'elle est INTROUVABLE ailleurs - le projet
« tortoisehg » de PyPI est vide (aucun fichier publie), et l'archive amont est ecrite pour
PyQt5, donc inutilisable sous le PySide6 de Spyder. Cf. outils/vendoriser_tortoisehg.py,
qui la produit.

_vendor est ajoute en QUEUE de sys.path, et seulement si tortoisehg n'est pas deja
importable : une installation faite par ailleurs - le venv autonome de ~/.scripts/thg.sh,
ou le paquet de la distribution - garde la priorite. Un greffon ne doit jamais masquer ce
que la machine a deja.
"""

import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_vendor')


def _activer_tortoisehg_embarque():
    """Ajoute _vendor a sys.path si, et seulement si, il apporte quelque chose."""
    if not os.path.isdir(_VENDOR):
        # Depot de developpement dont _vendor n'a pas encore ete produit : ce n'est pas une
        # erreur, le panneau saura dire que TortoiseHg est absent (cf. thg_contexte).
        return
    try:
        import tortoisehg  # noqa: F401
    except ImportError:
        pass
    else:
        return
    if _VENDOR not in sys.path:
        sys.path.append(_VENDOR)


_activer_tortoisehg_embarque()
