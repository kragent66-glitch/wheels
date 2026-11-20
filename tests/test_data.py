"""Validate the published index and request data, not fixture copies.

Malformed entries are rejected here instead of silently disappearing from the
generated index and human page. This never edits production data files.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
import tempfile
import unittest
from pathlib import Path

from scripts import build_gap_index, gap_wheels

ROOT = Path(__file__).resolve().parents[1] / "data"
WHEELS = ROOT / "gap-wheels.json"
REQUESTS = ROOT / "gap-wheel-requests.json"
OPTOUT = ROOT / "gap-wheels-optout.txt"

ENTRY_KEYS = {
    "name", "version", "target", "wheel", "sha256", "sdist", "sdist_sha256",
    "builds", "licence", "requires_python", "verified", "batch", "published", "publish_run",
}
SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
# A target dropped from PUBLISH_TAGS (say "3.14 win-arm64", later): its wheels stay published until withdrawn.
RETIRED_TARGET = re.compile(r"3\.([0-9]{1,2})(t?) [a-z0-9]+(?:-[a-z0-9_]+)+", re.ASCII)


def run_url(value: object) -> bool:
    """Require the project's own wheel or older tracker Actions run."""
    return (
        isinstance(value, str)
        and gap_wheels.RUN_URL.fullmatch(value) is not None
        and value.startswith(("https://github.com/wheelgap/wheels/actions/runs/",
                              "https://github.com/wheelgap/tracker/actions/runs/"))
    )


def versions(version: str) -> set[str]:
    """The spellings of `version` a wheel or sdist file name may carry, as gap_wheels.wheel_problem accepts them."""
    return {version.lower(), version.lower().replace("-", "_")}


def sdist_ok(sdist: object, project: str, version: str) -> bool:
    """A .tar.gz or .zip named `<project>-<version>` (any spelling of the name, a version spelling wheels may use)."""
    if not isinstance(sdist, str) or not sdist.endswith((".tar.gz", ".zip")):
        return False
    stem = sdist.lower().removesuffix(".tar.gz").removesuffix(".zip")
    return any(stem.endswith(f"-{v}") and build_gap_index.canonical(stem[: -len(v) - 1]) == project
               for v in versions(version))


def target_ok(filename: str, target: object) -> bool:
    """The wheel carries its target's one publishable tag; for a retired target, one plain CPython tag of its version."""
    if not isinstance(target, str):
        return False
    if target in gap_wheels.PUBLISH_TAGS:
        return gap_wheels.tag_ok(filename, target)
    m = RETIRED_TARGET.fullmatch(target)
    parts = filename[: -len(".whl")].split("-")
    if m is None or len(parts) not in (5, 6) or "." in "".join(parts[-3:]):
        return False
    py = f"cp3{m.group(1)}"
    return parts[-3] == py and parts[-2] == py + m.group(2)


def published_date(value: object) -> dt.date | None:
    if not isinstance(value, str) or not DATE.fullmatch(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def validation_errors(data: object, optout: set[str]) -> list[str]:
    """One actionable message per violated rule, identifying the affected wheel."""
    if not isinstance(data, dict) or data.get("schema") != gap_wheels.INDEX_SCHEMA:
        return ["data/gap-wheels.json: invalid index schema"]
    if not isinstance(data.get("wheels"), list):
        return ["data/gap-wheels.json: wheels is not a list"]
    errors: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(data["wheels"]):
        if not isinstance(entry, dict):
            errors.append(f"entry {i}: not a wheel object")
            continue
        filename = entry.get("wheel")
        label = filename if isinstance(filename, str) else f"entry {i}"
        if missing := sorted(ENTRY_KEYS - set(entry)):  # a field added later is fine; one dropped or misspelt isn't
            errors.append(f"{label}: missing {missing}")
        if not build_gap_index.usable(entry):
            errors.append(f"{label}: build_gap_index.usable rejected the entry")
        if not isinstance(filename, str):
            continue
        if filename in seen:
            errors.append(f"{label}: duplicate wheel filename")
        seen.add(filename)

        name, version = entry.get("name"), entry.get("version")
        project = build_gap_index.canonical(name) if isinstance(name, str) else ""
        if not isinstance(name, str) or not project or project in optout:
            errors.append(f"{label}: invalid project or project opted out")
        if not isinstance(version, str):
            errors.append(f"{label}: invalid version")
            continue
        parsed = build_gap_index.wheel_tags(filename)
        if parsed is None or parsed[0] != project or parsed[1] not in versions(version):
            errors.append(f"{label}: wheel filename differs from name or version")
        if not target_ok(filename, entry.get("target")):
            errors.append(f"{label}: filename tag does not match its publish target")
        if not sdist_ok(entry.get("sdist"), project, version):
            errors.append(f"{label}: sdist filename does not match the project and version")
        for key in ("sha256", "sdist_sha256"):
            val = entry.get(key)
            if not isinstance(val, str) or not SHA256.fullmatch(val):
                errors.append(f"{label}: invalid lowercase {key}")

        # Only a wheel built with a library recipe has `recipes`; when it does, it is what publish writes.
        if "recipes" in entry and not gap_wheels.recipe_records_valid(entry["recipes"]):
            errors.append(f"{label}: invalid library recipes")

        builds = entry.get("builds")
        if not isinstance(builds, list) or len(builds) != 2 or not all(run_url(u) for u in builds):
            errors.append(f"{label}: builds must contain exactly two valid project Actions URLs")
        elif builds[0] == builds[1]:
            errors.append(f"{label}: two builds point at the same run")
        for key in ("batch", "publish_run"):
            if not run_url(entry.get(key)):
                errors.append(f"{label}: invalid {key} Actions URL")

        verified, published = published_date(entry.get("verified")), published_date(entry.get("published"))
        if verified is None:
            errors.append(f"{label}: verified must be a YYYY-MM-DD date")
        if published is None:
            errors.append(f"{label}: published must be a YYYY-MM-DD date")
        if verified is not None and published is not None and published < verified:
            errors.append(f"{label}: published date is before verified date")
    return errors


class PublishedData(unittest.TestCase):
    def test_real_wheel_index_is_well_formed(self):
        raw = json.loads(WHEELS.read_text(encoding="utf-8"))
        failures = validation_errors(raw, gap_wheels.opted_out(OPTOUT))
        self.assertEqual(failures, [], "\n".join(failures))

    def test_real_requests_are_never_silently_dropped(self):
        raw = json.loads(REQUESTS.read_text(encoding="utf-8"))
        self.assertIsInstance(raw, dict)
        result = build_gap_index.read_requests(REQUESTS)
        seen: dict[str, str] = {}
        for project in raw:
            canonical = build_gap_index.canonical(project)
            self.assertNotIn(
                canonical, seen, f"{project}: duplicate canonical project name also used by {seen.get(canonical)}"
            )
            seen[canonical] = project
            self.assertIn(
                canonical, result, f"{project}: request was rejected (check by and url fields)"
            )
        self.assertEqual(len(result), len(raw), f"{REQUESTS.name}: request count differs from source")

    def test_bad_request_handle_or_link_is_dropped_by_the_site_parser(self):
        original = {"example": {"by": "u/example", "url": "https://github.com/example"}}
        project = "example"
        for field, bad in (("by", "u/has space"), ("url", "https://evil.example/user")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                damaged = copy.deepcopy(original)
                damaged[project][field] = bad
                copied = Path(folder) / "gap-wheel-requests.json"
                copied.write_text(json.dumps(damaged), encoding="utf-8")
                self.assertNotEqual(len(build_gap_index.read_requests(copied)), len(damaged),
                                    f"{project}: invalid {field} was not rejected")

    def test_mutations_are_rejected_with_the_wheel_named(self):
        data = json.loads(WHEELS.read_text(encoding="utf-8"))
        sample = data["wheels"][0]
        cases = [
            ("missing key", lambda w: w.pop("sdist_sha256")),
            ("unusable", lambda w: w.update(sha256="invalid")),
            ("target", lambda w: w.update(target=next(t for t in gap_wheels.PUBLISH_TAGS if t != w["target"]))),
            ("retired target", lambda w: w.update(target="3.13 linux-riscv64")),
            ("wheel version", lambda w: w.update(wheel=w["wheel"].replace(w["version"], "999", 1))),
            ("sdist", lambda w: w.update(sdist="another-999.zip")),
            ("sdist hash", lambda w: w.update(sdist_sha256="F" * 64)),
            ("duplicate", lambda w: None),
            ("same run", lambda w: w.update(builds=[w["builds"][0]] * 2)),
            ("foreign run", lambda w: w.update(batch="https://github.com/other/repo/actions/runs/1")),
            ("bad date", lambda w: w.update(verified="2026-99-99")),
            ("date order", lambda w: w.update(published="2020-01-01")),
            ("recipes", lambda w: w.update(recipes=[{"library": "libyaml", "version": "0.2.5"}])),
        ]
        for description, mutate in cases:
            with self.subTest(description=description):
                entry = copy.deepcopy(sample)
                mutate(entry)
                changed = {"schema": gap_wheels.INDEX_SCHEMA,
                           "wheels": [entry, copy.deepcopy(entry)] if description == "duplicate" else [entry]}
                errors = validation_errors(changed, set())
                self.assertTrue(errors, description)
                self.assertTrue(any(str(entry["wheel"]) in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
