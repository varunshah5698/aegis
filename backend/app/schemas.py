"""Pydantic request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationOut(BaseModel):
    dataset_id: str
    filename: str
    size_bytes: int
    row_count: int
    column_count: int
    delimiter: str
    encoding: str
    status: str
    messages: list[str] = []
    warnings: list[str] = []
    headers: list[str] = []
    sample_rows: list[list[str]] = []


class DatasetOut(BaseModel):
    id: str
    filename: str
    size_bytes: int
    row_count: int
    column_count: int
    validation_status: str
    is_demo: bool
    created_at: str | None = None
    runs: list[dict] = []


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[list]
    total_rows: int
    truncated: bool
    column_types: dict[str, str]


class SchemaOut(BaseModel):
    columns: list[dict]
    semantic_map: dict[str, str]
    capabilities: dict[str, dict]
    detected: dict
    warnings: list[str] = []
    row_count: int


class QualityOut(BaseModel):
    score: float
    grade: str
    formula: str
    missing: dict
    duplicates: dict
    invalid: dict
    outliers: dict
    summary: list[str] = []
    recommendations: list[dict] = []


class ColumnMappingPayload(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)


class CleaningPayload(BaseModel):
    operations: list[dict] = Field(default_factory=list)


class StartAnalysisPayload(BaseModel):
    dataset_id: str
    column_overrides: dict[str, str] = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)


class AssistantPayload(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class NotePayload(BaseModel):
    text: str = Field(default="", max_length=5000)
