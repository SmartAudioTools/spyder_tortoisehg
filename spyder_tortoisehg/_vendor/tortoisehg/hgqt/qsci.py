# --- SmartOS : aiguillage Qt vers qtpy/PySide6 (patch_tortoisehg_qtpy.py) ---
# Fichier REECRIT par Commun/scripts/patch_tortoisehg_qtpy.py. La version d'origine ne savait
# choisir qu'entre PyQt5 et PyQt6 ; celle-ci passe par qtpy, donc par PySide6 - le binding de
# Spyder. Toute modification faite ici a la main sera perdue au prochain passage du script.

"""Aiguillage QScintilla - vers notre emulation, faute de binding PySide6.

QScintilla n'existe que pour PyQt (verifie sur PyPI le 03/08/2026). smartos_qsci reimplemente
sur QPlainTextEdit la part de son API que TortoiseHg utilise reellement ; cf. son en-tete pour
le perimetre exact et ce qui y est approche ou absent.
"""

from __future__ import annotations

from .qtcore import QT_API  # noqa: F401
from smartos_qsci import *  # noqa: F401,F403
