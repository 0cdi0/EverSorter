#!/usr/bin/env python3
"""
organize_retro_roms.py
macOS: find locally owned dumps of the listed classics and copy them
into a Nintendo / Sega folder tree.

Does NOT download games. Point --src at folders that already contain
your dumps (.nes, .gb, .gbc, .gba, .sfc, .smc, .gg, .sms, .md, …).
Zipped dumps are supported too: the script looks inside every .zip it
finds and matches on the actual rom files it contains, extracting only
the matched rom (not the whole archive) into the destination folder.

Usage:
  chmod +x organize_retro_roms.py
  ./organize_retro_roms.py --src ~/Roms --dest ~/EverSD_staging

  # dry run first (recommended)
  ./organize_retro_roms.py --src ~/Roms --dest ~/EverSD_staging --dry-run
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import zipfile
from pathlib import Path

EXTS = {
    "NES": {".nes", ".fc", ".fds"},
    "GB": {".gb"},
    "GBC": {".gbc"},
    "GBA": {".gba", ".agb"},
    "SNES": {".sfc", ".smc", ".fig", ".swc"},
    "GameGear": {".gg"},
    "MasterSystem": {".sms"},
    "MegaDrive": {".md", ".gen", ".smd"},
}

# Each entry: (folder under dest, display title, extra filename needles)
# Needles are extra tokens that help disambiguate dumps.
GAMES = {
    "Nintendo/NES": [
        "Super Mario Bros. 3",
        "The Legend of Zelda",
        "Metroid",
        "Mega Man 2",
        "Castlevania",
        "Punch-Out!!",
        "Tetris",
        "Contra",
        "Super Mario Bros.",
        "Kirby's Adventure",
    ],
    "Nintendo/GB": [
        "Tetris",
        "Super Mario Land 2",
        "The Legend of Zelda: Link's Awakening",
        "Pokemon Red",
        "Pokemon Blue",
        "Metroid II",
        "Kirby's Dream Land",
        "Donkey Kong",
        "Final Fantasy Adventure",
        "Wario Land",
        "Kid Dracula",
        "Gargoyle's Quest",
    ],
    "Nintendo/GBC": [
        "Pokemon Gold",
        "Pokemon Silver",
        "Pokemon Crystal",
        "Oracle of Seasons",
        "Oracle of Ages",
        "Wario Land 3",
        "Pokemon Pinball",
        "Shantae",
        "Metal Gear Solid",
        "Mario Tennis",
        "Dragon Warrior III",
        "Harvest Moon",
        "Bionic Commando",
    ],
    "Nintendo/GBA": [
        "The Minish Cap",
        "Metroid Fusion",
        "Metroid Zero Mission",
        "Advance Wars",
        "Fire Emblem",
        "Pokemon Emerald",
        "Pokemon FireRed",
        "Mario Kart Super Circuit",
        "Aria of Sorrow",
        "Golden Sun",
        "Super Mario World",
        "Super Mario Advance 2",
    ],
    "Nintendo/SNES": [
        "Super Mario World",
        "A Link to the Past",
        "Super Metroid",
        "Chrono Trigger",
        "Super Mario Kart",
        "Donkey Kong Country",
        "Street Fighter II",
        "Final Fantasy VI",
        "Final Fantasy III",  # JP title of FF6
        "Super Punch-Out!!",
        "EarthBound",
        "Secret of Mana",
    ],
    "Sega/GameGear": [
        "Sonic the Hedgehog",
        "Sonic Chaos",
        "Shining Force II",
        "Shinobi",
        "Streets of Rage",
        "Columns",
        "Land of Illusion",
        "Gunstar Heroes",
        "Tails Adventure",
    ],
    "Sega/MasterSystem": [
        "Sonic the Hedgehog",
        "Wonder Boy III",
        "The Dragon's Trap",
        "Phantasy Star",
        "Master of Darkness",
        "Alex Kidd",
        "Psycho Fox",
        "Wonder Boy in Monster Land",
        "R-Type",
        "Out Run",
        "Land of Illusion",
    ],
    "Sega/MegaDrive": [
        "Sonic the Hedgehog 2",
        "Sonic 3",
        "Sonic & Knuckles",
        "Streets of Rage 2",
        "Gunstar Heroes",
        "Phantasy Star IV",
        "Shining Force II",
        "Thunder Force IV",
        "The Wily Wars",
        "Bloodlines",
        "NHL 94",
        "NHL '94",
        "Super Street Fighter II",
    ],
}

STOP = {
    "the", "of", "a", "an", "and", "in", "ii", "iii", "iv", "2", "3",
}

# Preferred region, best first. Used only to break ties between dumps of the
# same game (e.g. picking a (Europe) dump over a (USA) one when both match
# a title equally well). Edit this list to change the preference.
REGION_ORDER = ["europe", "world", "usa", "japan"]


class RomCandidate:
    """A rom file, either sitting on disk directly or inside (possibly nested) zips.

    Romsets are often distributed as one zip per system where every game is
    itself a separate zip archive (e.g. "Nintendo - Game Boy Advance.zip" ->
    "Golden Sun (USA).zip" -> "Golden Sun (USA).gba"). member_chain records
    the full path of zip entry names needed to reach the actual rom file.
    """

    __slots__ = ("display_name", "suffix", "path", "source_zip", "member_chain")

    def __init__(self, path: Path):
        self.display_name = path.name
        self.suffix = path.suffix.lower()
        self.path = path
        self.source_zip: Path | None = None
        self.member_chain: list[str] | None = None

    @classmethod
    def from_zip_chain(cls, zip_path: Path, member_chain: list[str]) -> "RomCandidate":
        self = cls.__new__(cls)
        self.display_name = Path(member_chain[-1]).name
        self.suffix = Path(member_chain[-1]).suffix.lower()
        self.path = None
        self.source_zip = zip_path
        self.member_chain = member_chain
        return self

    def describe(self) -> str:
        if self.source_zip is not None:
            return f"{self.source_zip} :: " + " :: ".join(self.member_chain)
        return str(self.path)

    def _read_bytes(self) -> bytes:
        with zipfile.ZipFile(self.source_zip) as zf:
            data = zf.read(self.member_chain[0])
        for name in self.member_chain[1:]:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                data = zf.read(name)
        return data

    def copy_to(self, out_dir: Path, dry_run: bool) -> Path:
        out = out_dir / self.display_name
        if dry_run:
            return out
        out_dir.mkdir(parents=True, exist_ok=True)
        if self.source_zip is not None:
            out.write_bytes(self._read_bytes())
        elif self.path.resolve() != out.resolve():
            shutil.copy2(self.path, out)
        return out


def norm(s: str) -> str:
    s = s.lower()
    s = s.replace("&", " and ")
    s = s.replace("pokemon", "pokemon")
    s = s.replace("pokémon", "pokemon")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(title: str) -> list[str]:
    parts = [t for t in norm(title).split() if t and t not in STOP]
    return parts or norm(title).split()


def score(filename: str, title: str) -> int:
    """Higher is better. 0 = no match."""
    fn = norm(Path(filename).stem)
    title_n = norm(title)
    toks = tokens(title)
    if not toks:
        return 0
    if title_n and title_n in fn:
        return 100 + len(title_n)
    if all(t in fn for t in toks):
        return 50 + sum(len(t) for t in toks)
    # allow 1 missing token for long titles
    hits = sum(1 for t in toks if t in fn)
    if len(toks) >= 3 and hits >= len(toks) - 1:
        return 20 + hits * 5
    return 0


def region_priority(filename: str) -> int:
    """Lower is more preferred. Reads (Region) style tags in the filename."""
    tags = re.findall(r"\(([^)]*)\)", filename.lower())
    best = len(REGION_ORDER)
    for tag in tags:
        for rank, region in enumerate(REGION_ORDER):
            if region in tag:
                best = min(best, rank)
    return best


MAX_ZIP_NESTING = 4


def _scan_zip(
    zf: zipfile.ZipFile,
    zip_path: Path,
    wanted: set[str],
    candidates: list[RomCandidate],
    chain: list[str],
    depth: int,
) -> None:
    if depth > MAX_ZIP_NESTING:
        print(f"  WARN  Zip nested too deep, stopping: {zip_path} :: {' :: '.join(chain)}", file=sys.stderr)
        return
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        new_chain = chain + [name]
        suffix = Path(name).suffix.lower()
        if suffix in wanted:
            candidates.append(RomCandidate.from_zip_chain(zip_path, new_chain))
        elif suffix == ".zip":
            try:
                data = zf.read(name)
                with zipfile.ZipFile(io.BytesIO(data)) as nested_zf:
                    _scan_zip(nested_zf, zip_path, wanted, candidates, new_chain, depth + 1)
            except (zipfile.BadZipFile, KeyError, RuntimeError, OSError):
                print(f"  WARN  Skipping corrupt zip entry: {zip_path} :: {' :: '.join(new_chain)}", file=sys.stderr)


def collect_roms(src: Path) -> list[RomCandidate]:
    wanted = set().union(*EXTS.values())
    candidates: list[RomCandidate] = []
    for p in src.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in wanted:
            candidates.append(RomCandidate(p))
        elif p.suffix.lower() == ".zip":
            print(f"  scanning {p.name} …")
            try:
                with zipfile.ZipFile(p) as zf:
                    _scan_zip(zf, p, wanted, candidates, [], 0)
            except zipfile.BadZipFile:
                print(f"  WARN  Skipping corrupt zip: {p}", file=sys.stderr)
    return candidates


def system_key(dest_rel: str) -> str:
    return dest_rel.split("/")[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy listed retro dumps into a folder tree.")
    ap.add_argument("--src", required=True, type=Path, help="Folder to search (your dump library)")
    ap.add_argument("--dest", required=True, type=Path, help="Destination root")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only")
    ap.add_argument("--min-score", type=int, default=20, help="Minimum match score (default 20)")
    args = ap.parse_args()

    src = args.src.expanduser().resolve()
    dest = args.dest.expanduser().resolve()
    if not src.is_dir():
        print(f"Source not found: {src}", file=sys.stderr)
        return 1

    print(f"Scanning {src} …")
    roms = collect_roms(src)
    print(f"Found {len(roms)} candidate files (including zipped roms).\n")

    # create tree
    for rel in GAMES:
        target = dest / rel
        if not args.dry_run:
            target.mkdir(parents=True, exist_ok=True)

    missing: list[tuple[str, str]] = []
    copied = 0

    for rel, titles in GAMES.items():
        sysname = system_key(rel)
        allowed = EXTS[sysname]
        pool = [c for c in roms if c.suffix in allowed]
        print(f"== {rel} ({len(pool)} files with right extension) ==")
        used: set[RomCandidate] = set()
        for title in titles:
            best_key: tuple[int, int] | None = None
            best_c: RomCandidate | None = None
            for c in pool:
                if c in used:
                    continue
                sc = score(c.display_name, title)
                if sc < args.min_score:
                    continue
                # Higher score wins; among ties, lower region_priority (more
                # preferred region) wins - hence the negation.
                key = (sc, -region_priority(c.display_name))
                if best_key is None or key > best_key:
                    best_key = key
                    best_c = c
            if best_c is None:
                print(f"  MISS  {title}")
                missing.append((rel, title))
                continue
            sc, c = best_key[0], best_c
            used.add(c)
            out_dir = dest / rel
            out = out_dir / c.display_name
            print(f"  COPY  {title}")
            print(f"        {c.describe()}  ->  {out}  (score {sc})")
            c.copy_to(out_dir, args.dry_run)
            copied += 1
        print()

    print(f"{'Would copy' if args.dry_run else 'Copied'}: {copied} files")
    print(f"Missing: {len(missing)}")
    if missing:
        print("\nNot found (dump may use another name, or you do not have it):")
        for rel, title in missing:
            print(f"  [{rel}] {title}")
    print(
        "\nNext: point EverLoader3 at the dest folders (or drag the copied ROMs in).\n"
        "This script never fetches games from the network."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
