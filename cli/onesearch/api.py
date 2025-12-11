"""API client wrapper for OneSearch backend."""

from typing import Any
from urllib.parse import urljoin

import requests


class APIError(Exception):
    """Exception raised for API errors."""

    def __init__(self, message: str, status_code: int | None = None, details: Any = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class OneSearchAPI:
    """Client for the OneSearch backend API."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30):
        """Initialize the API client.

        Args:
            base_url: Backend API base URL.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, endpoint: str) -> str:
        """Build full URL for an endpoint."""
        return urljoin(self.base_url + "/", endpoint.lstrip("/"))

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        """Make an API request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            endpoint: API endpoint path.
            params: Query parameters.
            json: JSON body data.

        Returns:
            Response JSON data.

        Raises:
            APIError: If the request fails.
        """
        url = self._url(endpoint)
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json,
                timeout=self.timeout,
            )
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.ConnectionError:
            raise APIError(
                f"Could not connect to OneSearch at {self.base_url}. "
                "Is the server running?"
            )
        except requests.exceptions.Timeout:
            raise APIError(f"Request to {url} timed out after {self.timeout}s")
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            try:
                details = e.response.json()
                message = details.get("detail", str(e))
            except Exception:
                details = None
                message = str(e)
            raise APIError(message, status_code=status_code, details=details)

    # Health endpoints
    def health(self) -> dict:
        """Check system health."""
        return self._request("GET", "/api/health")

    def status(self) -> dict:
        """Get system status."""
        return self._request("GET", "/api/status")

    def source_status(self, source_id: str) -> dict:
        """Get status for a specific source."""
        return self._request("GET", f"/api/status/{source_id}")

    # Source endpoints
    def list_sources(self) -> list[dict]:
        """List all sources."""
        return self._request("GET", "/api/sources")

    def get_source(self, source_id: str) -> dict:
        """Get a specific source."""
        return self._request("GET", f"/api/sources/{source_id}")

    def create_source(
        self,
        name: str,
        root_path: str,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> dict:
        """Create a new source.

        Args:
            name: Source display name.
            root_path: Root path to index.
            include_patterns: List of glob patterns to include.
            exclude_patterns: List of glob patterns to exclude.

        Returns:
            Created source data.
        """
        data = {
            "name": name,
            "root_path": root_path,
        }
        if include_patterns:
            data["include_patterns"] = include_patterns
        if exclude_patterns:
            data["exclude_patterns"] = exclude_patterns
        return self._request("POST", "/api/sources", json=data)

    def update_source(
        self,
        source_id: str,
        name: str | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> dict:
        """Update a source.

        Args:
            source_id: Source ID.
            name: New source name.
            include_patterns: New include patterns (list of globs).
            exclude_patterns: New exclude patterns (list of globs).

        Returns:
            Updated source data.
        """
        data = {}
        if name is not None:
            data["name"] = name
        if include_patterns is not None:
            data["include_patterns"] = include_patterns
        if exclude_patterns is not None:
            data["exclude_patterns"] = exclude_patterns
        return self._request("PUT", f"/api/sources/{source_id}", json=data)

    def delete_source(self, source_id: str) -> None:
        """Delete a source."""
        self._request("DELETE", f"/api/sources/{source_id}")

    def reindex_source(self, source_id: str) -> dict:
        """Trigger reindex for a source.

        Args:
            source_id: Source ID.

        Returns:
            Reindex result with statistics.
        """
        return self._request("POST", f"/api/sources/{source_id}/reindex")

    # Search endpoints
    def search(
        self,
        query: str,
        source_id: str | None = None,
        file_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Search indexed documents.

        Args:
            query: Search query string.
            source_id: Filter by source ID.
            file_type: Filter by file type (text, markdown, pdf).
            limit: Maximum results to return.
            offset: Result offset for pagination.

        Returns:
            Search results with metadata.
        """
        data: dict = {
            "q": query,
            "limit": limit,
            "offset": offset,
        }
        if source_id is not None:
            data["source_id"] = source_id
        if file_type is not None:
            data["type"] = file_type
        return self._request("POST", "/api/search", json=data)
