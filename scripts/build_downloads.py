"""Build the release files listed in downloads.toml from the commits they pin.

downloads.toml is EWE's Downloads page config (see ewe_dioxus/downloads.toml.example),
plus one extra key per [[release]], `commit`, naming the git revision that release is
built from - EWE ignores keys it doesn't know, so the same file serves both purposes.
Each file's kind is inferred from its filename:

    *.zip      the YAML source (src/) at that commit
    *.xml.gz   WN-LMF XML, via `ewe-cli export xml`
    *.ttl.gz   RDF/Turtle, via `ewe-cli export rdf --format turtle`
    *.rdf.gz   RDF/XML, via `ewe-cli export rdf --format rdf-xml`

The built files go in `downloads_dir`, which is git-ignored.

The EWE CLI is found via the EWE environment variable: either the `ewe-cli` binary
itself or a checkout of https://github.com/jmccrae/ewe (using its
target/release/ewe-cli). Defaults to `ewe-cli` on the PATH.

Usage:
    uv run scripts/build_downloads.py add VERSION [--commit REV] [--description TEXT]
    uv run scripts/build_downloads.py build [VERSION ...] [--force]
"""

import argparse
import functools
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOWNLOADS_TOML = REPO / "downloads.toml"
SETTINGS_TOML = REPO / "settings.toml"

LANGUAGE = "sga"
# OEWN, which this wordnet is extended from, is CC BY 4.0.
LICENSE = "https://creativecommons.org/licenses/by/4.0/"


@functools.cache
def ewe_cli() -> str:
    ewe = os.environ.get("EWE", "ewe-cli")
    if Path(ewe).is_dir():
        ewe = str(Path(ewe) / "target" / "release" / "ewe-cli")
    if shutil.which(ewe) is None:
        sys.exit(
            f"EWE CLI not found at {ewe!r}; set EWE to the ewe-cli binary "
            "or an ewe checkout with a release build"
        )
    return ewe


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout.strip()


def file_kind(filename: str) -> str:
    for suffix, kind in [
        (".zip", "yaml"),
        (".xml.gz", "xml"),
        (".ttl.gz", "turtle"),
        (".rdf.gz", "rdf-xml"),
    ]:
        if filename.endswith(suffix):
            return kind
    raise ValueError(f"Don't know how to build {filename}")


def release_block(version: str, commit: str, date: str, description: str) -> str:
    name = f"sga-wordnet-{version}"
    return f'''[[release]]
version = "{version}"
commit = "{commit}"
date = "{date}"
description = "{description}"
files = [
    {{ filename = "{name}.zip", format = "YAML source", description = "Full source in YAML format" }},
    {{ filename = "{name}.xml.gz", format = "WN-LMF XML", description = "WordNet LMF XML dump (gzipped)" }},
    {{ filename = "{name}.ttl.gz", format = "RDF/Turtle", description = "RDF Turtle dump (gzipped)" }},
]
'''


def insert_release(toml_text: str, block: str) -> str:
    """Insert `block` before the first [[release]], so releases stay newest first."""
    match = re.search(r"^\[\[release\]\]", toml_text, re.MULTILINE)
    if match is None:
        return toml_text.rstrip("\n") + "\n\n" + block
    return toml_text[: match.start()] + block + "\n" + toml_text[match.start() :]


def add(args: argparse.Namespace) -> None:
    config = tomllib.loads(DOWNLOADS_TOML.read_text())
    if any(r["version"] == args.version for r in config.get("release", [])):
        sys.exit(f"Release {args.version} is already in downloads.toml")
    commit = git("rev-parse", "--verify", f"{args.commit}^{{commit}}")
    date = git("show", "-s", "--format=%cs", commit)
    description = args.description or f"Old Irish Wordnet {args.version}"
    block = release_block(args.version, commit, date, description)
    DOWNLOADS_TOML.write_text(insert_release(DOWNLOADS_TOML.read_text(), block))
    print(f"Added release {args.version} ({commit[:12]}) to downloads.toml")


def export(kind: str, wordnet: Path, out: Path, version: str) -> None:
    settings = tomllib.loads(SETTINGS_TOML.read_text())
    metadata = [
        "--label", settings["project_name"],
        "--language", LANGUAGE,
        "--email", settings["contact_email"],
        "--license", LICENSE,
        "--version", version,
        "--url", settings["source_url"],
    ]  # fmt: skip
    if kind == "xml":
        command = ["export", "xml", "--id-prefix", settings["id_prefix"]]
    else:
        site = settings.get("base_url", settings["source_url"].rstrip("/") + "/")
        command = ["export", "rdf", "--format", kind, "--site", site]
    subprocess.run(
        [ewe_cli(), "--wordnet", str(wordnet), *command, *metadata, str(out)],
        check=True,
    )


def build_release(release: dict, downloads_dir: Path, force: bool) -> None:
    version, commit = release["version"], release.get("commit")
    if commit is None:
        sys.exit(f"Release {version} has no `commit` in downloads.toml")
    todo = [
        f["filename"]
        for f in release.get("files", [])
        if force or not (downloads_dir / f["filename"]).exists()
    ]
    if not todo:
        print(f"Release {version}: up to date")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive = subprocess.run(
            ["git", "archive", commit, "src"], cwd=REPO, check=True, capture_output=True
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive, check=True)
        for filename in todo:
            out = downloads_dir / filename
            kind = file_kind(filename)
            print(f"Release {version}: building {filename}")
            if kind == "yaml":
                prefix = filename.removesuffix(".zip") + "/"
                git("archive", "--format=zip", f"--prefix={prefix}", "-o", str(out),
                    commit, "src")  # fmt: skip
                continue
            plain = tmp / filename.removesuffix(".gz")
            export(kind, tmp / "src" / "yaml", plain, version)
            with open(plain, "rb") as src, gzip.open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def build(args: argparse.Namespace) -> None:
    config = tomllib.loads(DOWNLOADS_TOML.read_text())
    releases = config.get("release", [])
    if args.versions:
        unknown = set(args.versions) - {r["version"] for r in releases}
        if unknown:
            sys.exit(f"Not in downloads.toml: {', '.join(sorted(unknown))}")
        releases = [r for r in releases if r["version"] in args.versions]
    downloads_dir = REPO / config.get("downloads_dir", "downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    for release in releases:
        build_release(release, downloads_dir, args.force)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    subparsers = parser.add_subparsers(required=True)

    add_parser = subparsers.add_parser("add", help="Add a release to downloads.toml")
    add_parser.add_argument("version")
    add_parser.add_argument("--commit", default="HEAD", help="Revision (default HEAD)")
    add_parser.add_argument("--description")
    add_parser.set_defaults(func=add)

    build_parser = subparsers.add_parser("build", help="Build the release files")
    build_parser.add_argument("versions", nargs="*", help="Default: all releases")
    build_parser.add_argument(
        "--force", action="store_true", help="Rebuild files that already exist"
    )
    build_parser.set_defaults(func=build)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
