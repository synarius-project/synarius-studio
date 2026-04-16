Connector Rendering — Technische Dokumentation
===============================================

Diese Dokumentation beschreibt die vollständige Rendering-Pipeline für
orthogonale Konnektoren im Synarius Studio.  Sie richtet sich an Entwickler, die
Block-Typen hinzufügen, die Routing-Logik ändern oder das interaktive Bend-Drag
verstehen wollen.

.. note::

   **Kritische Invariante** — siehe Abschnitt :ref:`dual-path-invariant`:
   Für jeden Block-Typ muss die Pin-Positionsberechnung in ``synarius-core``
   (``diagram_geometry.py``) exakt mit der Layout-Berechnung in
   ``synarius-studio`` (``dataflow_items.py``) übereinstimmen.  Eine Abweichung
   von auch nur wenigen Pixeln führt zu einem sichtbaren Sprung des
   Konnektors nach jedem Drag-Release-Zyklus.


Übersicht: Zwei-Repo-Architektur
---------------------------------

Synarius trennt **Domäne** (``synarius-core``) und **Präsentation**
(``synarius-studio``) strikt.  Für Konnektoren bedeutet das:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Schicht
     - Verantwortlichkeit
   * - ``synarius-core`` — ``model/connector.py``
     - Datenmodell: ``source_instance_id``, ``source_pin``, ``target_instance_id``,
       ``target_pin``, ``_orthogonal_bends`` (relativ zum Source-Pin gespeichert)
   * - ``synarius-core`` — ``model/diagram_geometry.py``
     - **Block-Geometrie-Spiegel**: berechnet Pin-Positionen in Szenenkoordinaten
       *ohne* Qt-Abhängigkeit — muss identische Ergebnisse wie das Studio liefern
   * - ``synarius-core`` — ``model/connector_routing.py``
     - Reine Routing-Algorithmen: ``orthogonal_polyline``, ``polyline_for_endpoints``,
       ``bends_relative_to_absolute`` / ``bends_absolute_to_relative``, u. a.
   * - ``synarius-studio`` — ``diagram/dataflow_items.py``
     - Qt-Item-Klassen: ``FmuBlockItem``, ``VariableBlockItem``, ``OperatorBlockItem``
       mit ``connection_point()``; ``ConnectorStrokeItem`` mit interaktivem Drag
   * - ``synarius-studio`` — ``diagram/connector_interactive.py``
     - Routing-Werkzeug (neuen Konnektor zeichnen); ``_normalize_final_bends``
   * - ``synarius-studio`` — ``main_window.py``
     - Bridge: ``_apply_connector_orthogonal_bends`` emittiert ``set``-Befehle

Koordinatensystem
-----------------

Alle Geometrie-Berechnungen laufen in **Szenen-Pixeln**::

    _UI_SCALE = 70.0 / 100.0 = 0.7          # Modell-Einheit → Szenen-Pixel
    _MODULE   = 15.0 * _UI_SCALE = 10.5 px  # Grundrastereinheit

Modell-Koordinaten (``inst.x``, ``inst.y``) werden über
``_block_origin_scene(inst)`` in Szenen-Koordinaten umgerechnet::

    bx, by = inst.x * _UI_SCALE, inst.y * _UI_SCALE

Das Snapping-Raster für Bend-Koordinaten ist ``MODULE * 0.5 = 5.25 px``
(``_GRID_HALF`` / ``_HALF_MODULE``).


Speicherformat ``orthogonal_bends``
-------------------------------------

Das Attribut ``Connector._orthogonal_bends`` speichert eine alternierende Liste
von Absolutkoordinaten *relativ zum Source-Pin*::

    # Gerade-indiziert (0, 2, 4, …): x-Koordinate, als Offset von sx
    # Ungerade-indiziert (1, 3, 5, …): y-Koordinate, als Offset von sy

    _orthogonal_bends = [dx0, dy0, dx1, dy1, ...]
    # Absolut: abs[i] = rel[i] + (sx if i%2==0 else sy)

Konvertierung::

    abs = bends_relative_to_absolute(sx, sy, rel)
    rel = bends_absolute_to_relative(sx, sy, abs)

Die letzte y-Koordinate eines geradzahlig langen Lists wird *nicht* gespeichert:
das End-Approach-y wird immer vom Ziel-Pin ``ty`` abgeleitet.  Drei Code-Pfade
erzwingen dies:

1. Neuer Konnektor (interaktiv) → ``_normalize_final_bends``
   [``connector_interactive.py``]
2. Drag-Release → ``Connector._set_orthogonal_bends`` via ``set``-Befehl
   [``connector.py``]
3. Datei-Laden → ``_cmd_new_connector`` in ``synarius_controller.py``


Block-Geometrie-Varianten
--------------------------

``FmuBlockItem`` in ``dataflow_items.py`` rendert **vier** geometrisch
unterschiedliche Block-Typen.  Jede Variante hat eine eigene Größenberechnung,
die in ``diagram_geometry.py`` gespiegelt werden **muss**:

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - Block-Typ
     - Studio-Breite (``dataflow_items.py``)
     - Core-Geometrie (``diagram_geometry.py``)
   * - ``std.Kennwert``
     - ``variable_diagram_block_width_scene(name)``
       (gleiche Funktion wie ``VariableBlockItem``)
     - ``variable_diagram_block_width_scene(name)``
       — Sonderfall vor der FMU-Standardberechnung
   * - ``STD_PARAM_LOOKUP`` (Kennlinie / Kennfeld)
     - ``LOOKUP_BLOCK_SIZE = 6.0 * MODULE = 63 px`` (Festgröße, quadratisch)
     - ``_LOOKUP_BLOCK_SIZE = 6.0 * _MODULE``
       — Sonderfall vor der FMU-Standardberechnung
   * - ``STD_ARITHMETIC_OP`` (Kompakt-Operator)
     - ``OPERATOR_SIZE = 3.0 * MODULE = 31.5 px`` (quadratisch)
     - ``_OPERATOR_SIZE = 3.0 * _MODULE``
   * - Normaler FMU / Elementary-Block
     - ``inner_w = max(4.8·M, tw+1.4·M, pin_text_w)``; ``block_w`` snapped auf
       ``0.5·M``-Raster
     - identische Formel; ``tw`` per ``_approx_text_metrics``
       (Näherung — kann bei breiten Titeln minimal abweichen)

.. warning::

   Bei der FMU-Standardberechnung approximiert der Core die Schrift-Breite via
   ``_approx_text_metrics``, während das Studio ``QFontMetricsF`` verwendet.  Die
   Approximation wurde so kalibriert, dass das Raster-Snapping in der Praxis
   identische ``block_w``-Werte liefert.  Bei sehr langen Titel-Strings *könnte*
   jedoch ein Off-by-one-Rastersprung auftreten.  Für jeden neuen Block-Typ mit
   eigener Geometrie **muss** daher immer ein dedizierter Sonderfall (wie bei
   Kennwert / Kennlinie / Kennfeld) eingeführt werden, statt sich auf die
   Approximation zu verlassen.


Pin-Attachment-Punkte
---------------------

Studio: ``connection_point(pin_name)``
   Gibt den absoluten Szenen-Punkt des Pin-Ankerpunkts zurück.  Er entspricht
   ``pin_item.mapToScene(pin_item.outer_attachment_local())``.  Für einen
   Ausgangspin, der auf ``setPos(block_w, py)`` sitzt::

       sx = block.scenePos().x() + block_w + PIN_STUB_OUTER_REACH
       sy = block.scenePos().y() + py

   ``PIN_STUB_OUTER_REACH`` ist auf ``_GRID_HALF`` gerundet und entspricht exakt
   ``_PIN_STUB_SCENE`` im Core (beide = 15.75 px).

Core: ``elementary_lib_block_pin_diagram_xy(inst, pin_name)``
   Reproduziert die Pin-Position ohne Qt::

       bx, by = _block_origin_scene(inst)       # inst.x * _UI_SCALE
       sx = bx + block_w + _PIN_STUB_SCENE
       sy = by + py

   ``block_w`` und ``py`` müssen exakt mit dem Studio übereinstimmen.


.. _dual-path-invariant:

Die Dual-Path-Invariante
------------------------

Wenn die beiden Berechnungen abweichen, entsteht ein permanenter Drift::

    # Drag-Phase (Studio):
    #   working = bends_relative_to_absolute(p1.x(), p1.y(), c._orthogonal_bends)
    #   Segment visualisiert bei x = p1.x() + rel[0]

    # Release-Phase (Core über 'set'-Befehl):
    #   _set_orthogonal_bends speichert rel = bends_absolute_to_relative(sx_model, …)
    #   → c._orthogonal_bends[0] = abs[0] - sx_model

    # Nächste Render-Phase (Studio):
    #   abs = bends_relative_to_absolute(p1.x(), …, c._orthogonal_bends)
    #   Segment visualisiert bei x = p1.x() + (abs[0] - sx_model)
    #                              = abs[0] + (p1.x() - sx_model)   ← Drift!

Jede Abweichung ``p1.x() ≠ sx_model`` akkumuliert sich bei jedem
Drag-Release-Zyklus (der Wert wird nach jeder Verschiebung neu gespeichert und
beim nächsten Drag neu gelesen).

**Historischer Bug (behoben 2026-04):**
Für ``std.Kennwert``, ``std.Kennlinie`` und ``std.Kennfeld`` verwendete der Core
fälschlicherweise die generische FMU-Formel statt der tatsächlichen
Studio-Geometrie.  Der Fehler erzeugte ``sx_model ≈ bx + 110px``, während das
Studio ``p1.x() ≈ bx + 79px`` verwendete — ein permanenter Drift von ca. 37 px
pro Drag-Release.


Rendering-Pipeline
------------------

Statisches Rendering (``ConnectorStrokeItem.paint``)
   .. code-block:: python

      p1 = att_src.connection_point(src_pin)   # Szenen-Koordinaten
      p2 = att_dst.connection_point(dst_pin)
      poly = c.polyline_xy((p1.x(), p1.y()), (p2.x(), p2.y()))
      # → bends_relative_to_absolute(p1.x(), p1.y(), c._orthogonal_bends)

Drag-Phase (``mousePressEvent`` / ``mouseMoveEvent``)
   .. code-block:: python

      # Arbeitskopie in absoluten Koordinaten (Basis: p1.x())
      _bend_drag_local = bends_relative_to_absolute(p1.x(), …, c._orthogonal_bends)
      # _bend_drag speichert Anchor auf der Segment-Linie:
      anchor_pt = QPointF(start_val, sp.y())   # axis='x': anchor auf Segment-x
      # Drag-Delta: new_v = start_val + (cursor.x - anchor_pt.x)

Release-Phase (``mouseReleaseEvent``)
   .. code-block:: python

      final_bends = list(_bend_drag_local)   # absolute Koordinaten
      _apply_bends_list(final_bends)
      # → _apply_connector_orthogonal_bends(c, final_bends) [main_window.py]
      # → "set connector@hash.orthogonal_bends [v1,v2,...]"
      # → Connector._set_orthogonal_bends([v1, v2, ...])
      #     → canonicalize_absolute_bends(sx_model, sy_model, tx_model, ty_model, …)
      #     → bends_absolute_to_relative(sx_model, sy_model, …)
      #     → c._orthogonal_bends = rel   (source-relativ gespeichert)

``parse_value``-Kompatibilität
   Das ``set``-Kommando übergibt die Bends als ``[v1,v2,...]``-Literal
   (nicht als Komma-String), damit ``parse_value`` stets eine Liste
   zurückgibt und der ``_set_orthogonal_bends``-Setter sauber arbeitet.


Checkliste: Neuen Block-Typ einführen
--------------------------------------

Wenn ein neuer ``ElementaryInstance``-Subtyp mit eigener Geometrie eingeführt
wird, **müssen** folgende Stellen aktualisiert werden:

1. **Studio** ``dataflow_items.py`` — ``FmuBlockItem.__init__``:
   neue ``elif``-Verzweigung mit eigener Größenberechnung und ``connection_point``-
   Implementierung.

2. **Core** ``diagram_geometry.py`` — ``elementary_lib_block_pin_diagram_xy``:
   eigenen Sonderfall *vor* der generischen FMU-Berechnung einfügen, der exakt
   dieselbe Breite und Pin-y-Position reproduziert.

3. **Core** ``diagram_geometry_constants.py`` (optional):
   Block-Größen-Konstante mit Kommentar hinzufügen, der auf den Studio-
   Gegenwert verweist.

4. **Verifikation**:
   Sicherstellen, dass ``connection_point(pin).x() == elementary_lib_block_pin_diagram_xy(inst, pin)[0]``
   für einen Block an Position ``(inst.x, inst.y) == (0, 0)``.
   Differenz muss exakt 0 sein.

Weitere relevante Dateien
--------------------------

- ``synarius-core/src/synarius_core/model/connector_routing.py`` —
  Routing-Algorithmen (``orthogonal_polyline``, ``polyline_for_endpoints``,
  ``encode_bends_from_polyline``, ``canonicalize_absolute_bends``, etc.)
- ``synarius-core/src/synarius_core/model/diagram_geometry_constants.py`` —
  geteilte Layout-Konstanten (``_MODULE``, ``_PIN_STUB_SCENE``,
  ``_LOOKUP_BLOCK_SIZE``, ``_FMU_PIN_LABEL_*``, etc.)
- ``synarius-core/tests/test_connector_routing.py`` —
  Routing-Unit-Tests (15 Tests)
- ``synarius-studio/src/synarius_studio/diagram/connector_interactive.py`` —
  interaktives Routing-Werkzeug (``ConnectorRouteTool``, ``_normalize_final_bends``)
