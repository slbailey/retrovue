# 🤝 Contributing to Retrovue

Thank you for your interest in contributing to Retrovue! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- Code of Conduct
- Getting Started
- Development Workflow
- Coding Standards
- Testing
- Operator CLI Conventions
- Contract-driven Tests
- Submitting Changes
- Documentation
- What to Contribute
- Communication
- License

## 📜 Code of Conduct

### Our Standards

- Be respectful and inclusive to all contributors.
- Be constructive when providing feedback.
- Focus on what's best for the community and project.
- Show empathy towards other community members.

## 🚀 Getting Started

### Prerequisites

Before you begin, ensure you have:

- Python 3.8+ installed
- FFmpeg in your PATH
- Git for version control
- A GitHub account

### Fork and Clone

- Fork the Retrovue repository on GitHub.
- Clone your fork locally:
  ```bash
  git clone https://github.com/YOUR-USERNAME/Retrovue.git
  cd Retrovue
  ```
- Add the upstream repository:
  ```bash
  git remote add upstream https://github.com/slbailey/Retrovue.git
  ```

### Development Setup

**Linux/Ubuntu/WSL:**

```bash
python3 -m venv venv
source venv/bin/activate
# Or use the provided activation script:
# source activate.sh  # Note: use 'source', not './activate.sh'
pip install -e .  # Install package in editable mode with dependencies
pip install -e ".[dev]"  # Install with dev dependencies (optional)
# This creates the 'retrovue' command. If not installed, use: python -m retrovue.cli.main --help
```

### Verify Installation

Test the CLI:

```bash
python -m cli.plex_sync --help
```

Run tests:

```bash
pytest tests/ -v
```

## 🔄 Development Workflow

1. Create a Feature Branch

```bash
git fetch upstream
git checkout main
git merge upstream/main
git checkout -b feature/your-feature-name
```

2. Make Your Changes

- Write clear, documented code.
- Follow coding standards.
- Add tests for new functionality.
- Update documentation if needed.

3. Test Your Changes

```bash
flake8 .
mypy cli/ src/retrovue/ --ignore-missing-imports
pytest tests/ -v --cov
```

4. Commit Your Changes

```bash
git add .
git commit -m "feat: Add feature description"
```

5. Push and Create a Pull Request

```bash
git push origin feature/your-feature-name
```

Then open a Pull Request on GitHub.

## 📝 Coding Standards

### Python Style

- Follow PEP 8.
- Format with black: `black .`
- Sort imports with isort: `isort .`
- Max line length: 127 characters.
- Use type hints where appropriate.

### Code Quality

- Write docstrings for all public functions and classes.
- Keep functions focused on one purpose.
- Use meaningful variable names.
- Comment complex or non-obvious logic.

## 🧪 Testing

### Writing Tests

- Place all tests under `tests/`.
- Use pytest.
- Aim for at least 80% coverage.
- Test both success and failure cases.

### Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=cli --cov=src/retrovue --cov-report=term-missing
PLEX_OFFLINE=1 pytest tests/ -v
```

## 💻 Operator CLI Conventions

Retrovue’s CLI is treated as a first-class user interface. Every command must be intuitive, readable,
and predictable for a human operator. The CLI follows a strict **noun → verb → parameters** pattern.

**General Syntax:**

```
retrovue <noun> <verb> [options]
```

**Examples:**

```
retrovue collection wipe channels --dry-run
retrovue sync schedule --test-db
retrovue ingest media --force
```

**Guidelines:**

- Keep verbs action-oriented (`sync`, `wipe`, `ingest`, `list`, `show`, `rebuild`).
- Keep nouns clear and singular (`collection`, `asset`, `source`, `schedule`).
- Destructive commands must require `--confirm` or `--force`.
- All commands must support `--dry-run` for safety.
- Optional `--test-db` flag redirects DB I/O to the mock database.
- Human-readable output comes first; machine-readable `--json` is secondary.

## 🔍 Contract-driven Tests

Retrovue treats the CLI as part of the product. Every operator-facing command
(`retrovue collection wipe`, `retrovue source sync`, etc.) has a written contract,
and tests that enforce that contract.

**The contract docs live in** `docs/contracts/*.md`.

Each contract MUST define:

- CLI shape (noun + verb), e.g. `retrovue collection wipe`
- Required/optional flags (`--dry-run`, `--json`, `--force`, etc.)
- Exit code expectations
- Confirmation / safety behavior for destructive actions
- Human-readable and machine-readable output formats
- Data integrity guarantees

**The tests live in** `tests/contracts/`.

We use two styles of contract tests:

1. CLI contract tests – test help text, required flags, output, exit codes.
2. Data contract tests – run real logic against a test DB and validate state.

**Referenced Contracts:**

- [`collectionwipecontract.md`](docs/contracts/collectionwipecontract.md)
- [`syncidempotencycontract.md`](docs/contracts/syncidempotencycontract.md)

These define expected CLI syntax, behavior, and testing obligations.
Any change to CLI syntax or side effects requires updating the relevant contract first.

Golden Rule: Implementation must change to satisfy the contract—not the other way around.

## 📤 Submitting Changes

Before Submitting:

- Follow style guidelines.
- Tests must pass locally.
- Add tests for new features.
- Update documentation.
- Clear, descriptive commits.
- Branch is up to date with main.

## 📚 Documentation

When updating functionality:

- Update docstrings and inline comments.
- Revise README.md if user-facing behavior changes.
- Keep guides in `documentation/` current.

### 📘 Contract Documentation Index

- **Collection Wipe Contract** → `docs/contracts/collectionwipecontract.md`
- **Sync Idempotency Contract** → `docs/contracts/syncidempotencycontract.md`

All operator commands must align with their documented contract, including syntax, flags, confirmation prompts,
and test coverage. If your contribution adds a new CLI command, create a new `docs/contracts/*.md` file following
the same pattern.

## 🎯 What to Contribute

High-Priority Areas:

- Bug fixes
- Test coverage improvements
- Documentation enhancements
- Performance optimizations

Feature Development:
See the [Development Roadmap](documentation/development-roadmap.md) for planned features.

## 💬 Communication

- GitHub Discussions – questions and ideas
- GitHub Issues – bugs and feature requests
- Pull Requests – code-specific discussions

## 📄 License

By contributing to Retrovue, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing to Retrovue!** 🎉📺
