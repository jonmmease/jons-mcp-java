"""Custom exceptions for jons-mcp-java."""


class JdtlsError(Exception):
    """Base exception for jons-mcp-java."""


class JdtlsNotFoundError(JdtlsError):
    """JDT.LS installation not found."""


class JavaNotFoundError(JdtlsError):
    """Java installation not found."""


class JavaVersionError(JdtlsError):
    """Java version is below 21."""


class JdtlsNotInitializedError(JdtlsError):
    """JDT.LS client not yet initialized."""


class LspRequestError(JdtlsError):
    """LSP request failed."""

    def __init__(self, message: str, code: int | None = None):
        self.code = code
        super().__init__(message)


class UnsupportedPlatformError(JdtlsError):
    """Platform not supported."""


# User-friendly error messages
ERROR_MESSAGES = {
    JdtlsNotFoundError: "JDT.LS not found. Install via: brew install jdtls",
    JavaNotFoundError: "Java not found. Install via: brew install openjdk@21",
    JavaVersionError: "Java 21+ required. Current version is too old.",
    JdtlsNotInitializedError: "Project is initializing. Please try again in a moment.",
}
