
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.git_service import fetch_github_repo


@pytest.mark.asyncio
async def test_fetch_github_repo():

    mock_response = {
        "name": "fastapi",
        "full_name": "tiangolo/fastapi",
        "description": "FastAPI framework",
        "html_url": "https://github.com/tiangolo/fastapi",
        "stargazers_count": 100,
        "forks_count": 20,
        "language": "Python",
        "default_branch": "master"
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:

        mock_get.return_value.status_code = 200

        mock_get.return_value.json = Mock(
            return_value=mock_response
        )

        result = await fetch_github_repo("tiangolo", "fastapi")

        assert result["name"] == "fastapi"
        assert result["stars"] == 100
        assert result["language"] == "Python"
