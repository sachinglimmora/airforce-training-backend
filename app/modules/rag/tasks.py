"""Celery tasks: embed_source, reembed_source, reembed_all_dim_mismatch, auto_close_idle_sessions."""

from app.worker import celery_app


@celery_app.task(name="rag.embed_source")
def embed_source(source_id: str):
    raise NotImplementedError


@celery_app.task(name="rag.reembed_source")
def reembed_source(source_id: str):
    raise NotImplementedError


@celery_app.task(name="rag.reembed_all_dim_mismatch")
def reembed_all_dim_mismatch():
    raise NotImplementedError


@celery_app.task(name="rag.auto_close_idle_sessions")
def auto_close_idle_sessions():
    raise NotImplementedError
