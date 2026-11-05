"""Shared Authorization & Permissions Layer.

Non-Negotiable Rule 2 & 3:
- Roles are stored per organization/club/activity (memberships),
  NEVER as a single role flag on the user.
- 14 Roles:
    RL01: Rider
    RL02: Club owner
    RL03: Club moderator
    RL04: Ride captain/marshal
    RL05: Event organizer
    RL06: Tour operator
    RL07: Business partner owner
    RL08: Partner staff
    RL09: Instructor
    RL10: Support agent
    RL11: Trust moderator
    RL12: Finance operator
    RL13: Platform administrator
    RL14: Super Admin

- ONE shared permission layer with default-deny evaluation.
"""

from enum import Enum


class RoleCode(str, Enum):
    """The 14 authenticated role codes in BYKERS."""

    RL01_RIDER = "RL01"
    RL02_CLUB_OWNER = "RL02"
    RL03_CLUB_MODERATOR = "RL03"
    RL04_RIDE_CAPTAIN_MARSHAL = "RL04"
    RL05_EVENT_ORGANIZER = "RL05"
    RL06_TOUR_OPERATOR = "RL06"
    RL07_PARTNER_OWNER = "RL07"
    RL08_PARTNER_STAFF = "RL08"
    RL09_INSTRUCTOR = "RL09"
    RL10_SUPPORT_AGENT = "RL10"
    RL11_TRUST_MODERATOR = "RL11"
    RL12_FINANCE_OPERATOR = "RL12"
    RL13_PLATFORM_ADMIN = "RL13"
    RL14_SUPER_ADMIN = "RL14"
