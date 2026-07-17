from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce3.stack import write_parallel_runner, write_runner


def test_parallel_runner_uses_hdf5_validity_check(tmp_path: Path) -> None:
    write_parallel_runner(tmp_path)
    script = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    # A shared validity helper, not a bare -s test.
    assert "is_valid_product" in script
    assert "h5py" in script
    # SKIP still emitted, but now gated on validity.
    assert "SKIP" in script
    assert 'is_valid_product "$out_file"' in script


def test_parallel_runner_skip_not_only_nonempty(tmp_path: Path) -> None:
    """The old SKIP relied solely on `-s "$out_file"`; the RUN/SKIP decision must
    now go through is_valid_product (which itself opens the HDF5)."""
    write_parallel_runner(tmp_path)
    script = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    assert 'if is_valid_product "$out_file" && [ "$out_file" -nt "$cfg" ]; then' in script


def test_serial_runner_has_validity_skip(tmp_path: Path) -> None:
    configs = [tmp_path / "runconfigs" / "20200101_20200113.yaml"]
    write_runner(tmp_path, configs)
    script = (tmp_path / "run_all.sh").read_text(encoding="utf-8")
    assert "is_valid_product" in script
    assert "h5py" in script
    assert "SKIP" in script
    # Extracts the product path from each runconfig to validate it.
    assert "sas_output_file" in script


def test_is_valid_product_helper_reads_root_groups(tmp_path: Path) -> None:
    """Both scripts should reject an HDF5 with zero root groups (corrupt/empty)."""
    for writer, args in ((write_parallel_runner, (tmp_path,)),
                         (write_runner, (tmp_path, []))):
        writer(*args)
    parallel = (tmp_path / "run_parallel.sh").read_text(encoding="utf-8")
    serial = (tmp_path / "run_all.sh").read_text(encoding="utf-8")
    for script in (parallel, serial):
        assert "h5py.File" in script
        assert "len(" in script  # root-group count guard


def test_runners_skip_guarded_on_config_change_by_mtime(tmp_path: Path) -> None:
    """SKIP must also require the product be NEWER than its runconfig (mtime
    guard). Otherwise a config edit (e.g. a toggled stage) leaves the still-valid
    old product in place and the runner would skip it — silently dropping the
    change. `-nt "$cfg"` forces a re-run when the runconfig was touched after the
    product was written, while preserving crash-resume (products stay newer than
    their unchanged cfgs)."""
    write_parallel_runner(tmp_path)
    write_runner(tmp_path, [tmp_path / "runconfigs" / "20200101_20200113.yaml"])
    for name in ("run_parallel.sh", "run_all.sh"):
        script = (tmp_path / name).read_text(encoding="utf-8")
        assert '-nt "$cfg"' in script
