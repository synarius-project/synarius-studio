Architecture Requirements
=========================

.. arch:: The GUI shall act as an adapter: it reads domain state and translates user actions into explicit intentions/commands without deep internal cross-manipulation.
   :id: STUDIO-ARCH-001

.. arch:: Domain and rendering concerns shall be separated so graph/simulation logic remains testable and usable independently from Qt rendering.
   :id: STUDIO-ARCH-002

.. arch:: Resource resolution shall avoid absolute hardcoded paths and use project-relative or configurable paths.
   :id: STUDIO-ARCH-003

.. arch:: Simulation concurrency shall be encapsulated via defined signals/queues and must not block the GUI thread.
   :id: STUDIO-ARCH-004

