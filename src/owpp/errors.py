class OwppError(Exception):
    """A problem the user can fix (bad manifest, failed API call, ...). The CLI prints it without a traceback."""
