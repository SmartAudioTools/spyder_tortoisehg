# -*- coding: utf-8 -*-
"""Monte le contexte minimal que les widgets de TortoiseHg exigent, DANS le processus hote.

POURQUOI CE MODULE EXISTE
    TortoiseHg construit d'ordinaire ses widgets depuis un QtRunner (hgqt/qtapp.py) qui cree
    lui-meme le QApplication et se croit seul maitre a bord : instance unique, serveur de
    fenetres, capture des exceptions, sortie du programme. Rien de tout cela n'a de sens dans
    Spyder, qui a deja son application.

    Mesure du 03/08/2026 (Commun/scripts/thg_capture/epreuve_repowidget.py) : les widgets ne
    dependent PAS du QtRunner. Il suffit de refaire a la main les cinq preparatifs qu'il fait
    avant eux. Ce module les fait une fois par processus, et rien de plus.

LES CINQ PREPARATIFS, ET CE QUI ARRIVE SI ON EN OUBLIE UN
    1. hglib.loadui()                   l'objet ui de Mercurial.
    2. la ligne "extensions"            declare les reglages par defaut de TortoiseHg. SANS
                                        elle, le serveur de commandes part avec un delai
                                        d'attente a None et leve un TypeError des sa
                                        construction - erreur qui ne nomme pas sa cause.
    3. qtlib.configstyles(ui)           couleurs.
    4. qtlib.initfontcache(ui)          polices. Sans lui, getfont() leve une assertion.
    5. ActionRegistry + RepoManager     ce que le RepoWidget recoit en arguments.

ET UN SIXIEME GESTE, QUI N'EST PAS UN PREPARATIF MAIS UNE CORRECTION
    _confiner_les_raccourcis_standard() : TortoiseHg pose ses raccourcis de touche standard
    (Ctrl+F, F5) sur la FENETRE, ce qui n'a de sens que dans son Workbench. Dans Spyder, cette
    fenetre est celle de l'editeur, et le Ctrl+F de l'editeur devient ambigu. Cf. la fonction.

⚠ CE MODULE N'IMPORTE TORTOISEHG QU'A L'APPEL, JAMAIS AU CHARGEMENT. Spyder avale en silence
  toute exception levee pendant le chargement d'un greffon : un import manquant ferait
  disparaitre le panneau du menu, sans un mot. Ici, l'absence de TortoiseHg est un etat NOMME,
  que le panneau affiche a l'utilisateur.
"""

import io
import os
import sys

_contexte = None

# Flux de remplacement poses pour Mercurial : gardes en vie pour toute la duree du processus,
# cf. l'avertissement dans _flux_utilisables().
_SUBSTITUTS = []


def _flux_utilisables():
    """Donne a Mercurial des flux standard qu'il puisse utiliser, le temps de l'import.

    ⚠ SANS CELA, LE PANNEAU ANNONCE A TORT « TortoiseHg n'est pas installe ». Mercurial lit
    sys.stdin/stdout/stderr .buffer DES L'IMPORT de mercurial.utils.procutil. Or Spyder LANCE
    DEPUIS LE MENU n'a pas de console : ses flux standard sont des objets sans .buffer (ou
    None), et l'import leve AttributeError - que le panneau interprete alors comme une absence
    de TortoiseHg. Signale par l'utilisateur le 03/08/2026.

    Le defaut avait echappe aux essais parce qu'ils lancaient Spyder DEPUIS UN TERMINAL, ou les
    flux sont de vrais fichiers : le contexte n'est pas le meme, et c'est le contexte reel qui
    fait foi.

    Les flux poses visent /dev/null, et c'est double benefice : Mercurial peut ecrire, et ce
    qu'il ecrit ne part PAS dans la console interne de Spyder, qui traite chaque ligne recue
    sur stderr comme une erreur et ouvre une fenetre « probleme interne ».

    Ils ne sont poses QUE le temps de l'import - Mercurial en garde la reference, ce qui est
    exactement l'effet voulu -, puis les flux d'origine de Spyder sont remis en place.

    ⚠ ET ILS SONT GARDES DANS _SUBSTITUTS, sans quoi rien ne marche : des qu'on les retire de
    sys, plus personne ne les reference cote Python, le ramasse-miettes les detruit, le fichier
    sous-jacent se ferme - et Mercurial, qui en garde le .buffer, echoue plus tard sur « I/O
    operation on closed file ». Constate en direct en ecrivant ce correctif.
    """
    remplaces = {}
    for nom, mode in (('stdin', 'rb'), ('stdout', 'wb'), ('stderr', 'wb')):
        flux = getattr(sys, nom, None)
        if flux is not None and hasattr(flux, 'buffer'):
            continue
        remplaces[nom] = flux
        substitut = io.TextIOWrapper(open(os.devnull, mode))
        _SUBSTITUTS.append(substitut)
        setattr(sys, nom, substitut)
    return remplaces


class ContexteAbsent(Exception):
    """TortoiseHg ou Mercurial n'est pas installe dans le venv de Spyder."""


class ContexteThg:
    """Les objets partages par tous les depots ouverts dans le panneau."""

    def __init__(self, ui, registre, gestionnaire):
        self.ui = ui
        self.registre = registre
        self.gestionnaire = gestionnaire


def disponible():
    """TortoiseHg est-il importable ici ? Ne construit rien, ne leve rien.

    N'est PAS appele par le panneau - qui constate l'absence au premier depot a ouvrir, pour
    ne pas importer toute la pile graphique de TortoiseHg au demarrage de Spyder. Sert au banc
    d'essai de l'installateur.
    """
    remplaces = _flux_utilisables()
    try:
        import tortoisehg.hgqt.repowidget  # noqa: F401
    except Exception:
        return False
    finally:
        for nom, flux in remplaces.items():
            setattr(sys, nom, flux)
    return True


def contexte():
    """Rend le contexte partage, en le construisant au premier appel.

    Leve ContexteAbsent si TortoiseHg n'est pas installe - le panneau le dit alors a
    l'utilisateur au lieu de disparaitre.
    """
    global _contexte
    if _contexte is not None:
        return _contexte

    remplaces = _flux_utilisables()
    try:
        from tortoisehg.util import hglib
        from tortoisehg.hgqt import qtlib, shortcutregistry, thgrepo
    except Exception as erreur:
        raise ContexteAbsent(str(erreur))
    finally:
        for nom, flux in remplaces.items():
            setattr(sys, nom, flux)

    ui = hglib.loadui()
    ui.setconfig(b'extensions', b'tortoisehg.util.configitems', b'', b'spyder_tortoisehg')
    _montrer_les_onglets_de_taches(ui)
    qtlib.configstyles(ui)
    qtlib.initfontcache(ui)
    _confiner_les_raccourcis_standard(qtlib)

    registre = shortcutregistry.ActionRegistry()
    registre.readSettings()
    _rendre_le_registre_des_depots_partage()

    _contexte = ContexteThg(ui, registre, thgrepo.RepoManager(ui))
    return _contexte


def _confiner_les_raccourcis_standard(qtlib):
    """Confine au panneau les raccourcis « touche standard » que TortoiseHg pose sur la FENETRE.

    ⚠ SANS CELA, CTRL+F NE FAIT PLUS RIEN DANS L'EDITEUR DES QUE LE PANNEAU A ETE OUVERT UNE
    FOIS. Signale par l'utilisateur le 04/10/2026 : « rien du tout ne s'affiche, il ne se passe
    rien ». TortoiseHg cree ses raccourcis de touche standard par qtlib.newshortcutsforstdkey(),
    qui n'appelle pas setContext() : le contexte retombe donc sur le defaut de Qt,
    Qt.WindowShortcut. Dans son Workbench, la fenetre est a lui et c'est sans consequence ; dans
    Spyder, la fenetre est celle de l'editeur. La vue de fichier (HgFileView) pose ainsi un
    Ctrl+F valable dans TOUTE la fenetre, qui vient s'ajouter a celui de l'editeur (porte sur
    EditorMainWidget, en WidgetWithChildrenShortcut). Deux detenteurs actifs couvrant le widget
    focalise : Qt declare le raccourci AMBIGU et n'en declenche AUCUN, sans un mot sur la sortie
    d'erreur.

    Mesure du 04/10/2026 (sonde_correctif.py, offscreen, config reelle de l'utilisateur) : avec
    le focus dans l'editeur, activatedAmbiguously du raccourci de l'editeur se declenche des que
    le panneau est ouvert, et la barre de recherche ne s'ouvre pas ; raccourcis confines, c'est
    activated qui revient et la barre s'ouvre. Le raccourci Ctrl+F de TortoiseHg continue de
    fonctionner quand c'est SA vue de fichier qui a le focus - ce qui est le garde-fou : il ne
    s'agit pas de guerir l'editeur en cassant la recherche du panneau.

    ON ENVELOPPE L'AIDE, PAS SES SEPT APPELANTS. Le defaut est dans newshortcutsforstdkey, pas
    dans l'appel de HgFileView : six autres widgets de TortoiseHg l'utilisent (chunks, rejects,
    qscilib, commit, status, quickop, revdetails), pour Find et pour Refresh - donc pour F5, que
    Spyder utilise aussi (« Executer le fichier »). Les envelopper d'un coup, ici, couvre les
    appels a venir ; reposer le contexte apres coup sur les QShortcut d'un RepoWidget construit
    ne couvrirait que les widgets deja crees - les onglets de taches de TortoiseHg se
    construisent a la demande.

    ALTERNATIVE ECARTEE : corriger la ligne fautive dans la copie embarquee
    (_vendor/tortoisehg/hgqt/fileview.py). Elle est versionnee, mais REGENEREE par
    outils/vendoriser_tortoisehg.py : le correctif aurait du vivre dans cet outil, et n'aurait
    de toute facon rien fait tant que la copie active est celle installee dans le venv. Ici, le
    greffon corrige le comportement sans modifier TortoiseHg, donc sans rien a rejouer apres une
    reinstallation ou une montee de version.

    WidgetWithChildrenShortcut plutot que WidgetShortcut : la touche doit agir quand le focus est
    sur un ENFANT du widget qui l'enregistre - l'editeur Scintilla pour la vue de fichier.
    """
    from qtpy.QtCore import Qt

    origine = qtlib.newshortcutsforstdkey

    def newshortcutsforstdkey(key, *args, **kwargs):
        raccourcis = origine(key, *args, **kwargs)
        for raccourci in raccourcis:
            raccourci.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        return raccourcis

    qtlib.newshortcutsforstdkey = newshortcutsforstdkey


def _montrer_les_onglets_de_taches(ui):
    """Rend visible le bandeau d'onglets du RepoWidget : valider, rechercher, journal, synchro.

    ⚠ SANS CELA LE PANNEAU EST EN CONSULTATION SEULE, ET SANS LE DIRE. Le RepoWidget CONTIENT
    deja ces cinq onglets - le dialogue de validation compris - mais TortoiseHg cache leur
    bandeau par defaut (tortoisehg.tasktabs vaut « off ») : dans son Workbench, c'est la barre
    d'outils de la fenetre principale qui en tient lieu. Ici il n'y a pas de fenetre principale,
    donc rien du tout. Signale par l'utilisateur le 04/08/2026 : « je n'ai aucun bouton ».

    On n'ecrit donc pas de barre d'onglets : on allume celle que TortoiseHg a deja.

    Le reglage n'est pose que s'il n'a pas ete choisi par l'utilisateur dans son hgrc - un « off »
    explicite reste respecte -, et il ne vaut QUE pour ce processus : rien n'est ecrit sur disque,
    l'application autonome garde son propre reglage.
    """
    if not ui.hasconfig(b'tortoisehg', b'tasktabs'):
        ui.setconfig(b'tortoisehg', b'tasktabs', b'west', b'spyder_tortoisehg')


def eclaircir_les_couleurs_de_branche(sombre):
    """Eclaircit la palette des branches, illisible sur fond sombre.

    Le nom de branche et le trait du graphe sont peints avec tortoisehg.hgqt.graph.COLORS,
    dont la premiere entree - celle de « default », donc la plus vue - est un bleu pur
    (#0000ff) qui disparait sur un fond a #19232d. Les suivantes ne valent guere mieux : vert
    fonce, bleu fonce, pourpre.

    On ECLAIRCIT au lieu de reecrire une liste : les teintes restent celles de TortoiseHg, donc
    deux branches continuent de se distinguer l'une de l'autre, et une version amont qui
    changerait cette liste serait suivie sans rien a mettre a jour ici.

    ⚠ ET ON ECLAIRCIT JUSQU'A UN SEUIL MESURE, PAS D'UN COEFFICIENT FIXE. Un simple
    lighter(160) applique a tous laissait #00008b a #0000de - toujours illisible, parce qu'un
    bleu sature reste sombre a l'oeil quoi qu'on fasse au canal. Le critere est donc la
    luminance PERCUE (0,299 R + 0,587 V + 0,114 B), portee au moins a 120 sur les 255 possibles,
    contre un fond qui en fait 33. Mesure du 04/08/2026 : deux a quatre passes selon la teinte,
    et le bleu clair du dodger, deja lisible, n'est pas touche du tout.

    Appelee une fois par processus, avant toute construction de RepoWidget - le modele met ses
    couleurs en cache des la premiere lecture.
    """
    if not sombre:
        return
    from qtpy.QtGui import QColor
    from tortoisehg.hgqt import graph
    graph.COLORS[:] = [_eclaircir(QColor(c)).name() for c in graph.COLORS]


def _luminance(couleur):
    return 0.299 * couleur.red() + 0.587 * couleur.green() + 0.114 * couleur.blue()


def _eclaircir(couleur, seuil=120, passes_max=12):
    """Eclaircit par paliers jusqu'au seuil de luminance percue. La borne evite la boucle
    infinie sur un noir pur, que lighter() ne peut pas eclaircir."""
    passes = 0
    while _luminance(couleur) < seuil and passes < passes_max:
        couleur = couleur.lighter(130)
        passes += 1
    return couleur


def _rendre_le_registre_des_depots_partage():
    """Fait pointer le registre des depots sur le fichier de l'utilisateur, pas sur un neuf.

    ⚠ SANS CELA, LE PANNEAU LATERAL ARRIVE VIDE. TortoiseHg localise son fichier de
    recensement a cote de ses reglages, et il les trouve par un QSettings SANS argument -
    donc par le nom d'organisation de l'APPLICATION. Dans son Workbench, son propre lanceur a
    pose « TortoiseHg » ; dans Spyder, ce nom est celui de Spyder, et le chemin obtenu ici
    devenait « Unknown Organization ». Mesure du 03/08/2026 : fichier introuvable, registre a
    une seule entree vide, alors que celui de l'utilisateur en compte quarante-sept.

    On ne touche PAS au nom d'organisation de l'application : ce serait deplacer les reglages
    de Spyder lui-meme. On remplace la seule fonction qui calcule ce chemin, en construisant un
    QSettings explicitement au nom de TortoiseHg - exactement ce que la fonction d'origine
    obtiendrait dans le Workbench.

    Effet voulu, et c'est la demande : le panneau et l'application autonome partagent LE MEME
    recensement. Un depot ajoute d'un cote apparait de l'autre.
    """
    from qtpy.QtCore import QSettings
    from tortoisehg.hgqt import reporegistry

    def settingsfilename():
        reglages = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                             'TortoiseHg', 'TortoiseHgQt')
        return os.path.join(os.path.dirname(reglages.fileName()), 'thg-reporegistry.xml')

    reporegistry.settingsfilename = settingsfilename


def racine_depot(chemin):
    """Rend la racine du depot Mercurial contenant ce chemin, ou None.

    Remonte les dossiers a la recherche d'un .hg, plutot que d'appeler Mercurial : c'est
    appele a chaque changement de fichier dans l'editeur, et un depot absent est le cas le
    plus frequent (un fichier ouvert au hasard n'est pas toujours dans un depot).
    """
    if not chemin:
        return None
    dossier = os.path.abspath(chemin)
    if not os.path.isdir(dossier):
        dossier = os.path.dirname(dossier)
    while True:
        if os.path.isdir(os.path.join(dossier, '.hg')):
            return dossier
        parent = os.path.dirname(dossier)
        if parent == dossier:
            return None
        dossier = parent
