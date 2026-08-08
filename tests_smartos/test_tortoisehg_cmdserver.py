#!/usr/bin/env python3
"""Fait tourner une VRAIE commande Mercurial par le serveur de commandes de TortoiseHg.

CE QUE CE BANC ATTRAPE, ET QUE LES AUTRES LAISSAIENT PASSER
    Sous PySide6, QIODevice.read() rend un QByteArray la ou PyQt rend des bytes. Le protocole du
    serveur de commandes (hgqt/cmdcore.py) traite ce qu'il lit comme des bytes : la poignee de
    main echouait donc systematiquement, sur

        AttributeError: 'PySide6.QtCore.QByteArray' object has no attribute 'splitlines'

    Signale par l'utilisateur le 04/08/2026, APRES la campagne d'essais du greffon. Le defaut lui
    avait echappe parce que ces essais AFFICHAIENT un depot - graphe, fichiers, diff - ce qui
    passe par les objets Mercurial en direct, sans jamais lancer de commande. Tout ce qui LANCE
    une commande (actualiser, tirer, exporter, valider) tombait, en tracant dans la console sans
    rien casser a l'ecran : un defaut silencieux pour qui ne regarde que la fenetre.

    D'ou ce banc : il ne regarde aucun widget, il execute une commande et lit sa sortie. C'est le
    seul chemin qui exerce la poignee de main.

CHEMIN SUIVI - LE MEME QUE LE GREFFON, ET C'EST DELIBERE
    Le depot est ouvert par un RepoManager, et la commande lancee par le RepoAgent qui en sort.
    Construire un CmdAgent directement ne marcherait pas : le delai d'attente du serveur vient
    d'un reglage declare par l'extension configitems de TortoiseHg, laquelle n'est chargee qu'a
    l'ouverture d'un depot. Un CmdAgent bati sur un ui neuf part avec un delai a None et leve un
    TypeError des sa construction - erreur qui ne nomme pas sa cause. Essaye, ecarte, 04/08/2026.

    Le depot interroge est celui de SmartOS, en LECTURE SEULE (hg log d'une revision).

USAGE
    test_tortoisehg_cmdserver.py [depot]      code de sortie 0 si tout passe
"""

import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from qtpy.QtCore import QTimer  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402


def main(depot):
    # Pas de flux de remplacement ici, contrairement au greffon : ce banc est toujours lance
    # depuis un shell, donc sys.stdout a le .buffer que Mercurial lit des l'import. Le probleme
    # ne se pose qu'a une application lancee depuis un menu, et c'est le banc du greffon
    # (tests/test_thg_contexte.py) qui couvre ce cas-la.
    from tortoisehg.hgqt import qtlib, thgrepo
    from tortoisehg.util import hglib

    app = QApplication.instance() or QApplication([])

    ui = hglib.loadui()
    ui.setconfig(b'extensions', b'tortoisehg.util.configitems', b'', b'test_cmdserver')
    qtlib.configstyles(ui)

    gestionnaire = thgrepo.RepoManager(ui)
    agent = gestionnaire.openRepoAgent(depot)

    session = agent.runCommand(['log', '-l', '1', '--template', '{node|short}\\n'])
    session.setCaptureOutput(True)

    resultat = {}
    session.commandFinished.connect(lambda code: resultat.setdefault('code', code))
    session.commandFinished.connect(app.quit)
    # Sans ce garde-fou, un echec de poignee de main laisse la boucle tourner sans fin : la
    # session n'est jamais lancee, donc commandFinished n'est jamais emis.
    QTimer.singleShot(30000, app.quit)
    app.exec()

    echecs = []
    if resultat.get('code') is None:
        echecs.append('la commande ne s_est jamais terminee (poignee de main echouee ?)')
    elif resultat['code'] != 0:
        echecs.append('hg log a rendu %d : %s' % (resultat['code'], session.errorString()))

    # read() et readAll() empruntent deux chemins differents dans cmdcore : les deux doivent
    # rendre des bytes, et les deux passaient a cote du convertisseur.
    debut = session.read(4)
    if not isinstance(debut, bytes):
        echecs.append('CmdSession.read() rend %s, pas des bytes' % type(debut).__name__)
    reste = bytes(session.readAll())
    sortie = (bytes(debut) + reste).strip()
    if len(sortie) != 12:
        echecs.append('sortie inattendue pour {node|short} : %r' % sortie)

    # Le serveur de commandes est un processus a part : sans cet arret explicite suivi d'un tour
    # de boucle, Qt le detruit encore vivant et le dit sur la sortie d'erreur - bruit qui ferait
    # passer un banc vert pour un banc douteux.
    agent.stopService()
    agent.serviceStopped.connect(app.quit)
    QTimer.singleShot(5000, app.quit)
    app.exec()
    gestionnaire.releaseRepoAgent(depot)

    for echec in echecs:
        print('ECHEC : %s' % echec)
    if echecs:
        return 1
    print('OK : serveur de commandes fonctionnel, hg log rend %s' % sortie.decode())
    return 0


if __name__ == '__main__':
    chemin = sys.argv[1] if len(sys.argv) > 1 else '/DATA/Python/SmartOS'
    sys.exit(main(chemin))
