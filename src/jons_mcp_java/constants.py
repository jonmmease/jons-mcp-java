"""Constants for jons-mcp-java."""

# LSP method constants
LSP_INITIALIZE = "initialize"
LSP_INITIALIZED = "initialized"
LSP_SHUTDOWN = "shutdown"
LSP_EXIT = "exit"

# Text document methods
LSP_TEXT_DOCUMENT_DID_OPEN = "textDocument/didOpen"
LSP_TEXT_DOCUMENT_DID_CHANGE = "textDocument/didChange"
LSP_TEXT_DOCUMENT_DID_CLOSE = "textDocument/didClose"
LSP_TEXT_DOCUMENT_DID_SAVE = "textDocument/didSave"
LSP_TEXT_DOCUMENT_DEFINITION = "textDocument/definition"
LSP_TEXT_DOCUMENT_TYPE_DEFINITION = "textDocument/typeDefinition"
LSP_TEXT_DOCUMENT_REFERENCES = "textDocument/references"
LSP_TEXT_DOCUMENT_IMPLEMENTATION = "textDocument/implementation"
LSP_TEXT_DOCUMENT_HOVER = "textDocument/hover"
LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL = "textDocument/documentSymbol"
LSP_TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS = "textDocument/publishDiagnostics"

# Workspace methods
LSP_WORKSPACE_SYMBOL = "workspace/symbol"
LSP_WORKSPACE_CONFIGURATION = "workspace/configuration"
LSP_WORKSPACE_WORKSPACE_FOLDERS = "workspace/workspaceFolders"

# Client methods (server -> client requests)
LSP_CLIENT_REGISTER_CAPABILITY = "client/registerCapability"
LSP_CLIENT_UNREGISTER_CAPABILITY = "client/unregisterCapability"

# Window methods
LSP_WINDOW_WORK_DONE_PROGRESS_CREATE = "window/workDoneProgress/create"
LSP_WINDOW_LOG_MESSAGE = "window/logMessage"

# JDT.LS specific methods
JDTLS_LANGUAGE_STATUS = "language/status"
JDTLS_PROGRESS = "$/progress"

# Timeout defaults (in seconds)
JDTLS_TIMEOUT = 60
JDTLS_INIT_TIMEOUT = 120

# Maximum concurrent JDT.LS instances
JDTLS_MAX_CLIENTS = 3

# JVM memory allocation
JDTLS_MEMORY = "1G"

# Java minimum version
JAVA_MIN_VERSION = 21
