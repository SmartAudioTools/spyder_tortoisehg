#!/usr/bin/env python3
"""Fait passer TortoiseHg de PyQt a qtpy/PySide6, en reecrivant ses cinq modules d'aiguillage.

POURQUOI
    Le greffon Spyder vise (TODO - Spyder - plugin TortoiseHg.txt) doit afficher des widgets de
    TortoiseHg DANS le processus de Spyder. Deux bindings Qt ne cohabitent pas dans un meme
    processus : TortoiseHg doit donc tourner sur le meme que Spyder, c'est-a-dire PySide6, via
    qtpy. Ce script est la premiere moitie de ce portage ; la seconde est smartos_qsci.py, qui
    reimplemente QScintilla (aucun binding PySide6 n'existe, cf. son en-tete).

CE QUI EST PATCHE, ET POURQUOI PAR REECRITURE COMPLETE
    TortoiseHg centralise TOUS ses imports Qt dans cinq modules de quelques lignes
    (hgqt/qtcore.py, qtgui.py, qtnetwork.py, qsci.py, plus le bloc sip de qtlib.py) : leur seule
    raison d'etre est de choisir entre PyQt5 et PyQt6. Les reecrire en entier est donc plus sur
    qu'une retouche chirurgicale - il n'y a rien d'autre dedans a preserver - et le resultat se
    relit d'un coup d'oeil. Chaque fichier reecrit porte un marqueur d'en-tete qui rend le
    script idempotent ET metteur a jour : un fichier deja patche par une version anterieure est
    remplace par la version courante.

    S'y ajoutent les cinq *_ui.py livres dans le tarball, generes par pyuic5 et qui importent
    PyQt5 en dur (serve, hgemail, postreview, phabreview, webconf) : seules leurs lignes
    d'import changent - il y en a DEUX dans certains, la seconde tout en bas du fichier. Une
    verification finale refuse de rendre la main s'il reste le moindre import PyQt5 vivant.
    A noter au passage : le paquet Arch de TortoiseHg tourne en PyQt6 avec ces fichiers
    intacts, donc ces cinq dialogues y sont casses - le portage qtpy les repare.

CE QUI RESTE INTACT
    Tout le reste de TortoiseHg, soit 130 fichiers. Le code y est deja compatible Qt6 (le
    paquet Arch tourne en PyQt6) : enums scopes, exec() et non exec_(), aucun QVariant. Ne
    manquaient que les noms proprement PyQt - pyqtSignal, pyqtSlot, pyqtBoundSignal,
    PYQT_VERSION - que qtpy ne fournit PAS sous PySide6 (verifie le 03/08/2026 : qtpy 2.4.3
    n'expose ni pyqtSignal ni pyqtSlot), et qui sont donc definis ici comme alias.

USAGE
    patch_tortoisehg_qtpy.py <racine>     ou <racine> contient le dossier tortoisehg/

    A appliquer sur les SOURCES avant l'installation, et non sur site-packages apres : le
    setup.py de TortoiseHg importe hgqt/qtcore.py pour generer util/config.py, donc l'install
    echoue avant meme de commencer si le binding n'est pas deja aiguille.
"""

import os
import re
import sys

MARQUEUR = '# --- SmartOS : aiguillage Qt vers qtpy/PySide6 (patch_tortoisehg_qtpy.py) ---'

EN_TETE = MARQUEUR + '''
# Fichier REECRIT par Commun/scripts/patch_tortoisehg_qtpy.py. La version d'origine ne savait
# choisir qu'entre PyQt5 et PyQt6 ; celle-ci passe par qtpy, donc par PySide6 - le binding de
# Spyder. Toute modification faite ici a la main sera perdue au prochain passage du script.
'''

QTCORE = EN_TETE + '''
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
'''

QTGUI = EN_TETE + '''
"""Aiguillage QtGui + QtWidgets, via qtpy."""

from __future__ import annotations

from .qtcore import QT_API  # noqa: F401  (pose QT_API et la variable d'environnement)
from qtpy.QtGui import *  # noqa: F401,F403
from qtpy.QtWidgets import *  # noqa: F401,F403
'''

QTNETWORK = EN_TETE + '''
"""Aiguillage QtNetwork, via qtpy."""

from __future__ import annotations

from .qtcore import QT_API  # noqa: F401
from qtpy.QtNetwork import *  # noqa: F401,F403
'''

QSCI = EN_TETE + '''
"""Aiguillage QScintilla - vers notre emulation, faute de binding PySide6.

QScintilla n'existe que pour PyQt (verifie sur PyPI le 03/08/2026). smartos_qsci reimplemente
sur QPlainTextEdit la part de son API que TortoiseHg utilise reellement ; cf. son en-tete pour
le perimetre exact et ce qui y est approche ou absent.
"""

from __future__ import annotations

from .qtcore import QT_API  # noqa: F401
from smartos_qsci import *  # noqa: F401,F403
'''

# Bloc sip de qtlib.py. TortoiseHg ne s'en sert qu'a deux fins : savoir si un objet C++ a ete
# detruit (sip.isdeleted) et transtyper un widget en QObject pour QSignalMapper (sip.cast).
SIP_ANCIEN = '''if QT_API == "PyQt6":
    import PyQt6.sip as sip  # pytype: disable=import-error
else:
    import sip  # pytype: disable=import-error'''

SIP_NOUVEAU = '''# --- SmartOS : sip remplace par un equivalent qui marche sous les deux familles ---
# (patch_tortoisehg_qtpy.py) sip est propre a PyQt ; sous PySide6 l'equivalent est shiboken6,
# dont isValid() est l'inverse exact de sip.isdeleted(). Le transtypage, lui, n'a d'objet sous
# aucune des deux : QSignalMapper accepte le widget tel quel.
# Les deux familles sont servies, pas seulement PySide6 : RaspberryPi5 tourne en PyQt6, faute
# de roue PySide6 aarch64.
class _Sip:
    @staticmethod
    def isdeleted(obj):
        try:
            import shiboken6
        except ImportError:
            import PyQt6.sip as _sip
            return _sip.isdeleted(obj)
        return not shiboken6.isValid(obj)

    @staticmethod
    def cast(obj, type_):
        return obj


sip = _Sip()'''

# setup.py, commande build_ui : elle appelle _wrapuic() DES SON ENTREE, donc importe le module
# uic de PyQt avant meme de regarder s'il y a quelque chose a recompiler. Comme les cinq _ui.py
# sont deja livres dans le tarball (et patches ci-dessus), rien n'est jamais a recompiler : on
# deplace cet appel dans _compile_ui, la ou il sert. Sans quoi l'installation echoue d'entree
# sur "No module named 'PyQt5'". Qui voudrait regenerer les .ui garde le comportement d'avant,
# a ceci pres qu'il lui faudra un PyQt - inchange, uic n'existe pas sous PySide6.
SETUP_ANCIEN = '''    def run(self):
        self._wrapuic()
        basepath = os.path.join(os.path.dirname(__file__), 'tortoisehg', 'hgqt')'''

SETUP_NOUVEAU = '''    def run(self):
        # SmartOS (patch_tortoisehg_qtpy.py) : _wrapuic() deplace dans _compile_ui, pour ne pas
        # exiger PyQt quand il n'y a rien a recompiler.
        basepath = os.path.join(os.path.dirname(__file__), 'tortoisehg', 'hgqt')'''

SETUP_COMPILE_ANCIEN = '''    def _compile_ui(self, ui_file, py_file):
        uic = self._impuic()'''

SETUP_COMPILE_NOUVEAU = '''    def _compile_ui(self, ui_file, py_file):
        self._wrapuic()  # SmartOS : deplace depuis run()
        uic = self._impuic()'''

# Lanceur thg : le chargement paresseux de Mercurial (demandimport) est incompatible avec
# shiboken6. Constate en direct le 03/08/2026, sur un simple "thg version" :
#     Fatal Python error: libshiboken: missing class name in GetTypeKey
#     AttributeError: '_LazyModule' object has no attribute '__qualname__'
# shiboken enregistre ses types en interrogeant le module qui les porte ; si ce module est
# encore un _LazyModule, l'interpreteur meurt - pas une exception, un abandon.
#
# TortoiseHg connaissait deja le probleme pour SES modules Qt : sa liste IGNORES exclut
# hgqt.qtcore, qtgui, qtnetwork et qsci, "pour ne pas creer de demandmods pour un paquet
# d'attributs Q*". Le portage deplace simplement la frontiere : ce sont maintenant qtpy,
# PySide6 et shiboken6 qui sont derriere.
#
# IGNORES compare des noms de module COMPLETS (module.__name__ in ignores), donc y lister
# 'PySide6' ne couvrirait pas 'PySide6.QtCore'. Plutot que d'enumerer des sous-modules - liste
# qui serait fausse a la premiere version suivante - on remplace l'ensemble par une variante
# qui sait reconnaitre un PREFIXE. Une seule ligne du mecanisme d'origine est touchee, et
# l'ensemble d'origine est recopie dedans.
LANCEUR_ANCIEN = '''demandimport.enable()'''

LANCEUR_NOUVEAU = '''# --- SmartOS (patch_tortoisehg_qtpy.py) : jamais de chargement paresseux sous Qt ---
class _IgnoresParPrefixe(set):
    """IGNORES etendu aux ARBORESCENCES, et non aux seuls noms exacts."""

    # PySide6/shiboken6 parce qu'ils ont reellement fait abandonner l'interpreteur ; qtpy et
    # smartos_qsci parce qu'ils sont les intermediaires que ce portage ajoute. PyQt6 n'y est
    # PAS : le paquet Arch de TortoiseHg tourne en PyQt6 AVEC le chargement paresseux, donc
    # rien ne justifie de l'exclure.
    PREFIXES = ('PySide6', 'shiboken6', 'qtpy', 'smartos_qsci')

    def __contains__(self, nom):
        if set.__contains__(self, nom):
            return True
        return any(nom == p or nom.startswith(p + '.') for p in self.PREFIXES)


from hgdemandimport import demandimportpy3 as _thg_demandimportpy3
_thg_demandimportpy3.ignores = _IgnoresParPrefixe(demandimport.IGNORES)

demandimport.enable()'''

# repoview.py, LabeledDelegate.paint : le dessin des etiquettes du graphe des revisions.
#
# ⚠ SOUS PYSIDE6, TOUCHER A option.widget ICI FAIT TOMBER LE PROCESSUS - pas une exception, un
# segfault - DES QU'UNE FEUILLE DE STYLE GLOBALE EST POSEE. C'est exactement le cas de Spyder,
# qui applique QDarkStyle : le greffon faisait mourir Spyder pendant que le graphe se
# remplissait. Trouve le 03/08/2026 par la pile d'un faulthandler arme depuis l'interieur du
# processus, qui designait la ligne de subElementRect.
#
# Reproduit HORS de Spyder, en soixante secondes, en posant simplement la meme feuille de style
# sur la sonde autonome - sans elle, le meme widget vit vingt-cinq secondes sans broncher. Cette
# reproduction rapide est ce qui a permis d'isoler la cause exacte, en trois essais :
#   - style de QApplication + widget None    -> vit
#   - style DU WIDGET       + widget None    -> tombe
#   - widget lu AVANT la copie de l'option   -> tombe
# Ce n'est donc ni la copie de l'option ni l'argument passe : c'est l'USAGE de option.widget,
# quel qu'il soit. On ne le lit plus.
#
# Ce que cela coute : le rectangle de decoration est calcule par le style de l'application et
# non par celui du widget. Sous une feuille de style qui redefinirait les marges d'un item de
# vue, la position des etiquettes pourrait differer de quelques pixels. C'est le prix d'un
# panneau qui ne tue pas son hote.
DELEGUE_ANCIEN = '''        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        if option.widget:
            style = option.widget.style()
        else:
            style = QApplication.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option,
                                    option.widget)'''

DELEGUE_NOUVEAU = '''        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        # --- SmartOS (patch_tortoisehg_qtpy.py) : ne JAMAIS toucher a option.widget ici ---
        # Sous PySide6, l'utiliser fait SEGFAULTER des qu'une feuille de style globale est
        # posee (le cas de Spyder). Le style de l'application rend un rectangle equivalent a
        # quelques pixels pres. Detail complet dans le script qui pose ce bloc.
        style = QApplication.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, option,
                                    None)'''

# cmdcore.py, le dialogue avec le serveur de commandes de Mercurial.
#
# ⚠ SOUS PYSIDE6, QIODevice.read() REND UN QByteArray LA OU PyQt REND DES bytes. Le protocole du
# serveur lit des octets et les traite comme tels : la poignee de main echouait donc a tous les
# coups, sur
#     AttributeError: 'PySide6.QtCore.QByteArray' object has no attribute 'splitlines'
# et AUCUNE commande Mercurial ne pouvait etre lancee depuis le greffon - actualiser, tirer,
# exporter, valider. Signale par l'utilisateur le 04/08/2026.
#
# TortoiseHg connait le probleme et s'en protege deja : qtlib.qbytearray_or_bytes_to_bytes()
# existe pour cela, et est applique a peek() et readLine(). Il manque aux TROIS appels a read(),
# tout simplement parce qu'en amont personne ne fait tourner TortoiseHg sur PySide6. On applique
# le convertisseur maison plutot que d'en ecrire un.
#
# Le defaut avait passe la campagne d'essais du greffon parce qu'elle AFFICHAIT un depot - graphe,
# fichiers, diff -, ce qui passe par les objets Mercurial en direct sans lancer de commande. Le
# banc Commun/scripts/test_tortoisehg_cmdserver.py existe pour couvrir ce chemin-la, et rien
# d'autre.
CMDCORE = (
    ('''        # b'' for EOF; None for error (per PyQt's QIODevice.read() convention)
        if not self._datain:
            return b''
        return self._datain.read(size)''',
     '''        # b'' for EOF; None for error (per PyQt's QIODevice.read() convention)
        if not self._datain:
            return b''
        # SmartOS (patch_tortoisehg_qtpy.py) : read() rend un QByteArray sous PySide6
        donnees = self._datain.read(size)
        if donnees is None:
            return None
        return qtlib.qbytearray_or_bytes_to_bytes(donnees)'''),

    ('''                proc.read(headersize)
                data = proc.read(datasize)''',
     '''                proc.read(headersize)
                # SmartOS : idem - c'est ICI que la poignee de main tombait
                data = qtlib.qbytearray_or_bytes_to_bytes(proc.read(datasize))'''),

    ('''        """Read output if capturing enabled; ui messages are not included"""
        return self._dataoutrbuf.read(maxlen)''',
     '''        """Read output if capturing enabled; ui messages are not included"""
        # SmartOS : idem, et la signature annonce deja des bytes
        return qtlib.qbytearray_or_bytes_to_bytes(self._dataoutrbuf.read(maxlen))'''),
)

FICHIERS_UI = ('serve_ui.py', 'hgemail_ui.py', 'postreview_ui.py', 'phabreview_ui.py',
               'webconf_ui.py')
# pyuic5 ecrit DEUX sortes d'imports : celui des modules Qt, en tete, et - tout en BAS du
# fichier - celui des widgets promus, apres la classe qui s'en sert. Ne traiter que le premier
# laissait passer "from PyQt5 import Qsci" dans deux fichiers sur cinq, invisible tant que le
# chargement paresseux de Mercurial differait ces modules. Trouve en montant un RepoWidget a la
# main, qui les importe, lui, tout de suite.
IMPORTS_UI = (
    ('from PyQt5 import QtCore, QtGui, QtWidgets',
     'from qtpy import QtCore, QtGui, QtWidgets'
     '  # SmartOS : PyQt5 -> qtpy (patch_tortoisehg_qtpy.py)'),
    ('from PyQt5 import Qsci',
     'import smartos_qsci as Qsci'
     '  # SmartOS : QScintilla emule (patch_tortoisehg_qtpy.py)'),
)


def _ecrire(chemin, contenu):
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(contenu.lstrip('\n'))


def _echec(message):
    sys.stderr.write('patch_tortoisehg_qtpy : %s\n' % message)
    sys.exit(1)


def _patcher(chemin, temoin, remplacements, libelle, absence):
    """Applique a un fichier des remplacements EXACTS, une fois et une seule.

    Les cinq fichiers retouches chirurgicalement (les autres sont reecrits en entier) suivent
    tous la meme regle : si le temoin est la, c'est deja fait ; si tous les motifs d'origine sont
    la, on remplace ; sinon la version de TortoiseHg n'est pas celle attendue, et le script
    s'arrete plutot que de laisser passer un patch a moitie pose.

    Le temoin est un fragment du texte AJOUTE, jamais du texte d'origine : c'est ce qui rend le
    script rejouable sur une arborescence deja patchee.
    """
    with open(chemin, encoding='utf-8') as f:
        source = f.read()
    if temoin in source:
        print('inchange : %s' % libelle)
        return
    if not all(ancien in source for ancien, _nouveau in remplacements):
        _echec(absence)
    for ancien, nouveau in remplacements:
        source = source.replace(ancien, nouveau)
    _ecrire(chemin, source)
    print('patche : %s' % libelle)


def main(racine):
    hgqt = os.path.join(racine, 'tortoisehg', 'hgqt')
    if not os.path.isdir(hgqt):
        _echec('%s ne contient pas tortoisehg/hgqt - mauvaise racine ?' % racine)

    for nom, contenu in (('qtcore.py', QTCORE), ('qtgui.py', QTGUI),
                         ('qtnetwork.py', QTNETWORK), ('qsci.py', QSCI)):
        chemin = os.path.join(hgqt, nom)
        if not os.path.isfile(chemin):
            _echec('%s introuvable - arborescence de TortoiseHg changee ?' % chemin)
        _ecrire(chemin, contenu)
        print('reecrit : %s' % nom)

    # qtlib.py : seul le bloc sip change, le reste du fichier (1400 lignes) est a preserver.
    _patcher(os.path.join(hgqt, 'qtlib.py'),
             SIP_NOUVEAU.splitlines()[0], ((SIP_ANCIEN, SIP_NOUVEAU),),
             'qtlib.py (bloc sip)',
             'bloc sip introuvable dans qtlib.py - version de TortoiseHg inattendue')

    _patcher(os.path.join(hgqt, 'repoview.py'),
             'ne JAMAIS toucher a option.widget', ((DELEGUE_ANCIEN, DELEGUE_NOUVEAU),),
             'repoview.py (le delegue ne touche plus a option.widget)',
             'LabeledDelegate.paint introuvable dans repoview.py - version inattendue')

    _patcher(os.path.join(hgqt, 'cmdcore.py'),
             'read() rend un QByteArray sous PySide6', CMDCORE,
             'cmdcore.py (les trois lectures rendent des bytes)',
             'les appels a read() de cmdcore.py ne sont pas ceux attendus - version inattendue')

    chemin = os.path.join(racine, 'thg')
    if not os.path.isfile(chemin):
        _echec('lanceur thg introuvable a la racine %s' % racine)
    _patcher(chemin, '_IgnoresParPrefixe', ((LANCEUR_ANCIEN, LANCEUR_NOUVEAU),),
             'thg (demandimport ne touche plus au monde Qt)',
             'demandimport.enable() introuvable dans le lanceur thg')

    chemin = os.path.join(racine, 'setup.py')
    if os.path.isfile(chemin):
        _patcher(chemin, SETUP_COMPILE_NOUVEAU,
                 ((SETUP_ANCIEN, SETUP_NOUVEAU),
                  (SETUP_COMPILE_ANCIEN, SETUP_COMPILE_NOUVEAU)),
                 'setup.py (build_ui n_exige plus PyQt)',
                 'build_ui introuvable dans setup.py - version inattendue')

    for nom in FICHIERS_UI:
        chemin = os.path.join(hgqt, nom)
        if not os.path.isfile(chemin):
            _echec('%s introuvable' % chemin)
        with open(chemin, encoding='utf-8') as f:
            source = f.read()
        avant = source
        for ancien, nouveau in IMPORTS_UI:
            if ancien in source:
                source = source.replace(ancien, nouveau)
        if source != avant:
            _ecrire(chemin, source)
            print('patche : %s' % nom)
        else:
            print('inchange : %s' % nom)
        # build_ui recompile un _ui.py des qu'il est plus ancien que son .ui OU que setup.py -
        # et setup.py vient d'etre reecrit. Sans ce rajeunissement, une SECONDE execution du
        # script (ou la premiere sur une source deja patchee) relance la compilation des .ui,
        # donc reclame PyQt, donc echoue. Fait sur les cinq a chaque passage, y compris ceux
        # laisses inchanges : c'est justement le cas "inchange" qui trebuchait.
        os.utime(chemin, None)

    _verifier_aucun_pyqt5(os.path.join(racine, 'tortoisehg'))


def _verifier_aucun_pyqt5(racine):
    """Refuse de se dire termine s'il reste un import PyQt5 VIVANT dans l'arborescence.

    Ce garde-fou existe parce que la liste des points a patcher a ete etablie par relevé, et
    qu'un relevé rate ce qu'il n'a pas cherche : "from PyQt5 import Qsci", ecrit tout en BAS de
    deux fichiers generes par pyuic5, a survecu a la premiere version du script. Il n'a fait
    tomber personne pendant des heures, le chargement paresseux de Mercurial differant ces
    modules - c'est justement le genre de manque qu'un patch doit refuser de laisser passer.

    Le critere est EXACT, pas heuristique : une ligne d'import, pas une mention. TortoiseHg
    parle de PyQt5 dans une dizaine de commentaires, qui ne doivent evidemment pas alerter.
    """
    motif = re.compile(r'^\s*(from|import)\s+PyQt5\b', re.MULTILINE)
    restants = []
    for dossier, _sous, fichiers in os.walk(racine):
        for fichier in fichiers:
            if not fichier.endswith('.py'):
                continue
            chemin = os.path.join(dossier, fichier)
            with open(chemin, encoding='utf-8') as f:
                for numero, ligne in enumerate(f, 1):
                    if motif.match(ligne):
                        restants.append('%s:%d: %s' % (chemin, numero, ligne.strip()))
    if restants:
        _echec('il reste %d import(s) PyQt5 apres le patch :\n    %s'
               % (len(restants), '\n    '.join(restants)))
    print('verifie : aucun import PyQt5 vivant dans tortoisehg/')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__.split('USAGE')[1])
        sys.exit(2)
    main(sys.argv[1])
