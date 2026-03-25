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

3. Make your changes
4. Run tests:

   ```bash
   pytest
   ```

5. Open a Pull Request

## Development Guidelines

### Architecture

Synarius is split into two main components:

- **synarius-core**: simulation engine (no GUI dependencies)
- **synarius-studio**: graphical user interface

**Important:**

- Core must remain independent from the GUI
- All simulation logic belongs in synarius-core

### Code Style

- Follow PEP 8
- Keep functions small and focused
- Prefer explicit over implicit behavior
- Add docstrings where appropriate

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
