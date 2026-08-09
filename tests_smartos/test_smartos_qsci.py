#!/usr/bin/env python3
"""Banc d'essai de smartos_qsci.py, l'emulation de QScintilla, SANS TortoiseHg.

Pourquoi ce banc existe : verifier l'emulation en lancant TortoiseHg coute une minute par essai
et mobilise un depot. Ici on eprouve directement les conventions sur lesquelles TortoiseHg
s'appuie - et qui sont les seules a pouvoir casser en silence, parce qu'elles sont numeriques :
positions en OCTETS et non en caracteres, lignes rendues avec leur fin de ligne, masques de
marqueurs, intervalles d'indicateurs. Une couleur fausse se voit ; un decalage d'un octet sur un
texte accentue, non.

Il tourne sans serveur graphique (plateforme offscreen) en une fraction de seconde. A rejouer
apres toute retouche de smartos_qsci.py, et a la moindre montee de version de TortoiseHg.

Usage : QT_QPA_PLATFORM=offscreen python test_smartos_qsci.py [--capture <fichier.png>]
        Sortie 0 si tout passe, 1 sinon.
"""

import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

# Cette machine exporte QT_API=PyQt5, binding qui n'est installe nulle part ici : qtpy s'en
# contente d'un avertissement avant de retomber sur son repli. On tranche explicitement, comme
# le fait le qtcore.py patche de TortoiseHg.
import importlib.util  # noqa: E402

_BINDINGS = [('pyside6', 'PySide6'), ('pyqt6', 'PyQt6')]
_installes = [cle for cle, module in _BINDINGS if importlib.util.find_spec(module)]
if not _installes:
    sys.exit('aucun binding Qt installe (PySide6 ou PyQt6)')
if os.environ.get('QT_API', '').lower() not in _installes:
    os.environ['QT_API'] = _installes[0]

from qtpy.QtCore import QEvent, QPointF, Qt  # noqa: E402
from qtpy.QtGui import QColor, QFont, QMouseEvent  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from smartos_qsci import QsciLexerDiff, QsciScintilla  # noqa: E402

DIFF = ("diff -r a1b2 exemple.py\n"
        "--- a/exemple.py\n"
        "+++ b/exemple.py\n"
        "@@ -1,5 +1,5 @@\n"
        "-def salut():\n"
        "+def salut(nom):\n"
        "     print('bonjour')\n")

_controles = []


def verifie(nom, obtenu, attendu):
    _controles.append((nom, obtenu == attendu, obtenu, attendu))


def relacher_la_souris(editeur, position_caractere):
    """Relache le bouton gauche AU PIXEL du caractere demande.

    On vise un pixel et pas une position logique : c'est tout l'objet du test. Scintilla decide
    d'emettre SCN_INDICATORRELEASE a partir de l'endroit CLIQUE, et une emulation qui se
    contenterait du curseur de texte courant passerait ce banc tout en etant fausse a l'ecran.
    """
    curseur = editeur.textCursor()
    curseur.setPosition(position_caractere)
    point = editeur.cursorRect(curseur).center()
    evenement = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(point), QPointF(point),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier)
    editeur.mouseReleaseEvent(evenement)


def main():
    app = QApplication([])
    e = QsciScintilla()
    e.setFont(QFont('monospace', 10))

    lexer = QsciLexerDiff()
    lexer.setColor(QColor('#22aa22'), QsciLexerDiff.LineAdded)
    lexer.setColor(QColor('#cc3333'), QsciLexerDiff.LineRemoved)
    lexer.setColor(QColor('#3388cc'), QsciLexerDiff.Position)
    e.setLexer(lexer)
    e.setText(DIFF)
    e.setMarginLineNumbers(1, True)
    e.setMarginWidth(1, '000')
    e.resize(700, 260)

    # --- Texte et positions
    verifie('nombre de lignes', e.lines(), 8)
    verifie('une ligne porte sa fin de ligne', e.text(4), '-def salut():\n')
    verifie('longueur comptee en octets', e.length(), len(e.text().encode('utf-8')))
    e.setCursorPosition(4, 3)
    verifie('position du curseur', e.getCursorPosition(), (4, 3))
    verifie('aller-retour ligne/index <-> position',
            e.lineIndexFromPosition(e.positionFromLineIndex(4, 3)), (4, 3))
    e.setSelection(4, 0, 4, 4)
    verifie('texte selectionne', e.selectedText(), '-def')

    # --- Marqueurs de ligne : TortoiseHg s'en sert comme de drapeaux, et les relit par masque.
    m = e.markerDefine(QsciScintilla.MarkerSymbol.Background)
    e.setMarkerBackgroundColor(QColor('#ffdddd'), m)
    e.markerAdd(4, m)
    verifie('marqueurs presents sur la ligne', e.markersAtLine(4), 1 << m)
    verifie('marqueur precedent trouve', e.markerFindPrevious(7, 0xffffffff), 4)
    e.markerDelete(4, m)
    verifie('marqueur retire', e.markersAtLine(4), 0)
    e.markerAdd(4, m)

    # --- Indicateurs poses par message SCI, donc en positions d'OCTETS.
    e.SendScintilla(QsciScintilla.SCI_SETINDICATORCURRENT, 3)
    e.SendScintilla(QsciScintilla.SCI_INDICSETSTYLE, 3, QsciScintilla.INDIC_ROUNDBOX)
    e.SendScintilla(QsciScintilla.SCI_INDICSETFORE, 3, 0x00ffff)
    e.SendScintilla(QsciScintilla.SCI_INDICATORFILLRANGE, e.positionFromLineIndex(5, 0), 5)
    verifie('un indicateur est pose', len(e.extraSelections()) >= 1, True)
    e.SendScintilla(QsciScintilla.SCI_INDICATORCLEARRANGE, 0, e.length())
    verifie('indicateurs effaces', e.extraSelections(), [])

    # --- SCN_INDICATORRELEASE : le lien bleu « afficher quand meme ».
    #     TortoiseHg pose un indicateur sur ces quelques mots du message d'erreur d'un fichier
    #     qu'il refuse d'afficher, et s'y branche pour le rendre cliquable (fileview.py et
    #     chunks.py, _setupForceViewIndicator). Sans ce signal, selectionner un tel fichier
    #     leve une AttributeError - signale par l'utilisateur le 09/08/2026.
    #     DEUX controles, et le SECOND compte autant : un relachement AILLEURS dans le message
    #     ne doit RIEN emettre, sinon cliquer dans le vide forcerait l'affichage du fichier.
    texte = "Le fichier est trop gros pour etre affiche. afficher quand meme ?\n"
    lien = "afficher quand meme"
    e.setWrapMode(QsciScintilla.WrapMode.WrapNone)
    e.resize(900, 200)
    e.setText(texte)
    debut, fin = texte.index(lien), texte.index(lien) + len(lien)
    #     LE BRANCHEMENT EST CELUI DE TORTOISEHG, PAS UN BRANCHEMENT DE CONFORT : slot SANS
    #     AUCUN argument, en QueuedConnection. Un signal a arguments `object` livre en differe
    #     est le cas ou Qt exige que le type soit connu de son systeme de metatypes ; le tester
    #     autrement (connexion directe, slot a deux arguments) laisserait passer precisement ce
    #     qui casserait a l'ecran.
    numero = e.indicatorDefine(QsciScintilla.IndicatorStyle.PlainIndicator)
    e.setIndicatorDrawUnder(True, numero)
    e.setIndicatorForegroundColor(QColor('blue'), numero)
    e.fillIndicatorRange(0, debut, 0, fin, numero)
    differes, positions = [], []
    e.SCN_INDICATORRELEASE.connect(lambda: differes.append(1), Qt.ConnectionType.QueuedConnection)
    e.SCN_INDICATORRELEASE.connect(lambda position, modificateurs: positions.append(position))
    milieu = (debut + fin) // 2
    relacher_la_souris(e, milieu)
    app.processEvents()
    verifie('relachement SUR le lien : slot differe appele', len(differes), 1)
    verifie('position rendue en octets', positions[:1], [e.positionFromLineIndex(0, milieu)])
    relacher_la_souris(e, 3)
    app.processEvents()
    verifie('relachement HORS du lien : silence', len(differes), 1)
    e.SendScintilla(QsciScintilla.SCI_INDICATORCLEARRANGE, 0, e.length())
    e.setText(DIFF)

    # --- Recherche par expression reguliere (Scintilla.find de TortoiseHg passe par la).
    e.setCursorPosition(0, 0)
    verifie('recherche trouvee', e.findFirst('salut', True, True, False, False, True), True)
    verifie('recherche introuvable',
            e.findFirst('introuvable42', True, True, False, False, True), False)

    # --- Accents : c'est ici que la convention en octets se casse si elle est mal tenue.
    #     Le texte d'essai en porte VRAIMENT - une premiere version de ce banc etait ecrite sans
    #     accents, et ne testait donc rien du tout, tout en passant au vert.
    e.setText("premiere ligne\ndeuxième : élève\n")
    verifie('accents, aller-retour', e.lineIndexFromPosition(e.positionFromLineIndex(1, 10)),
            (1, 10))
    verifie('accents, longueur en octets', e.length(), len(e.text().encode('utf-8')))
    # Le "e" accent grave de "deuxieme" est au rang 5 : il occupe 2 octets, pas 1.
    verifie('un caractere accentue vaut 2 octets',
            e.positionFromLineIndex(1, 6) - e.positionFromLineIndex(1, 5), 2)
    verifie('accents, ligne relue a l_identique', e.text(1), "deuxième : élève\n")

    if '--capture' in sys.argv:
        e.setText(DIFF)
        e.markerAdd(4, m)
        e.grab().save(sys.argv[sys.argv.index('--capture') + 1])

    echecs = [c for c in _controles if not c[1]]
    for nom, ok, obtenu, attendu in _controles:
        if ok:
            print('  ok    %s' % nom)
        else:
            print('  ECHEC %s : obtenu %r, attendu %r' % (nom, obtenu, attendu))
    print('%d/%d controles passes' % (len(_controles) - len(echecs), len(_controles)))
    return 1 if echecs else 0


if __name__ == '__main__':
    sys.exit(main())
