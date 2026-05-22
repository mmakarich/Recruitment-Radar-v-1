from __future__ import annotations

import re
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
    "java": "Java",
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    "hibernate": "Hibernate",
    "openapi": "OpenAPI",
    "asyncapi": "AsyncAPI",
    "jms": "JMS",
    "mq": "MQ",
    "git": "Git",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node js": "Node.js",
    "nestjs": "Nest.js",
    "nest.js": "Nest.js",
    "nest js": "Nest.js",
}

_KEYWORD_BLOCKLIST = {
    "account management",
    "asyncapi",
    "calculation engine",
    "ci/cd",
    "cicd",
    "customer facing reports",
    "design patterns",
    "financial",
    "git",
    "investment",
    "jms",
    "messaging",
    "mq",
    "oop",
    "openapi",
    "pension",
    "savings",
    "sql",
    "taxation",
    "tax regulations",
    "upgrade",
}

_KEYWORD_TECH_ALLOWLIST = {
    "aws",
    "azure",
    "django",
    "docker",
    "fastapi",
    "hibernate",
    "java",
    "javascript",
    "k8s",
    "kubernetes",
    "nest.js",
    "nestjs",
    "node",
    "node js",
    "node.js",
    "nodejs",
    "postgres",
    "postgresql",
    "py",
    "py3",
    "python",
    "python3",
    "react",
    "spring",
    "spring boot",
    "springboot",
    "ts",
    "typescript",
}

_ROLE_KEYWORD_RE = re.compile(
    r"\b("
    r"architect|backend|consultant|developer|devops|engineer|frontend|fullstack|"
    r"full stack|junior|lead|manager|mid|pmo|product|project|qa|senior|"
    r"specialist|tester"
    r")\b",
    re.IGNORECASE,
)


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
            cleaned = _normalize_keyword(item)
            key = cleaned.lower()
            if cleaned and key not in seen:
                normalized.append(cleaned)
                seen.add(key)

        return tuple(normalized)

    @model_validator(mode="after")
    def derive_search_keywords(self) -> JDParsed:
        keywords: list[str] = []
        if self.title.strip():
            keywords.append(self.title.strip())

        keywords.extend(self.tech_stack)
        keywords.extend(self.keywords)

        normalized: list[str] = []
        seen: set[str] = set()
        for keyword in keywords:
            cleaned = _normalize_keyword(keyword)
            if not cleaned and keyword in self.tech_stack:
                cleaned = keyword
            key = cleaned.lower()
            if cleaned and key not in seen:
                normalized.append(cleaned)
                seen.add(key)

        object.__setattr__(self, "keywords", tuple(normalized[:8]))
        return self


def _normalize_technology(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""

    alias = _TECH_ALIASES.get(cleaned.lower())
    return alias if alias is not None else cleaned


def _normalize_keyword(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if lowered in _KEYWORD_BLOCKLIST:
        return ""

    without_version = re.sub(r"\s+\d+(?:[.\-\w+x]*)?$", "", cleaned).strip()
    lowered_without_version = without_version.lower()
    if lowered_without_version in _KEYWORD_BLOCKLIST:
        return ""

    canonical = _normalize_technology(without_version)
    if lowered_without_version in _KEYWORD_TECH_ALLOWLIST:
        return canonical

    if _ROLE_KEYWORD_RE.search(cleaned):
        return cleaned

    if lowered in _TECH_ALIASES:
        return _normalize_technology(cleaned)

    return ""
