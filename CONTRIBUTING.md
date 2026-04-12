# Contributing to Synarius

Thank you for your interest in contributing to Synarius!

Synarius is a Python-first platform for graphical system modeling and simulation.
We welcome contributions of all kinds, including code, documentation, bug reports, and ideas.

## Ways to Contribute

You can contribute by:

- Reporting bugs
- Suggesting features
- Improving documentation
- Submitting code changes

## Getting Started

1. Fork the repository
2. Create a feature branch:

   ```bash
   git checkout -b feature/my-feature
   ```

3. **Local setup:** use a **venv** and install this package in **editable** mode from `synarius-studio/` so dependencies (including **PySide6** and local `synarius-core` / `synarius-apps` per `pyproject.toml`) land in one environment. See **[README.md](README.md) — Develop / Run (monorepo)** for the full sequence. Use the venv’s `python` for `pip` and `pytest`, and select that interpreter in your IDE.

4. Make your changes
5. Run tests:

   ```bash
   pytest
   ```

6. Open a Pull Request

## Development Guidelines

**Canonical programming guidelines** (Python 3.11, repository boundaries, code style, testing, pull requests) are maintained in the **[Synarius programming guidelines](https://synarius-project.github.io/synarius-guidelines/programming_guidelines.html)** (Sphinx documentation built from [synarius-guidelines](https://github.com/synarius-project/synarius-guidelines)). Follow that document first; the sections below only add repository-specific reminders.

### Architecture

Synarius is split into separate repositories:

- **synarius-core**: simulation engine and GUI-less backend (no PySide/Qt dependency).
- **synarius-apps**: DataViewer, ParaWiz, and shared Qt tools — depends on core; usable **without** Synarius Studio.
- **synarius-studio**: graphical modeling and simulation IDE (PySide6).

**Important:**

- Core must remain independent from the GUI
- All simulation logic belongs in synarius-core

### Icons (Synarius Studio)

- Prefer icons from the [KDE Breeze Icons](https://develop.kde.org/frameworks/breeze-icons/) theme (e.g. entries under [Breeze theme icons](https://develop.kde.org/themeicons/breeze/actions/32/)) for toolbars, menus, and other GUI artwork.
- When you add a Breeze icon, vendor the asset under `src/synarius_studio/icons/`, keep the upstream filename where practical, and include license compliance: ship the library license text from the Breeze Icons repository (`COPYING.LIB`, stored here as `icons/BREEZE_ICONS_COPYING.LIB`) and extend `icons/BREEZE_ICONS_NOTICE.txt` so the set of vendored files and sources stays accurate.

### Testing

- All new features should include tests
- Bug fixes must include a regression test if possible
- Run tests before submitting a PR

### Pull Request Guidelines

- Keep PRs small and focused
- Provide a clear description of changes
- Reference related issues
- Ensure CI is passing

## Contributor License Agreement (CLA)

By submitting a contribution, you agree to the Synarius CLA.

Contributions cannot be merged without accepting the CLA.

See [CLA.md](CLA.md) for details and links.

## Communication

- Use GitHub Issues for bugs and feature requests
- Use GitHub Discussions for questions and ideas

Please follow the Code of Conduct in all interactions.

## Questions?

If you're unsure about anything, feel free to open an issue or discussion.

We're happy to help!
