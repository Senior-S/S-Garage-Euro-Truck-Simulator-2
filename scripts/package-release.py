"""Package the built app, notices, licenses, and pinned tool sources."""
import hashlib
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
version = sys.argv[1]
app = root / "dist/S Garage"
release = root / "release"
release.mkdir(exist_ok=True)
for name in ("LICENSE", "README.md", "START_HERE.txt", "THIRD_PARTY.md"):
    shutil.copy2(root / name, app / name)
licenses = app / "third-party-licenses"
licenses.mkdir(exist_ok=True)
for package in ("react", "react-dom", "scheduler", "three", "lucide-react", "@fontsource/barlow-condensed", "@fontsource/ibm-plex-sans", "@fontsource/ibm-plex-mono"):
    for file in (root / "ui/node_modules" / package).glob("LICENSE*"):
        shutil.copy2(file, licenses / (package.replace("/", "-").replace("@", "") + ".txt"))
for package in ("pillow", "pyinstaller"):
    metadata = distribution(package)
    for file in metadata.files:
        if "license" in file.name.lower() or "copying" in file.name.lower():
            source = Path(metadata.locate_file(file))
            if source.is_file():
                shutil.copy2(source, licenses / f"{package}-{source.name}")
shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
for file in (Path(sys.base_prefix) / "tcl").rglob("license.terms"):
    shutil.copy2(file, licenses / ("Tcl-Tk-" + file.parent.name + ".txt"))
sources = [
    ("ConverterPIX-SGarage", "Senior-S/ConverterPIX-SGarage", "cfdbd60d5654881bb8eb7997fe228e53dc1acbe7"),
    ("SII-Decrypt-cpp", "liam-dong/SII-Decrypt-cpp", "7dd74d79cc0c847be602dc6bb8309f4ecacdbd2a"),
]
archives = []
for name, repository, commit in sources:
    target = release / f"{name}-source-{commit}.zip"
    if not target.is_file():
        with urlopen(f"https://codeload.github.com/{repository}/zip/{commit}") as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)
    archives.append(target)
archive = release / f"S-Garage-v{version}-Windows-x64.zip"
with ZipFile(archive, "w", ZIP_DEFLATED) as output:
    for file in sorted(app.rglob("*")):
        if file.is_file() and file.relative_to(app).parts[0] != "docs":
            output.write(file, file.relative_to(app.parent))
archives.insert(0, archive)
video = release / "S-Garage-demo.mp4"
if video.is_file():
    archives.append(video)
(release / "SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n" for file in archives), encoding="utf-8")
print(f"Built {archive.name} ({archive.stat().st_size / 1024 / 1024:.1f} MB)")
