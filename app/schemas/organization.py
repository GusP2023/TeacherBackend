"""
Schemas Pydantic para Organization
"""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class OrganizationBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)


class OrganizationCreate(OrganizationBase):
    """Usado al registrar una nueva escuela"""
    pass


class OrganizationResponse(OrganizationBase):
    id: int
    slug: str
    active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
