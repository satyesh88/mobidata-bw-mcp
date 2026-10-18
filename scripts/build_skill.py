"""Build the uploadable mobidata-bw skill archive using only the standard library."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
MEMBER = "mobidata-bw/SKILL.md"


def build(output: Path) -> None:
    content = (ROOT / "skill" / "SKILL.md").read_bytes()
    if not content.startswith(b"---\nname: mobidata-bw\n"):
        raise ValueError("Skill frontmatter must identify mobidata-bw")
    output.parent.mkdir(parents=True, exist_ok=True)
    entry = ZipInfo(MEMBER, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    with ZipFile(output, "w") as archive:
        archive.writestr(entry, content, compress_type=ZIP_DEFLATED, compresslevel=9)
    with ZipFile(output) as archive:
        if archive.namelist() != [MEMBER] or archive.read(MEMBER) != content:
            raise ValueError("Built archive does not match the skill source")
        if archive.testzip() is not None:
            raise ValueError("Built archive failed its integrity check")
    print(f"Built {output} ({output.stat().st_size} bytes)")
    print(f"Contents: {MEMBER}")
    print(f"SHA256: {hashlib.sha256(output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "mobidata-bw.zip")
    build(parser.parse_args().output)
