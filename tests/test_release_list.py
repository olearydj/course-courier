from __future__ import annotations

import json
import stat
import subprocess
from hashlib import sha256
from pathlib import Path

import jupytext
import nbformat
import pytest

from course_courier.planner import CourierError, create_plan
from course_courier.staging import build, verify


def write_config(content_root: Path, *, managed_subtree: str = "course", notebooks: str = "") -> Path:
    manifest = content_root / "PUBLISH.toml"
    manifest.write_text(
        "\n".join(
            [
                "version = 2",
                'release_manifest = "RELEASES.txt"',
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                f'managed_subtree = "{managed_subtree}"',
                notebooks,
            ]
        )
    )
    return manifest


def write_releases(content_root: Path, text: str) -> Path:
    releases = content_root / "RELEASES.txt"
    releases.write_text(text)
    return releases


def write_notebook_markdown(path: Path, code: str = "print('lesson')") -> None:
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(code)])
    jupytext.write(notebook, path, fmt="md:myst")


def test_v2_plan_resolves_files_renames_and_directories(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("license")
    (tmp_path / "notes.md").write_text("notes")
    data = tmp_path / "data"
    (data / "unit1").mkdir(parents=True)
    (data / "unit1" / "b.csv").write_text("b")
    (data / "unit1" / "a.csv").write_text("a")
    (data / "unit1" / ".DS_Store").write_text("junk")
    (data / "unit1" / "draft.tmp").write_text("junk")
    manifest = write_config(tmp_path)
    releases = write_releases(
        tmp_path,
        "# comment\n\nLICENSE\nnotes.md -> handout/notes.md\ndata/ -> shared/\n",
    )

    plan = create_plan(manifest)
    rendered = json.loads(plan.to_json())

    assert rendered["version"] == 2
    assert rendered["release_manifest"] == "RELEASES.txt"
    assert rendered["release_manifest_sha256"] == sha256(releases.read_bytes()).hexdigest()
    assert [entry["destination"] for entry in rendered["exports"]] == [
        "course/LICENSE",
        "course/handout/notes.md",
        "course/shared/unit1/a.csv",
        "course/shared/unit1/b.csv",
    ]
    assert rendered["directory_expansions"] == [{"entry": "data/", "excluded": 2, "resolved": 2}]
    assert rendered["source_tracking"] == "skipped"
    assert rendered["notebook_targets"] == []


def test_v2_rejects_export_and_notebook_tables_and_v1_rejects_v2_fields(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    write_releases(tmp_path, "one.txt\n")
    manifest = write_config(tmp_path)
    manifest.write_text(manifest.read_text() + '\n[[export]]\nsource = "one.txt"\ndestination = "one.txt"\n')
    with pytest.raises(CourierError, match="unknown"):
        create_plan(manifest)

    manifest.write_text(
        "\n".join(
            [
                "version = 1",
                'release_manifest = "RELEASES.txt"',
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                'managed_subtree = "course"',
                "",
                "[[export]]",
                'source = "one.txt"',
                'destination = "one.txt"',
            ]
        )
    )
    with pytest.raises(CourierError, match="unknown"):
        create_plan(manifest)


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        ('release_manifest = "missing.txt"', "not a file"),
        ('release_manifest = "../RELEASES.txt"', "safe relative"),
        ('release_manifest = ""', "non-empty"),
    ],
)
def test_rejects_invalid_release_manifest_settings(tmp_path: Path, configuration: str, message: str) -> None:
    (tmp_path / "one.txt").write_text("one")
    write_releases(tmp_path, "one.txt\n")
    manifest = write_config(tmp_path)
    manifest.write_text(manifest.read_text().replace('release_manifest = "RELEASES.txt"', configuration))

    with pytest.raises(CourierError, match=message):
        create_plan(manifest)


@pytest.mark.parametrize(
    ("roots", "message"),
    [
        ('jupytext_roots = ["."]', "safe relative"),
        ('jupytext_roots = ["missing"]', "not a directory"),
        ('jupytext_roots = ["lectures", "lectures/unit1"]', "overlap"),
        ("jupytext_roots = []", "non-empty"),
    ],
)
def test_rejects_invalid_jupytext_roots(tmp_path: Path, roots: str, message: str) -> None:
    (tmp_path / "lectures" / "unit1").mkdir(parents=True)
    (tmp_path / "one.txt").write_text("one")
    write_releases(tmp_path, "one.txt\n")
    write_config(tmp_path, notebooks=f"\n[notebooks]\n{roots}\n")

    with pytest.raises(CourierError, match=message):
        create_plan(tmp_path / "PUBLISH.toml")


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("LICENSE # note", "inline comments"),
        ("a.txt -> b.txt -> c.txt", "single ` -> `"),
        ("a.txt->b.txt", "single ` -> `"),
        ("a.txt -> ", "single ` -> `"),
        ("a.txt  ->  b.txt", "single ` -> `"),
        ("data/ -> file.txt", "directory to a directory"),
        ("../escape.txt", "safe relative"),
        (".git/config", ".git"),
        ("draft.tmp", "transient"),
        ("slides.pdf -> .ipynb_checkpoints/slides.pdf", "transient"),
        ("assets/ -> scratch.tmp/", "transient"),
    ],
)
def test_rejects_malformed_release_lines_with_line_numbers(tmp_path: Path, line: str, message: str) -> None:
    (tmp_path / "one.txt").write_text("one")
    write_releases(tmp_path, f"one.txt\n{line}\n")
    manifest = write_config(tmp_path)

    with pytest.raises(CourierError, match=message) as error:
        create_plan(manifest)
    assert "RELEASES.txt:2" in str(error.value)


def test_rejects_byte_order_mark_and_accepts_crlf_and_padding(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_config(tmp_path)
    (tmp_path / "RELEASES.txt").write_bytes(b"\xef\xbb\xbfone.txt\n")
    with pytest.raises(CourierError, match="byte-order mark"):
        create_plan(manifest)

    (tmp_path / "RELEASES.txt").write_bytes(b"  one.txt  \r\n# comment\r\n\r\n")
    plan = create_plan(manifest)
    assert [entry.source for entry in plan.exports] == ["one.txt"]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ("one.txt\none.txt", "duplicates the source on line 1"),
        ("data/\ndata/inner.txt", "overlaps the entry on line 1"),
        ("data/\ndata/nested/", "overlaps the entry on line 1"),
    ],
)
def test_rejects_duplicate_and_overlapping_entries(tmp_path: Path, lines: str, message: str) -> None:
    (tmp_path / "one.txt").write_text("one")
    (tmp_path / "data" / "nested").mkdir(parents=True)
    (tmp_path / "data" / "inner.txt").write_text("inner")
    write_releases(tmp_path, lines + "\n")
    manifest = write_config(tmp_path)

    with pytest.raises(CourierError, match=message):
        create_plan(manifest)


def test_rejects_empty_release_list_and_empty_expansion(tmp_path: Path) -> None:
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "# only a comment\n")
    with pytest.raises(CourierError, match="no entries"):
        create_plan(manifest)

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".hidden").write_text("hidden")
    write_releases(tmp_path, "data/\n")
    with pytest.raises(CourierError, match="no publishable files"):
        create_plan(manifest)


def test_expansion_rejects_symlink_members_and_nested_git(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "kept.txt").write_text("kept")
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "data/\n")

    (data / ".git").mkdir()
    with pytest.raises(CourierError, match=r"\.git"):
        create_plan(manifest)
    (data / ".git").rmdir()

    try:
        (data / "link.txt").symlink_to(data / "kept.txt")
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(CourierError, match="symbolic link"):
        create_plan(manifest)


def test_expansion_destinations_collide_case_insensitively_with_explicit_entries(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("explicit")
    data = tmp_path / "data"
    data.mkdir()
    (data / "README.TXT").write_text("expanded")
    write_releases(tmp_path, "readme.txt -> shared/readme.txt\ndata/ -> shared/\n")
    manifest = write_config(tmp_path)

    with pytest.raises(CourierError, match="case-insensitively"):
        create_plan(manifest)


def test_expansion_requires_tracked_members_inside_a_git_work_tree(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "tracked.txt").write_text("tracked")
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "data/\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "data/tracked.txt"], check=True)

    plan = create_plan(manifest)
    assert plan.source_tracking == "verified"

    (data / "untracked.txt").write_text("untracked")
    with pytest.raises(CourierError, match="not tracked by Git"):
        create_plan(manifest)


def test_directly_listed_sources_require_tracking_inside_a_git_work_tree(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "one.txt\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    with pytest.raises(CourierError, match="not tracked by Git"):
        create_plan(manifest)

    subprocess.run(["git", "-C", str(tmp_path), "add", "one.txt"], check=True)
    assert create_plan(manifest).source_tracking == "verified"


def test_generated_notebook_requires_tracked_markdown_but_not_the_private_notebook(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    write_notebook_markdown(lectures / "lesson.md")
    private = jupytext.read(lectures / "lesson.md")
    nbformat.write(private, lectures / "lesson.ipynb")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    with pytest.raises(CourierError, match="not tracked by Git"):
        create_plan(manifest)

    subprocess.run(["git", "-C", str(tmp_path), "add", "lectures/lesson.md"], check=True)
    plan = create_plan(manifest)
    assert plan.source_tracking == "verified"
    assert plan.notebook_targets[0].source_present is True


def test_expansion_excludes_transient_directory_components(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "draft.tmp").mkdir(parents=True)
    (data / "kept.txt").write_text("kept")
    (data / "draft.tmp" / "leaky.txt").write_text("leak")
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "data/\n")

    plan = create_plan(manifest)

    assert [entry.source for entry in plan.exports] == ["data/kept.txt"]
    assert plan.directory_expansions[0].excluded == 1


def test_generated_notebook_builds_without_a_private_notebook(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    write_notebook_markdown(lectures / "lesson.md")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")
    output = tmp_path / "staged"

    inventory = build(manifest, output)

    staged_path = output / "course" / "lectures" / "lesson.ipynb"
    staged = nbformat.read(staged_path, as_version=4)
    assert staged.cells[0].source == "print('lesson')"
    assert staged.cells[0].outputs == []
    assert stat.S_IMODE(staged_path.stat().st_mode) == 0o644
    rendered = json.loads(inventory.to_json())
    assert rendered["notebook_targets"] == [
        {"destination": "course/lectures/lesson.ipynb", "generated": True, "markdown": "lectures/lesson.md"}
    ]
    assert rendered["notebook_exports"][0]["generated"] is True
    assert rendered["notebook_exports"][0]["markdown"] == "lectures/lesson.md"
    assert "source" not in rendered["notebook_exports"][0]
    assert verify(manifest, output).to_json() == inventory.to_json()


def test_generated_notebook_validates_an_existing_private_notebook(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    write_notebook_markdown(lectures / "lesson.md")
    private = jupytext.read(lectures / "lesson.md")
    nbformat.write(private, lectures / "lesson.ipynb")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")

    inventory = build(manifest, tmp_path / "staged")
    rendered = json.loads(inventory.to_json())
    assert rendered["notebook_exports"][0]["source"] == "lectures/lesson.ipynb"

    private.cells[0].source = "print('drifted')"
    nbformat.write(private, lectures / "lesson.ipynb")
    with pytest.raises(CourierError, match="out of sync"):
        build(manifest, tmp_path / "staged-drifted")


def test_notebook_without_markdown_is_normalized_from_the_private_notebook(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print('lesson')")])
    notebook.cells[0].execution_count = 3
    notebook.cells[0].outputs = [nbformat.v4.new_output("stream", name="stdout", text="lesson\n")]
    nbformat.write(notebook, lectures / "lesson.ipynb")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")
    output = tmp_path / "staged"

    inventory = build(manifest, output)

    staged = nbformat.read(output / "course" / "lectures" / "lesson.ipynb", as_version=4)
    assert staged.cells[0].execution_count is None
    assert staged.cells[0].outputs == []
    rendered = json.loads(inventory.to_json())
    assert rendered["notebook_exports"][0]["generated"] is False
    assert rendered["notebook_exports"][0]["source"] == "lectures/lesson.ipynb"


def test_notebook_with_neither_markdown_nor_private_source_fails(tmp_path: Path) -> None:
    (tmp_path / "lectures").mkdir()
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")

    with pytest.raises(CourierError, match="neither a Markdown source nor a private notebook"):
        create_plan(manifest)


def test_notebook_outside_jupytext_roots_is_copied_byte_for_byte(tmp_path: Path) -> None:
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print('raw')")])
    notebook.cells[0].execution_count = 9
    notebook.cells[0].outputs = [nbformat.v4.new_output("stream", name="stdout", text="raw\n")]
    nbformat.write(notebook, tmp_path / "raw.ipynb")
    manifest = write_config(tmp_path)
    write_releases(tmp_path, "raw.ipynb\n")
    output = tmp_path / "staged"

    build(manifest, output)

    staged = output / "course" / "raw.ipynb"
    assert staged.read_bytes() == (tmp_path / "raw.ipynb").read_bytes()


def test_directory_entry_excludes_notebook_material_under_a_root_but_allows_listing_it(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    write_notebook_markdown(lectures / "lesson.md")
    (lectures / "data.csv").write_text("data")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/\nlectures/lesson.ipynb\n")

    plan = create_plan(manifest)

    assert [entry.source for entry in plan.exports] == ["lectures/data.csv"]
    assert plan.directory_expansions[0].excluded == 1
    assert [target.destination for target in plan.notebook_targets] == ["course/lectures/lesson.ipynb"]


def test_verify_detects_markdown_drift_for_a_generated_notebook(tmp_path: Path) -> None:
    lectures = tmp_path / "lectures"
    lectures.mkdir()
    write_notebook_markdown(lectures / "lesson.md")
    manifest = write_config(tmp_path, notebooks='\n[notebooks]\njupytext_roots = ["lectures"]\n')
    write_releases(tmp_path, "lectures/lesson.ipynb\n")
    output = tmp_path / "staged"
    build(manifest, output)

    write_notebook_markdown(lectures / "lesson.md", code="print('rewritten')")

    with pytest.raises(CourierError, match="does not match plan"):
        verify(manifest, output)
