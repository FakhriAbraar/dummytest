"""Tests untuk classification API — tanpa Docker, semua DB di-mock."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette import status

from app.models.models import Classification, IGRSRules


# ---------------------------------------------------------------------------
# Helper: buat IGRSRules mock object
# ---------------------------------------------------------------------------

def _make_igrs_rule(
    id: int = 1,
    kategori_ai: str = "SAFE",
    age_rating_minimal: str = "SU",
    dominant_modality: str = "VISUAL",
) -> IGRSRules:
    rule = MagicMock(spec=IGRSRules)
    rule.id = id
    rule.kategori_ai = kategori_ai
    rule.age_rating_minimal = age_rating_minimal
    rule.dominant_modality = dominant_modality
    return rule


def _make_classification(
    classification_id: int = 1,
    content_id: int = 10,
    agent_id: int = 2,
    category: str = "SAFE",
    igrs_rule: IGRSRules | None = None,
) -> Classification:
    clf = MagicMock(spec=Classification)
    clf.classification_id = classification_id
    clf.content_id = content_id
    clf.agent_id = agent_id
    clf.category = category
    clf.reasoning_category = "SAFE"
    clf.unsafe_reason = None
    clf.confidence_score = 0.95
    clf.classification_timestamp = datetime.now(timezone.utc)
    clf.igrs_rule = igrs_rule or _make_igrs_rule()
    return clf


# ---------------------------------------------------------------------------
# Test: health check
# ---------------------------------------------------------------------------

async def test_health_check(client: AsyncClient, fastapi_app: FastAPI) -> None:
    """Health endpoint harus return 200."""
    url = fastapi_app.url_path_for("health_check")
    response = await client.get(url)
    assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# Test: POST /api/classification/classify  — SAFE content
# ---------------------------------------------------------------------------

async def test_classify_safe_content(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """Konten SAFE harus return 201 dengan category=SAFE."""
    rule = _make_igrs_rule(kategori_ai="SAFE", age_rating_minimal="SU")
    clf = _make_classification(category="SAFE", igrs_rule=rule)

    with patch(
        "app.services.classification.classify_content",
        new_callable=AsyncMock,
        return_value=clf,
    ), patch(
        "app.web.api.classification.views.classify_content",
        new_callable=AsyncMock,
        return_value=clf,
    ):
        url = fastapi_app.url_path_for("classify_content_endpoint")
        payload = {
            "content_id": 10,
            "agent_id": 2,
            "kategori_ai": "SAFE",
            "confidence_score": 0.95,
        }
        response = await client.post(url, json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["category"] == "SAFE"
    assert data["content_id"] == 10
    assert data["igrs_rule"]["kategori_ai"] == "SAFE"


# ---------------------------------------------------------------------------
# Test: POST /api/classification/classify  — UNSAFE content
# ---------------------------------------------------------------------------

async def test_classify_unsafe_content(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """Konten berbahaya harus return 201 dengan category=UNSAFE."""
    rule = _make_igrs_rule(id=2, kategori_ai="Violence", age_rating_minimal="PRC")
    clf = _make_classification(
        classification_id=2,
        content_id=20,
        category="UNSAFE",
        igrs_rule=rule,
    )
    clf.unsafe_reason = "Konten menampilkan kekerasan fisik."

    with patch(
        "app.web.api.classification.views.classify_content",
        new_callable=AsyncMock,
        return_value=clf,
    ):
        url = fastapi_app.url_path_for("classify_content_endpoint")
        payload = {
            "content_id": 20,
            "agent_id": 2,
            "kategori_ai": "Violence",
            "confidence_score": 0.88,
            "unsafe_reason": "Konten menampilkan kekerasan fisik.",
        }
        response = await client.post(url, json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["category"] == "UNSAFE"
    assert data["unsafe_reason"] == "Konten menampilkan kekerasan fisik."


# ---------------------------------------------------------------------------
# Test: POST /api/classification/classify  — kategori tidak dikenal
# ---------------------------------------------------------------------------

async def test_classify_unknown_kategori_returns_422(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """kategori_ai yang tidak ada di igrs_rules harus return 422."""
    from app.web.api.classification.views import classify_content as _svc  # noqa: F401

    with patch(
        "app.web.api.classification.views.classify_content",
        new_callable=AsyncMock,
        side_effect=ValueError("kategori_ai 'Unknown' tidak ditemukan di igrs_rules."),
    ):
        url = fastapi_app.url_path_for("classify_content_endpoint")
        payload = {
            "content_id": 99,
            "agent_id": 1,
            "kategori_ai": "Unknown",
            "confidence_score": 0.5,
        }
        response = await client.post(url, json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "tidak ditemukan" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test: GET /api/classification/{id}  — found
# ---------------------------------------------------------------------------

async def test_get_classification_found(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """GET classification yang ada harus return 200 dengan data lengkap."""
    rule = _make_igrs_rule()
    clf = _make_classification(classification_id=5, igrs_rule=rule)

    with patch(
        "app.web.api.classification.views.get_classification",
        new_callable=AsyncMock,
        return_value=clf,
    ):
        url = fastapi_app.url_path_for("get_classification_endpoint", classification_id=5)
        response = await client.get(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["classification_id"] == 5
    assert data["category"] in ("SAFE", "UNSAFE")


# ---------------------------------------------------------------------------
# Test: GET /api/classification/{id}  — not found
# ---------------------------------------------------------------------------

async def test_get_classification_not_found(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """GET classification yang tidak ada harus return 404."""
    with patch(
        "app.web.api.classification.views.get_classification",
        new_callable=AsyncMock,
        return_value=None,
    ):
        url = fastapi_app.url_path_for(
            "get_classification_endpoint", classification_id=999
        )
        response = await client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Test: GET /api/classification/content/{content_id}
# ---------------------------------------------------------------------------

async def test_get_content_classifications(
    client: AsyncClient,
    fastapi_app: FastAPI,
) -> None:
    """GET classifications untuk satu content harus return list."""
    rule = _make_igrs_rule()
    clfs = [
        _make_classification(classification_id=1, content_id=10, igrs_rule=rule),
        _make_classification(
            classification_id=2, content_id=10, category="UNSAFE", igrs_rule=rule
        ),
    ]

    with patch(
        "app.web.api.classification.views.get_classifications_for_content",
        new_callable=AsyncMock,
        return_value=clfs,
    ):
        url = fastapi_app.url_path_for("get_content_classifications", content_id=10)
        response = await client.get(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


# ---------------------------------------------------------------------------
# Test: unit — _determine_category logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("kategori_ai", "age_rating_minimal", "expected"),
    [
        ("SAFE", "SU", "SAFE"),
        ("Animasi_Ringan", "SU", "SAFE"),
        ("Medical_Ringan", "7+", "SAFE"),
        ("Violence", "PRC", "UNSAFE"),
        ("Pornography_Keras", "PRC", "UNSAFE"),
        ("Weapon_Ringan", "17+", "UNSAFE"),
        ("Toy_Keras", "13+", "UNSAFE"),
    ],
)
def test_determine_category_logic(
    kategori_ai: str,
    age_rating_minimal: str,
    expected: str,
) -> None:
    """_determine_category harus return SAFE/UNSAFE sesuai rule."""
    from app.services.classification import _determine_category  # noqa: PLC0415

    rule = _make_igrs_rule(
        kategori_ai=kategori_ai, age_rating_minimal=age_rating_minimal
    )
    result = _determine_category(rule)
    assert result == expected


# ---------------------------------------------------------------------------
# Test: unit — _safe_category helper di views
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("SAFE", "SAFE"),
        ("UNSAFE", "UNSAFE"),
        (None, "UNSAFE"),       # None → default UNSAFE
        ("REVIEW", "UNSAFE"),   # nilai lama → UNSAFE
        ("", "UNSAFE"),
    ],
)
def test_safe_category_helper(value: str | None, expected: str) -> None:
    """_safe_category harus selalu return Literal['SAFE','UNSAFE']."""
    from app.web.api.classification.views import _safe_category  # noqa: PLC0415

    assert _safe_category(value) == expected
