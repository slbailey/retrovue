# Ambiguity: ProgramDirector import alias

**Domain:** systems (disambiguation)

## Protocol vs implementation naming

RetroVue Core may expose **protocol types** re-exported under names that look like concrete classes (historical compatibility in the runtime module). For **reasoning**, treat **ProgramDirector** as:

| Concept | Meaning |
|---------|---------|
| **ProgramDirector (product)** | HTTP + lifecycle supervisor service | `service:program-director` |
| **ProgramDirectorProtocol** | Interface for typing/di | Same **logical** service boundary—not a second activation owner. |

## Resolution rule

**Ownership questions** (“who activates channels?”) always resolve to the **single supervisor** pattern: one logical PD regardless of import path.

## Relationships

See `relationships/cross-domain.yaml` (`ambiguity:program-director-import-alias`).
