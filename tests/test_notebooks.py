from __future__ import annotations

import json
from pathlib import Path

import jupytext
import nbformat
import pytest

from course_courier.planner import CourierError, create_plan
from course_courier.staging import _pair_comparison_bytes, build, verify


def write_pair(tmp_path: Path, *, synchronized: bool = True) -> tuple[Path, Path, Path]:
    markdown = tmp_path / "lesson.md"
    notebook = tmp_path / "lesson.ipynb"
    authoring = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print('lesson')")])
    jupytext.write(authoring, markdown, fmt="md:myst")
    private = jupytext.read(markdown)
    private.cells[0].execution_count = 7
    private.cells[0].outputs = [nbformat.v4.new_output("stream", name="stdout", text="lesson\n")]
    if not synchronized:
        private.cells[0].source = "print('different')"
    nbformat.write(private, notebook)
    manifest = tmp_path / "PUBLISH.toml"
    manifest.write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                'managed_subtree = "course"',
                "",
                "[[export]]",
                'source = "lesson.ipynb"',
                'destination = "lesson.ipynb"',
                "",
                "[[notebook]]",
                'notebook = "lesson.ipynb"',
                'markdown = "lesson.md"',
            ]
        )
    )
    return manifest, notebook, markdown


def test_build_normalizes_declared_notebook_only_in_staging(tmp_path: Path) -> None:
    manifest, source_notebook, _ = write_pair(tmp_path)
    source_bytes = source_notebook.read_bytes()
    output = tmp_path / "staged"

    inventory = build(manifest, output)

    staged_path = output / "course" / "lesson.ipynb"
    staged = nbformat.read(staged_path, as_version=4)
    assert source_notebook.read_bytes() == source_bytes
    assert staged.cells[0].execution_count is None
    assert staged.cells[0].outputs == []
    rendered = json.loads(inventory.to_json())
    assert rendered["notebook_exports"][0]["destination"] == "course/lesson.ipynb"
    assert rendered["notebook_exports"][0]["sha256"] != create_plan(manifest).exports[0].sha256
    assert verify(manifest, output).to_json() == inventory.to_json()


def test_pair_validation_ignores_jupytext_markdown_representation_metadata(tmp_path: Path) -> None:
    manifest, source_notebook, _ = write_pair(tmp_path)
    notebook = nbformat.read(source_notebook, as_version=4)
    notebook.metadata["jupytext"].pop("text_representation", None)
    nbformat.write(notebook, source_notebook)

    build(manifest, tmp_path / "staged")


def test_pair_comparison_ignores_empty_jupytext_metadata_and_nbformat_minor() -> None:
    markdown_notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell("lesson")])
    markdown_notebook.metadata["jupytext"] = {"text_representation": {"extension": ".md"}}
    markdown_notebook.nbformat_minor = 5
    private_notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell("lesson")])
    private_notebook.nbformat_minor = 6

    assert _pair_comparison_bytes(markdown_notebook) == _pair_comparison_bytes(private_notebook)


def test_build_rejects_out_of_sync_notebook_pair(tmp_path: Path) -> None:
    manifest, _, _ = write_pair(tmp_path, synchronized=False)

    with pytest.raises(CourierError, match="out of sync"):
        build(manifest, tmp_path / "staged")


def test_verify_rejects_changed_normalized_notebook(tmp_path: Path) -> None:
    manifest, _, _ = write_pair(tmp_path)
    output = tmp_path / "staged"
    build(manifest, output)
    staged_path = output / "course" / "lesson.ipynb"
    staged = nbformat.read(staged_path, as_version=4)
    staged.cells[0].source = "print('tampered')"
    nbformat.write(staged, staged_path)

    with pytest.raises(CourierError, match="does not match plan"):
        verify(manifest, output)


@pytest.mark.parametrize(
    ("notebook", "markdown", "message"),
    [
        ("missing.ipynb", "lesson.md", "not an exported source"),
        ("lesson.ipynb", "lesson.txt", "must pair"),
    ],
)
def test_planner_rejects_invalid_notebook_declarations(
    tmp_path: Path, notebook: str, markdown: str, message: str
) -> None:
    manifest, _, _ = write_pair(tmp_path)
    manifest.write_text(
        manifest.read_text()
        .replace('notebook = "lesson.ipynb"', f'notebook = "{notebook}"')
        .replace('markdown = "lesson.md"', f'markdown = "{markdown}"')
    )

    with pytest.raises(CourierError, match=message):
        create_plan(manifest)


def test_planner_rejects_duplicate_notebook_declarations(tmp_path: Path) -> None:
    manifest, _, _ = write_pair(tmp_path)
    manifest.write_text(manifest.read_text() + '\n[[notebook]]\nnotebook = "lesson.ipynb"\nmarkdown = "lesson.md"\n')

    with pytest.raises(CourierError, match="duplicates"):
        create_plan(manifest)


def test_build_rejects_malformed_markdown_source(tmp_path: Path) -> None:
    manifest, _, markdown = write_pair(tmp_path)
    markdown.write_text("---\njupyter: [unclosed\n---\n# lesson\n")

    with pytest.raises(CourierError, match="cannot validate notebook pair"):
        build(manifest, tmp_path / "staged")


def test_build_rejects_malformed_notebook_json(tmp_path: Path) -> None:
    manifest, notebook, _ = write_pair(tmp_path)
    notebook.write_text("{not notebook json")

    with pytest.raises(CourierError, match="cannot validate notebook pair"):
        build(manifest, tmp_path / "staged")


def test_notebook_markdown_transient_diagnostic_names_the_markdown_field(tmp_path: Path) -> None:
    manifest, _, _ = write_pair(tmp_path)
    transient = tmp_path / ".ipynb_checkpoints" / "lesson.md"
    transient.parent.mkdir()
    transient.write_text("transient")
    manifest.write_text(
        manifest.read_text().replace('markdown = "lesson.md"', 'markdown = ".ipynb_checkpoints/lesson.md"')
    )

    with pytest.raises(CourierError, match=r"notebook entry 1.markdown"):
        create_plan(manifest)
