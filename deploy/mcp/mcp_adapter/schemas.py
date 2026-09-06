"""Typed public inputs; backend routing is intentionally not a tool parameter."""
from typing import Annotated, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class SellOrdersInput(Input):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={
        "anyOf": [
            {"required": ["name"], "properties": {"name": {"type": "string"}}},
            {"required": ["type_id"], "properties": {"type_id": {"type": "integer"}}},
        ]
    })
    name: Name | None = None
    type_id: PositiveInt | None = None
    region_name: Name | None = None
    system_name: Name | None = None
    cheapest: bool = False
    top: Annotated[int, Field(strict=True, ge=1, le=100)] = 10

    @model_validator(mode="after")
    def require_item(self):
        if self.name is None and self.type_id is None:
            raise ValueError("Provide name or type_id; type_id takes precedence when both are supplied")
        return self

class HistoryInput(Input):
    name: Name
    region_name: Name
    days: PositiveInt | None = None

class ProductionInput(Input):
    name: Name
    quantity: PositiveInt = 1
    fit: Annotated[str, Field(max_length=8000)] = ""
    blueprint_me: int = 0
    production_efficiency: int = 0
    blueprint_te: int = 0
    industry_skill: int = 0
    advanced_industry_skill: int = 0
    mass_production_skill: int = 0
    advanced_mass_production_skill: int = 0
    supply_chain_management_skill: int = 0
    structure_material_bonus: int = 0
    structure_time_bonus: int = 0
    rig_material_bonus: int = 0
    rig_time_bonus: int = 0

class AdapterResponse(BaseModel):
    data: dict[str, Any] = Field(description="Unmodified backend JSON, including all completeness and error details")
    warnings: list[str] = Field(default_factory=list, description="Adapter context; never replaces backend warnings")
