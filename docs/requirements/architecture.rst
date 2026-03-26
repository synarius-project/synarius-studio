Architecture Requirements
=========================

.. arch:: GUI as Adapter
   :id: STUDIO-ARCH-001
   :status: Must

   The GUI reads domain state and translates user actions into explicit intentions/commands without deep internal cross-manipulation.

.. arch:: Domain and Rendering Separation
   :id: STUDIO-ARCH-002
   :status: Must

   Graph/simulation logic remains testable and usable independently from Qt rendering.

.. arch:: Robust Resource Resolution
   :id: STUDIO-ARCH-003
   :status: Must

   No absolute hardcoded paths are used; resources are resolved via project-relative or configurable paths.

.. arch:: Encapsulated Concurrency
   :id: STUDIO-ARCH-004
   :status: Must

   Simulation threading is encapsulated via defined signals/queues and does not block the GUI thread.

