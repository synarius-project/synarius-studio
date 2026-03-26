Requirements
============

ID Policy
---------

Requirement IDs follow this scheme:

- ``<REPO>-<LEVEL>-NNN`` for system and architecture requirements
- ``<REPO>-COMP-<COMP>-NNN`` for component requirements

Where:

- ``REPO`` is ``CORE`` or ``STUDIO``
- ``LEVEL`` is ``SYS`` or ``ARCH``
- ``COMP`` is a repository-specific component code
- ``NNN`` is a zero-padded running number (for example ``001``)

Examples:

- ``STUDIO-SYS-001``
- ``STUDIO-ARCH-001``
- ``STUDIO-COMP-GUI-001``

.. toctree::
   :maxdepth: 2

   system
   architecture
   components/index

