from typing import Literal

from pydantic import BaseModel, Field


class LdapConfigCreate(BaseModel):
    server_uri: str = Field(..., examples=["ldap://dc.corp.example.com:389"])
    bind_method: Literal["direct_bind", "search_bind", "upn_bind"]
    base_dn: str = Field(..., examples=["dc=corp,dc=example,dc=com"])
    direct_bind_dn_template: str | None = Field(
        None, description="direct_bind only; default 'uid={username},{base_dn}'"
    )
    service_bind_dn: str | None = Field(None, description="search_bind only")
    service_bind_password_env: str | None = Field(
        None, description="search_bind only -- the NAME of an env var holding the service account's password, never the secret itself"
    )
    user_search_filter: str | None = Field(None, examples=["(sAMAccountName={username})"], description="search_bind only")
    upn_domain: str | None = Field(None, examples=["corp.example.com"], description="upn_bind only")
    group_search_base: str | None = Field(None, description="Defaults to base_dn if unset")
    is_enabled: bool = True


class LdapConfigUpdate(BaseModel):
    server_uri: str | None = None
    bind_method: Literal["direct_bind", "search_bind", "upn_bind"] | None = None
    base_dn: str | None = None
    direct_bind_dn_template: str | None = None
    service_bind_dn: str | None = None
    service_bind_password_env: str | None = None
    user_search_filter: str | None = None
    upn_domain: str | None = None
    group_search_base: str | None = None
    is_enabled: bool | None = None


class LdapConfigOut(BaseModel):
    id: str
    org_id: str | None
    server_uri: str
    bind_method: str
    base_dn: str
    direct_bind_dn_template: str | None = None
    service_bind_dn: str | None = None
    service_bind_password_env: str | None = None
    user_search_filter: str | None = None
    upn_domain: str | None = None
    group_search_base: str | None = None
    is_enabled: bool
    created_at: str
    updated_at: str


class LdapGroupMappingCreate(BaseModel):
    group_dn: str
    role_id: str


class LdapGroupMappingOut(BaseModel):
    id: str
    ldap_config_id: str
    group_dn: str
    role_id: str


class LdapTestRequest(BaseModel):
    username: str
    password: str


class LdapTestResult(BaseModel):
    success: bool
    dn: str | None = None
    groups: list[str] = Field(default_factory=list)
    detail: str | None = None
