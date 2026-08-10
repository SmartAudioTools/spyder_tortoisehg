# --- SmartOS : aiguillage Qt vers qtpy/PySide6 (patch_tortoisehg_qtpy.py) ---
# Fichier REECRIT par Commun/scripts/patch_tortoisehg_qtpy.py. La version d'origine ne savait
# choisir qu'entre PyQt5 et PyQt6 ; celle-ci passe par qtpy, donc par PySide6 - le binding de
# Spyder. Toute modification faite ici a la main sera perdue au prochain passage du script.

"""Aiguillage QtCore, via qtpy."""

from __future__ import annotations

# CE MODULE NE CHOISIT PAS LE BINDING, ET C'EST DELIBERE.
# Il n'importe que qtpy ; le moteur est designe par la variable d'environnement QT_API, posee
# par le LANCEUR - Commun/scripts/thg.sh en ligne de commande, ou l'application hote (Spyder)
# quand ces widgets tourneront dans son processus. C'est exactement le dispositif de Spyder :
# aucun binding nomme dans le code, un seul endroit qui tranche, et la detection elle-meme
# partagee entre les deux lanceurs (Commun/scripts/qt_api_env.sh).
#
# Conséquence a connaitre : lancer TortoiseHg SANS passer par le lanceur laisse qtpy appliquer
# ses propres regles. Sur cette machine, ou l'environnement exporte QT_API=PyQt5 - binding
# installe nulle part - il se rabat en silence sur ce qu'il trouve, en n'emettant qu'un
# avertissement (mesure le 03/08/2026). Ce n'est pas un mode supporte : passer par thg.sh.
import qtpy
from qtpy import QtCore as _QtCore
from qtpy.QtCore import *  # noqa: F401,F403

# TortoiseHg compare QT_API a "PyQt5" / "PyQt6" : qtpy publie deja exactement ces noms-la,
# inutile de retranscrire sa cle en minuscules.
QT_API = qtpy.API_NAME


def _detectapi():
    """Conserve pour setup.py, qui l'appelle pour ecrire util/config.py."""
    return QT_API


# --- Noms proprement PyQt, absents de PySide6 et non fournis par qtpy.
pyqtSignal = _QtCore.Signal
pyqtSlot = _QtCore.Slot
pyqtProperty = _QtCore.Property
pyqtBoundSignal = _QtCore.SignalInstance


def _encode(version):
    """Encode "6.11.1" en 0x060b01, forme que TortoiseHg compare a des constantes."""
    morceaux = [int(x) for x in version.split('.')[:3]]
    while len(morceaux) < 3:
        morceaux.append(0)
    return (morceaux[0] << 16) | (morceaux[1] << 8) | morceaux[2]


QT_VERSION_STR = _QtCore.qVersion()
QT_VERSION = _encode(QT_VERSION_STR)
# TortoiseHg compare PYQT_VERSION a un minimum (5.11) pour refuser de demarrer sur un binding
# trop vieux. La version du binding reellement installe y repond, quel qu'il soit.
PYQT_VERSION_STR = qtpy.PYSIDE_VERSION or qtpy.PYQT_VERSION or QT_VERSION_STR
PYQT_VERSION = _encode(PYQT_VERSION_STR)
