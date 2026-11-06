"""Pydantic Schemas for Module Registry, Menu, and Customization."""

import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class MenuItemOut(BaseModel):
    """An authorized, active module item for the user's web interface navigation."""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., description="DPR module code (e.g. M06)")
    name: str = Field(..., description="Module display name")
    access: Literal["view", "manage"] = Field(..., description="Access level: view or manage")
    display_order: int = Field(..., description="Sort order in the web menu")


class MenuResponse(BaseModel):
    """Menu navigation response for the active session and workspace."""

    interface: str
    organization_id: Optional[uuid.UUID] = None
    modules: List[MenuItemOut]


class InterfaceModuleOut(BaseModel):
    """Module configuration for a web interface."""

    model_config = ConfigDict(from_attributes=True)

    module_id: uuid.UUID
    module_code: str
    module_name: str
    release: str
    is_active: bool
    display_order: int
    default_enabled: bool


class InterfaceModuleUpdateIn(BaseModel):
    """Staff payload to reorder or toggle default enablement of an interface module."""

    display_order: Optional[int] = Field(None, ge=0)
    default_enabled: Optional[bool] = None


class OrganizationModuleOut(BaseModel):
    """Module status for an organization."""

    module_code: str
    module_name: str
    enabled: bool
    can_toggle: bool
    set_at: Optional[datetime] = None


class OrganizationModuleToggleIn(BaseModel):
    """Payload to toggle modules for an organization."""

    modules: Dict[str, bool] = Field(
        ...,
        description="Dictionary mapping module codes (e.g. 'M06', 'M12') to enabled boolean state",
    )


class RoleModuleAccessOut(BaseModel):
    """Access level granted to a role for a module within an interface."""

    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID
    role_code: str
    module_code: str
    interface: str
    access: Literal["none", "view", "manage"]


class RoleModuleAccessUpdateIn(BaseModel):
    """Update role access for a module in an interface."""

    access: Literal["none", "view", "manage"]


class OrganizationCategoryOut(BaseModel):
    """Partner business category and its approval state."""

    category: str
    approval_state: Literal["pending", "approved", "rejected"]
    approved_at: Optional[datetime] = None
