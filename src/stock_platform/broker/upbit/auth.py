from __future__ import annotations

import hashlib
import uuid
from typing import Any, Mapping
from urllib.parse import urlencode

import jwt


def build_query_hash(
    params: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """
    업비트 Query Hash (SHA512).

    GET/POST 쿼리·바디 파라미터를 urlencode 한 뒤 해시한다.
    파라미터가 없으면 (None, None).
    """

    if not params:
        return None, None

    # doseq=True: list 값도 업비트 관례에 맞게 직렬화
    query_string = urlencode(
        [(str(key), str(value)) for key, value in params.items()],
        doseq=True,
    ).encode("utf-8")
    digest = hashlib.sha512(query_string).hexdigest()
    return digest, "SHA512"


def build_jwt_payload(
    *,
    access_key: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JWT 클레임 구성 (시크릿은 포함하지 않음)."""

    if not access_key.strip():
        raise ValueError("access_key is required")

    payload: dict[str, Any] = {
        "access_key": access_key.strip(),
        "nonce": str(uuid.uuid4()),
    }
    query_hash, algorithm = build_query_hash(params)
    if query_hash and algorithm:
        payload["query_hash"] = query_hash
        payload["query_hash_alg"] = algorithm
    return payload


def encode_authorization_token(
    *,
    access_key: str,
    secret_key: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Authorization: Bearer <JWT> 에 넣을 토큰을 발급한다."""

    if not secret_key.strip():
        raise ValueError("secret_key is required")

    payload = build_jwt_payload(
        access_key=access_key,
        params=params,
    )
    token = jwt.encode(
        payload,
        secret_key.strip(),
        algorithm="HS256",
    )
    # PyJWT 구버전은 bytes 반환 가능
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def authorization_header(
    *,
    access_key: str,
    secret_key: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    token = encode_authorization_token(
        access_key=access_key,
        secret_key=secret_key,
        params=params,
    )
    return {"Authorization": f"Bearer {token}"}
