"""Pydantic Request and Response Schemas for Authorization, Workspaces, and Applications."""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceOut(BaseModel):
    """User approved workspace view."""

    user_id: uuid.UUID = Field(description="Rider user identifier")
    account_status: str = Field(description="Account lifecycle status")
    workspace_id: uuid.UUID = Field(description="Workspace identifier (user id or organization id)")
    workspace_type: str = Field(description="Type of workspace: personal, club, business, staff")
    organization_id: Optional[uuid.UUID] = Field(
        default=None, description="Linked organization ID if applicable"
    )
    organization_name: Optional[str] = Field(
        default=None, description="Display name of the organization"
    )
    role_codes: List[str] = Field(description="Active role codes in this workspace")
    permission_version: int = Field(default=1, description="Active permission version sequence")
    authentication_assurance: str = Field(default="otp_verified", description="Assurance tier")
    enabled_module_ids: List[str] = Field(
        description="List of platform modules available in this workspace"
    )
    is_active: bool = Field(
        default=False, description="True if this is the currently active workspace"
    )


class ActiveWorkspaceIn(BaseModel):
    """Select active workspace payload."""

    workspace_id: uuid.UUID = Field(
        description="Target workspace ID to activate",
        examples=["191a823e-0000-0000-0000-000000000000"],
    )


class ActiveWorkspaceOut(BaseModel):
    """Result of active workspace switch."""

    workspace_id: uuid.UUID
    workspace_type: str
    organization_id: Optional[uuid.UUID]
    role_codes: List[str]
    capabilities: List[str]
    message: str = "Active workspace successfully updated"


class CapabilitiesOut(BaseModel):
    """Filtered capabilities and menu items for client UI."""

    workspace_type: str
    organization_id: Optional[uuid.UUID] = None
    role_codes: List[str]
    enabled_module_ids: List[str]
    actions: List[str]


class ApplicationCreateIn(BaseModel):
    """Official application payload."""

    kind: str = Field(
        ...,
        description="Kind of application (club, organizer, tour_operator, partner, instructor)",
        examples=["club"],
    )
    name: str = Field(
        ...,
        min_length=2,
        max_length=150,
        description="Organization or club name",
        examples=["Hyderabad Riders Club"],
    )
    city: Optional[str] = Field(
        default="Hyderabad", description="Base city", examples=["Hyderabad"]
    )
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Application specific metadata"
    )


class ApplicationOut(BaseModel):
    """Application entity view."""

    id: uuid.UUID
    applicant_id: uuid.UUID
    kind: str
    status: str
    payload: Dict[str, Any]
    reviewer_id: Optional[uuid.UUID] = None
    reviewer_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationDecisionIn(BaseModel):
    """Review decision payload."""

    decision: str = Field(
        ...,
        pattern=r"^(approved|rejected|changes_requested)$",
        description="Decision: approved, rejected, or changes_requested",
        examples=["approved"],
    )
    notes: Optional[str] = Field(
        default=None,
        description="Review feedback or rationale",
        examples=["Approved verified motorcycle club"],
    )


class ApplicationDecisionOut(BaseModel):
    """Result of application decision."""

    application_id: uuid.UUID
    status: str
    organization_id: Optional[uuid.UUID] = None
    membership_id: Optional[uuid.UUID] = None
    message: str


class RoleInvitationCreateIn(BaseModel):
    """Create role invitation payload."""

    role_code: str = Field(
        ...,
        description="Role to assign (e.g. RL03 for Club Moderator, RL04 for Captain)",
        examples=["RL03"],
    )
    recipient_user_id: Optional[uuid.UUID] = Field(
        default=None, description="Specific recipient user ID"
    )
    recipient_contact: Optional[str] = Field(
        default=None, description="Recipient phone or email", examples=["+919876543210"]
    )


class RoleInvitationOut(BaseModel):
    """Created role invitation details."""

    id: uuid.UUID
    organization_id: uuid.UUID
    role_code: str
    recipient_contact: Optional[str]
    expires_at: datetime
    invitation_token: Optional[str] = Field(
        default=None, description="Raw token to share with recipient (shown only once)"
    )


class InvitationAcceptOut(BaseModel):
    """Result of invitation acceptance."""

    organization_id: uuid.UUID
    organization_name: str
    role_code: str
    membership_id: uuid.UUID
    message: str = "Invitation accepted successfully"


class MemberUpdateIn(BaseModel):
    """Update organization member status."""

    status: str = Field(
        ...,
        pattern=r"^(active|suspended|revoked)$",
        description="Updated status: active, suspended, or revoked",
        examples=["suspended"],
    )
    version: int = Field(..., description="Optimistic locking version check", examples=[1])


class MemberOut(BaseModel):
    """Organization membership view."""

    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role_code: str
    status: str
    version: int

    model_config = ConfigDict(from_attributes=True)


class AuditEventOut(BaseModel):
    """Audit log entry."""

    id: uuid.UUID
    actor_id: str
    active_context: Dict[str, Any]
    target: str
    action: str
    outcome: str
    reason: Optional[str] = None
    request_id: str
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DevMakeAdminIn(BaseModel):
    """Dev helper payload to grant platform admin rights to a test account."""

    user_id: Optional[uuid.UUID] = Field(
        default=None, description="Target user ID (defaults to caller)"
    )
    role_code: str = Field(
        default="RL13", description="RL13 (Platform Admin) or RL14 (Super Admin)", examples=["RL13"]
    )


class DevMakeAdminOut(BaseModel):
    """Result of dev make-admin promotion."""

    user_id: uuid.UUID
    role_code: str
    message: str = "Test account promoted successfully to platform admin"
