"""Create or update a facies configuration by scanning source GRDECL files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from grdecl_utils import tokenize_grdecl


PALETTE = (
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
)


def expand_integer_values(tokens: list[str], path: Path, property_name: str) -> list[int]:
    """Expand GRDECL repeat notation such as ``120*8`` to integer facies codes."""
    values: list[int] = []
    for token in tokens:
        count = 1
        value = token
        if "*" in token:
            count_text, value = token.split("*", 1)
            count = int(count_text)
        number = float(value)
        if not number.is_integer():
            raise ValueError(f"{path.name}: {property_name} contains non-integer value {token!r}")
        values.extend([int(number)] * count)
    return values


def scan_facies(grdecl_dir: Path, property_name: str) -> tuple[Counter[int], dict[int, list[str]]]:
    files = sorted(path for path in grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not files:
        raise ValueError(f"No GRDECL files found in {grdecl_dir}")
    counts: Counter[int] = Counter()
    occurrences: dict[int, list[str]] = {}
    for path in files:
        try:
            tokens = tokenize_grdecl(path, {property_name})[property_name]
        except KeyError as exc:
            raise ValueError(f"{path.name}: facies property {property_name!r} was not found") from exc
        values = expand_integer_values(tokens, path, property_name)
        counts.update(values)
        for code in set(values):
            occurrences.setdefault(code, []).append(path.name)
    return counts, occurrences


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def ask(prompt: str, default: str) -> str:
    return input(f"{prompt} [{default}]: ").strip() or default


def ask_yes_no(prompt: str, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} ({default_text}): ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please enter y or n.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan GRDECL facies codes and create a portable project facies_config.json.")
    parser.add_argument("--grdecl-dir", type=Path, required=True, help="Folder containing one or more .grdecl files.")
    parser.add_argument("--property", default="Facies", help="Case-sensitive GRDECL facies keyword.")
    parser.add_argument("--config", type=Path, help="Configuration to write. Defaults to <grdecl-dir>/facies_config.json.")
    parser.add_argument("--redefine", action="store_true", help="Prompt again for every code found, including existing codes.")
    parser.add_argument("--replace", action="store_true", help="Discard definitions for codes absent from this source folder.")
    parser.add_argument("--non-interactive", action="store_true", help="Create placeholder names and colours without prompts.")
    args = parser.parse_args()

    args.grdecl_dir = args.grdecl_dir.resolve()
    config_path = (args.config or args.grdecl_dir / "facies_config.json").resolve()
    counts, occurrences = scan_facies(args.grdecl_dir, args.property)
    existing = load_config(config_path)
    old_names = {str(k): str(v) for k, v in existing.get("facies_names", {}).items()}
    old_colors = {str(k): str(v) for k, v in existing.get("facies_colors", {}).items()}
    old_metadata = existing.get("facies_metadata", {})
    observed = sorted(counts)

    print(f"Found {len(observed)} facies code(s) in {args.grdecl_dir} using {args.property!r}:")
    for code in observed:
        print(f"  {code}: {counts[code]} cells across {len(occurrences[code])} file(s)")

    names = {} if args.replace else old_names.copy()
    colors = {} if args.replace else old_colors.copy()
    metadata = {} if args.replace else old_metadata.copy()
    for position, code in enumerate(observed):
        key = str(code)
        if key in names and not args.redefine:
            continue
        previous = metadata.get(key, {}) if isinstance(metadata.get(key), dict) else {}
        default_name = names.get(key, f"Facies {code}")
        default_color = colors.get(key, PALETTE[position % len(PALETTE)])
        default_category = str(previous.get("category", "reservoir" if code != 0 else "non_reservoir"))
        default_tmap = bool(previous.get("tmap_enabled", code != 0))
        print(f"\nFacies {code}: {counts[code]} cells; present in {', '.join(occurrences[code])}")
        if args.non_interactive:
            name, color, category, tmap_enabled = default_name, default_color, default_category, default_tmap
        else:
            name = ask("  Geological name", default_name)
            color = ask("  Display colour (#RRGGBB)", default_color)
            category = ask("  Category (for example reservoir or non_reservoir)", default_category)
            tmap_enabled = ask_yes_no("  Include this facies in future T>Map hand-offs", default_tmap)
        names[key] = name
        colors[key] = color
        metadata[key] = {"category": category, "tmap_enabled": tmap_enabled}

    if args.replace:
        keep = {str(code) for code in observed}
        names = {key: value for key, value in names.items() if key in keep}
        colors = {key: value for key, value in colors.items() if key in keep}
        metadata = {key: value for key, value in metadata.items() if key in keep}

    payload = {
        "facies_property": args.property,
        "source_grdecl_directory": str(args.grdecl_dir),
        "generated_on": date.today().isoformat(),
        "facies_names": dict(sorted(names.items(), key=lambda item: int(item[0]))),
        "facies_colors": dict(sorted(colors.items(), key=lambda item: int(item[0]))),
        "facies_metadata": dict(sorted(metadata.items(), key=lambda item: int(item[0]))),
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {config_path}")


if __name__ == "__main__":
    main()
