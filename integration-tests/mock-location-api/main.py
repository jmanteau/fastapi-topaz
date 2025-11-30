from __future__ import annotations

import hashlib

from fastapi import FastAPI, Query

app = FastAPI(title="Mock Location API")


# Non-restricted countries for normal users
SAFE_COUNTRIES = ["US", "GB", "FR", "DE", "JP", "CA", "AU"]
# Restricted countries for explicit testing (user_id starting with "restricted_")
RESTRICTED_COUNTRIES = ["CN", "KP", "IR"]


@app.get("/location")
def get_location(user_id: str = Query(..., description="User ID to lookup location")):
    """
    Return mock location data for a user.

    Uses deterministic hashing to assign countries.
    Normal users get safe countries; use user_id prefix "restricted_" for restricted countries.
    """
    # Check if this user should get a restricted country
    if user_id.startswith("restricted_"):
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        country_code = RESTRICTED_COUNTRIES[hash_value % len(RESTRICTED_COUNTRIES)]
    else:
        # Normal users get safe (non-restricted) countries
        hash_value = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        country_code = SAFE_COUNTRIES[hash_value % len(SAFE_COUNTRIES)]

    # Generate deterministic IP based on user_id
    ip_parts = [(hash_value >> (i * 8)) & 0xFF for i in range(4)]
    ip_address = ".".join(str(part) for part in ip_parts)

    return {
        "user_id": user_id,
        "country_code": country_code,
        "ip": ip_address,
        "city": "Mock City",
        "region": "Mock Region",
    }


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
