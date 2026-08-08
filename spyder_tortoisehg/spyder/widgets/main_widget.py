# -*- coding: utf-8 -*-
"""Panneau « Mercurial » : le RepoWidget de TortoiseHg, ancre dans Spyder.

CE QUE CE PANNEAU AFFICHE
    A gauche, le REGISTRE DES DEPOTS de TortoiseHg - la liste de tous les depots connus, celle
    de son panneau lateral, alimentee par le meme fichier de recensement que l'application
    autonome. Cliquer un depot bascule l'affichage dessus.
    A droite, le RepoWidget complet - graphe des revisions, liste des fichiers, message, vue de
    diff. C'est le coeur de TortoiseHg, pas une reimplementation : le meme widget que son
    Workbench, monte ici dans le processus de Spyder.

    C'est possible parce que TortoiseHg tourne desormais sur qtpy avec le meme binding que
    Spyder (cf. Commun/scripts_installation/patch_tortoisehg_qtpy.py et smartos_qsci.py) : deux bindings Qt
    ne cohabitent pas dans un processus, et sans ce portage il n'y aurait pas d'autre voie
    qu'un processus externe - ce que l'objectif du TODO excluait explicitement.

TROIS ETATS, ET UN SEUL EST LE BON CAS
    - TortoiseHg absent du venv       le panneau le DIT, en affichant l'erreur d'import. Il ne
                                      disparait pas : Spyder avale en silence les exceptions de
                                      chargement d'un greffon, un panneau muet serait
                                      indiscernable d'un greffon casse.
    - aucun depot sous le projet      message d'attente ; c'est le cas quand aucun projet n'est
                                      ouvert, ou qu'il n'est pas versionne sous Mercurial.
    - un depot                        le registre et le RepoWidget.

⚠ UN REPOWIDGET PAR DEPOT, ET ON GARDE LES PRECEDENTS. Ouvrir un depot demarre un serveur de
  commandes Mercurial et lit tout le graphe : refaire ce travail a chaque aller-retour entre
  deux depots rendrait le panneau inutilisable. Les widgets deja construits sont donc empiles
  et rappeles, comme le fait le Workbench avec ses onglets.
"""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel, QSplitter, QStackedWidget, QVBoxLayout

import qtawesome as qta

from spyder.api.translations import _
from spyder.api.widgets.main_widget import PluginMainWidget
from spyder.utils.icon_manager import ima
from spyder.utils.stylesheet import AppStyle

from spyder_tortoisehg.spyder import thg_contexte

# LA PANOPLIE DU WORKBENCH, REPRISE TELLE QUELLE
#     (identifiant, libelle, icone, methode du RepoWidget)
#
# Chaque entree delegue a une methode que le RepoWidget expose DEJA : c'est exactement ce que
# fait le Workbench de TortoiseHg, dont chaque bouton n'est qu'un appel a la meme methode sur
# l'onglet courant (workbench.py, _repofwd). Rien n'est reimplemente ici : le geste, le
# dialogue et le resultat sont ceux de l'application autonome.
#
# Le partage barre / menu est celui du Workbench, et il a sa logique : la barre porte ce qu'on
# fait tous les jours, le menu ce qu'on fait une fois par mois. Le reprendre evite d'avoir a
# trancher soi-meme, et donne les memes reperes des deux cotes.
#
# ⚠ LES ICONES SONT CELLES DE SPYDER (qtawesome), PAS CELLES DE TORTOISEHG. Ses icones se
#   demandent a qtlib.geticon(), donc en important toute sa pile graphique - or setup() tourne
#   au DEMARRAGE DE SPYDER, meme si le panneau n'est jamais ouvert. Tout ce module est bati
#   pour ne pas payer ce prix-la (voir setup()), et une icone ne vaut pas de le renier.
ACTIONS_BARRE = (
    ('reload',   _('Actualiser'),                       'mdi.refresh',         'reload'),
    ('gotocur',  _('Aller à la révision de travail'),   'mdi.home',            'gotoParent'),
    ('update',   _('Mettre à jour la copie de travail'),'mdi.update',          'updateToRevision'),
    ('merge',    _('Fusionner avec l’autre tête'),      'mdi.source-merge',    'mergeWithOtherHead'),
)
ACTIONS_SYNCHRO = (
    ('incoming', _('Entrantes (aperçu)'),        'mdi.arrow-down-circle-outline', 'incoming'),
    ('pull',     _('Tirer'),                     'mdi.arrow-down-bold-circle',    'pull'),
    ('outgoing', _('Sortantes (aperçu)'),        'mdi.arrow-up-circle-outline',   'outgoing'),
    ('push',     _('Pousser'),                   'mdi.arrow-up-bold-circle',      'push'),
)
ACTIONS_MENU = (
    ('shelve',   _('Remiser…'),                  'mdi.archive-arrow-down-outline', 'shelve'),
    ('import',   _('Importer un correctif…'),    'mdi.file-import-outline',        'thgimport'),
    ('unbundle', _('Appliquer un bundle…'),      'mdi.package-down',               'unbundle'),
    ('resolve',  _('Résoudre les conflits…'),    'mdi.alert-decagram-outline',     'resolve'),
    ('rollback', _('Annuler la dernière transaction…'), 'mdi.undo-variant',        'rollback'),
    ('purge',    _('Purger les fichiers non suivis…'),  'mdi.broom',               'purge'),
    ('verify',   _('Vérifier le dépôt…'),        'mdi.check-decagram-outline',     'verify'),
    ('recover',  _('Récupérer après interruption…'),    'mdi.lifebuoy',            'recover'),
    ('bisect',   _('Bissection…'),               'mdi.magnify-scan',               'bisect'),
)


def _icone(nom):
    return qta.icon(nom, color=ima.MAIN_FG_COLOR)


class TortoiseHgWidget(PluginMainWidget):
    """Panneau ancrable qui heberge le registre des depots et le RepoWidget de TortoiseHg."""

    # LA MARGE DU HAUT, ET C'EST ELLE QUI REND LES COINS ARRONDIS VISIBLES.
    #
    # Demande de l'utilisateur (04/08/2026) : « les cadres ne sont pas arrondis, fais que le
    # greffon suive la feuille de style de Spyder ». Verification faite cadre par cadre, dans un
    # vrai Spyder : ILS LE SONT DEJA. Graphe, arbre des depots, liste de fichiers, vue de diff
    # ont tous un cadre a coins arrondis - la feuille de style de Spyder les atteint bel et bien.
    # Ce qui manquait n'etait pas le style mais la PLACE : Spyder pose ses marges a gauche, a
    # droite et en bas, et laisse MARGIN_TOP a zero ; le contenu touchait donc l'arete haute du
    # panneau, ou les coins arrondis s'ecrasaient. MARGIN_TOP est le reglage prevu pour cela par
    # l'API des greffons, il n'y a rien d'autre a faire.
    #
    # ⚠ Ne PAS poser de marges sur la disposition dans setup() : PluginMainWidget.setLayout()
    # les reecrit juste apres. La premiere version de ce correctif faisait exactement cela, et
    # la mesure a montre du code mort.
    #
    # Trois fausses pistes ecartees en chemin, chacune par un essai en vrai Spyder : poser
    # APP_STYLESHEET sur le RepoWidget (captures identiques a l'octet pres - la feuille y est
    # deja), repolir tous ses widgets par le style (idem), elargir les poignees. Un temoin a ete
    # intercale, un fond rouge criard, pour verifier que la capture voit bien un changement :
    # elle le voit, ces resultats negatifs sont donc reels et non un defaut de mesure.
    MARGIN_TOP = AppStyle.MarginSize

    def __init__(self, name, plugin, parent=None):
        super().__init__(name, plugin, parent)
        self._pages = {}        # racine du depot -> RepoWidget
        self._actions = {}      # identifiant -> QAction, pour update_actions()
        self._racine = None
        self._registre = None   # RepoRegistryView, construit avec le premier depot

        self._pile = QStackedWidget(self)
        self._message = QLabel('', self)
        self._message.setWordWrap(True)
        self._message.setMargin(16)
        self._pile.addWidget(self._message)

        self._separateur = QSplitter(Qt.Orientation.Horizontal, self)
        self._separateur.addWidget(self._pile)

    # --- API PluginMainWidget ------------------------------------------------

    def get_title(self):
        return _('Mercurial')

    def get_focus_widget(self):
        return self._pile.currentWidget()

    def setup(self):
        disposition = QVBoxLayout()
        disposition.addWidget(self._separateur)
        # PAS DE setContentsMargins ICI : PluginMainWidget.setLayout() les REECRIT juste apres,
        # avec les marges de Spyder. Toute valeur posee ici serait du code mort - c'est ce
        # qu'etait la premiere version de ce correctif, et la mesure l'a montre.
        self.setLayout(disposition)

        barre = self.get_main_toolbar()
        for identifiant, libelle, icone, methode in ACTIONS_BARRE:
            self.add_item_to_toolbar(self._creer(identifiant, libelle, icone, methode),
                                     toolbar=barre, section='depot')
        # « Arreter » n'est pas une methode du RepoWidget : c'est l'agent du depot qu'on
        # interrompt. Meme geste que le bouton du Workbench (workbench.py, _abortCommands).
        self._actions['abort'] = arreter = self.create_action(
            'tortoisehg_abort', text=_('Arrêter l’opération en cours'),
            icon=_icone('mdi.stop-circle-outline'), triggered=self.arreter)
        self.add_item_to_toolbar(arreter, toolbar=barre, section='depot')
        for identifiant, libelle, icone, methode in ACTIONS_SYNCHRO:
            self.add_item_to_toolbar(self._creer(identifiant, libelle, icone, methode),
                                     toolbar=barre, section='synchro')
        for identifiant, libelle, icone, methode in ACTIONS_MENU:
            self.add_item_to_menu(self._creer(identifiant, libelle, icone, methode),
                                  menu=self.get_options_menu(), section='depot')
        self.update_actions()
        self._fondre_les_poignees()   # celle du panneau ; celles du depot au premier affichage
        # ⚠ ON NE VERIFIE PAS ICI QUE TORTOISEHG EST LA. setup() tourne au DEMARRAGE de Spyder,
        # meme si le panneau n'est jamais ouvert : le tester reviendrait a importer toute la
        # pile graphique de TortoiseHg a chaque lancement, pour un panneau souvent inutilise.
        # Ce depot a deja des correctifs entiers consacres a differer des imports lourds au
        # demarrage (cf. patch_spyder_lazy_imports.py) ; on ne va pas en rajouter un.
        # L'absence de TortoiseHg est donc constatee au premier depot a ouvrir, et dite
        # a l'utilisateur a ce moment-la.
        self._afficher_message(_('Ouvrez un projet versionné sous Mercurial.'))

    def update_actions(self):
        # Toutes les actions demandent un depot affiche - c'est le « enabled='repoopen' » du
        # Workbench. Sans depot, elles seraient des boutons qui ne font rien.
        ouvert = self._racine is not None
        for action in self._actions.values():
            action.setEnabled(ouvert)

    # --- Actions -------------------------------------------------------------

    def _creer(self, identifiant, libelle, icone, methode):
        """Cree une action qui appelle `methode` sur le RepoWidget affiche."""
        action = self.create_action(
            'tortoisehg_%s' % identifiant, text=libelle, icon=_icone(icone),
            triggered=lambda *_a, nom=methode: self._appeler(nom))
        self._actions[identifiant] = action
        return action

    def _appeler(self, nom):
        """Transmet le geste au RepoWidget courant - le _repofwd du Workbench.

        Les erreurs sont dites dans le message du panneau plutot que remontees : une action de
        depot qui echoue (pas de chemin « default » configure, depot verrouille) est un cas
        ordinaire, et Spyder traite toute exception non rattrapee comme un probleme interne,
        avec la fenetre qui va avec.
        """
        page = self._pages.get(self._racine)
        if page is None:
            return
        try:
            getattr(page, nom)()
        except Exception as erreur:
            self.show_status_message(_('Mercurial : %s') % erreur, 8000)

    def arreter(self):
        """Interrompt les commandes en cours sur le depot affiche."""
        if self._racine is None:
            return
        try:
            thg_contexte.contexte().gestionnaire.repoAgent(self._racine).abortCommands()
        except Exception as erreur:
            self.show_status_message(_('Mercurial : %s') % erreur, 8000)

    def on_close(self):
        # Chaque depot ouvert tient un serveur de commandes Mercurial : le relacher est ce qui
        # laisse Spyder se fermer sans processus orphelin.
        for racine in list(self._pages):
            self._fermer_depot(racine)

    # --- Pilotage ------------------------------------------------------------

    def afficher_pour(self, chemin):
        """Affiche le depot contenant ce chemin, s'il y en a un."""
        racine = thg_contexte.racine_depot(chemin)
        if racine == self._racine:
            return
        if racine is None:
            self._racine = None
            self._afficher_message(_('Ouvrez un projet versionné sous Mercurial.'))
            self.update_actions()
            return
        self._afficher_depot(racine)

    def _afficher_depot(self, racine):
        if racine not in self._pages:
            try:
                contexte = thg_contexte.contexte()
                # Avant le premier RepoWidget : le modele met les couleurs de branche en
                # cache des sa premiere lecture, les eclaircir apres coup ne changerait rien.
                thg_contexte.eclaircir_les_couleurs_de_branche(self._fond_sombre())
                from tortoisehg.hgqt import repowidget
                agent = contexte.gestionnaire.openRepoAgent(racine)
                page = repowidget.RepoWidget(contexte.registre, agent, self)
            except thg_contexte.ContexteAbsent as erreur:
                self._afficher_message(
                    _("TortoiseHg n'est pas installé dans cet environnement Python.\n\n%s")
                    % erreur)
                return
            except Exception as erreur:
                # Un depot illisible ne doit pas emporter le panneau avec lui.
                self._afficher_message(
                    _("Dépôt « %s » impossible à ouvrir :\n%s") % (racine, erreur))
                return
            self._pages[racine] = page
            self._pile.addWidget(page)
            # Les poignees d'ABORD : poser une feuille de style fait repasser Qt sur la
            # palette des widgets concernes, ce qui defaisait l'alignement fait avant.
            self._fondre_les_poignees(page)
            self._aligner_la_palette(page)
        self._assurer_registre()
        self._racine = racine
        self._pile.setCurrentWidget(self._pages[racine])
        self.update_actions()

    def _fond_sombre(self):
        """Le panneau est-il habille d'un theme sombre ?

        C'est la palette DU PANNEAU qui fait foi, pas celle de l'application : sous Spyder en
        theme sombre, QApplication.palette() reste claire (#ffffff mesure le 04/08/2026) - le
        theme est pose par une feuille de style, pas par la palette applicative. Le test que
        TortoiseHg utilise pour lui-meme, qtlib.isDarkTheme() sans argument, repondrait donc
        « clair » ici, et a tort.
        """
        from qtpy.QtGui import QPalette
        return self.palette().color(QPalette.ColorRole.Base).black() >= 0x80

    def _fondre_les_poignees(self, page=None):
        """Teinte les poignees de redimensionnement de la couleur du fond de Spyder.

        Demande de l'utilisateur (04/08/2026) : « j'avais dans Spyder change la couleur de ses
        poignees pour qu'elles aient exactement la meme couleur que le fond ; fais la meme
        chose pour le greffon ». Par defaut Qt les dessine dans la couleur de fond du THEME DE
        WIDGETS, plus claire que le fond du panneau : des barres pales traversent l'affichage.

        MEME GESTE QUE LE GREFFON CLAUDE (spyder_claude/mosaique.py, poser_couleur_poignees),
        et la meme couleur - COLOR_BACKGROUND_1 - pour que les deux panneaux se ressemblent :
        c'est ce qui a ete demande la premiere fois, il n'y a pas a en choisir une autre.

        On ne cible que QSplitter::handle, jamais QSplitter nu : une regle nue redescendrait
        sur tout le contenu des splitters - graphe, liste de fichiers, vue de diff.

        ⚠ ET ON LES ELARGIT, CE QUI EST L'AUTRE MOITIE DU MEME SUJET. « J'ai toujours des cadres
        avec des coins carres, on dirait qu'il y a plusieurs cadres imbriques a chaque fois »
        (04/08/2026). Mesure faite widget par widget, DANS UNE COPIE DE LA CONFIGURATION DE
        L'UTILISATEUR : chaque cadre est bel et bien arrondi, un par un. Ce qui se lisait comme
        un cadre carre exterieur etait la RENCONTRE de deux cadres arrondis voisins - Qt separe
        deux panneaux par une poignee de quelques pixels, et a cette distance l'oeil recompose
        un rectangle a partir des aretes qui se font face. Le pixel du « coin carre » appartient
        d'ailleurs a une QSplitterHandle, pas a un cadre : verifie par childAt().

        Les elargir a la marge des panneaux de Spyder donne a chaque coin arrondi la place de
        se voir. C'est le meme espacement que Spyder met entre ses propres panneaux, ce qui est
        exactement ce qui etait demande : suivre son habillage.
        """
        from spyder.utils.palette import SpyderPalette
        from qtpy.QtWidgets import QSplitter
        style = ('QSplitter::handle { background-color: %s; }'
                 % SpyderPalette.COLOR_BACKGROUND_1)
        separateurs = [self._separateur]
        if page is not None:
            separateurs += page.findChildren(QSplitter)
        for separateur in separateurs:
            separateur.setStyleSheet(style)
            separateur.setHandleWidth(2 * AppStyle.MarginSize)

    def _aligner_la_palette(self, page):
        """Rend au graphe des revisions la palette du panneau qui l'heberge.

        ⚠ SANS CELA, LE TEXTE DU GRAPHE EST QUASI INVISIBLE SOUS UN THEME SOMBRE : numeros de
        revision, branches et surtout MESSAGES DE COMMIT s'ecrivent en #232629 - la couleur de
        texte du theme CLAIR - sur le fond sombre du panneau. Signale par l'utilisateur le
        04/08/2026 : « le texte a cote de la vue graph est beaucoup trop sombre, on n'arrive
        pas a lire les messages des commits ».

        MESURE, ET NON DEDUCTION. Un releve fait dans un vrai Spyder a compte, sur les 200
        widgets du RepoWidget, EXACTEMENT UN dont la palette est restee claire : la vue du
        graphe. Tout le reste - details de revision, liste de fichiers, vue de diff - avait
        deja la palette sombre. Le correctif porte donc sur ce seul widget, et il n'y a rien a
        deviner sur les autres.

        La cause est le PaletteSwitcher de TortoiseHg (qtlib.py), qui photographie la palette
        du widget A SA CONSTRUCTION - donc avant que Spyder ne l'habille - et la lui REPOSE a
        chaque changement de filtre (repowidget.py, enablefilterpalette). D'ou les deux gestes
        ci-dessous : reparer la photographie, puis reappliquer. Reparer seulement l'affichage
        courant ne tiendrait pas au premier filtre saisi.

        Rien n'est fait sous un theme clair - c'est le cas de l'application autonome, ou la
        photographie est juste.
        """
        if not self._fond_sombre():
            return
        panneau = self.palette()
        vue = getattr(page, 'repoview', None)
        commutateur = getattr(vue, '_paletteswitcher', None)
        if commutateur is None:
            return
        commutateur._defaultpalette = panneau
        vue.setPalette(panneau)

    def _assurer_registre(self):
        """Construit le registre des depots au premier depot affiche, une seule fois.

        ⚠ RepoRegistryView est un QDockWidget - c'est ainsi que le Workbench de TortoiseHg
        l'ancre. Ici il n'y a pas de fenetre principale ou l'ancrer : on prend son CONTENU
        (l'arbre) pour le poser dans le separateur, et on garde l'objet lui-meme, qui reste
        le controleur - c'est lui qui porte le signal d'ouverture, le modele, et la
        surveillance du fichier de recensement.

        Construit tard, et pas dans setup() : il lit le fichier qui recense les depots et pose
        un surveillant dessus. Rien de tout cela n'a lieu d'etre tant qu'aucun depot n'est
        affiche.
        """
        if self._registre is not None:
            return
        try:
            from tortoisehg.hgqt.reporegistry import RepoRegistryView
            contexte = thg_contexte.contexte()
            registre = RepoRegistryView(contexte.gestionnaire, self)
        except Exception:
            # Le registre est un CONFORT : s'il manque, le panneau reste utilisable avec le
            # depot du projet. On ne fait pas tomber l'affichage pour lui.
            return
        # openRepo(chemin, nouvelle_fenetre) : le second argument ne nous concerne pas, il n'y
        # a qu'un panneau.
        registre.openRepo.connect(lambda chemin, _nouvelle: self._afficher_depot(chemin))
        contenu = registre.widget()
        self._registre = registre
        self._separateur.insertWidget(0, contenu)
        # Un quart pour la liste, trois quarts pour le graphe - et la poignee reste libre.
        largeur = max(self.width(), 800)
        self._separateur.setSizes([largeur // 4, largeur - largeur // 4])

    def _fermer_depot(self, racine):
        page = self._pages.pop(racine, None)
        if page is None:
            return
        self._pile.removeWidget(page)
        page.setParent(None)
        try:
            thg_contexte.contexte().gestionnaire.releaseRepoAgent(racine)
        except Exception:
            pass

    def _afficher_message(self, texte):
        self._message.setText(texte)
        self._pile.setCurrentWidget(self._message)

    def racine_courante(self):
        return self._racine

    def registre_present(self):
        """Pour le banc d'essai : le registre des depots est-il en place ?"""
        return self._registre is not None
