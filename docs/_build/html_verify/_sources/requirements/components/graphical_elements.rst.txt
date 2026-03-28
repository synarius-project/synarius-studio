Graphical elements (view model)
===============================

This UML describes the **presentation layer** for the **data-flow graph** in Synarius Studio: variable blocks, operator blocks, and directed edges. It extends the **domain data model in synarius-core** (see the ``data_model`` document there): semantics, IDs, and ``Connector`` live in core; **layout**, **ports**, and **edge rendering** are modelled here. The studio GUI may map these types to concrete widgets; this specification stays **framework-agnostic**.

The graph is shown on a **zoomable canvas**: a **diagram view** applies zoom and pan via a view-to-surface transform; a **diagram surface** holds the drawable elements and is **populated** when the diagram is built or updated.

UML diagram
-----------

.. uml:: graphical_elements_uml.puml

View concepts
-------------

- **ZoomableDiagramView** — Viewport with zoom level and pan; optional **fit** to content; user input (wheel, buttons, gestures) adjusts the transform while **surface coordinates** stay stable.
- **DiagramSurface** — Container for one diagram page: **GraphBlockNode**, **PortHandle**, and **ConnectionEdge** instances; supports clear and rebuild from **GraphDiagram**.
- **VariableBlockNode** / **OperatorBlockNode** — On-canvas nodes for domain **Variable** / **BasicOperator**; **stack_order** and **bounds** control drawing order and layout.
- **PortHandle** — Edge anchor; **logical_pin_name** aligns with ``Connector`` **source_pin** / **target_pin**.
- **ConnectionEdge** — Routed polyline or path for a **Connector**; **connector_id** links to the domain object.

Relationship to the domain model
--------------------------------

- **GraphBlockNode** typically pairs 1:1 with an ``ElementaryInstance`` (``Variable`` or ``BasicOperator``) via **domain_object_id**.
- **ConnectionEdge** references a ``Connector`` via **connector_id**; port handles match **source_pin** / **target_pin**.
- On-canvas geometry may be tracked independently of ``LocatableInstance.position`` in the domain; keeping them in sync is an implementation choice.
