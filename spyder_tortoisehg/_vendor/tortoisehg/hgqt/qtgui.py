# --- SmartOS : aiguillage Qt vers qtpy/PySide6 (patch_tortoisehg_qtpy.py) ---
# Fichier REECRIT par Commun/scripts/patch_tortoisehg_qtpy.py. La version d'origine ne savait
# choisir qu'entre PyQt5 et PyQt6 ; celle-ci passe par qtpy, donc par PySide6 - le binding de
# Spyder. Toute modification faite ici a la main sera perdue au prochain passage du script.

"""Aiguillage QtGui + QtWidgets, via qtpy."""

from __future__ import annotations

from .qtcore import QT_API  # noqa: F401  (pose QT_API et la variable d'environnement)
from qtpy.QtGui import *  # noqa: F401,F403
from qtpy.QtWidgets import *  # noqa: F401,F403
