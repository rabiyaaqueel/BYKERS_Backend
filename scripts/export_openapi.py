"""OpenAPI Specification Exporter.

Exports the current FastAPI OpenAPI JSON schema to docs/openapi.json.
Used by the CI/CD pipeline to ensure the committed OpenAPI spec matches the codebase.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app


def main() -> None:
    """Generate and write the OpenAPI specification to docs/openapi.json."""
    openapi_schema = app.openapi()
    output_path = Path("docs/openapi.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)
        f.write("\n")

    print(f"OpenAPI schema successfully exported to {output_path.resolve()}")


if __name__ == "__main__":
    main()
