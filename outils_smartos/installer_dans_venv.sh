#!/bin/bash
# Installation de CE greffon dans le venv Spyder d'une machine SmartOS (mecanisme .pth
# "editable" : le greffon reste dans ce depot, seul un pointeur part dans site-packages).
# Sorti d'installation_SmartPythonEditor.sh le 08/08/2026 (demande utilisateur : les notes et
# verifications de chaque greffon vivent dans SON depot) - le script SmartOS n'est plus qu'un
# appel d'une ligne vers ce fichier. L'installation DISTRIBUEE (install.sh du fork
# SmartPythonEditor) n'utilise PAS ce script : elle passe par pip.
#
# Usage : installer_dans_venv.sh <python du venv Spyder> <sans_tests true|false> \
#                                <install_spyder_plugin.py> <spyder_config_set.py> <spyder.ini>
set -u
SPYDER_PYTHON="${1:?python du venv Spyder}"
SANS_TESTS="${2:-true}"
OUTIL_INSTALL="${3:?chemin de install_spyder_plugin.py}"
OUTIL_CONFIG="${4:?chemin de spyder_config_set.py}"
SPYDER_INI="${5:?chemin du spyder.ini}"
PLUGIN_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.." && pwd)"
# Version de TortoiseHg a construire : 6e argument optionnel (l'installation SmartOS y
# passe la version de son venv TortoiseHg pour rester alignee), sinon la version connue
# de ce depot.
THG_VERSION="${6:-7.2.2}"

# =============================================================================
# Plugin Spyder "Mercurial" - le RepoWidget de TortoiseHg, ancre dans Spyder
# (TODO - Spyder - plugin TortoiseHg.txt, etape 3)
# =============================================================================
# Installe dans l'environnement pyenv de Spyder le greffon versionne dans
# $COMMUN_DIR/spyder_plugins/spyder_tortoisehg/, qui ajoute UN panneau "Mercurial"
# affichant l'historique du depot du fichier courant : graphe des revisions,
# fichiers de la revision, message, et vue de diff.
#
# CE N'EST PAS UNE REIMPLEMENTATION : c'est le RepoWidget de TortoiseHg lui-meme,
# le meme widget que son Workbench, monte dans le processus de Spyder.
#
# CE QUE CE SCRIPT INSTALLE DANS LE VENV DE SPYDER, ET POURQUOI
#   1. mercurial              TortoiseHg ne peut rien sans lui.
#   2. tortoisehg PATCHE      les sources officielles, passees par
#                             Commun/scripts_installation/patch_tortoisehg_qtpy.py : l'amont
#                             n'importe que PyQt, et deux bindings Qt ne cohabitent
#                             pas dans un processus. Un "pip install tortoisehg"
#                             installerait l'amont, qui ne peut pas tourner ici.
#   3. smartos_qsci.py        l'emulation de QScintilla, dont TortoiseHg se sert
#                             partout (vues de fichier, diffs, message de commit) et
#                             qui n'a AUCUN binding PySide6.
#   4. le greffon             par install_spyder_plugin.py, comme les autres.
#
# ⚠ CE SCRIPT AJOUTE DONC DES PAQUETS AU VENV DE SPYDER, volontairement fige par
#   ailleurs au contenu du bundle officiel (cf. l'en-tete de installation_SmartPythonEditor.sh).
#   C'est assume et sans alternative : le greffon doit importer TortoiseHg DANS le
#   processus de Spyder. Ces paquets sont sans recouvrement avec ceux de Spyder.
#
# ⚠ IL EXISTE UN AUTRE ENVIRONNEMENT TORTOISEHG, ET IL NE SERT PAS ICI :
#   installation_TortoiseHg.sh cree un venv separe, pour lancer TortoiseHg en
#   application autonome (~/.scripts/thg.sh). Les deux partagent les memes sources
#   patchees et la meme emulation, mais un greffon ne peut pas importer depuis un
#   autre venv : le portage est donc REJOUE ici, dans celui de Spyder.
#
# Invocation : installation_SmartPythonEditor.sh --greffon tortoisehg
# =============================================================================

# PAS de "set -e" : error_handler.sh installe un trap ERR interactif, incompatible
# avec errexit (cf. l'explication detaillee en tete de installation_SmartPythonEditor.sh).

if [ ! -f "$PLUGIN_DIR/pyproject.toml" ]; then
  echo "ERREUR : greffon introuvable dans $PLUGIN_DIR - abandon." >&2
  exit 1
fi

if [ ! -x "$SPYDER_PYTHON" ]; then
  echo "ERREUR : $SPYDER_PYTHON introuvable." >&2
  echo "         Installez d'abord Spyder (./installation_SmartPythonEditor.sh)." >&2
  exit 1
fi
SPYDER_VENV="$(cd "$(dirname "$SPYDER_PYTHON")/.." && pwd -P)"
echo "Environnement Spyder cible : $SPYDER_VENV"

echo "Version de TortoiseHg : $THG_VERSION"
PIP_CACHE_ARGS="${PIP_CACHE_ARGS:-}"

# --- Sources de TortoiseHg, patchees -----------------------------------------
# L'archive est mise en cache a cote du venv quand c'est possible (reinstallations sans
# reseau), sinon en temporaire. La CONSTRUCTION, elle, est toujours en temporaire jetable :
# un arbre de build remanent d'une session precedente (autre compte, autre version du
# patch) est exactement le genre d'etat qui produit de faux diagnostics - constate le
# 08/08/2026 avec un build du 03/08 possede par un autre compte, indestructible depuis
# celui-ci.
SOURCES_DIR="$SPYDER_VENV/../../sources"
mkdir -p "$SOURCES_DIR" 2>/dev/null && [ -w "$SOURCES_DIR" ] || SOURCES_DIR="$(mktemp -d)"
BUILD_PARENT="$(mktemp -d)"
trap 'rm -rf "$BUILD_PARENT"' EXIT
BUILD_DIR="$BUILD_PARENT/tortoisehg-$THG_VERSION-spyder"
ARCHIVE="$SOURCES_DIR/tortoisehg-$THG_VERSION.tar.gz"
if [ ! -s "$ARCHIVE" ]; then
  echo "Telechargement de TortoiseHg $THG_VERSION..."
  curl -sSL --fail -o "$ARCHIVE" \
    "https://www.mercurial-scm.org/release/tortoisehg/targz/tortoisehg-$THG_VERSION.tar.gz" || {
      echo "Telechargement impossible - abandon." >&2
      rm -f "$ARCHIVE"
      exit 1
    }
fi
mkdir -p "$BUILD_DIR"
tar xzf "$ARCHIVE" -C "$BUILD_DIR" --strip-components=1
python3 "$PLUGIN_DIR/outils/patch_tortoisehg_qtpy.py" "$BUILD_DIR" || exit 1

# --- Installation dans le venv de Spyder --------------------------------------
# --no-deps : mercurial est deja pose ci-dessus, et le setup.py de TortoiseHg ne declare
# rien d'autre d'utile ici. --no-build-isolation : le venv n'a pas d'acces reseau garanti
# au moment de la construction, et setuptools y est deja.
echo "Installation de mercurial et setuptools dans le venv de Spyder..."
"$SPYDER_PYTHON" -m pip install $PIP_CACHE_ARGS "mercurial>=7.2,<8" setuptools || exit 1
echo "Installation de TortoiseHg (sources patchees)..."
"$SPYDER_PYTHON" -m pip install $PIP_CACHE_ARGS --no-deps --no-build-isolation "$BUILD_DIR" \
  || exit 1

# L'emulation QScintilla, deposee A COTE de TortoiseHg : le qsci.py patche l'importe par son
# nom, elle doit donc etre sur le chemin d'import - pas dans le paquet tortoisehg, qui est
# reinstalle en bloc a chaque passage.
for SITE_PACKAGES in "$SPYDER_VENV"/lib/python*/site-packages; do
  cp -f "$PLUGIN_DIR/smartos_qsci.py" "$SITE_PACKAGES/smartos_qsci.py"
done

echo "Installation du greffon..."
"$SPYDER_PYTHON" "$OUTIL_INSTALL" \
  "$PLUGIN_DIR" "$SPYDER_PYTHON" || exit 1

# --- Smoke-test ---------------------------------------------------------------
# On verifie ce que Spyder fera au demarrage : les modules du greffon s'importent, l'icone
# qta se valide (une icone invalide leve dans setup(), et Spyder AVALE l'exception -> greffon
# absent du menu), le contexte TortoiseHg se monte, et un RepoWidget se construit vraiment
# sur un depot reel. QT_QPA_PLATFORM=offscreen : qtawesome exige une QApplication.
if [ "$SANS_TESTS" = false ]; then
  # Les bancs tournent sur le binding VOULU. Ne PAS ecrire PySide6 en dur ici : ce script est
  # partage avec RaspberryPi5, ou PySide6 n'existe pas (aucune roue aarch64) et ou c'est PyQt6
  # qui est installe. Le choix est fait a un seul endroit, qt_api_env.sh, comme pour les lanceurs.
  ANCIEN_PATH="$PATH"
  PATH="$(dirname "$SPYDER_PYTHON"):$PATH"
  . "$PLUGIN_DIR/outils/qt_api_env.sh"
  PATH="$ANCIEN_PATH"

  echo
  echo "--- Banc d'essai de l'emulation QScintilla ---"
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" \
    "$PLUGIN_DIR/tests_smartos/test_smartos_qsci.py" || exit 1

  echo
  echo "--- Smoke-test : imports, icone, point d'entree, contexte TortoiseHg ---"
  # Un depot Mercurial REEL pour le banc (RepoWidget) : surchargable, defaut SmartOS.
  DEPOT_TEST="${SPYDER_TORTOISEHG_DEPOT_TEST:-/DATA/Python/SmartOS}"
  if ! QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" - "$DEPOT_TEST" <<'PYEOF'
import sys
from qtpy.QtWidgets import QApplication
app = QApplication([])  # requis pour que qtawesome valide les noms d'icones
import qtawesome as qta
from spyder_tortoisehg.spyder.plugin import TortoiseHgPlugin
from spyder_tortoisehg.spyder import thg_contexte

qta.icon('mdi.source-branch')
assert TortoiseHgPlugin.NAME == 'tortoisehg', 'NAME inattendu'
assert thg_contexte.disponible(), 'TortoiseHg non importable dans le venv de Spyder'

racine = thg_contexte.racine_depot(sys.argv[1])
assert racine, 'aucun depot Mercurial sous %s' % sys.argv[1]

# Le vrai test : le contexte se monte ET un RepoWidget se construit. C'est ce qui echouerait
# si un preparatif manquait (cf. thg_contexte : sans la declaration des reglages par defaut,
# le serveur de commandes leve un TypeError qui ne nomme pas sa cause).
contexte = thg_contexte.contexte()
from tortoisehg.hgqt import repowidget
agent = contexte.gestionnaire.openRepoAgent(racine)
w = repowidget.RepoWidget(contexte.registre, agent)
assert w is not None
print('OK  greffon + contexte + RepoWidget construit sur', racine)
PYEOF
  then
    echo "ERREUR : le greffon ne se charge pas - installation a verifier." >&2
    exit 1
  fi

  # Le RepoWidget ci-dessus AFFICHE un depot, ce qui passe par les objets Mercurial en direct :
  # il ne lance aucune commande, donc il ne dit rien de la poignee de main avec le serveur de
  # commandes. C'est exactement ce trou qui a laisse passer un QByteArray pris pour des bytes,
  # lequel cassait TOUT ce qui lance une commande - actualiser, tirer, exporter, valider
  # (signale par l'utilisateur le 04/08/2026, apres la campagne d'essais).
  echo "--- Smoke-test : une vraie commande Mercurial passe-t-elle ? ---"
  if ! QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" \
        "$PLUGIN_DIR/tests_smartos/test_tortoisehg_cmdserver.py" "$DEPOT_TEST"; then
    echo "ERREUR : le greffon afficherait les depots sans pouvoir lancer de commande." >&2
    exit 1
  fi

  # Le cas que TOUTE la campagne d'essais avait manque : Spyder lance depuis le MENU n'a pas
  # de console, et Mercurial exige un .buffer sur les flux standard. Ce test le reproduit -
  # aucun lancement depuis un terminal ne le fera jamais.
  echo "--- Smoke-test : le contexte se monte-t-il SANS console ? ---"
  if ! QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" \
        "$PLUGIN_DIR/tests/test_thg_contexte.py" "$DEPOT_TEST"; then
    echo "ERREUR : le greffon annoncerait « TortoiseHg absent » sous Spyder sans console." >&2
    exit 1
  fi
fi

echo
echo "Greffon Mercurial installe dans $SPYDER_VENV"
echo "  Le panneau apparait dans Affichage > Panneaux, sous le nom « Mercurial »."
