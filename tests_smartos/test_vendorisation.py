#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banc de la copie embarquee de TortoiseHg (spyder_tortoisehg/_vendor/).

POURQUOI CE BANC EXISTE
    outils/vendoriser_tortoisehg.py est un outil de maintenance : il se lance A LA MAIN, a
    la montee de version. C'est donc la moitie « qui produit » d'un mecanisme dont la moitie
    « qui consomme » (spyder_tortoisehg/__init__.py) tourne, elle, a chaque demarrage de
    Spyder. Sans un banc appele, la copie embarquee peut deriver de l'archive amont, ou
    disparaitre d'un commit, sans que rien ne le signale.

    Il ne demande NI Qt, NI mercurial, NI reseau : c'est de la lecture de fichiers, pour
    qu'aucune raison ne dissuade de le lancer.

    Le banc fonctionnel, lui, est ailleurs : tests_smartos/test_tortoisehg_cmdserver.py et
    tests/test_thg_contexte.py construisent un vrai RepoWidget et lancent une vraie commande.

USAGE
    python3 tests_smartos/test_vendorisation.py
"""

import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(RACINE, 'spyder_tortoisehg', '_vendor')

echecs = []


def verifier(condition, message):
    if condition:
        print('  OK    %s' % message)
    else:
        print('  ECHEC %s' % message)
        echecs.append(message)


def main():
    print('Copie embarquee : %s' % VENDOR)
    if not os.path.isdir(VENDOR):
        sys.stderr.write(
            "_vendor/ absent. Le produire :\n"
            "    python3 outils/vendoriser_tortoisehg.py\n")
        return 1

    # 1. Ce que le repli de tortoisehg/util/paths.py va chercher, A COTE du paquet.
    for nom in ('tortoisehg', 'icons', 'locale'):
        verifier(os.path.isdir(os.path.join(VENDOR, nom)),
                 '%s/ present a la racine de _vendor (repli de paths.get_prog_root)' % nom)
    verifier(os.path.isfile(os.path.join(VENDOR, 'COPYING.txt')),
             'COPYING.txt present (GPLv2 de TortoiseHg : l\'embarquer, c\'est le redistribuer)')
    verifier(os.path.isfile(os.path.join(RACINE, 'LICENSE')),
             'LICENSE presente a la racine du depot')

    # 2. _vendor est une RACINE de sys.path, pas un paquet : un __init__.py y ferait importer
    #    TortoiseHg sous un nom qu'aucun de ses fichiers ne connait.
    verifier(not os.path.exists(os.path.join(VENDOR, '__init__.py')),
             '_vendor/ n\'a pas d\'__init__.py (c\'est une racine, pas un paquet)')

    # 3. config.py doit rester ABSENT : c'est lui qui figeait des chemins absolus et un
    #    « qt_api = PyQt5 » faux. Son absence est ce qui declenche le repli amont.
    verifier(not os.path.exists(os.path.join(VENDOR, 'tortoisehg', 'util', 'config.py')),
             'tortoisehg/util/config.py absent (sinon les chemins seraient figes)')

    # 4. Le portage lui-meme : plus aucun import PyQt5 vivant. Meme critere EXACT que le
    #    patch (une ligne d'import, pas une mention : TortoiseHg cite PyQt5 en commentaire).
    motif = re.compile(r'^\s*(from|import)\s+PyQt5\b', re.MULTILINE)
    restants = []
    fichiers_py = 0
    for dossier, _sous, fichiers in os.walk(os.path.join(VENDOR, 'tortoisehg')):
        for fichier in fichiers:
            if not fichier.endswith('.py'):
                continue
            fichiers_py += 1
            chemin = os.path.join(dossier, fichier)
            with open(chemin, encoding='utf-8') as f:
                for numero, ligne in enumerate(f, 1):
                    if motif.match(ligne):
                        restants.append('%s:%d' % (os.path.relpath(chemin, VENDOR), numero))
    verifier(not restants,
             'aucun import PyQt5 vivant dans les %d fichiers du paquet%s'
             % (fichiers_py, (' (restants : %s)' % ', '.join(restants[:5])) if restants else ''))
    verifier(fichiers_py > 100,
             'le paquet est complet (%d fichiers .py, une centaine attendue)' % fichiers_py)

    # 5. Les traductions sont livrees deja compilees par l'amont - rien a passer par msgfmt.
    verifier(os.path.isfile(os.path.join(VENDOR, 'locale', 'fr', 'LC_MESSAGES',
                                         'tortoisehg.mo')),
             'catalogue francais present')

    # 6. La version vendorisee est ecrite, et c'est elle que la montee de version change.
    chemin_version = os.path.join(VENDOR, 'VERSION.txt')
    verifier(os.path.isfile(chemin_version), 'VERSION.txt present')
    if os.path.isfile(chemin_version):
        with open(chemin_version, encoding='utf-8') as f:
            version = f.read().strip()
        verifier(re.match(r'^\d+\.\d+(\.\d+)?$', version),
                 'VERSION.txt lisible (%s)' % version)

    # 7. La moitie qui consomme : le greffon doit poser _vendor sur sys.path.
    init = os.path.join(RACINE, 'spyder_tortoisehg', '__init__.py')
    with open(init, encoding='utf-8') as f:
        source = f.read()
    verifier('_vendor' in source and 'sys.path' in source,
             '__init__.py du greffon ajoute bien _vendor a sys.path')

    print()
    if echecs:
        print('%d verification(s) en echec.' % len(echecs))
        return 1
    print('Copie embarquee conforme.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
