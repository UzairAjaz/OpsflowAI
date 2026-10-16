from __future__ import annotations

from typing import Type, TypeVar

from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)

def get_llm(temperature: float | None = None) -> ChatOllama:

    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=settings.llm_temperature if temperature is None else temperature,
    )

def get_structured_llm(schema: Type[T], temperature: float = 0.0) -> object:

    llm = get_llm(temperature=temperature)
    return llm.with_structured_output(schema, method="json_schema")
