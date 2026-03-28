Architecture Requirements
=========================

.. arch:: GUI as Adapter
   :id: STUDIO-ARCH-001
   :status: Must

   The GUI reads domain state and translates user actions into explicit intentions/commands without deep internal cross-manipulation.
   Persistent changes to the domain model are applied only through the Synarius Core controller surface that implements the Controller Command Protocol (STUDIO-ARCH-005).

.. arch:: Controller command protocol for model mutations
   :id: STUDIO-ARCH-005
   :status: Must

   Every change to domain model content that must be reflected in a saved project or be reproducible from a command script SHALL be executed exclusively through that controller API (Controller Command Protocol; specified in synarius-core).
   Studio MUST NOT mutate the model graph or user-relevant attributes by bypassing this layer (for example direct writes to ``model.root`` children, ad-hoc mutation of domain instances without going through controller commands, or parallel “shadow” graphs that diverge from the controller-owned model).

   Exceptions are limited to: read-only access for display and layout; purely transient GUI/scene state that is not part of the persisted model; and documented temporary gaps until the protocol exposes the missing operation.

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

