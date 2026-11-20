"""Library recipes: the reviewed allowlist of system libraries a gap-wheel build may compile and link in.

Some packages' C extensions need a library the pinned build image doesn't have (PyYAML needs libyaml). Installing the
distro's package isn't an option: `dnf install` and `apk add` aren't pinned, and what they fetch changes under the same
image digest. A recipe says instead, for one package on the targets it lists: build this library, at this version,
from this exact source archive (URL and sha256), with these fixed steps, as a static library in a prefix of its own,
and show it to the package's build with these environment variables. gap_wheels.py does the work (build_libraries,
before the package's build, in the same image and run); this file is only the data and how it is looked up, so a new
recipe is a change to RECIPES (and NEEDS) that a maintainer reviews. See README.md, "Adding a recipe".

Nothing here comes from a package, a workflow input or the network: every field is a constant in this file, and a
recipe's sha256 (`digest`) is recorded with each build, so a build run can't claim a recipe other than the one the
coordinator planned.

Each recipe:

- `library`, `version`: what is built, as the site names it ("bundles libyaml 0.2.5 (MIT)").
- `targets`: the lab targets it applies to. A package with recipes but none for a target isn't built there.
- `url`, `sha256`: the source archive. Fetched once per build and checked before it is unpacked.
- `licence`: the library's SPDX expression; it must pass the same OSI check as a package's (gap_wheels.osi_expression).
- `licence_file`, `licence_sha256`: the licence text in the archive, by path under its one top-level folder. It is
  copied into the wheel's `.dist-info/licenses/` (a statically linked MIT library's notice has to ship with it) and
  staging checks it is there with this sha256.
- `steps`: argv lists run in order in the unpacked source folder, with build_env(). `{prefix}` is the only
  substitution. No shell, so no string from anywhere else can become a command.
- `provides`: files the steps must leave under the prefix. A shared library there fails the build: the result must
  be static, so the wheel gains no DT_NEEDED entry and auditwheel has nothing to graft.
- `env`: added to the package's build only (`{prefix}` again). Where the package offers one, a switch that makes a
  missing library a build failure, not a silent fallback to pure Python.
- `import_check`: Python the install test runs in the wheel's fresh venv (`python -I -c`), in a container with no
  compiler and no copy of the library, which must fail unless the library is really in use.
"""

from __future__ import annotations

import re

try:
    from . import build_lab, build_tool_lock
except ImportError:  # executed directly by scripts/gap_wheels.py
    import build_lab
    import build_tool_lock


class RecipeError(ValueError):
    pass


LIBRARY = re.compile(r"[a-z0-9][a-z0-9+._-]{0,49}", re.ASCII)
LIBRARY_VERSION = re.compile(r"[0-9][0-9A-Za-z.+_-]{0,39}", re.ASCII)
SOURCE_URL = re.compile(r"https://[A-Za-z0-9.-]{1,100}/[A-Za-z0-9._~%+/-]{1,300}\.(?:tar\.gz|tar\.xz|tar\.bz2|zip)", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
RELATIVE = re.compile(r"[A-Za-z0-9._+-]{1,100}(?:/[A-Za-z0-9._+-]{1,100}){0,9}", re.ASCII)  # a path inside a folder
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,60}", re.ASCII)
MAX_RECIPES = 5  # for one package

# Packages known to need a system library to build their extension. One listed here is built only where it has a
# recipe (RECIPES); elsewhere the plan skips it and says so, where today it would be built without the library:
# PyYAML then quietly makes a wheel with no compiled code at all, and the others fail partway through a build run.
# Every package in RECIPES is here too (the tests check).
NEEDS: dict[str, str] = {
    "pyyaml": "libyaml",
    "psycopg2": "libpq",
    "mysqlclient": "a MySQL or MariaDB client library",
    "h5py": "HDF5",
}

RECIPES: dict[str, tuple[dict, ...]] = {
    # PyYAML's extension (yaml._yaml, Cython) wraps libyaml. Without yaml.h the build skips it and makes a wheel with
    # no compiled code, which auditwheel rightly refuses. PyYAML's own wheels are built the same way as here: libyaml
    # as a static PIC library (its packaging/build/libyaml.sh), linked into the extension.
    "pyyaml": (
        {
            "library": "libyaml",
            "version": "0.2.5",
            "targets": ["3.14t linux-x86_64", "3.15 linux-x86_64"],
            # The release tarball (with a generated ./configure), as attached to the yaml/libyaml 0.2.5 release. The
            # same bytes as https://pyyaml.org/download/libyaml/yaml-0.2.5.tar.gz, which distros build from.
            "url": "https://github.com/yaml/libyaml/releases/download/0.2.5/yaml-0.2.5.tar.gz",
            "sha256": "c642ae9b75fee120b2d96c712538bd2cf283228d2337df2cf2988e3c02678ef4",
            "licence": "MIT",
            "licence_file": "License",
            "licence_sha256": "c40112449f254b9753045925248313e9270efa36d226b22d82d4cc6c43c57f29",
            "steps": [
                # No -g: nothing of the build's paths goes into the objects, so nothing of them into the extension.
                # --libdir: said outright, so no site default (lib64) moves the library from where `env` points.
                ["./configure", "--prefix={prefix}", "--libdir={prefix}/lib", "--disable-shared", "--enable-static",
                 "--with-pic", "--disable-dependency-tracking", "CFLAGS=-O2 -fPIC"],
                ["make"],
                ["make", "install"],
            ],
            "provides": ["include/yaml.h", "lib/libyaml.a"],
            "env": {
                # gcc reads both: yaml.h for the compile, and for `-lyaml` only libyaml.a is there to find.
                "C_INCLUDE_PATH": "{prefix}/include",
                "LIBRARY_PATH": "{prefix}/lib",
                # setup.py's ext_status(): with this set, a compile or link error is raised, not swallowed.
                "PYYAML_FORCE_LIBYAML": "1",
            },
            "import_check": (
                "import yaml\n"
                "import yaml._yaml\n"
                "assert yaml.__with_libyaml__ is True, 'PyYAML was built without libyaml'\n"
                "assert yaml._yaml.get_version_string() == '0.2.5', yaml._yaml.get_version_string()\n"
                "assert yaml.load('a: [1, two]', Loader=yaml.CSafeLoader) == {'a': [1, 'two']}\n"
                "assert yaml.dump({'a': 1}, Dumper=yaml.CSafeDumper) == 'a: 1\\n'\n"
            ),
        },
    ),
}  # fmt: skip

RECIPE_KEYS = frozenset({"library", "version", "targets", "url", "sha256", "licence", "licence_file",
                         "licence_sha256", "steps", "provides", "env", "import_check"})  # fmt: skip
RECORD_KEYS = frozenset({"library", "version", "url", "sha256", "licence", "licence_sha256", "recipe_sha256"})


def problem(recipe: object) -> str | None:
    """Why a recipe isn't one this file may hold (None if it is). The data is ours, so this is a guard against a
    slip in review, checked by the tests and again before a build uses it."""
    if not isinstance(recipe, dict) or set(recipe) != RECIPE_KEYS:
        return "keys"
    texts = ("library", "version", "url", "sha256", "licence", "licence_file", "licence_sha256", "import_check")
    if not all(isinstance(recipe[k], str) for k in texts):
        return "a field isn't text"
    if not (LIBRARY.fullmatch(recipe["library"]) and LIBRARY_VERSION.fullmatch(recipe["version"])):
        return "library or version"
    if not SOURCE_URL.fullmatch(recipe["url"]) or ".." in recipe["url"]:
        return "url"
    if not (SHA256.fullmatch(recipe["sha256"]) and SHA256.fullmatch(recipe["licence_sha256"])):
        return "sha256"
    if not 0 < len(recipe["licence"]) <= 100:
        return "licence"
    if not RELATIVE.fullmatch(recipe["licence_file"]) or ".." in recipe["licence_file"].split("/"):
        return "licence_file"
    targets = recipe["targets"]
    if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets) or not all(
        t in build_lab.TARGETS for t in targets
    ):
        return "targets"
    steps = recipe["steps"]
    if not isinstance(steps, list) or not 0 < len(steps) <= 20 or not all(
        isinstance(step, list) and step and all(isinstance(a, str) and a and "\0" not in a for a in step)
        for step in steps
    ):
        return "steps"
    provides = recipe["provides"]
    if not isinstance(provides, list) or not provides or not all(
        isinstance(p, str) and RELATIVE.fullmatch(p) and ".." not in p.split("/") for p in provides
    ):
        return "provides"
    env = recipe["env"]
    if not isinstance(env, dict) or not all(
        isinstance(k, str) and ENV_NAME.fullmatch(k) and isinstance(v, str) and "\0" not in v for k, v in env.items()
    ):
        return "env"
    if not 0 < len(recipe["import_check"]) <= 4000:
        return "import_check"
    return None


def digest(recipe: dict) -> str:
    """The sha256 of the whole recipe definition (canonical JSON): any change to a step, a flag, an environment
    variable or the import check changes it."""
    return build_tool_lock.digest(recipe)


def record(recipe: dict) -> dict[str, str]:
    """What a build, the manifest and data/gap-wheels.json record about a recipe: which library, from which source,
    under which licence, and the recipe's own digest."""
    return {"library": recipe["library"], "version": recipe["version"], "url": recipe["url"],
            "sha256": recipe["sha256"], "licence": recipe["licence"], "licence_sha256": recipe["licence_sha256"],
            "recipe_sha256": digest(recipe)}  # fmt: skip


def for_pair(name: str, target: str) -> list[dict]:
    """The package's recipes for a target, in the order they are built; [] when it has none there."""
    return [r for r in RECIPES.get(build_lab.canonical(name), ()) if target in r["targets"]]


def records(name: str, target: str) -> list[dict[str, str]]:
    return [record(r) for r in for_pair(name, target)]


def missing(name: str, target: str) -> str | None:
    """Why a pair can't be built for want of a recipe (None when it needs none, or has one): the package is known to
    need a library and there is no recipe for it on this target."""
    project = build_lab.canonical(name)
    if (project not in NEEDS and project not in RECIPES) or for_pair(name, target):
        return None
    needs = NEEDS.get(project) or ", ".join(sorted({r["library"] for r in RECIPES[project]}))
    return f"needs {needs}, and there is no library recipe for this target"


def licence_member(dist_info: str, rec: dict) -> str:
    """Where a recipe's licence text goes in the wheel: under the .dist-info folder's licenses/ (PEP 639), in a
    folder of its own so it can't collide with one of the package's licence files."""
    return f"{dist_info}/licenses/bundled/{rec['library']}-{rec['version']}/LICENSE"
