# jons-mcp-java

MCP server that provides Java language intelligence through Eclipse JDT.LS.

This project is currently intended to be installed from a source checkout or
from GitHub. It is not documented as a PyPI package.

The current public API is aligned with `jons-mcp-typescript`: public positions
are one-based, successful tool responses use structured `items` and pagination
shapes, and refactoring previews are read-only.

## Requirements

- Python 3.10+
- Java 21+
- Eclipse JDT.LS
- A target Java workspace containing Gradle project markers:
  `settings.gradle`, `settings.gradle.kts`, `build.gradle`, or `build.gradle.kts`

On macOS with Homebrew:

```bash
brew install openjdk@21 jdtls
```

If Java is not on your PATH, set `JAVA_HOME`. If JDT.LS is installed somewhere
custom, set `JDTLS_HOME`. The server also tries to resolve a `jdtls`
executable on PATH.

If `JDTLS_HOME` points at a read-only install such as the Nix store, the server
copies the small platform `config_<os>` directory into a writable cache under
`$XDG_CACHE_HOME/jons-mcp-java` or `~/.cache/jons-mcp-java`. Set
`JDTLS_CONFIG_DIR` to choose a specific writable configuration directory. The
cached copy is repaired to be user-writable even when the source archive or
package ships read-only mode bits.

## Install and Run

From a source checkout:

```bash
git clone git@github.com:jonmmease/jons-mcp-java.git
cd jons-mcp-java
uv sync
uv run jons-mcp-java /path/to/java-workspace
```

From GitHub without a persistent checkout:

```bash
uvx --from git+https://github.com/jonmmease/jons-mcp-java.git \
  jons-mcp-java /path/to/java-workspace
```

Pass the Java workspace root as the optional positional argument, or set
`JONS_MCP_JAVA_WORKSPACE`. The positional argument takes precedence. If neither
is provided, the server uses the MCP process current working directory. All
relative tool paths are resolved from this workspace root.

## MCP Client Examples

Claude Code using a source checkout:

```bash
claude mcp add jons-mcp-java \
  -- uv run --project /path/to/jons-mcp-java \
  jons-mcp-java /path/to/java-workspace
```

Claude Code using GitHub:

```bash
claude mcp add jons-mcp-java \
  -- uvx --from git+https://github.com/jonmmease/jons-mcp-java.git \
  jons-mcp-java /path/to/java-workspace
```

Codex CLI using GitHub:

```bash
codex mcp add jons-mcp-java \
  -- uvx --from git+https://github.com/jonmmease/jons-mcp-java.git \
  jons-mcp-java /path/to/java-workspace
```

`.mcp.json`:

```json
{
  "mcpServers": {
    "jons-mcp-java": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/jonmmease/jons-mcp-java.git",
        "jons-mcp-java",
        "/path/to/java-workspace"
      ]
    }
  }
}
```

Codex TOML:

```toml
[mcp_servers.jons-mcp-java]
command = "uvx"
args = [
  "--from",
  "git+https://github.com/jonmmease/jons-mcp-java.git",
  "jons-mcp-java",
  "/path/to/java-workspace",
]
```

## Workspace and Path Behavior

The configured workspace root is the filesystem security boundary.

- Tool paths may be workspace-relative paths, absolute in-workspace paths, or
  `file://` URIs.
- Relative paths are resolved from the configured workspace root, not from the
  MCP server process cwd.
- Paths containing `..`, paths outside the workspace, non-file URIs, malformed
  URIs, missing files, and symlink escapes are rejected before any filesystem or
  JDT.LS access.
- LSP locations outside the workspace may still be returned with
  `"inWorkspace": false`, but the server does not open or read external files.

Path and startup failures use a stable error shape:

```json
{
  "status": "error",
  "error": {
    "type": "path_outside_workspace",
    "message": "Path resolves outside the configured workspace root.",
    "path": "../outside.java"
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `definition` | Go to symbol definition |
| `references` | Find all references to a symbol |
| `implementation` | Find implementations of interfaces/abstract methods |
| `type_definition` | Go to type definition |
| `document_symbols` | List symbols in a file |
| `workspace_symbols` | Search symbols in an initialized project |
| `diagnostics` | Get fresh diagnostics for one file |
| `symbol_info` | Get hover-style Javadoc and type information |
| `preview_rename` | Preview symbol rename edits without writing files |
| `restart_server` | Stop one or all JDT.LS clients and clear runtime state |

The first file-backed call for a project starts JDT.LS lazily and usually
returns:

```json
{
  "status": "initializing",
  "message": "Starting project initialization; please retry shortly.",
  "project": "/path/to/java-workspace/app"
}
```

Retry the same tool after initialization finishes.

## Tool Behavior

Tools that accept or return `line` and `character` use one-based positions,
matching editor and agent `Read` output. If your editor shows line 28, pass
`line=28`; returned ranges use the same convention. Use `document_symbols` to
discover one-based symbol ranges when you do not already know a position.

Successful navigation tools return normalized items:

```json
{
  "items": [
    {
      "uri": "file:///path/to/Main.java",
      "range": {
        "start": { "line": 12, "character": 8 },
        "end": { "line": 12, "character": 12 }
      },
      "inWorkspace": true
    }
  ],
  "totalItems": 1
}
```

`references`, `document_symbols`, `workspace_symbols`, and `diagnostics` return
paginated results with `items`, `totalItems`, `offset`, `limit`, `hasMore`, and
`nextOffset`.

Navigation tools preserve JDT.LS result order and return `items` plus
`totalItems`. `references`, diagnostics, and symbol lists are sorted
deterministically before pagination.

`preview_rename` is safe to inspect. It returns a flat list of file URI,
one-based replacement range, `newText`, and `inWorkspace` values, plus
`totalEdits`. It does not write to disk.

## Freshness and Restart

The server tracks open LSP documents and compares disk metadata plus content
hashes before read-style tool calls. If a file changed outside JDT.LS, the
server sends a full-document `didChange` and `didSave` before requesting fresh
language data.

`diagnostics` is file-scoped and always refreshes the target file before
returning compiler diagnostics.

Use `restart_server` only as a fallback:

```json
{ "file_path": "app/src/main/java/example/Main.java" }
```

With no `file_path`, `restart_server` stops all active JDT.LS clients. Servers
restart lazily on the next file-backed tool call.

## Troubleshooting

- `JDT.LS not found`: install JDT.LS, put `jdtls` on PATH, or set `JDTLS_HOME`.
- `Java 21+ required`: install Java 21+ or set `JAVA_HOME`.
- `project_not_found`: the file is inside the workspace, but not under a
  discovered Gradle root.
- `path_outside_workspace`: the path resolves outside
  the configured workspace root.
- `project_startup_failed`: the project import failed; check the JDT.LS stderr
  log under the generated workspace data directory in `~/.cache/jdtls-workspaces`.
- Read-only `JDTLS_HOME`: set `JDTLS_CONFIG_DIR` to a writable directory, or let
  the server create and permission-repair its cached config copy automatically.
