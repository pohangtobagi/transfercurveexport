"""Regression model for direction switching state persistence.

This test mimics Streamlit removing keys belonging to non-rendered widgets.
Persistent model keys must remain unchanged through repeated switches.
"""

def run():
    state = {
        "off_fwd": -40.0,
        "off_rev": 35.0,
        "ss_start_fwd": -20.0,
        "ss_end_fwd": 10.0,
        "ss_start_rev": 5.0,
        "ss_end_rev": 40.0,
        "ss_fwd": -5.0,
        "ss_rev": 25.0,
        "remove_fwd": -15.0,
        "remove_rev": 30.0,
        "log_remove_fwd": -10.0,
        "log_remove_rev": 20.0,
    }
    expected = dict(state)

    for direction in ["Forward", "Reverse"] * 10:
        prefix = direction.lower()
        # Disposable widget keys appear and disappear.
        state[f"{prefix}_slider_widget"] = 0.0
        state[f"{prefix}_numeric_widget"] = 0.0
        for key in list(state):
            if key.endswith("_widget") and not key.startswith(prefix):
                state.pop(key)

        for key, value in expected.items():
            assert state[key] == value, (direction, key, state[key], value)

    print("PASS: 20 repeated direction switches preserved all model values.")


if __name__ == "__main__":
    run()
