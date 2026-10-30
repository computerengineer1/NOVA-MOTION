"""Shared API response envelopes."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorInfo(BaseModel):
    code: str
    summary: str
    recovery: str | None = None
    retryable: bool = False


class OkResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


class KeyValue(BaseModel):
    key: str
    value: Any
