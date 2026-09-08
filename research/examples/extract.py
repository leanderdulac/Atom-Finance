"""Extract an article through the authenticated ATOM gateway."""

import os
import httpx

with httpx.Client(timeout=200) as client:
    response = client.post(
        os.getenv("ATOM_API_URL", "http://127.0.0.1:8000") + "/api/research/papers",
        headers={"Authorization": "Bearer " + os.environ["ATOM_JWT"]},
        json={
            "kind": "text",
            "content": "Replace this with the full research article.",
        },
    )
    response.raise_for_status()
    print(response.json())
