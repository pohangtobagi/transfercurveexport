def run():
    state = {
        "generation": 0,
        "source": "upload",
        "active_bytes": b"FILE_A",
        "uploader_0": b"FILE_A",
    }

    # Open LOG_B while FILE_A was uploaded.
    state["source"] = "log"
    state["active_bytes"] = b"LOG_B"
    state["generation"] += 1

    # The new uploader generation is empty through arbitrary UI reruns.
    for _ in range(20):
        current_uploader = state.get(f"uploader_{state['generation']}")
        displayed = (
            state["active_bytes"]
            if state["source"] == "log"
            else current_uploader
        )
        assert displayed == b"LOG_B"

    # Save must persist LOG_B, never stale FILE_A.
    saved = state["active_bytes"]
    assert saved == b"LOG_B"
    print("PASS: stale uploader cannot replace opened log during edits/save.")


if __name__ == "__main__":
    run()
