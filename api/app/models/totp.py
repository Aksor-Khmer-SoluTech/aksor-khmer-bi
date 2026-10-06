from pydantic import BaseModel, Field


class TotpEnrollOut(BaseModel):
    """Response to POST /users/me/totp/enroll -- `secret` is the raw
    base32 value shown as manual-entry fallback (some authenticator apps
    don't support scanning), `qr_code_data_url` is a ready-to-render
    `data:image/png;base64,...` string of the same otpauth:// URI.
    Nothing is persisted as *enabled* yet -- POST /totp/confirm with a
    code generated from this secret is what turns it on.
    """

    secret: str
    otpauth_url: str
    qr_code_data_url: str


class TotpCodeRequest(BaseModel):
    code: str = Field(..., description="Current 6-digit code from the authenticator app")
