"""Server configuration loaded from environment variables or a .env file.

Every field can be overridden by an environment variable of the same name
(upper- or lower-case). Copy `.env.example` to `.env` for local development.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MCP server settings. Override any field via environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Transport ─────────────────────────────────────────────────────────────
    # "stdio"           — local subprocess (Claude Desktop / Claude Code / Zed)
    # "streamable-http" — remote HTTP server (containers, cloud deploys)
    #
    # NOTE: app.py also auto-selects HTTP when a platform injects DATABRICKS_APP_PORT
    # or PORT, so you usually do NOT need to set this on a cloud host.
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # ── Data file path ────────────────────────────────────────────────────────
    # Relative path to the fixed-width flat file. Override with the
    # DAT_FILE_PATH environment variable (or .env entry). MCP callers cannot
    # supply or change this path; only an operator may configure it through
    # the environment or .env mechanism.
    dat_file_path: str = "sample-data/AI_HACK_TEST_TWO.DAT"

    # ── Reference file path ───────────────────────────────────────────────────
    # Relative path to the PINE/NFC SINQ error reference file (fixed-width,
    # 75 characters per record). Override with the REFERENCE_FILE_PATH
    # environment variable (or .env entry). MCP callers cannot supply or
    # change this path; only an operator may configure it through the
    # environment or .env mechanism.
    reference_file_path: str = "reference-data/sinq_error_reference.txt"

    # ── watsonx.ai (natural-language ask feature) ─────────────────────────────
    # Required to enable the Ask box on the dashboard.
    # Set these in your local .env file — never commit real values.
    # Find WATSONX_PROJECT_ID on your watsonx.ai project Settings page.
    # Find WATSONX_URL in IBM Cloud under your watsonx.ai service instance.
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_model_id: str = "ibm/granite-3-3-8b-instruct"

    # ── Dataset API keys ──────────────────────────────────────────────────────
    # Add a typed field for each API key your tools need, then read it from
    # `settings.<field>` in your tool. Document the matching env var in
    # `.env.example`. Example:
    #
    #   example_api_key: str = ""   # ← set EXAMPLE_API_KEY in the environment


settings = Settings()
