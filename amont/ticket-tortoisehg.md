**Title:** `qtlib.newshortcutsforstdkey()` leaves the Qt default context, so its shortcuts collide with the host application when thg widgets are embedded

## Summary

`tortoisehg.hgqt.qtlib.newshortcutsforstdkey()` builds its `QShortcut` objects without
ever calling `setContext()`, so they keep Qt's default `Qt.WindowShortcut`. That context
covers the whole top-level window, not just the thg widget the shortcut belongs to.

When a thg widget is *embedded* into another Qt application, the host usually owns the
same standard sequence (here `QKeySequence.StandardKey.Find`, i.e. `Ctrl+F`). Two enabled
shortcuts whose contexts both cover the focused widget make Qt declare the sequence
**ambiguous and fire neither of them** — silently, with no warning on stderr. From the
user's point of view the host's own feature simply stops working.

## Environment

* TortoiseHg 7.2.2 (`tortoisehg.util.version.version()`), Mercurial 7.2
* qtpy over PySide6 6.11, Qt 6.11, Linux (Wayland), Python 3.12
* thg widgets embedded as a dockable panel inside a Spyder-based editor (our own plugin)

## Where

`tortoisehg/hgqt/qtlib.py`:

```python
def newshortcutsforstdkey(
    key: QKeySequence.StandardKey, *args, **kwargs,
) -> List[QShortcut]:
    """Create [QShortcut,...] for all key bindings of the given StandardKey"""
    return [QShortcut(keyseq, *args, **kwargs)
            for keyseq in QKeySequence.keyBindings(key)]
```

Call sites affected (all of them get `Qt.WindowShortcut`):

| file | line | key |
|---|---|---|
| `hgqt/qscilib.py` | 854 | `Find` |
| `hgqt/chunks.py` | 592 | `Find` |
| `hgqt/fileview.py` | 268 | `Find` |
| `hgqt/rejects.py` | 74 | `Find` |
| `hgqt/quickop.py` | 176 | `Refresh` |
| `hgqt/commit.py` | 1627 | `Refresh` |
| `hgqt/status.py` | 1266 | `Refresh` |
| `hgqt/revdetails.py` | 592 | `Refresh` |

Note that on Linux `QKeySequence.StandardKey.Find` expands to **two** bindings
(`Ctrl+F` and the `Find` media key), so each call site installs two such shortcuts.

## Evidence

Measured in the running application (offscreen, scripted), by connecting both signals of
every `QShortcut` found through `QApplication.allWidgets()` and then posting a real
`Ctrl+F` key event to the host's focused editor:

| | before | after the patch below |
|---|---|---|
| host shortcut `activated` | 0 | 1 |
| host shortcut `activatedAmbiguously` | 1 | 0 |
| host search bar opens | no | yes |
| thg's own `Ctrl+F` (focus inside the thg file view) | works | still works |

`activatedAmbiguously` is the authoritative observable here: it is emitted exactly when
Qt refuses to pick between two candidate shortcuts.

This does not show up in standalone thg because the host sequence does not exist there.

## Proposed fix

Purely additive, no behaviour change by default: an optional `context` argument, plus a
module-level default an embedder can set once. With both left to `None`, nothing is set
and Qt's own default applies, exactly as today.

```diff
+#: Shortcut context given to the shortcuts built by newshortcutsforstdkey()
+#: when no explicit context is passed.  Left to None, nothing is set and Qt's
+#: own default (Qt.WindowShortcut) applies, exactly as before.  An application
+#: that EMBEDS thg widgets next to its own can set this to
+#: Qt.WidgetWithChildrenShortcut so these shortcuts stay confined to the thg
+#: widget they belong to.
+stdkeyshortcutcontext: Optional[Qt.ShortcutContext] = None
+
 def newshortcutsforstdkey(
-    key: QKeySequence.StandardKey, *args, **kwargs,
+    key: QKeySequence.StandardKey, *args,
+    context: Optional[Qt.ShortcutContext] = None, **kwargs,
 ) -> List[QShortcut]:
     """Create [QShortcut,...] for all key bindings of the given StandardKey"""
-    return [QShortcut(keyseq, *args, **kwargs)
-            for keyseq in QKeySequence.keyBindings(key)]
+    shortcuts = [QShortcut(keyseq, *args, **kwargs)
+                 for keyseq in QKeySequence.keyBindings(key)]
+    if context is None:
+        context = stdkeyshortcutcontext
+    if context is not None:
+        for shortcut in shortcuts:
+            shortcut.setContext(context)
+    return shortcuts
```

`Qt` and `Optional` are already imported in `qtlib.py` (lines 36 and 104), so the patch
adds no import. It applies to 7.2.2 with `patch -p1 --fuzz=0` and the module still parses.

A stricter variant would be to make `Qt.WidgetWithChildrenShortcut` the default for every
call site, which is arguably what these per-widget shortcuts mean; we did not propose that
because it would change standalone behaviour (today `Ctrl+F` works from anywhere in a thg
window, not only from inside the widget that owns the shortcut).

## Current workaround, for anyone hitting this

Wrapping the helper from the embedder, before any thg widget is built:

```python
from qtpy.QtCore import Qt
from tortoisehg.hgqt import qtlib

_origin = qtlib.newshortcutsforstdkey

def _confined(key, *args, **kwargs):
    shortcuts = _origin(key, *args, **kwargs)
    for shortcut in shortcuts:
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    return shortcuts

qtlib.newshortcutsforstdkey = _confined
```
