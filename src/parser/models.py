from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Currency = Literal["PLN", "EUR", "USD"]
SalaryPeriod = Literal["month", "hour"]
ContractKind = Literal["b2b", "uop"]
Seniority = Literal["junior", "mid", "senior", "lead", "expert"]
WorkMode = Literal["remote", "hybrid", "onsite"]
Language = Literal["pl", "en"]


_TECH_ALIASES = {
    "py": "Python",
    "py3": "Python",
    "python3": "Python",
    "python": "Python",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "aws": "AWS",
    "azure": "Microsoft Azure",
    "react": "React",
    "fastapi": "FastAPI",
    "django": "Django",
    "docker": "Docker",
}


class SalaryRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    min: int
    max: int
    currency: Currency
    period: SalaryPeriod
    contract: ContractKind

    @model_validator(mode="after")
    def validate_range(self) -> SalaryRange:
        if self.min < 0 or self.max < 0:
            raise ValueError("salary cannot be negative")
        if self.min > self.max:
            raise ValueError("min cannot exceed max")
        return self


class JDParsed(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    seniority: Seniority | None = None
    tech_stack: tuple[str, ...] = ()
    location: str | None = None
    work_mode: WorkMode | None = None
    salary: SalaryRange | None = None
    keywords: tuple[str, ...] = ()
    language: Language
    raw_text: str

    @field_validator("tech_stack", mode="before")
    @classmethod
    def normalize_tech_stack(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(value, str):
            raw_items = [value]
        elif isinstance(value, list | tuple):
            raw_items = [item for item in value if isinstance(item, str)]
        else:
            return ()

        normalized: list[str] = []
        seen: set[str] = set()

        for item in raw_items:
            canonical = _normalize_technology(item)
            key = canonical.lower()
            if canonical and key not in seen:
                normalized.append(canonical)
                seen.add(key)

        return tuple(normalized)

    @field_validator("keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(value, str):
            raw_items = [value]
        elif isinstance(value, list | tuple):
            raw_items = [item for item in value if isinstance(item, str)]
        else:
            return ()

        normalized: list[str] = []
        seen: set[str] = set()

        for item in raw_items:
            cleaned = " ".join(item.strip().split())
            key = cleaned.lower()
            if cleaned and key not in seen:
                normalized.append(cleaned)
                seen.add(key)

        return tuple(normalized)


def _normalize_technology(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""

    alias = _TECH_ALIASES.get(cleaned.lower())
    return alias if alias is not None else cleaned
