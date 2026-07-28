from openscan_firmware.main import make_version_app


def _response_content(schema: dict, path: str) -> dict:
    return schema["paths"][path]["get"]["responses"]["200"]["content"]


def _assert_binary(content: dict, media_type: str) -> None:
    assert content[media_type]["schema"] == {"type": "string", "format": "binary"}


def test_next_openapi_describes_binary_and_stream_responses() -> None:
    schema = make_version_app("next").openapi()

    preview = _response_content(schema, "/cameras/{camera_name}/preview")
    _assert_binary(preview, "image/jpeg")
    _assert_binary(preview, "multipart/x-mixed-replace")

    photo = _response_content(schema, "/cameras/{camera_name}/photo")
    _assert_binary(photo, "image/jpeg")
    _assert_binary(photo, "application/x-npy")
    assert photo["application/json"]["schema"]["$ref"] == "#/components/schemas/PhotoMetadataResponse"

    photo_payload = _response_content(schema, "/cameras/{camera_name}/photo/payload/{payload_id}")
    _assert_binary(photo_payload, "application/octet-stream")

    thumbnail = _response_content(schema, "/projects/{project_name}/thumbnail")
    _assert_binary(thumbnail, "image/jpeg")

    scan_photo = _response_content(schema, "/projects/{project_name}/{scan_index}/photo")
    _assert_binary(scan_photo, "application/octet-stream")
    assert scan_photo["application/json"]["schema"]["$ref"] == "#/components/schemas/PhotoResponse"

    for path in (
        "/projects/{project_name}/zip",
        "/projects/{project_name}/scans/zip",
        "/projects/{project_name}/model/zip",
        "/logs/archive",
    ):
        _assert_binary(_response_content(schema, path), "application/zip")

    logs = _response_content(schema, "/logs/tail")
    assert logs == {
        "text/plain": {"schema": {"type": "string"}},
        "application/x-ndjson": {"schema": {"type": "string"}},
    }


def test_legacy_openapi_contracts_remain_unchanged() -> None:
    for version in ("0.8", "0.9"):
        schema = make_version_app(version).openapi()
        content = _response_content(schema, "/cameras/{camera_name}/preview")
        assert content == {"application/json": {"schema": {}}}
