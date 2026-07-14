"""The North Star, made legible: one tagline, and every verb in a labelled room."""

from typer.testing import CliRunner

from verivann.cli import _GROUP_OF, app


def test_every_command_and_subapp_is_grouped():
    """No command may sit outside a help panel - a flat wall of 49 verbs is the thing
    this grouping exists to prevent, so a new ungrouped command should fail the build."""
    names = {c.name for c in app.registered_commands} | {g.name for g in app.registered_groups}
    ungrouped = sorted(n for n in names if n not in _GROUP_OF)
    assert ungrouped == [], f"these commands have no help panel: {ungrouped}"


def test_the_group_map_has_no_phantom_entries():
    names = {c.name for c in app.registered_commands} | {g.name for g in app.registered_groups}
    phantom = sorted(n for n in _GROUP_OF if n not in names)
    assert phantom == [], f"the group map names commands that don't exist: {phantom}"


def test_each_command_carries_its_panel():
    for command in app.registered_commands:
        assert command.rich_help_panel == _GROUP_OF[command.name]


def test_help_renders_the_north_star_and_the_panels():
    # Wide terminal so rich doesn't wrap the tagline mid-phrase; collapse whitespace
    # anyway so the assertions don't depend on exact line breaks.
    result = CliRunner().invoke(app, ["--help"], env={"COLUMNS": "200", "TERM": "dumb"})
    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    # the one tagline names what nothing else does
    assert "honest note you own" in flat
    assert "proposal until you accept it" in flat
    # and the rooms are labelled
    assert "Start here" in flat
    assert "Capture" in flat
    assert "Decide" in flat
