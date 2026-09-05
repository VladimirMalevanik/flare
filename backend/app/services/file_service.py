"""Document ingestion orchestration will live here.

The service will create an immutable document version, store the original file,
and enqueue extraction without coupling HTTP routes to a concrete worker.
"""
