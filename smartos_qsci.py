#!/usr/bin/env python3
"""Emulation de QScintilla (QsciScintilla, lexers, QsciAPIs, QsciStyle) sur QPlainTextEdit.

POURQUOI CE MODULE EXISTE
    TortoiseHg est ecrit pour PyQt : ses vues de fichier, ses diffs et sa zone de message de
    commit sont des QsciScintilla. Or QScintilla n'a AUCUN binding PySide6 - verifie le
    03/08/2026 sur PyPI : "QScintilla" exige PyQt5, "pyqt6-qscintilla" exige PyQt6, et aucun
    paquet PySide6-QScintilla n'existe (quatre noms plausibles interroges, tous en 404). Comme
    deux bindings Qt ne peuvent pas cohabiter dans un meme processus, et que le greffon Spyder
    vise doit tourner DANS Spyder, donc sous PySide6, la seule voie est de reimplementer la
    partie de l'API QScintilla que TortoiseHg utilise reellement.

PERIMETRE, MESURE ET NON DEVINE
    La surface a couvrir a ete relevee par un parcours ast de tortoisehg/hgqt (135 fichiers) :
    28 constantes de classe, ~120 methodes, 5 signaux, et les messages SCI_* passes a
    SendScintilla. Tout ce qui est ici sert quelque part dans TortoiseHg ; rien n'a ete ajoute
    "au cas ou".

CE QUI EST FIDELE, ET CE QUI NE L'EST PAS
    Fidele    texte et positions (y compris la convention Scintilla de positions en OCTETS),
              curseur, selection, annuler/refaire, lecture seule, recherche par expression
              reguliere, marges (numeros de ligne, texte de marge, symboles), marqueurs de
              ligne (fond, symbole, invisibles servant de drapeaux), indicateurs (surlignage
              de recherche, lignes exclues), retour a la ligne, tabulations, espaces visibles.
    Approche  ensureLineVisible se cale sur la barre de defilement en unites de blocs : exact
              sans retour a la ligne, approche avec.
    Absent    la coloration syntaxique par lexer. QScintilla la tient de Scintilla, qui n'a pas
              d'equivalent ici ; les lexers sont donc des porteurs de reglages (police,
              couleurs) inertes, SAUF QsciLexerDiff, reimplemente pour de bon - c'est celui
              qui compte dans TortoiseHg, ou l'essentiel du texte affiche est un diff.
              Repli-ligne (setFolding), correspondance de parentheses et ligne de bord sont
              acceptes puis ignores : purement cosmetiques, aucun code de TortoiseHg ne les
              interroge en retour.

CONVENTION DE POSITION
    Scintilla compte les positions en octets UTF-8, et TortoiseHg s'appuie dessus (cf.
    Scintilla.highlightText, qui cherche ses motifs dans self.text().encode('utf-8') puis
    passe les offsets obtenus a SCI_INDICATORFILLRANGE). Les conversions octets <-> caracteres
    passent donc par une table des debuts de ligne, reconstruite a chaque modification du
    document et interrogee par dichotomie.
"""

from __future__ import annotations

import bisect
import enum
import os
import re

from qtpy.QtCore import QPoint, QRect, QSize, Qt, Signal
from qtpy.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextOption,
)
from qtpy.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

# Version annoncee a TortoiseHg. Elle sert a deux endroits : bugreport.py l'affiche, et
# qscilib.py compare a 0x20500 pour decider s'il doit contourner un vieux bug de Backtab.
# On annonce donc une version RECENTE, pour que ces contournements restent desactives.
QSCINTILLA_VERSION = 0x20e01
QSCINTILLA_VERSION_STR = '2.14.1 (emule par smartos_qsci)'


# --- Messages SCI_* --------------------------------------------------------------------------
# Valeurs reelles de Scintilla.h. Seule la coherence interne importe (nous sommes a la fois
# l'emetteur et le recepteur), mais garder les vraies valeurs rend le code lisible face a la
# documentation de Scintilla, et evite qu'une collision de numeros passe inapercue.
SCI_SCROLLCARET = 2169
SCI_SETHSCROLLBAR = 2130
SCI_SETMARGINTYPEN = 2240
SCI_SETMARGINWIDTHN = 2242
SCI_SETMARGINMASKN = 2244
SCI_STYLESETBACK = 2052
SCI_STYLESETFONT = 2056
SCI_STYLESETSIZE = 2055
SCI_GETENDSTYLED = 2028
SCI_SETSELEOLFILLED = 2480
SCI_SETTARGETSTART = 2190
SCI_SETTARGETEND = 2192
SCI_REPLACETARGET = 2194
SCI_SETENDATLASTLINE = 2277
SCI_SETVISIBLEPOLICY = 2394
SCI_LINEFROMPOSITION = 2166
SCI_POSITIONFROMPOINT = 2022
SCI_POINTXFROMPOSITION = 2164
SCI_POINTYFROMPOSITION = 2165
SCI_GETCARETWIDTH = 2189
SCI_SETMULTIPLESELECTION = 2563
SCI_SETADDITIONALSELECTIONTYPING = 2565
SCI_SETMULTIPASTE = 2614
SCI_SETVIRTUALSPACEOPTIONS = 2596
SCI_SETINDICATORCURRENT = 2500
SCI_INDICATORFILLRANGE = 2504
SCI_INDICATORCLEARRANGE = 2505
SCI_INDICSETSTYLE = 2080
SCI_INDICSETFORE = 2082
SCI_INDICSETUNDER = 2510
SCI_INDICSETALPHA = 2523

SC_MULTIPASTE_EACH = 1
SCVS_RECTANGULARSELECTION = 1

# Styles Scintilla predefinis : les styles applicatifs commencent au-dela.
STYLE_LASTPREDEFINED = 39

# Indicateurs : numeros et styles de trace.
INDIC_PLAIN = 0
INDIC_SQUIGGLE = 1
INDIC_STRIKE = 4
INDIC_HIDDEN = 5
INDIC_ROUNDBOX = 7
INDIC_MAX = 35


# --- Mode decouverte -------------------------------------------------------------------------
# Le perimetre de ce module a d'abord ete releve par parcours ast de TortoiseHg. Cette methode
# rate ce qui est atteint par une variable (self.sci.SCN_ZOOM), qu'aucune analyse statique ne
# rattache a QsciScintilla sans inference de types. Trouver ces manques un par un couterait un
# lancement complet de TortoiseHg par attribut.
#
# D'ou ce mode : SMARTOS_QSCI_DECOUVERTE=<fichier> fait rendre a tout attribut inconnu un objet
# passe-partout - appelable, connectable, comparable - et consigne son nom. UNE execution rend
# la liste entiere. Il sert a porter une version suivante de TortoiseHg, pas a faire tourner
# l'existante : sans cette variable, un attribut inconnu leve AttributeError, bruyamment.
_DECOUVERTE = os.environ.get('SMARTOS_QSCI_DECOUVERTE')


class _Passepartout:
    """Objet inerte rendu en mode decouverte : accepte tout, ne fait rien."""

    def __init__(self, nom):
        self._nom = nom

    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, nom):
        return _Passepartout('%s.%s' % (self._nom, nom))

    def connect(self, *args, **kwargs):
        return None

    def disconnect(self, *args, **kwargs):
        return None

    def emit(self, *args, **kwargs):
        return None

    def __int__(self):
        return 0

    def __bool__(self):
        return False

    def __repr__(self):
        return '<manquant dans smartos_qsci : %s>' % self._nom


def _consigner(nom):
    with open(_DECOUVERTE, 'a') as f:
        f.write(nom + '\n')


def _tocolor(value):
    """Rend un QColor a partir d'un QColor ou d'un entier Scintilla 0xbbggrr."""
    if isinstance(value, QColor):
        return value
    v = int(value)
    return QColor(v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff)


class _StandardCommands:
    """Jeu de commandes clavier de Scintilla, reduit a ce que TortoiseHg lui demande.

    qscilib.unbindConflictedKeys() appelle standardCommands() HORS de son try/except, puis
    boundTo() DEDANS : rendre None suffit a lui faire conclure qu'aucune commande n'occupe la
    touche, ce qui est vrai - un QPlainTextEdit n'a pas de table de raccourcis interne.
    """

    def boundTo(self, key):
        return None


class QsciStyle:
    """Porteur de style (numero, police, papier, encre), tel que TortoiseHg l'emploie.

    Il ne sert qu'a la marge d'annotation de fileview.py, qui lit style(), paper() et font()
    pour les repasser a SendScintilla. Aucun rendu ne lui est demande directement.
    """

    def __init__(self, style=-1, description='', color=None, paper=None,
                 font=None, eolFill=False):
        self._style = style
        self._description = description
        self._color = color if color is not None else QColor(Qt.GlobalColor.black)
        self._paper = paper if paper is not None else QColor(Qt.GlobalColor.white)
        self._font = font if font is not None else QFont()
        self._eolfill = eolFill

    def style(self):
        return self._style

    def description(self):
        return self._description

    def color(self):
        return self._color

    def setColor(self, color):
        self._color = color

    def paper(self):
        return self._paper

    def setPaper(self, paper):
        self._paper = paper

    def font(self):
        return self._font

    def setFont(self, font):
        self._font = font

    def eolFill(self):
        return self._eolfill

    def setEolFill(self, eolfill):
        self._eolfill = eolfill


# --- Lexers ----------------------------------------------------------------------------------

class QsciLexer:
    """Porteur de reglages de coloration, sans analyse lexicale.

    Les sous-classes nommees plus bas existent parce que lexers.py de TortoiseHg les designe
    par leur nom en fonction de l'extension du fichier ; seul QsciLexerDiff colore reellement
    (cf. _rules()), les autres se contentent de retenir police et couleurs pour que le code
    appelant de TortoiseHg fonctionne sans cas particulier.
    """

    language_name = 'Generic'

    def __init__(self, parent=None):
        self._fonts = {}
        self._colors = {}
        self._papers = {}
        self._eolfills = {}
        self._defaultfont = QFont()
        self._defaultcolor = QColor(Qt.GlobalColor.black)
        self._defaultpaper = QColor(Qt.GlobalColor.white)
        self._editor = None

    def language(self):
        return self.language_name

    def lexer(self):
        return self.language_name.lower()

    def setFont(self, font, style=-1):
        if style == -1:
            self._defaultfont = font
            self._fonts.clear()
        else:
            self._fonts[style] = font
        self._refresh()

    def font(self, style=-1):
        return self._fonts.get(style, self._defaultfont)

    def setColor(self, color, style=-1):
        if style == -1:
            self._defaultcolor = color
        else:
            self._colors[style] = color
        self._refresh()

    def color(self, style=-1):
        return self._colors.get(style, self._defaultcolor)

    def setPaper(self, paper, style=-1):
        if style == -1:
            self._defaultpaper = paper
        else:
            self._papers[style] = paper
        self._refresh()

    def paper(self, style=-1):
        return self._papers.get(style, self._defaultpaper)


    def defaultFont(self, style=-1):
        return self._defaultfont

    def setEolFill(self, eolfill, style=-1):
        self._eolfills[style] = bool(eolfill)
        self._refresh()

    def eolFill(self, style=-1):
        return self._eolfills.get(style, False)

    def setAPIs(self, apis):
        self._apis = apis

    def apis(self):
        return getattr(self, '_apis', None)

    def description(self, style):
        return ''

    def setEditor(self, editor):
        self._editor = editor

    def editor(self):
        return self._editor

    def refreshProperties(self):
        self._refresh()

    def _refresh(self):
        editor = self._editor
        if editor is not None:
            editor._relexer()

    def _rules(self):
        """Regles de coloration, sous forme de liste (motif compile, QTextCharFormat).

        Vide par defaut : un lexer sans regle laisse le texte tel quel, ce qui est le
        comportement voulu pour les langages qu'on n'analyse pas.
        """
        return []


class QsciLexerDiff(QsciLexer):
    """Le seul lexer reellement implemente : c'est celui qui sert partout dans TortoiseHg.

    Les numeros de style sont ceux de Scintilla (SCE_DIFF_*), afin que les couleurs posees par
    lexers.py de TortoiseHg via setColor(couleur, numero) atterrissent au bon endroit.
    """

    language_name = 'Diff'

    # Noms ET numeros de QScintilla : lexers.py de TortoiseHg pose ses couleurs par
    # QsciLexerDiff.LineAdded / LineRemoved / Position, il faut donc les retrouver ici.
    Default = 0
    Comment = 1
    Command = 2
    Header = 3
    Position = 4
    LineRemoved = 5
    LineAdded = 6
    LineChanged = 7

    def _rules(self):
        regles = [
            (re.compile(r'^(diff|index|new file|deleted file|old mode|new mode)\b'),
             self.Command),
            (re.compile(r'^(---|\+\+\+)'), self.Header),
            (re.compile(r'^@@'), self.Position),
            (re.compile(r'^-'), self.LineRemoved),
            (re.compile(r'^\+'), self.LineAdded),
            (re.compile(r'^!'), self.LineChanged),
        ]
        sorties = []
        for motif, style in regles:
            fmt = QTextCharFormat()
            if style in self._colors:
                fmt.setForeground(self._colors[style])
            if style in self._papers:
                fmt.setBackground(self._papers[style])
            if style in self._fonts:
                fmt.setFont(self._fonts[style])
            sorties.append((motif, fmt))
        return sorties


class QsciLexerMakefile(QsciLexer):
    """Inerte comme les autres, mais il porte ses numeros de style : messageentry.py s'en sert
    pour peindre en rouge les lignes trop longues du message de commit."""

    language_name = 'Makefile'

    Default = 0
    Comment = 1
    Preprocessor = 2
    Variable = 3
    Operator = 4
    Target = 5
    Error = 6


def _lexer(nom, langage):
    """Fabrique une sous-classe inerte de QsciLexer, pour un langage qu'on ne colore pas."""
    return type(nom, (QsciLexer,), {'language_name': langage})


# Les 28 lexers designes par lexers.py de TortoiseHg, en fonction de l'extension du fichier.
QsciLexerBash = _lexer('QsciLexerBash', 'Bash')
QsciLexerBatch = _lexer('QsciLexerBatch', 'Batch')
QsciLexerCMake = _lexer('QsciLexerCMake', 'CMake')
QsciLexerCPP = _lexer('QsciLexerCPP', 'C++')
QsciLexerCSS = _lexer('QsciLexerCSS', 'CSS')
QsciLexerCSharp = _lexer('QsciLexerCSharp', 'C#')
QsciLexerD = _lexer('QsciLexerD', 'D')
QsciLexerFortran = _lexer('QsciLexerFortran', 'Fortran')
QsciLexerFortran77 = _lexer('QsciLexerFortran77', 'Fortran 77')
QsciLexerHTML = _lexer('QsciLexerHTML', 'HTML')
QsciLexerJava = _lexer('QsciLexerJava', 'Java')
QsciLexerJavaScript = _lexer('QsciLexerJavaScript', 'JavaScript')
QsciLexerLua = _lexer('QsciLexerLua', 'Lua')
QsciLexerMatlab = _lexer('QsciLexerMatlab', 'Matlab')
QsciLexerPascal = _lexer('QsciLexerPascal', 'Pascal')
QsciLexerPerl = _lexer('QsciLexerPerl', 'Perl')
QsciLexerProperties = _lexer('QsciLexerProperties', 'Properties')
QsciLexerPython = _lexer('QsciLexerPython', 'Python')
QsciLexerRuby = _lexer('QsciLexerRuby', 'Ruby')
QsciLexerSQL = _lexer('QsciLexerSQL', 'SQL')
QsciLexerSpice = _lexer('QsciLexerSpice', 'Spice')
QsciLexerTCL = _lexer('QsciLexerTCL', 'TCL')
QsciLexerTeX = _lexer('QsciLexerTeX', 'TeX')
QsciLexerVHDL = _lexer('QsciLexerVHDL', 'VHDL')
QsciLexerVerilog = _lexer('QsciLexerVerilog', 'Verilog')
QsciLexerXML = _lexer('QsciLexerXML', 'XML')
QsciLexerYAML = _lexer('QsciLexerYAML', 'YAML')


class QsciAPIs:
    """Base d'auto-completion. TortoiseHg l'alimente (revsets, noms de fichiers) mais rien ne
    la relit : l'auto-completion elle-meme n'est pas emulee. On garde l'API pour que le code
    appelant tourne sans branchement particulier."""

    def __init__(self, lexer=None):
        self._lexer = lexer
        self._entries = []

    def add(self, entry):
        self._entries.append(entry)

    def clear(self):
        self._entries = []

    def prepare(self):
        pass


class _Highlighter(QSyntaxHighlighter):
    """Applique les regles du lexer courant, ligne par ligne."""

    def __init__(self, document):
        super().__init__(document)
        self._rules = []

    def setRules(self, rules):
        self._rules = rules
        self.rehighlight()

    def highlightBlock(self, text):
        for motif, fmt in self._rules:
            if motif.match(text):
                self.setFormat(0, len(text), fmt)
                return


class _MarginArea(QWidget):
    """Zone de marge a gauche du texte : numeros de ligne, texte de marge, symboles.

    QPlainTextEdit n'a pas de marges ; celles de Scintilla sont donc redessinees ici, dans un
    widget place par setViewportMargins. Les clics y sont convertis en marginClicked, signal
    dont TortoiseHg se sert pour cocher les sections d'un diff (chunks.py).
    """

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor._totalMarginWidth(), 0)

    def paintEvent(self, event):
        self._editor._paintMargins(self, event)

    def mousePressEvent(self, event):
        self._editor._marginMousePress(event)


class QsciScintilla(QPlainTextEdit):
    """Emulation de QsciScintilla. Cf. l'en-tete du module pour le perimetre exact."""

    # Signal de Scintilla emis a la fin de chaque peinture. docklog.py s'y connecte le temps
    # de faire defiler jusqu'au curseur, puis s'en deconnecte.
    SCN_PAINTED = Signal()
    # Emis quand la taille de police change (Ctrl+molette). fileview.py s'y branche pour
    # recalculer la largeur de defilement horizontal.
    SCN_ZOOM = Signal()
    marginClicked = Signal(int, int, object)
    # QScintilla emet cursorPositionChanged(ligne, index) la ou QPlainTextEdit emet un signal
    # SANS argument. On ne peut pas simplement redeclarer le nom : sous PySide6 (mesure du
    # 03/08/2026) le signal masquant est bien celui qu'on obtient par attribut, mais celui de
    # la classe de base n'est alors plus joignable pour s'y brancher, et rien n'est jamais
    # emis. D'ou ce nom prive, aliase sur l'instance dans __init__ APRES la connexion au
    # signal de base - variante mesuree fonctionnelle.
    _qsciCursorPositionChanged = Signal(int, int)

    # --- Enumerations. IntEnum et non Enum : TortoiseHg reconstruit ces valeurs depuis des
    #     entiers relus dans QSettings (QsciScintilla.WrapMode(readInt(...))) et lit leur .value
    #     pour les y ecrire.
    class WrapMode(enum.IntEnum):
        WrapNone = 0
        WrapWord = 1
        WrapCharacter = 2
        WrapWhitespace = 3

    class WrapVisualFlag(enum.IntEnum):
        WrapFlagNone = 0
        WrapFlagByText = 1
        WrapFlagByBorder = 2
        WrapFlagInMargin = 3

    class WhitespaceVisibility(enum.IntEnum):
        WsInvisible = 0
        WsVisible = 1
        WsVisibleAfterIndent = 2

    class EolMode(enum.IntEnum):
        EolWindows = 0
        EolUnix = 1
        EolMac = 2

    class EdgeMode(enum.IntEnum):
        EdgeNone = 0
        EdgeLine = 1
        EdgeBackground = 2

    class BraceMatch(enum.IntEnum):
        NoBraceMatch = 0
        StrictBraceMatch = 1
        SloppyBraceMatch = 2

    class FoldStyle(enum.IntEnum):
        NoFoldStyle = 0
        PlainFoldStyle = 1
        CircledFoldStyle = 2
        BoxedFoldStyle = 3
        CircledTreeFoldStyle = 4
        BoxedTreeFoldStyle = 5

    class MarkerSymbol(enum.IntEnum):
        Circle = 0
        Rectangle = 1
        RightTriangle = 2
        SmallRectangle = 3
        RightArrow = 4
        Invisible = 5
        DownTriangle = 6
        Minus = 7
        Plus = 8
        VerticalLine = 9
        BottomLeftCorner = 10
        LeftSideSplitter = 11
        BoxedPlus = 12
        Background = 22
        FullRectangle = 26
        LeftRectangle = 27

    class MarginType(enum.IntEnum):
        SymbolMargin = 0
        SymbolMarginDefaultForegroundColor = 1
        SymbolMarginDefaultBackgroundColor = 2
        NumberMargin = 3
        TextMargin = 4
        TextMarginRightJustified = 5

    class AutoCompletionSource(enum.IntEnum):
        AcsNone = 0
        AcsAll = 1
        AcsDocument = 2
        AcsAPIs = 3

    class IndicatorStyle(enum.IntEnum):
        PlainIndicator = INDIC_PLAIN
        SquiggleIndicator = INDIC_SQUIGGLE
        StrikeIndicator = INDIC_STRIKE
        HiddenIndicator = INDIC_HIDDEN
        RoundBoxIndicator = INDIC_ROUNDBOX

    # Anciens noms plats, encore utilises tels quels par qscilib.py.
    PlainIndicator = INDIC_PLAIN
    StrikeIndicator = INDIC_STRIKE
    HiddenIndicator = INDIC_HIDDEN
    RoundBoxIndicator = INDIC_ROUNDBOX

    INDIC_PLAIN = INDIC_PLAIN
    INDIC_SQUIGGLE = INDIC_SQUIGGLE
    INDIC_STRIKE = INDIC_STRIKE
    INDIC_HIDDEN = INDIC_HIDDEN
    INDIC_ROUNDBOX = INDIC_ROUNDBOX
    INDIC_MAX = INDIC_MAX
    STYLE_LASTPREDEFINED = STYLE_LASTPREDEFINED
    SC_MULTIPASTE_EACH = SC_MULTIPASTE_EACH
    SCVS_RECTANGULARSELECTION = SCVS_RECTANGULARSELECTION

    # Les messages SCI_* sont aussi lus comme attributs de classe (self.SCI_INDICSETSTYLE).
    SCI_SCROLLCARET = SCI_SCROLLCARET
    SCI_SETHSCROLLBAR = SCI_SETHSCROLLBAR
    SCI_SETMARGINTYPEN = SCI_SETMARGINTYPEN
    SCI_SETMARGINWIDTHN = SCI_SETMARGINWIDTHN
    SCI_SETMARGINMASKN = SCI_SETMARGINMASKN
    SCI_STYLESETBACK = SCI_STYLESETBACK
    SCI_STYLESETFONT = SCI_STYLESETFONT
    SCI_STYLESETSIZE = SCI_STYLESETSIZE
    SCI_GETENDSTYLED = SCI_GETENDSTYLED
    SCI_SETSELEOLFILLED = SCI_SETSELEOLFILLED
    SCI_SETTARGETSTART = SCI_SETTARGETSTART
    SCI_SETTARGETEND = SCI_SETTARGETEND
    SCI_REPLACETARGET = SCI_REPLACETARGET
    SCI_SETENDATLASTLINE = SCI_SETENDATLASTLINE
    SCI_SETVISIBLEPOLICY = SCI_SETVISIBLEPOLICY
    SCI_LINEFROMPOSITION = SCI_LINEFROMPOSITION
    SCI_POSITIONFROMPOINT = SCI_POSITIONFROMPOINT
    SCI_POINTXFROMPOSITION = SCI_POINTXFROMPOSITION
    SCI_POINTYFROMPOSITION = SCI_POINTYFROMPOSITION
    SCI_GETCARETWIDTH = SCI_GETCARETWIDTH
    SCI_SETMULTIPLESELECTION = SCI_SETMULTIPLESELECTION
    SCI_SETADDITIONALSELECTIONTYPING = SCI_SETADDITIONALSELECTIONTYPING
    SCI_SETMULTIPASTE = SCI_SETMULTIPASTE
    SCI_SETVIRTUALSPACEOPTIONS = SCI_SETVIRTUALSPACEOPTIONS
    SCI_SETINDICATORCURRENT = SCI_SETINDICATORCURRENT
    SCI_INDICATORFILLRANGE = SCI_INDICATORFILLRANGE
    SCI_INDICATORCLEARRANGE = SCI_INDICATORCLEARRANGE
    SCI_INDICSETSTYLE = SCI_INDICSETSTYLE
    SCI_INDICSETFORE = SCI_INDICSETFORE
    SCI_INDICSETUNDER = SCI_INDICSETUNDER
    SCI_INDICSETALPHA = SCI_INDICSETALPHA

    def __init__(self, parent=None):
        super().__init__(parent)

        # Etat des marges : 5 comme Scintilla, indexees de 0 a 4.
        self._marginWidths = [0] * 5
        self._marginTypes = [self.MarginType.SymbolMargin] * 5
        self._marginLineNumbers = [False] * 5
        self._marginMasks = [0xffffffff] * 5
        self._marginSensitive = [False] * 5
        self._marginTexts = {}          # (marge, ligne) -> (texte, QsciStyle)
        self._marginsFont = self.font()

        # Marqueurs : definition (symbole ou pixmap), couleurs, et pose par ligne.
        self._markerSymbols = {}        # numero -> MarkerSymbol ou QPixmap
        self._markerBg = {}
        self._markerFg = {}
        self._lineMarkers = {}          # ligne -> masque de bits
        self._nextMarker = 0

        # Indicateurs : style, couleur, et intervalles poses (en positions de CARACTERE).
        self._indicStyles = {}
        self._indicColors = {}
        self._indicUnder = {}
        self._indicRanges = {}          # numero -> liste (debut, fin)
        self._currentIndic = 0

        self._lexer = None
        self._highlighter = _Highlighter(self.document())
        self._eolMode = self.EolMode.EolUnix
        self._acThreshold = -1
        self._acSource = self.AutoCompletionSource.AcsNone
        self._lastFind = None
        self._caretLineVisible = False
        self._caretLineColor = QColor(Qt.GlobalColor.yellow).lighter(180)
        self._utf8 = True

        # Table des debuts de ligne en octets, pour les conversions exigees par Scintilla.
        self._byteStarts = [0]
        self._byteStartsValid = False
        self.document().contentsChanged.connect(self._invalidateByteStarts)

        self._margin = _MarginArea(self)
        self.blockCountChanged.connect(lambda _n: self._updateMarginGeometry())
        self.updateRequest.connect(self._onUpdateRequest)
        self._updateMarginGeometry()

        # Alias du signal de position : cf. le commentaire de _qsciCursorPositionChanged.
        self.cursorPositionChanged.connect(self._emitQsciCursorPosition)
        self.cursorPositionChanged = self._qsciCursorPositionChanged

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    # --- Conversions de position ---------------------------------------------------------

    def _invalidateByteStarts(self):
        self._byteStartsValid = False

    def _ensureByteStarts(self):
        if self._byteStartsValid:
            return
        starts = [0]
        total = 0
        doc = self.document()
        for i in range(doc.blockCount()):
            texte = doc.findBlockByNumber(i).text()
            # +1 pour la fin de ligne, qui compte comme un octet cote Scintilla.
            total += len(texte.encode('utf-8')) + 1
            starts.append(total)
        self._byteStarts = starts
        self._byteStartsValid = True

    def _charToByte(self, charpos):
        doc = self.document()
        bloc = doc.findBlock(charpos)
        if not bloc.isValid():
            self._ensureByteStarts()
            return self._byteStarts[-1]
        self._ensureByteStarts()
        debut = self._byteStarts[bloc.blockNumber()]
        prefixe = bloc.text()[:charpos - bloc.position()]
        return debut + len(prefixe.encode('utf-8'))

    def _byteToChar(self, bytepos):
        self._ensureByteStarts()
        i = bisect.bisect_right(self._byteStarts, bytepos) - 1
        i = max(0, min(i, self.document().blockCount() - 1))
        bloc = self.document().findBlockByNumber(i)
        reste = bytepos - self._byteStarts[i]
        octets = bloc.text().encode('utf-8')
        if reste >= len(octets):
            return bloc.position() + len(bloc.text())
        return bloc.position() + len(octets[:reste].decode('utf-8', 'ignore'))

    # --- Texte ---------------------------------------------------------------------------

    def text(self, line=None):
        if line is None:
            return self.toPlainText()
        bloc = self.document().findBlockByNumber(line)
        if not bloc.isValid():
            return ''
        # QScintilla rend la ligne AVEC sa fin de ligne, sauf pour la derniere.
        if line < self.document().blockCount() - 1:
            return bloc.text() + '\n'
        return bloc.text()

    def setText(self, text):
        self.setPlainText(text)

    def append(self, text):
        curseur = QTextCursor(self.document())
        curseur.movePosition(QTextCursor.MoveOperation.End)
        curseur.insertText(text)

    def insert(self, text):
        """Insere au curseur SANS le deplacer, comme QScintilla."""
        curseur = self.textCursor()
        position = curseur.position()
        curseur.insertText(text)
        curseur.setPosition(position)
        self.setTextCursor(curseur)

    def insertAt(self, text, line, index):
        curseur = QTextCursor(self.document())
        curseur.setPosition(self._positionFrom(line, index))
        curseur.insertText(text)

    def clear(self):
        super().clear()
        self._lineMarkers.clear()
        self._indicRanges.clear()
        self._marginTexts.clear()
        self._refreshExtraSelections()

    def length(self):
        """Longueur en OCTETS, convention Scintilla."""
        self._ensureByteStarts()
        return max(0, self._byteStarts[-1] - 1)

    def lines(self):
        return self.document().blockCount()

    def lineLength(self, line):
        bloc = self.document().findBlockByNumber(line)
        if not bloc.isValid():
            return -1
        return len(bloc.text().encode('utf-8')) + (
            1 if line < self.document().blockCount() - 1 else 0)

    def _positionFrom(self, line, index):
        bloc = self.document().findBlockByNumber(line)
        if not bloc.isValid():
            return self.document().characterCount() - 1
        return bloc.position() + min(index, len(bloc.text()))

    def positionFromLineIndex(self, line, index):
        return self._charToByte(self._positionFrom(line, index))

    def lineIndexFromPosition(self, position):
        charpos = self._byteToChar(position)
        bloc = self.document().findBlock(charpos)
        if not bloc.isValid():
            return (-1, -1)
        return (bloc.blockNumber(), charpos - bloc.position())

    def getCursorPosition(self):
        curseur = self.textCursor()
        return (curseur.blockNumber(), curseur.position() - curseur.block().position())

    def setCursorPosition(self, line, index):
        curseur = self.textCursor()
        curseur.setPosition(self._positionFrom(line, index))
        self.setTextCursor(curseur)

    def getSelection(self):
        curseur = self.textCursor()
        if not curseur.hasSelection():
            return (-1, -1, -1, -1)
        doc = self.document()
        debut, fin = curseur.selectionStart(), curseur.selectionEnd()
        bd, bf = doc.findBlock(debut), doc.findBlock(fin)
        return (bd.blockNumber(), debut - bd.position(),
                bf.blockNumber(), fin - bf.position())

    def setSelection(self, lineFrom, indexFrom, lineTo, indexTo):
        curseur = self.textCursor()
        curseur.setPosition(self._positionFrom(lineFrom, indexFrom))
        curseur.setPosition(self._positionFrom(lineTo, indexTo),
                            QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(curseur)

    def selectedText(self):
        # \u2029 ecrit en ECHAPPEMENT et non en clair : ce caractere est un
        # separateur de paragraphe Unicode, que Python (splitlines) et les editeurs
        # comptent comme une fin de ligne. Pose en clair dans la source, il faisait
        # signaler a Spyder des « fins de ligne melangees » a chaque ouverture du
        # fichier (signale par l'utilisateur le 03/08/2026).
        return self.textCursor().selectedText().replace('\u2029', '\n')

    def hasSelectedText(self):
        return self.textCursor().hasSelection()

    def removeSelectedText(self):
        self.textCursor().removeSelectedText()

    def selectAll(self, select=True):
        if select:
            super().selectAll()
        else:
            curseur = self.textCursor()
            curseur.clearSelection()
            self.setTextCursor(curseur)

    def beginUndoAction(self):
        self.textCursor().beginEditBlock()

    def endUndoAction(self):
        self.textCursor().endEditBlock()

    def isUndoAvailable(self):
        return self.document().isUndoAvailable()

    def isRedoAvailable(self):
        return self.document().isRedoAvailable()

    def isModified(self):
        return self.document().isModified()

    def setModified(self, modified):
        self.document().setModified(modified)

    def setUtf8(self, utf8):
        self._utf8 = utf8


    # --- Recherche -----------------------------------------------------------------------

    def findFirst(self, expr, re_, cs, wo, wrap, forward=True, line=-1, index=-1,
                  show=True, posix=False):
        self._lastFind = (expr, re_, cs, wo, wrap, forward)
        return self._find(from_cursor=True)

    def findNext(self):
        if not self._lastFind:
            return False
        return self._find(from_cursor=True)

    def _find(self, from_cursor=True):
        from qtpy.QtCore import QRegularExpression
        expr, re_, cs, wo, wrap, forward = self._lastFind
        drapeaux = self._findFlags(cs, wo, forward)
        doc = self.document()
        depart = self.textCursor()
        if re_:
            motif = QRegularExpression(expr)
            if not cs:
                motif.setPatternOptions(
                    QRegularExpression.PatternOption.CaseInsensitiveOption)
            trouve = doc.find(motif, depart, drapeaux)
            if trouve.isNull() and wrap:
                debut = QTextCursor(doc)
                if not forward:
                    debut.movePosition(QTextCursor.MoveOperation.End)
                trouve = doc.find(motif, debut, drapeaux)
        else:
            trouve = doc.find(expr, depart, drapeaux)
            if trouve.isNull() and wrap:
                debut = QTextCursor(doc)
                if not forward:
                    debut.movePosition(QTextCursor.MoveOperation.End)
                trouve = doc.find(expr, debut, drapeaux)
        if trouve.isNull():
            return False
        self.setTextCursor(trouve)
        return True

    @staticmethod
    def _findFlags(cs, wo, forward):
        drapeaux = QTextDocument.FindFlag(0)
        if cs:
            drapeaux |= QTextDocument.FindFlag.FindCaseSensitively
        if wo:
            drapeaux |= QTextDocument.FindFlag.FindWholeWords
        if not forward:
            drapeaux |= QTextDocument.FindFlag.FindBackward
        return drapeaux

    # --- Apparence -----------------------------------------------------------------------

    def setWrapMode(self, mode):
        mode = self.WrapMode(int(mode))
        if mode == self.WrapMode.WrapNone:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        else:
            self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            option = self.wordWrapMode()
            if mode == self.WrapMode.WrapCharacter:
                option = QTextOption.WrapMode.WrapAnywhere
            elif mode == self.WrapMode.WrapWord:
                option = QTextOption.WrapMode.WordWrap
            self.setWordWrapMode(option)
        self._wrapMode = mode

    def wrapMode(self):
        return getattr(self, '_wrapMode', self.WrapMode.WrapNone)

    def setWrapVisualFlags(self, endFlag, startFlag=None, indent=0):
        pass  # purement cosmetique, rien ne le relit

    def setWhitespaceVisibility(self, mode):
        mode = self.WhitespaceVisibility(int(mode))
        option = self.document().defaultTextOption()
        drapeaux = option.flags()
        if mode == self.WhitespaceVisibility.WsInvisible:
            drapeaux &= ~QTextOption.Flag.ShowTabsAndSpaces
        else:
            drapeaux |= QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(drapeaux)
        self.document().setDefaultTextOption(option)
        self._wsVisibility = mode

    def whitespaceVisibility(self):
        return getattr(self, '_wsVisibility', self.WhitespaceVisibility.WsInvisible)

    def setEolVisibility(self, visible):
        option = self.document().defaultTextOption()
        drapeaux = option.flags()
        if visible:
            drapeaux |= QTextOption.Flag.ShowLineAndParagraphSeparators
        else:
            drapeaux &= ~QTextOption.Flag.ShowLineAndParagraphSeparators
        option.setFlags(drapeaux)
        self.document().setDefaultTextOption(option)
        self._eolVisible = bool(visible)

    def eolVisibility(self):
        return getattr(self, '_eolVisible', False)

    def setEolMode(self, mode):
        self._eolMode = self.EolMode(int(mode))

    def eolMode(self):
        return self._eolMode

    def setIndentationsUseTabs(self, tabs):
        self._useTabs = bool(tabs)

    def indentationsUseTabs(self):
        return getattr(self, '_useTabs', False)

    def setIndentationWidth(self, width):
        self._indentWidth = width


    def setTabWidth(self, width):
        self._tabWidth = width
        self.setTabStopDistance(width * QFontMetrics(self.font()).horizontalAdvance(' '))


    def setAutoIndent(self, autoindent):
        self._autoIndent = bool(autoindent)


    def setBraceMatching(self, mode):
        pass  # cosmetique

    def setMatchedBraceBackgroundColor(self, color):
        pass  # cosmetique

    def setEdgeMode(self, mode):
        pass  # cosmetique

    def setEdgeColumn(self, column):
        pass  # cosmetique

    def setEdgeColor(self, color):
        pass  # cosmetique

    def setFolding(self, style, margin=2):
        pass  # le repli de lignes n'est pas emule

    def setCaretLineVisible(self, enable):
        self._caretLineVisible = bool(enable)
        self._refreshExtraSelections()

    def setCaretLineBackgroundColor(self, color):
        self._caretLineColor = color
        self._refreshExtraSelections()

    def setCaretWidth(self, width):
        self.setCursorWidth(width)

    def setColor(self, color):
        palette = self.palette()
        palette.setColor(palette.ColorRole.Text, color)
        self.setPalette(palette)

    def color(self):
        return self.palette().color(self.palette().ColorRole.Text)

    def setPaper(self, color):
        palette = self.palette()
        palette.setColor(palette.ColorRole.Base, color)
        self.setPalette(palette)

    def paper(self):
        return self.palette().color(self.palette().ColorRole.Base)


    def setFont(self, font):
        super().setFont(font)
        self._marginsFont = font
        self._updateMarginGeometry()

    def textHeight(self, line=-1):
        return QFontMetrics(self.font()).height()

    def ensureLineVisible(self, line):
        """Fait defiler jusqu'a la ligne, sans deplacer le curseur.

        La barre de defilement de QPlainTextEdit compte en blocs tant qu'il n'y a pas de retour
        a la ligne automatique : exact dans ce cas, approche sinon. C'est la seule approximation
        assumee du module, et elle ne concerne que le point d'arrivee du defilement.
        """
        barre = self.verticalScrollBar()
        premier = self.firstVisibleBlock().blockNumber()
        visibles = max(1, self.viewport().height() // max(1, self.textHeight()))
        if line < premier or line >= premier + visibles:
            barre.setValue(min(line, barre.maximum()))

    def firstVisibleLine(self):
        return self.firstVisibleBlock().blockNumber()


    def lineAt(self, point):
        curseur = self.cursorForPosition(point)
        rect = self.cursorRect(curseur)
        if point.y() < rect.top() - self.textHeight() or point.y() > rect.bottom() + self.textHeight():
            return -1
        return curseur.blockNumber()

    def setScrollWidth(self, width):
        """Sans effet, et c'est correct ici.

        Scintilla ignore la largeur reelle du texte et exige qu'on lui donne la course de sa
        barre horizontale. QPlainTextEdit la calcule lui-meme a partir du document : lui imposer
        une valeur n'aurait pas de sens, et ne rien faire donne le bon comportement.
        """

    def wheelEvent(self, event):
        # Ctrl+molette change la taille de police : c'est le zoom de Scintilla, et fileview.py
        # se branche sur SCN_ZOOM pour en tenir compte. Il faut passer par wheelEvent, seule
        # methode VIRTUELLE du trajet : zoomIn/zoomOut de QPlainTextEdit ne le sont pas, les
        # redefinir en Python ne les intercepterait donc pas quand Qt les appelle lui-meme.
        super().wheelEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.SCN_ZOOM.emit()

    def standardCommands(self):
        return _StandardCommands()


    # --- Auto-completion (inerte, cf. QsciAPIs) --------------------------------------------

    def setAutoCompletionSource(self, source):
        self._acSource = source


    def setAutoCompletionThreshold(self, threshold):
        self._acThreshold = threshold

    def autoCompletionThreshold(self):
        return self._acThreshold

    def setAutoCompletionFillupsEnabled(self, enabled):
        pass

    def isListActive(self):
        return False

    # --- Lexer ---------------------------------------------------------------------------

    def setLexer(self, lexer=None):
        self._lexer = lexer
        if lexer is not None:
            lexer.setEditor(self)
            police = lexer.defaultFont()
            if police is not None:
                super().setFont(police)
        self._relexer()

    def lexer(self):
        return self._lexer

    def _relexer(self):
        regles = self._lexer._rules() if self._lexer is not None else []
        self._highlighter.setRules(regles)

    # --- Marges --------------------------------------------------------------------------

    def setMarginType(self, margin, type_):
        self._marginTypes[margin] = type_
        self._margin.update()


    def setMarginWidth(self, margin, width):
        # QScintilla accepte un entier de pixels OU une chaine dont on prend la largeur.
        if isinstance(width, str):
            width = QFontMetrics(self._marginsFont).horizontalAdvance(width)
        self._marginWidths[margin] = int(width)
        self._updateMarginGeometry()


    def setMarginLineNumbers(self, margin, lnrs):
        self._marginLineNumbers[margin] = bool(lnrs)
        self._margin.update()


    def setMarginMarkerMask(self, margin, mask):
        self._marginMasks[margin] = mask
        self._margin.update()

    def setMarginSensitivity(self, margin, sens):
        self._marginSensitive[margin] = bool(sens)


    def setMarginsFont(self, font):
        self._marginsFont = font
        self._updateMarginGeometry()

    def setMarginText(self, line, text, style):
        self._marginTexts[line] = (text, style)
        self._margin.update()

    def clearMarginText(self, line=-1):
        if line == -1:
            self._marginTexts.clear()
        else:
            self._marginTexts.pop(line, None)
        self._margin.update()

    def _totalMarginWidth(self):
        return sum(self._marginWidths)

    def _updateMarginGeometry(self):
        largeur = self._totalMarginWidth()
        self.setViewportMargins(largeur, 0, 0, 0)
        cr = self.contentsRect()
        self._margin.setGeometry(QRect(cr.left(), cr.top(), largeur, cr.height()))
        self._margin.update()

    def _onUpdateRequest(self, rect, dy):
        if dy:
            self._margin.scroll(0, dy)
        else:
            self._margin.update(0, rect.y(), self._margin.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateMarginGeometry()

    def _marginXRange(self, margin):
        debut = sum(self._marginWidths[:margin])
        return debut, debut + self._marginWidths[margin]

    def _paintMargins(self, widget, event):
        peintre = QPainter(widget)
        peintre.fillRect(event.rect(), self.palette().window())
        peintre.setFont(self._marginsFont)
        metrique = QFontMetrics(self._marginsFont)

        bloc = self.firstVisibleBlock()
        haut = self.blockBoundingGeometry(bloc).translated(self.contentOffset()).top()
        while bloc.isValid() and haut <= event.rect().bottom():
            hauteur = self.blockBoundingRect(bloc).height()
            if haut + hauteur >= event.rect().top():
                ligne = bloc.blockNumber()
                for marge in range(5):
                    largeur = self._marginWidths[marge]
                    if largeur <= 0:
                        continue
                    x0, x1 = self._marginXRange(marge)
                    rect = QRect(x0, int(haut), largeur, int(hauteur))
                    if self._marginLineNumbers[marge]:
                        peintre.setPen(self.palette().color(
                            self.palette().ColorRole.WindowText))
                        peintre.drawText(rect.adjusted(0, 0, -2, 0),
                                         int(Qt.AlignmentFlag.AlignRight
                                             | Qt.AlignmentFlag.AlignVCenter),
                                         str(ligne + 1))
                    elif ligne in self._marginTexts:
                        texte, style = self._marginTexts[ligne]
                        if isinstance(style, QsciStyle):
                            peintre.fillRect(rect, style.paper())
                            peintre.setPen(style.color())
                        peintre.drawText(rect.adjusted(2, 0, -2, 0),
                                         int(Qt.AlignmentFlag.AlignLeft
                                             | Qt.AlignmentFlag.AlignVCenter),
                                         texte)
                    else:
                        self._paintMarkerSymbols(peintre, rect, ligne,
                                                 self._marginMasks[marge])
            bloc = bloc.next()
            haut += hauteur
        peintre.end()

    def _paintMarkerSymbols(self, peintre, rect, ligne, masque):
        bits = self._lineMarkers.get(ligne, 0) & masque
        if not bits:
            return
        for numero, symbole in self._markerSymbols.items():
            if not (bits & (1 << numero)):
                continue
            if isinstance(symbole, QPixmap):
                x = rect.x() + max(0, (rect.width() - symbole.width()) // 2)
                y = rect.y() + max(0, (rect.height() - symbole.height()) // 2)
                peintre.drawPixmap(x, y, symbole)
            elif symbole == self.MarkerSymbol.VerticalLine:
                couleur = self._markerFg.get(numero, QColor(Qt.GlobalColor.gray))
                peintre.fillRect(rect.x() + rect.width() // 2, rect.y(), 1,
                                 rect.height(), couleur)
            elif symbole == self.MarkerSymbol.Invisible:
                continue
            elif symbole != self.MarkerSymbol.Background:
                couleur = self._markerBg.get(numero, QColor(Qt.GlobalColor.gray))
                peintre.setBrush(couleur)
                peintre.setPen(Qt.PenStyle.NoPen)
                cote = min(rect.width(), int(rect.height())) - 2
                peintre.drawEllipse(rect.x() + (rect.width() - cote) // 2,
                                    rect.y() + (int(rect.height()) - cote) // 2,
                                    cote, cote)

    def _marginMousePress(self, event):
        x = int(event.position().x()) if hasattr(event, 'position') else event.x()
        y = int(event.position().y()) if hasattr(event, 'position') else event.y()
        marge = None
        for i in range(5):
            x0, x1 = self._marginXRange(i)
            if x0 <= x < x1 and self._marginWidths[i] > 0:
                marge = i
                break
        if marge is None or not self._marginSensitive[marge]:
            return
        ligne = self.cursorForPosition(QPoint(0, y)).blockNumber()
        self.marginClicked.emit(marge, ligne, event.modifiers())

    # --- Marqueurs -----------------------------------------------------------------------

    def markerDefine(self, symbol, markerNumber=-1):
        if markerNumber == -1:
            markerNumber = self._nextMarker
            self._nextMarker += 1
        self._markerSymbols[markerNumber] = symbol
        return markerNumber

    def markerAdd(self, linenr, markerNumber):
        self._lineMarkers[linenr] = self._lineMarkers.get(linenr, 0) | (1 << markerNumber)
        self._margin.update()
        self.viewport().update()
        return (linenr << 8) | markerNumber

    def markerDelete(self, linenr, markerNumber=-1):
        if markerNumber == -1:
            self._lineMarkers.pop(linenr, None)
        elif linenr in self._lineMarkers:
            self._lineMarkers[linenr] &= ~(1 << markerNumber)
            if not self._lineMarkers[linenr]:
                del self._lineMarkers[linenr]
        self._margin.update()
        self.viewport().update()

    def markerDeleteAll(self, markerNumber=-1):
        if markerNumber == -1:
            self._lineMarkers.clear()
        else:
            for ligne in list(self._lineMarkers):
                self.markerDelete(ligne, markerNumber)
        self._margin.update()
        self.viewport().update()

    def markersAtLine(self, linenr):
        return self._lineMarkers.get(linenr, 0)

    def markerFindNext(self, linenr, mask):
        for ligne in sorted(self._lineMarkers):
            if ligne >= linenr and (self._lineMarkers[ligne] & mask):
                return ligne
        return -1

    def markerFindPrevious(self, linenr, mask):
        for ligne in sorted(self._lineMarkers, reverse=True):
            if ligne <= linenr and (self._lineMarkers[ligne] & mask):
                return ligne
        return -1

    def setMarkerBackgroundColor(self, color, markerNumber=-1):
        self._markerBg[markerNumber] = color
        self.viewport().update()
        self._margin.update()

    def setMarkerForegroundColor(self, color, markerNumber=-1):
        self._markerFg[markerNumber] = color
        self.viewport().update()
        self._margin.update()

    # --- Indicateurs ---------------------------------------------------------------------

    def indicatorDefine(self, style, indicatorNumber=-1):
        if indicatorNumber == -1:
            indicatorNumber = 1 + len(self._indicStyles)
        self._indicStyles[indicatorNumber] = int(style)
        return indicatorNumber

    def setIndicatorForegroundColor(self, color, indicatorNumber=-1):
        self._indicColors[indicatorNumber] = color
        self._refreshExtraSelections()

    def setIndicatorDrawUnder(self, under, indicatorNumber=-1):
        self._indicUnder[indicatorNumber] = bool(under)

    def fillIndicatorRange(self, lineFrom, indexFrom, lineTo, indexTo, indicatorNumber):
        debut = self._positionFrom(lineFrom, indexFrom)
        fin = self._positionFrom(lineTo, indexTo)
        self._indicRanges.setdefault(indicatorNumber, []).append((debut, fin))
        self._refreshExtraSelections()

    def clearIndicatorRange(self, lineFrom, indexFrom, lineTo, indexTo, indicatorNumber):
        debut = self._positionFrom(lineFrom, indexFrom)
        fin = self._positionFrom(lineTo, indexTo)
        restants = [(d, f) for d, f in self._indicRanges.get(indicatorNumber, [])
                    if f <= debut or d >= fin]
        self._indicRanges[indicatorNumber] = restants
        self._refreshExtraSelections()

    def _refreshExtraSelections(self):
        selections = []
        if self._caretLineVisible:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(self._caretLineColor)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            selections.append(selection)
        for numero, intervalles in self._indicRanges.items():
            style = self._indicStyles.get(numero, INDIC_PLAIN)
            if style == INDIC_HIDDEN:
                continue
            couleur = self._indicColors.get(numero)
            for debut, fin in intervalles:
                selection = QTextEdit.ExtraSelection()
                if style == INDIC_STRIKE:
                    selection.format.setFontStrikeOut(True)
                    if couleur is not None:
                        selection.format.setForeground(couleur)
                elif style == INDIC_ROUNDBOX:
                    selection.format.setBackground(
                        couleur if couleur is not None else QColor(255, 255, 0, 100))
                else:
                    if couleur is not None:
                        selection.format.setUnderlineColor(couleur)
                    selection.format.setFontUnderline(True)
                curseur = QTextCursor(self.document())
                curseur.setPosition(debut)
                curseur.setPosition(fin, QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = curseur
                selections.append(selection)
        self.setExtraSelections(selections)

    # --- Peinture ------------------------------------------------------------------------

    def paintEvent(self, event):
        # Les marqueurs "Background" colorent toute la ligne : ils sont peints SOUS le texte,
        # donc avant l'appel a la classe de base.
        if self._lineMarkers and self._markerSymbols:
            peintre = QPainter(self.viewport())
            bloc = self.firstVisibleBlock()
            haut = self.blockBoundingGeometry(bloc).translated(self.contentOffset()).top()
            while bloc.isValid() and haut <= event.rect().bottom():
                hauteur = self.blockBoundingRect(bloc).height()
                bits = self._lineMarkers.get(bloc.blockNumber(), 0)
                if bits and haut + hauteur >= event.rect().top():
                    for numero, symbole in self._markerSymbols.items():
                        if not (bits & (1 << numero)):
                            continue
                        if symbole is self.MarkerSymbol.Background or \
                                symbole == self.MarkerSymbol.Background:
                            couleur = self._markerBg.get(numero)
                            if couleur is not None:
                                peintre.fillRect(0, int(haut), self.viewport().width(),
                                                 int(hauteur), couleur)
                bloc = bloc.next()
                haut += hauteur
            peintre.end()
        super().paintEvent(event)
        self.SCN_PAINTED.emit()

    def __getattr__(self, nom):
        # Appele UNIQUEMENT quand l'attribut est introuvable par la voie normale.
        if _DECOUVERTE and not nom.startswith('__'):
            _consigner(nom)
            return _Passepartout(nom)
        raise AttributeError(
            "'%s' n'a pas d'attribut '%s' : cette part de l'API QScintilla n'est pas emulee "
            "par smartos_qsci. Relancer avec SMARTOS_QSCI_DECOUVERTE=<fichier> pour recenser "
            "tout ce qui manque en une passe." % (type(self).__name__, nom))

    def _emitQsciCursorPosition(self):
        curseur = self.textCursor()
        self._qsciCursorPositionChanged.emit(
            curseur.blockNumber(), curseur.position() - curseur.block().position())

    # --- SendScintilla -------------------------------------------------------------------

    def SendScintilla(self, message, *args):
        """Achemine les messages Scintilla que TortoiseHg emet reellement.

        Un message inconnu est ignore et rend 0, exactement comme Scintilla le fait d'un
        message qu'il ne connait pas : ce n'est pas un silence commode, c'est le comportement
        d'origine. Les messages traites sont ceux releves dans tortoisehg/hgqt.
        """
        if message == SCI_SETINDICATORCURRENT:
            self._currentIndic = args[0]
            return 0
        if message == SCI_INDICATORFILLRANGE:
            debut, longueur = args[0], args[1]
            d = self._byteToChar(debut)
            f = self._byteToChar(debut + longueur)
            self._indicRanges.setdefault(self._currentIndic, []).append((d, f))
            self._refreshExtraSelections()
            return 0
        if message == SCI_INDICATORCLEARRANGE:
            debut, longueur = args[0], args[1]
            d = self._byteToChar(debut)
            f = self._byteToChar(debut + longueur)
            restants = [(a, b) for a, b in self._indicRanges.get(self._currentIndic, [])
                        if b <= d or a >= f]
            self._indicRanges[self._currentIndic] = restants
            self._refreshExtraSelections()
            return 0
        if message == SCI_INDICSETSTYLE:
            self._indicStyles[args[0]] = int(args[1])
            return 0
        if message == SCI_INDICSETFORE:
            self._indicColors[args[0]] = _tocolor(args[1])
            return 0
        if message == SCI_INDICSETALPHA:
            couleur = self._indicColors.get(args[0])
            if couleur is not None:
                couleur = QColor(couleur)
                couleur.setAlpha(int(args[1]))
                self._indicColors[args[0]] = couleur
            self._refreshExtraSelections()
            return 0
        if message == SCI_INDICSETUNDER:
            self._indicUnder[args[0]] = bool(args[1])
            return 0
        if message == SCI_LINEFROMPOSITION:
            return self.lineIndexFromPosition(args[0])[0]
        if message == SCI_POSITIONFROMPOINT:
            point = QPoint(int(args[0]), int(args[1]))
            return self._charToByte(self.cursorForPosition(point).position())
        if message == SCI_POINTXFROMPOSITION:
            curseur = QTextCursor(self.document())
            curseur.setPosition(self._byteToChar(args[1]))
            return self.cursorRect(curseur).x()
        if message == SCI_POINTYFROMPOSITION:
            curseur = QTextCursor(self.document())
            curseur.setPosition(self._byteToChar(args[1]))
            return self.cursorRect(curseur).y()
        if message == SCI_GETCARETWIDTH:
            return self.cursorWidth()
        if message == SCI_SCROLLCARET:
            self.ensureCursorVisible()
            return 0
        if message == SCI_SETHSCROLLBAR:
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded if args[0]
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            return 0
        if message == SCI_SETMARGINTYPEN:
            self._marginTypes[args[0]] = args[1]
            return 0
        if message == SCI_SETMARGINWIDTHN:
            self.setMarginWidth(args[0], args[1])
            return 0
        if message == SCI_SETMARGINMASKN:
            self._marginMasks[args[0]] = args[1]
            return 0
        if message == SCI_SETTARGETSTART:
            self._targetStart = args[0]
            return 0
        if message == SCI_SETTARGETEND:
            self._targetEnd = args[0]
            return 0
        if message == SCI_REPLACETARGET:
            debut = self._byteToChar(getattr(self, '_targetStart', 0))
            fin = self._byteToChar(getattr(self, '_targetEnd', 0))
            remplacement = args[1] if len(args) > 1 else b''
            if isinstance(remplacement, bytes):
                remplacement = remplacement.decode('utf-8', 'replace')
            curseur = QTextCursor(self.document())
            curseur.setPosition(debut)
            curseur.setPosition(fin, QTextCursor.MoveMode.KeepAnchor)
            curseur.insertText(remplacement)
            return 0
        if message == SCI_GETENDSTYLED:
            return self.document().characterCount()
        # SCI_STYLESET*, SCI_SETSELEOLFILLED, SCI_SETENDATLASTLINE, SCI_SETVISIBLEPOLICY,
        # selections multiples : reglages de rendu sans equivalent ici. Ignores.
        return 0
