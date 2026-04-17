# Synarius Studio

![Synarius title image](docs/_static/synarius-title.png)

**Synarius Studio is a PySide6 desktop application for graphically modeling systems, wiring simulations, and watching results**—built on the same Python project and data model as the rest of Synarius.

**Python 3.11–3.14** is supported (see `requires-python` in `pyproject.toml`). Use a **virtual environment** and the **same** interpreter for `pip`/`python` and for your IDE.

**Contributing:** follow the **[Synarius programming guidelines](https://synarius-project.github.io/synarius-guidelines/programming_guidelines.html)** (HTML) and this repository’s **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## What is this?

Synarius Studio is the **main graphical entry point** into Synarius: you work on a **diagram canvas**, use libraries and inspectors, and drive **simulation and measurement** through the shared **synarius-core** backend. It is where most people **see** Synarius as a product.

## What can I do with it?

- **Lay out a system** with blocks and connectors (project-oriented workflow).
- **Configure stimulation and measurement** for runs driven by the backend.
- **Observe signals** with built-in plotting patterns (including live-style views where the stack supports it).
- **Use companion tooling** that ships with Synarius (for example embedded or linked **DataViewer**-style views for time-series).

## Quickstart (about 5 minutes)

### Option A — Windows: install and run

1. Download the **latest MSI** from **[Releases](https://github.com/synarius-project/synarius-studio/releases/latest)** and install it.
2. Start **Synarius Studio** from the Start menu (or the shortcut the installer created).
3. You should see the **main window**: diagram canvas, library or browser-style panels, and supporting UI (see screenshot below).

### Option B — From source (monorepo-style checkout)

Typical layout: sibling folders `synarius-studio/`, `synarius-core/`, and `synarius-apps/` (Studio’s `pyproject.toml` references those paths).

1. Create and activate a venv (example on Windows):

   ```bash
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   ```

2. From **`synarius-studio/`**, install in editable mode:

   ```bash
   python -m pip install -U pip
   python -m pip install -e .
   ```

3. Confirm **PySide6** resolves in *this* interpreter:

   ```bash
   python -c "from PySide6.QtCore import Qt, QTimer; print('PySide6 OK')"
   ```

4. Launch Studio:

   ```bash
   run-synarius-studio
   ```

   or:

   ```bash
   python -m synarius_studio
   ```

5. Point your IDE at the same `python` (for example `.venv\Scripts\python.exe` on Windows).

If you change **synarius-apps** often, you can also install it editable: `python -m pip install -e ../synarius-apps`.

## Example workflow

1. **Open or create a project** in Studio.
2. **Add blocks** from the library and **connect** them on the canvas to match your system structure.
3. **Configure run settings** (stimulation / measurement as exposed by the UI and backend).
4. **Run** and **inspect outputs**—including plots and, where integrated, DataViewer-style signal inspection.

*(Exact menu labels evolve with releases; use in-app help or the Sphinx docs if something moved.)*

## Screenshots / demo

![Synarius Studio — diagram canvas, library, and console](docs/images/SynariusStudio.png)

## Contributing

**Why your contribution matters:** Studio is the **public face** of the project—polish here wins users and makes daily modeling easier.

**Where help is welcome:** UX and layout, diagram editor behavior, documentation, Windows packaging, and bug triage.

- **Issues:** https://github.com/synarius-project/synarius-studio/issues  
- **Guidelines:** https://synarius-project.github.io/synarius-guidelines/programming_guidelines.html  
- **This repo:** [CONTRIBUTING.md](CONTRIBUTING.md)

## Architecture (short)

- **This repository (`synarius_studio`)** — Qt UI, diagrams, project chrome, and orchestration.  
- **[synarius-core](https://github.com/synarius-project/synarius-core)** — simulation backend, persistence, and domain logic **without** a GUI.  
- **[synarius-apps](https://github.com/synarius-project/synarius-apps)** — shared Qt pieces (for example plotting widgets) and standalone tools Studio can reuse.

## Documentation

- **Live docs:** https://synarius-project.github.io/synarius-studio/  
- **Sources:** https://github.com/synarius-project/synarius-studio/tree/main/docs  
- Long-term backend perspective (SciPy, SimPy, Pyomo ideas): `docs/strategic_vision.rst` in this repository.

## Branching strategy

This repository uses a simple branching model that fits a solo-developer phase and can be tightened later without changing the overall flow.

### Branch roles

- `main`: stable, release-ready branch  
- `dev`: ongoing integration branch for daily development  
- `feature/*`: short-lived branches for features  
- optional short-lived branch prefixes: `fix/*`, `docs/*`, `refactor/*`

### Practical rules

1. Create new work branches from `dev`.  
2. Merge `feature/*` (and optional `fix/*`, `docs/*`, `refactor/*`) into `dev`.  
3. Merge `dev` into `main` when `dev` is stable and CI is green.  
4. Create release tags (`v*`) from `main` only.  
5. Direct pushes: allowed on `dev` (for now); avoided on `main` (use PR from `dev` to `main`).

### GitHub branch protection (recommended)

- **`main`:** require pull request before merge; require status checks to pass; approvals not required (for now); no force pushes, no branch deletion.  
- **`dev`:** keep permissive for now (direct pushes allowed); optionally block force pushes and deletion.

## Roadmap and deeper design (optional)

Near-term themes include **multi-FMU projects**, richer **stimulation/measurement** setup, **saving results**, and **plugin-style** extension points. Older “vision” bullets (code generation defaults, format evolution) remain directionally true; see Sphinx and in-repo docs for the current, concrete list.
