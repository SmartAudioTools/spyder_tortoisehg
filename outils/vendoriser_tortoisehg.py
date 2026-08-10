#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Depose dans le greffon une copie PATCHEE de TortoiseHg, prete a etre livree par pip.

POURQUOI CET OUTIL EXISTE
-------------------------
Le greffon a besoin d'un TortoiseHg porte sur qtpy/PySide6, et il ne peut le trouver nulle
part : le projet « tortoisehg » existe sur PyPI mais il est VIDE (version « unknown », aucun
fichier publie - mesure du 10/08/2026), et l'archive amont, elle, est ecrite pour PyQt5.
Le declarer en dependance est donc impossible, et pip n'offre aucun point d'entree
post-installation qui permettrait au greffon de l'installer lui-meme.

D'ou ce choix : les sources patchees sont COMMITEES dans le greffon, sous
spyder_tortoisehg/_vendor/, et livrees comme donnees de paquet. « pip install
spyder_tortoisehg » suffit alors, sans reseau et sans etape manuelle.

CE QUE L'OUTIL COPIE, ET POURQUOI SI PEU
----------------------------------------
Mesure du 10/08/2026, arbre installe compare a l'archive : la construction de TortoiseHg
n'AJOUTE qu'un seul fichier, tortoisehg/util/config.py, et n'en retire que les cinq .ui.
Il n'y a donc rien a compiler - ni extension C, ni ressource Qt (le icons_rc.py que
setup.py sait fabriquer n'est produit par aucun chemin d'installation reel : il est absent
de l'arbre installe qui fonctionne aujourd'hui).

Et config.py, justement, n'est PAS reproduit ici - c'est la simplification centrale de cet
outil. Ce fichier fige, EN DUR, les chemins absolus du prefixe de construction ; celui du
venv de Spyder contenait par exemple « qt_api = 'PyQt5' », faux, et des chemins qui ne
survivraient pas au deplacement du venv. Or tortoisehg/util/paths.py prevoit deja son
absence : ses quatre chemins retombent alors sur get_prog_root(), c'est-a-dire le dossier
qui CONTIENT le paquet tortoisehg. En deposant icons/, locale/ et COPYING.txt a cote du
paquet dans _vendor/, le repli amont resout tout seul, et juste. C'est le logiciel qui fait
deja le travail, pas nous.

Effet de bord bienvenu : les icones sont enfin trouvees. L'installation actuelle pointe
icon_path sur share/pixmaps/tortoisehg, qui ne contient que les .ico de l'integration a
l'explorateur Windows - paths.get_tortoise_icon() y imprime « icon not found ».

USAGE
    python3 outils/vendoriser_tortoisehg.py [--version 7.2.2] [--archive <tar.gz>]

Sans --archive, l'archive est cherchee dans les caches connus, puis telechargee. L'outil
est idempotent : il reconstruit _vendor/ de zero a chaque passage.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

VERSION_PAR_DEFAUT = '7.2.2'
URL = 'https://www.mercurial-scm.org/release/tortoisehg/targz/tortoisehg-%s.tar.gz'

# Caches ou l'archive a des chances de se trouver deja, pour ne pas dependre du reseau.
CACHES = [
    '/DATA/Python/SmartPython/CachyOS/sources',
    os.path.expanduser('~/.cache/tortoisehg'),
]

RACINE_GREFFON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(RACINE_GREFFON, 'spyder_tortoisehg', '_vendor')

# Retires par la construction amont (mesure du 10/08/2026) : ce sont les sources Designer
# des cinq dialogues, dont les *_ui.py generes sont deja dans l'archive.
SUFFIXES_INUTILES = ('.ui',)


def _echec(message):
    sys.stderr.write('vendoriser_tortoisehg : %s\n' % message)
    sys.exit(1)


def trouver_archive(version, chemin_donne):
    """Rend le chemin d'une archive utilisable, en la telechargeant au besoin."""
    nom = 'tortoisehg-%s.tar.gz' % version
    if chemin_donne:
        if not os.path.isfile(chemin_donne):
            _echec('archive introuvable : %s' % chemin_donne)
        return chemin_donne
    for cache in CACHES:
        candidat = os.path.join(cache, nom)
        if os.path.isfile(candidat):
            print('archive prise dans le cache : %s' % candidat)
            return candidat
    destination = os.path.join(CACHES[1], nom)
    os.makedirs(CACHES[1], exist_ok=True)
    print('telechargement de %s...' % (URL % version))
    code = subprocess.call(['curl', '-fL', '-o', destination, URL % version])
    if code != 0 or not os.path.isfile(destination):
        _echec('telechargement impossible - fournir --archive <tar.gz>')
    return destination


def extraire(archive, destination):
    """Extrait l'archive et rend la racine des sources (le dossier qui contient tortoisehg/)."""
    with tarfile.open(archive, 'r:gz') as tar:
        # filter='data' refuse liens absolus et chemins sortants ; absent avant Python 3.11.
        if sys.version_info >= (3, 12):
            tar.extractall(destination, filter='data')
        else:
            tar.extractall(destination)
    entrees = [os.path.join(destination, e) for e in os.listdir(destination)]
    dossiers = [e for e in entrees if os.path.isdir(e)]
    if len(dossiers) != 1:
        _echec('racine ambigue dans l\'archive : %r' % dossiers)
    return dossiers[0]


def appliquer_le_patch(racine):
    """Rejoue outils/patch_tortoisehg_qtpy.py sur les sources extraites.

    Passe par un sous-processus et non par un import : le patch est un programme, il a son
    propre __main__ et il ECHOUE bruyamment (code de retour) s'il reste un import PyQt5.
    """
    patch = os.path.join(RACINE_GREFFON, 'outils', 'patch_tortoisehg_qtpy.py')
    if not os.path.isfile(patch):
        _echec('patch introuvable : %s' % patch)
    code = subprocess.call([sys.executable, patch, racine])
    if code != 0:
        _echec('le patch a echoue (code %d) - rien n\'a ete depose' % code)


def deposer(racine, version):
    """Recopie dans _vendor/ ce qui doit etre livre, et rien de plus."""
    if os.path.isdir(VENDOR):
        shutil.rmtree(VENDOR)
    os.makedirs(VENDOR)

    def ignorer(dossier, noms):
        return {n for n in noms if n.endswith(SUFFIXES_INUTILES) or n == '__pycache__'}

    shutil.copytree(os.path.join(racine, 'tortoisehg'),
                    os.path.join(VENDOR, 'tortoisehg'), ignore=ignorer)

    # A COTE du paquet, jamais dedans : c'est ce que get_prog_root() va chercher.
    shutil.copytree(os.path.join(racine, 'icons'), os.path.join(VENDOR, 'icons'),
                    ignore=ignorer)
    shutil.copytree(os.path.join(racine, 'locale'), os.path.join(VENDOR, 'locale'),
                    ignore=ignorer)
    shutil.copy2(os.path.join(racine, 'COPYING.txt'), os.path.join(VENDOR, 'COPYING.txt'))

    # L'absence de tortoisehg/util/config.py - l'invariant sur lequel tient tout le montage -
    # est verifiee par tests_smartos/test_vendorisation.py, qui garde l'arbre DEPOSE : elle
    # n'a pas a l'etre ici en plus, ce serait le meme fait ecrit a deux endroits.

    with open(os.path.join(VENDOR, 'VERSION.txt'), 'w', encoding='utf-8') as f:
        f.write('%s\n' % version)


def rendre_compte():
    total = 0
    for dossier, _sous, fichiers in os.walk(VENDOR):
        for fichier in fichiers:
            total += os.path.getsize(os.path.join(dossier, fichier))
    print('_vendor/ depose : %.1f Mo' % (total / 1048576.0))


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument('--version', default=VERSION_PAR_DEFAUT)
    analyseur.add_argument('--archive', default=None)
    options = analyseur.parse_args()

    archive = trouver_archive(options.version, options.archive)
    with tempfile.TemporaryDirectory(prefix='vendoriser-thg-') as travail:
        racine = extraire(archive, travail)
        appliquer_le_patch(racine)
        deposer(racine, options.version)
    rendre_compte()
    print('fait : %s' % VENDOR)


if __name__ == '__main__':
    main()
