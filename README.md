# jons-mcp-java

MCP server that provides Java language intelligence through Eclipse JDT.LS.

This project is currently intended to be installed from a source checkout or
from GitHub. It is not documented as a PyPI package.

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
custom, set `JDTLS_HOME`.

## Install and Run

From a source checkout:

```bash
git clone git@github.com:jonmmease/jons-mcp-java.git
cd jons-mcp-java
uv sync
uv run jons-mcp-java
```

From GitHub without a persistent checkout:

```bash
uvx --from git+https://github.com/jonmmease/jons-mcp-java.git jons-mcp-java
```

Set `JONS_MCP_JAVA_WORKSPACE` to the Java workspace you want the server to
analyze. If omitted, the server uses the MCP process current working directory.
All relative tool paths are resolved from this workspace root.

## MCP Client Examples

Claude Code using a source checkout:

```bash
claude mcp add jons-mcp-java \
  -e JONS_MCP_JAVA_WORKSPACE=/path/to/java-workspace \
  -- uv run --project /path/to/jons-mcp-java jons-mcp-java
```

Claude Code using GitHub:

```bash
claude mcp add jons-mcp-java \
  -e JONS_MCP_JAVA_WORKSPACE=/path/to/java-workspace \
  -- uvx --from git+https://github.com/jonmmease/jons-mcp-java.git jons-mcp-java
```

Codex CLI using GitHub:

```bash
codex mcp add jons-mcp-java \
  -e JONS_MCP_JAVA_WORKSPACE=/path/to/java-workspace \
  -- uvx --from git+https://github.com/jonmmease/jons-mcp-java.git jons-mcp-java
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
        "jons-mcp-java"
      ],
      "env": {
        "JONS_MCP_JAVA_WORKSPACE": "/path/to/java-workspace"
      }
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
]

[mcp_servers.jons-mcp-java.env]
JONS_MCP_JAVA_WORKSPACE = "/path/to/java-workspace"
```

## Workspace and Path Behavior

The configured workspace root is the filesystem security boundary.

- Tool paths may be workspace-relative paths, absolute in-workspace paths, or
  `file://` URIs.
- Relative paths are resolved from `JONS_MCP_JAVA_WORKSPACE`, not from the MCP
  server process cwd.
- Paths containing `..`, paths outside the workspace, non-file URIs, malformed
  URIs, missing files, and symlink escapes are rejected before any filesystem or
  JDT.LS access.
- LSP locations outside the workspace may still be returned as locations, but
  the server does not open or read external files.

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
| `diagnostics` | Get cached or freshly refreshed diagnostics |
| `hover` | Get Javadoc and type information |
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

## Freshness and Restart

The server tracks open LSP documents and compares disk metadata plus content
hashes before read-style tool calls. If a file changed outside JDT.LS, the
server sends a full-document `didChange` and `didSave` before requesting fresh
language data.

Use `restart_server` only as a fallback:

```json
{ "file_path": "app/src/main/java/example/Main.java" }
```

With no `file_path`, `restart_server` stops all active JDT.LS clients. Servers
restart lazily on the next file-backed tool call.

## Troubleshooting

- `JDT.LS not found`: install JDT.LS or set `JDTLS_HOME`.
- `Java 21+ required`: install Java 21+ or set `JAVA_HOME`.
- `project_not_found`: the file is inside the workspace, but not under a
  discovered Gradle root.
- `path_outside_workspace`: the path resolves outside
  `JONS_MCP_JAVA_WORKSPACE`.
- `project_startup_failed`: the project import failed; check the JDT.LS stderr
  log under the generated workspace data directory in `~/.cache/jdtls-workspaces`.
