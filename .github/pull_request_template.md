## What Changed
<!-- Describe what this PR does, why it is needed, and link any related issue. -->

## How I Tested
<!-- Detail how you verified this change locally (e.g. running scripts/check.ps1, test coverage, manual API tests via curl or Swagger). -->
- [ ] Ran `.\scripts\check.ps1` locally and all checks passed.
- [ ] Tests added / updated covering new functionality.

## Quality & Safety Checklist
- **Database migration included?** [ ] Yes / [ ] No
  - *If Yes: Did you test reversible upgrade/downgrade (`alembic upgrade head -> alembic downgrade -1 -> alembic upgrade head`)?*
- **Rule 4 error shape respected?** [ ] Yes / [ ] No
  - *All API error responses must follow `{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}`.*
- **Breaking changes?** [ ] Yes / [ ] No
  - *If Yes: Does this affect mobile apps or external integrations?*

## Additional Notes
<!-- Any secrets, environment variables, or rollout considerations needed. -->
