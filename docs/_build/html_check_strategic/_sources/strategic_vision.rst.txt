Strategic vision: Python backends (SciPy, SimPy, Pyomo)
========================================================

This page records a **long-term architectural perspective** for Synarius Studio. It is **not** a committed roadmap; it aligns with the **Vision** (and related) sections in the repository ``README.md``.

Context
-------

Today, simulation and related execution are centered on **synarius_core** (dataflow, plugins such as FMU runtime, controller command protocol). The GUI (**synarius_studio**) prepares models and delegates where appropriate.

Long-term direction
--------------------

Over time, Synarius Studio may act as a **front-end** that:

- captures structure, parameters, and experiment intent in the graphical environment;
- exports or drives **well-defined** Python-side runs through established libraries.

Candidate ecosystems (examples):

**SciPy (ODE and numerical core)**
   Use **SciPy**—especially ``scipy.integrate`` and related modules—for **ordinary differential equations** and classical numerical workflows driven from Studio-prepared models or generated code.

**SimPy (discrete-event simulation)**
   Use **SimPy** for **process-oriented**, event-driven models (resources, queues, stochastic timing) where a block diagram or scenario editor in Studio maps to SimPy processes and resources.

**Pyomo (optimization)**
   Use **Pyomo** for **algebraic optimization**—linear, mixed-integer, nonlinear—when the domain model or a Studio workflow compiles to variables, constraints, and objectives suitable for Pyomo and external solvers.

Design principles
-----------------

- **Optional backends:** These stacks would complement—not necessarily replace—the existing core execution path unless a project explicitly chooses them.
- **Clear boundaries:** Prefer **plugins**, **controller-facing** preparation steps, and documented export formats so the Qt GUI does not embed solver-specific logic ad hoc.
- **Reuse:** Leverage community-maintained solvers and semantics where they fit the use case (control, OR, MBSE).

See also the **Vision** and **Roadmap** sections in the project ``README.md`` and the architecture requirements under :doc:`requirements/architecture`.

.. note::

   This document is maintained for **stakeholder alignment**. Implementation tracking remains in issues, milestones, and the numbered requirements (e.g. ``STUDIO-ARCH-*``).
