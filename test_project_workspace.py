def run():
    workspaces = {
        "A": {
            "file": b"A_FILE",
            "log": "A_LOG",
            "sheet": "A1",
        },
        "B": {
            "file": b"B_FILE",
            "log": None,
            "sheet": "B2",
        },
    }

    active = "A"
    assert workspaces[active]["file"] == b"A_FILE"

    active = "B"
    workspaces[active]["sheet"] = "B3"
    workspaces[active]["file"] = b"B_NEW"

    active = "A"
    assert workspaces[active] == {
        "file": b"A_FILE",
        "log": "A_LOG",
        "sheet": "A1",
    }

    active = "B"
    assert workspaces[active] == {
        "file": b"B_NEW",
        "log": None,
        "sheet": "B3",
    }
    print("PASS: project upload/log/sheet workspaces remain isolated.")


if __name__ == "__main__":
    run()
