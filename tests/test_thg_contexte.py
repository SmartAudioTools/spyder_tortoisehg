#!/usr/bin/env python3
"""Le contexte TortoiseHg se monte-t-il SANS flux standard utilisables ?

POURQUOI CE TEST EXISTE
    Spyder lance DEPUIS LE MENU n'a pas de console : ses sys.stdin/stdout/stderr sont des
    objets sans .buffer, quand ils ne sont pas None. Or Mercurial lit ce .buffer des l'import
    de mercurial.utils.procutil. Sans precaution, l'import leve AttributeError, et le panneau
    en conclut - a tort - que TortoiseHg n'est pas installe.

    Le defaut a ete signale par l'utilisateur le 03/08/2026, APRES une campagne d'essais qui
    l'avait entierement manque : ces essais lancaient Spyder depuis un TERMINAL, ou les flux
    sont de vrais fichiers. La lecon tient en une ligne - mesurer dans le vrai contexte - et ce
    test la fige : il reproduit l'absence de console, qu'aucun lancement depuis un terminal ne
    reproduira jamais.

    Il verifie aussi que les flux d'origine de Spyder sont RENDUS INTACTS : les remplacer et ne
    pas les rendre couperait la console interne de Spyder.

Usage : QT_QPA_PLATFORM=offscreen <python du venv Spyder> test_thg_contexte.py [<depot hg>]
        Sortie 0 si tout passe, 1 sinon.
"""

import os
import sys


class _SortieSansBuffer:
    """Ce que Spyder lance sans console met a la place de sys.stdout : pas de .buffer."""

    def write(self, texte):
        pass

    def flush(self):
        pass


def main(depot):
    from qtpy.QtWidgets import QApplication
    QApplication([])

    vrai_stdout = sys.stdout
    faux = (_SortieSansBuffer(), _SortieSansBuffer())
    sys.stdout, sys.stderr, sys.stdin = faux[0], faux[1], None
    try:
        from spyder_tortoisehg.spyder import thg_contexte
        contexte = thg_contexte.contexte()
        from tortoisehg.hgqt import repowidget
        agent = contexte.gestionnaire.openRepoAgent(depot)
        widget = repowidget.RepoWidget(contexte.registre, agent)
        monte = widget is not None
        erreur = None
    except Exception as exc:
        monte, erreur = False, '%s: %s' % (type(exc).__name__, exc)
    rendus = (sys.stdout is faux[0], sys.stderr is faux[1], sys.stdin is None)
    sys.stdout, sys.stderr = vrai_stdout, vrai_stdout

    echecs = []
    if not monte:
        echecs.append('le contexte ne se monte pas sans console : %s' % erreur)
    if not all(rendus):
        echecs.append('les flux de Spyder n_ont pas ete rendus intacts : %s' % (rendus,))

    # Le registre des depots doit viser le fichier de TortoiseHg, pas un fichier neuf calcule
    # sur le nom d'organisation de l'application hote. L'echec est SILENCIEUX - un panneau
    # lateral vide, sans erreur -, d'ou ce controle.
    if monte:
        from tortoisehg.hgqt import reporegistry
        fichier = reporegistry.settingsfilename()
        if os.path.basename(os.path.dirname(fichier)) != 'TortoiseHg':
            echecs.append('le registre des depots vise %s, pas le fichier de TortoiseHg'
                          % fichier)

    echecs.extend(_controler_les_couleurs_de_branche())

    for echec in echecs:
        print('  ECHEC %s' % echec)
    if not echecs:
        print('  ok    contexte monte et RepoWidget construit sans flux standard utilisables')
        print('  ok    flux d_origine rendus intacts')
        print('  ok    registre des depots partage avec TortoiseHg')
        print('  ok    couleurs de branche lisibles sur fond sombre')
    return 1 if echecs else 0


def _controler_les_couleurs_de_branche():
    """Toutes les couleurs de branche passent-elles le seuil de lisibilite sur fond sombre ?

    Le premier jet eclaircissait d'un coefficient FIXE, et cela sortait vert alors que le bleu
    fonce de la palette restait illisible (#00008b -> #0000de, luminance percue 27 sur 255).
    Ce controle porte donc sur le RESULTAT - chaque couleur au-dessus du seuil - et non sur le
    fait qu'un eclaircissement a eu lieu : c'est la difference entre verifier l'effet et
    verifier le geste.

    Il verifie aussi le sens inverse, tout aussi important : sous un fond CLAIR, la palette
    d'origine de TortoiseHg ne doit PAS etre touchee.
    """
    from spyder_tortoisehg.spyder import thg_contexte
    from tortoisehg.hgqt import graph
    from qtpy.QtGui import QColor

    origine = list(graph.COLORS)
    echecs = []

    thg_contexte.eclaircir_les_couleurs_de_branche(False)
    if list(graph.COLORS) != origine:
        echecs.append('les couleurs ont ete changees alors que le fond est clair')

    thg_contexte.eclaircir_les_couleurs_de_branche(True)
    for avant, apres in zip(origine, graph.COLORS):
        if thg_contexte._luminance(QColor(apres)) < 120:
            echecs.append('couleur de branche %s -> %s : luminance %.0f, toujours illisible'
                          % (avant, apres, thg_contexte._luminance(QColor(apres))))
    graph.COLORS[:] = origine
    return echecs


if __name__ == '__main__':
    depot = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(os.path.join(depot, '.hg')):
        sys.exit('%s n_est pas un depot Mercurial' % depot)
    sys.exit(main(depot))
