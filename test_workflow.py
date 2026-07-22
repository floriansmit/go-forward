"""Self-check for workflow.approach_commands. Run: python test_workflow.py"""

from workflow import approach_commands


def build(approach, **overrides):
    params = dict(
        source_dir="SRC",
        facies_property="FACIES",
        facies_config="CFG",
        property_profile="reservoir_quality",
        control_spacing="50",
        uber_spacing="25",
    )
    params.update(overrides)
    return approach_commands(approach, **params)


def test_step_counts():
    assert len(build("BestFit")) == 3
    assert len(build("Union")) == 3
    assert len(build("Control")) == 3
    assert len(build("Uber")) == 4
    assert len(build("All")) == 13  # 3 + 3 + 3 + 4, in order


def test_bestfit_starts_with_pointset_builder():
    assert build("BestFit")[0][0] == "scripts/grdecl_to_petrel_pointsets.py"


def test_control_passes_max_vertical_spacing():
    step = build("Control")[0]
    assert "--max-vertical-spacing" in step
    assert step[step.index("--max-vertical-spacing") + 1] == "50"


def test_uber_has_petrel_standard_step():
    assert build("Uber")[3][0] == "scripts/write_petrel_standard_uber_grdecls.py"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK")
