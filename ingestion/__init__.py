"""Alert ingestion domain layer.

Normalizes raw webhook payloads into a canonical Alert and applies
idempotency and deduplication rules before an incident is created.
"""
