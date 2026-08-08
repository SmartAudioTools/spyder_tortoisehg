# -*- coding: utf-8 -*-
"""Greffon « Mercurial » : le RepoWidget de TortoiseHg, ancre dans Spyder.

Le greffon est la seule couche qui connait les autres greffons de Spyder : il lui demande le
PROJET ouvert et en suit les changements, puis passe le chemin au panneau, qui se charge d'y
trouver un depot. Toute la logique d'affichage vit dans le widget, et le montage du contexte
TortoiseHg dans thg_contexte.py.

⚠ LE PROJET, ET NON LE FICHIER COURANT (demande de l'utilisateur, 03/08/2026). La premiere
version suivait le fichier ouvert dans l'editeur : le panneau changeait alors de depot au gre
des onglets, y compris pour un fichier ouvert au hasard hors du projet. Le projet est la bonne
unite - c'est lui qu'on versionne, et il ne change que quand on le decide.
"""

import qtawesome as qta

from spyder.api.plugin_registration.decorators import (
    on_plugin_available, on_plugin_teardown)
from spyder.api.plugins import Plugins, SpyderDockablePlugin
from spyder.api.translations import _
from spyder.utils.icon_manager import ima

from spyder_tortoisehg.spyder.widgets.main_widget import TortoiseHgWidget


class TortoiseHgPlugin(SpyderDockablePlugin):
    """Panneau Mercurial (graphe des revisions, fichiers, diff) du projet ouvert."""

    NAME = 'tortoisehg'  # doit etre identique au nom du point d'entree
    REQUIRES = [Plugins.Projects]
    TABIFY = [Plugins.Explorer]
    WIDGET_CLASS = TortoiseHgWidget
    CONF_SECTION = 'tortoisehg'
    CONF_FILE = False

    @staticmethod
    def get_name():
        return _('Mercurial')

    @staticmethod
    def get_description():
        return _("Affiche l'historique du dépôt Mercurial du projet ouvert : graphe des "
                 "révisions, fichiers modifiés et différences, par TortoiseHg.")

    @classmethod
    def get_icon(cls):
        return qta.icon('mdi.source-branch', color=ima.MAIN_FG_COLOR)

    # --- API SpyderDockablePlugin -------------------------------------------

    def on_initialize(self):
        pass

    @on_plugin_available(plugin=Plugins.Projects)
    def on_projects_available(self):
        projets = self.get_plugin(Plugins.Projects)
        projets.sig_project_loaded.connect(self._suivre_projet)
        # sig_project_closed a DEUX signatures (str et bool) ; celle qui porte le chemin est
        # emise a la fermeture, l'autre au changement. On vise la premiere, et on ferme.
        projets.sig_project_closed[str].connect(self._projet_ferme)
        # Un projet peut deja etre ouvert quand le greffon s'initialise.
        self._suivre_projet(projets.get_active_project_path())

    @on_plugin_teardown(plugin=Plugins.Projects)
    def on_projects_teardown(self):
        projets = self.get_plugin(Plugins.Projects)
        projets.sig_project_loaded.disconnect(self._suivre_projet)
        projets.sig_project_closed[str].disconnect(self._projet_ferme)

    # --- Interne -------------------------------------------------------------

    def _suivre_projet(self, chemin):
        self.get_widget().afficher_pour(chemin)

    def _projet_ferme(self, _chemin):
        self.get_widget().afficher_pour(None)
