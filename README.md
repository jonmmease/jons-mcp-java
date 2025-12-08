# jons-mcp-java

MCP server providing Java development capabilities through Eclipse JDT.LS.

## Requirements

- Python 3.10+
- Java 21+ (`brew install openjdk@21`)
- Eclipse JDT.LS (`brew install jdtls`)

## Installation

```bash
cd /path/to/jons-mcp-java
uv sync
```

## Usage with Claude Code

Add the MCP server to Claude Code:

```bash
claude mcp add jons-mcp-java -- uv run --project /path/to/jons-mcp-java jons-mcp-java
```

Replace `/path/to/jons-mcp-java` with the actual path to this repository.

To set the workspace root (defaults to current directory):

```bash
claude mcp add jons-mcp-java -e JONS_MCP_JAVA_WORKSPACE=/path/to/workspace -- uv run --project /path/to/jons-mcp-java jons-mcp-java
```

## Available Tools

| Tool | Description |
|------|-------------|
| `definition` | Go to symbol definition |
| `references` | Find all references to a symbol |
| `implementation` | Find implementations of interfaces/abstract methods |
| `type_definition` | Go to type definition |
| `document_symbols` | List all symbols in a file |
| `workspace_symbols` | Search for symbols across the workspace |
| `diagnostics` | Get errors and warnings |
| `hover` | Get Javadoc and type information |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JONS_MCP_JAVA_WORKSPACE` | Current directory | Root workspace for Java projects |
| `JDTLS_HOME` | Auto-detect | JDT.LS installation directory |
| `JAVA_HOME` | Auto-detect | Java 21+ installation |

## Features

- **Multi-project support**: Automatically discovers Gradle projects in mono-repos
- **Lazy initialization**: JDT.LS instances start on-demand per project
- **LRU eviction**: Manages memory by limiting active instances (default: 3)
- **Concurrent protection**: Handles parallel requests safely
