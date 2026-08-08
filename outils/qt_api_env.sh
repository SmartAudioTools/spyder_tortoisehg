# A SOURCER (pas executer), depuis un contexte ou "python" resout deja l'interpreteur du venv
# concerne - typiquement apres un "export PYENV_VERSION=...".
#
# Pose QT_API sur le binding Qt REELLEMENT installe dans ce venv. C'est tout ce que fait ce
# fichier, et c'est le seul endroit du depot ou ce choix se decide.
#
# POURQUOI UN FICHIER A PART, ET POURQUOI UNE DETECTION
#   Le code applicatif (Spyder, TortoiseHg porte sur qtpy) n'importe QUE qtpy, jamais un binding
#   nomme : c'est la variable d'environnement qui tranche, et elle est posee par le LANCEUR. Le
#   binding n'est donc jamais fige dans du code, seulement installe dans un venv.
#
#   ⚠ Et il ne peut pas etre fige ici non plus : ce fichier est partage par CachyOS,
#   RaspberryPi5 et UbuntuStudio. PySide6 ne publie AUCUNE roue aarch64 sur PyPI (verifie le
#   25/07/2026 : `pip download PySide6 --platform manylinux_2_28_aarch64` echoue pour toutes les
#   versions), donc RaspberryPi5 reste sur PyQt6. Ecrire PySide6 en dur y casserait tout.
#
#   Extrait de spyder_qt_env.sh le 03/08/2026, quand le lanceur de TortoiseHg a eu besoin de la
#   MEME detection : le fait « PySide6 s'il est la, PyQt6 sinon » n'est ecrit qu'ici, et les deux
#   lanceurs le lisent. Ecrit deux fois, il aurait coute le jour ou il devient faux a l'un des
#   deux.
#
#   ⚠ Une precision au passage, mesuree le 03/08/2026 : le commentaire d'origine affirmait que
#   qtpy leve QtBindingsNotFoundError des que QT_API vise un binding absent. C'est faux tant
#   qu'un AUTRE binding est installe - il se rabat alors dessus en n'emettant qu'un
#   avertissement, et l'application demarre sur un moteur qu'on n'a pas choisi. La detection
#   n'en est que plus necessaire : sans elle, l'echec serait silencieux, pas bruyant.

if python -c "import PySide6" 2>/dev/null; then
  export QT_API=PySide6
else
  export QT_API=PyQt6
fi
