"""A tiny mort.app, so macOS notifications show "mort" and the ghost instead of Script Editor.

macOS shows the icon of the app that posts a notification, and a script run with osascript posts as
Script Editor. The app is an AppleScript applet built with macOS's own tools (osacompile, sips,
iconutil, codesign). mort appends "subtitle<TAB>message" lines to a queue file and opens the app in
the background; the app shows every queued line, then quits.
"""
import plistlib
import subprocess
import tempfile
from pathlib import Path

from mort import state

ICON = Path(__file__).with_name("icon.png")
LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework"
              "/Support/lsregister")


def app():
    return state.HOME / "mort.app"


def queue():
    return state.HOME / "notify-queue"


def script(queue_path):
    return f'''on run
    set q to "{queue_path}"
    repeat
        set taken to do shell script "f=" & quoted form of q & "; if [ -s \\"$f\\" ]; then mv \\"$f\\" \\"$f.$$\\"; cat \\"$f.$$\\"; rm -f \\"$f.$$\\"; fi"
        if taken is "" then exit repeat
        set AppleScript's text item delimiters to tab
        repeat with ln in paragraphs of taken
            set parts to text items of (ln as text)
            if (count of parts) is 2 then display notification (item 2 of parts) with title "mort" subtitle (item 1 of parts)
        end repeat
        delay 0.3
    end repeat
end run
'''


def build():
    """(Re)build ~/.mort/mort.app. Returns its path."""
    dest = app()
    state.HOME.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mort.applescript"
        src.write_text(script(queue()))
        subprocess.run(["rm", "-rf", str(dest)], check=True)
        subprocess.run(["osacompile", "-o", str(dest), str(src)], check=True, capture_output=True)
        iconset = Path(tmp) / "mort.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(ICON), "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest / "Contents/Resources/applet.icns")],
                       check=True, capture_output=True)
    info = dest / "Contents/Info.plist"
    with open(info, "rb") as f:
        plist = plistlib.load(f)
    plist.update(CFBundleName="mort", CFBundleDisplayName="mort", CFBundleIdentifier="mort.notify",
                 LSUIElement=True)  # no Dock icon while it shows a notice
    # Newer osacompile also writes the stock script icon to Assets.car and names it in
    # CFBundleIconName, which wins over applet.icns; drop both so the ghost is used.
    plist.pop("CFBundleIconName", None)
    (dest / "Contents/Resources/Assets.car").unlink(missing_ok=True)
    with open(info, "wb") as f:
        plistlib.dump(plist, f)
    # Editing Info.plist breaks the applet's signature; an ad-hoc signature makes it valid again.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(dest)], check=True, capture_output=True)
    subprocess.run([LSREGISTER, "-f", str(dest)], capture_output=True)  # so macOS picks up the new icon
    return dest


def post(message, subtitle):
    """Queue a notice for mort.app and open it in the background. False when the app is missing."""
    if not app().exists():
        return False
    clean = lambda t: " ".join(str(t).split())  # tabs and newlines would break the queue format
    with open(queue(), "a") as f:
        f.write(f"{clean(message)}\t{clean(subtitle) or ' '}\n")
    # -n starts a new instance even if one is just quitting, so no queued line is left behind.
    subprocess.run(["open", "-g", "-n", str(app())], capture_output=True)
    return True
