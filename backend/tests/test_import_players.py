"""Excel / CSV 选手批量导入测试。"""

import io

from openpyxl import Workbook


def _create(client, group_count=4):
    tid = client.post(
        "/api/tournaments",
        json={"name": "导入测试", "date": "2025-06-01", "table_count": 6, "group_count": group_count, "qualify_per_group": 2},
    ).json()["id"]
    return tid


def test_import_csv_basic(client):
    tid = _create(client)
    csv_content = (
        "姓名,学院/单位,种子序号\n"
        "选手01,A学院,1\n"
        "选手02,B学院,2\n"
        "选手03,C学院,\n"
    ).encode("utf-8")
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("players.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 3
    assert data["imported"] == 3
    assert data["skipped"] == 0
    assert data["errors"] == []

    players = client.get(f"/api/tournaments/{tid}/players").json()
    assert len(players) == 3
    by_name = {p["name"]: p for p in players}
    assert by_name["选手01"]["seed_no"] == 1
    assert by_name["选手01"]["college"] == "A学院"
    assert by_name["选手02"]["seed_no"] == 2
    assert by_name["选手03"]["seed_no"] is None


def test_import_csv_with_bom_and_trim(client):
    tid = _create(client)
    csv_content = "姓名,学院,种子\n 张三 ,计算机学院,1\n李四,自动化学院,\n".encode("utf-8-sig")
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("名单.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 2
    players = client.get(f"/api/tournaments/{tid}/players").json()
    names = {p["name"]: p for p in players}
    assert "张三" in names  # 前后空格已 trim
    assert names["张三"]["seed_no"] == 1


def test_import_csv_gbk_and_gb18030(client):
    tid = _create(client)
    for filename, encoding, name in [
        ("gbk.csv", "gbk", "王五"),
        ("gb18030.csv", "gb18030", "赵六"),
    ]:
        content = f"姓名,学院\n{name},信息学院\n".encode(encoding)
        resp = client.post(
            f"/api/tournaments/{tid}/players/import",
            files={"file": (filename, content, "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1


def test_import_csv_invalid_encoding_has_actionable_hint(client):
    tid = _create(client)
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("broken.csv", b"\xff\xfe\x80\x81", "text/csv")},
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.json()["detail"]


def test_import_csv_english_headers(client):
    tid = _create(client)
    csv_content = "name,college,seed_no\n选手01,计算机学院,1\n".encode("utf-8")
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("p.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


def test_import_xlsx_chinese(client):
    tid = _create(client)
    wb = Workbook()
    ws = wb.active
    ws.append(["姓名", "学院/单位", "种子序号"])
    ws.append(["选手01", "计算机学院", 1])
    ws.append(["选手02", "自动化学院", 2])
    ws.append(["选手03", "机械学院", None])
    buf = io.BytesIO()
    wb.save(buf)
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("名单.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 3
    players = client.get(f"/api/tournaments/{tid}/players").json()
    assert len(players) == 3
    assert players[0]["name"] == "选手01" and players[0]["seed_no"] == 1


def test_import_missing_name_column_400(client):
    tid = _create(client)
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("p.csv", "学院,学号\nA学院,1001\n".encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 400
    assert "姓名" in resp.json()["detail"]


def test_import_after_group_stage_409(client):
    tid = _create(client)
    for i in range(1, 5):
        client.post(f"/api/tournaments/{tid}/players", json={"name": f"选手{i}"})
    client.post(f"/api/tournaments/{tid}/auto-group")
    client.post(f"/api/tournaments/{tid}/generate-group-matches")
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("p.csv", "姓名\n新选手\n".encode("utf-8"), "text/csv")},
    )
    assert resp.status_code == 409


def test_import_partial_errors(client):
    tid = _create(client, group_count=4)
    csv_content = (
        "姓名,学院/单位,种子序号\n"
        "选手01,A学院,1\n"
        "选手02,B学院,1\n"  # 重复种子：导入但种子不生效
        ",C学院,\n"          # 姓名为空（有内容）：跳过
        "选手03,C学院,abc\n"  # 种子格式错误：导入但种子不生效
    ).encode("utf-8")
    resp = client.post(
        f"/api/tournaments/{tid}/players/import",
        files={"file": ("p.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 4
    assert data["imported"] == 3
    assert data["skipped"] == 1
    assert len(data["errors"]) == 3
    players = client.get(f"/api/tournaments/{tid}/players").json()
    assert len(players) == 3
    by_name = {p["name"]: p for p in players}
    assert by_name["选手02"]["seed_no"] is None  # 重复种子不生效
    assert by_name["选手03"]["seed_no"] is None  # 格式错误不生效
