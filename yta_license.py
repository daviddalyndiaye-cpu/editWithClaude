"""YTA Expert member licence check.

Every member receives a personal licence file `yta-license.key`, signed by David Daly Ndiaye with a private key that never
leaves his computer. The tool only runs when a valid file is present: genuine signature, not expired, not revoked.

  python yta_license.py check            -> exit 0 and print the holder if valid, exit 1 with the reason if not
  python yta_license.py install <file|code> -> save a licence (file path or the pasted licence code) and check it

Issuing licences (owner only): tools/issue_license.py
"""
import base64, datetime as dt, json, os, shutil, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(ROOT, "yta-license.key")
REVOKED = os.path.join(ROOT, "licenses", "revoked.txt")
# Public half of David Daly Ndiaye's signing key (verifies licences; cannot create them).
PUBLIC_KEY_B64 = "DwTKprAHP3hLg5efwO48F68K4jnIWHzaFcFrQ3dy1fQ"


class LicenseError(Exception):
    pass


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify(text):
    """Return the licence payload (dict) or raise LicenseError."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        body, sig = text.strip().split(".")
        payload = json.loads(_b64d(body))
    except Exception:
        raise LicenseError("the licence file is damaged or not a YTA Expert licence")
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(PUBLIC_KEY_B64)).verify(_b64d(sig), body.encode())
    except (InvalidSignature, ValueError):
        raise LicenseError("the licence signature is not genuine")
    if payload.get("product") != "auto-broll-studio":
        raise LicenseError("this licence is for another product")
    exp = payload.get("expires")
    if exp and dt.date.fromisoformat(exp) < dt.date.today():
        raise LicenseError(f"the licence expired on {exp} - renew your YTA Expert membership")
    if os.path.exists(REVOKED):
        ids = {l.split("#")[0].strip() for l in open(REVOKED, encoding="utf-8")}
        if payload.get("id") in ids:
            raise LicenseError("this licence has been revoked")
    return payload


def check(path=KEY_FILE):
    if not os.path.exists(path):
        raise LicenseError("no licence file found (yta-license.key). YTA Expert members: ask for your personal licence file")
    return verify(open(path, encoding="utf-8").read())


def require():
    """Called on import by the studio and app packages: stop everything without a valid licence."""
    if os.environ.get("_YTA_LICENSE_OK") == "1":
        return
    try:
        p = check()
    except LicenseError as e:
        sys.stderr.write("\n[LICENSE] Auto B-Roll Studio will not run: " + str(e) + ".\n"
                         "[LICENSE] Licensed only to active YTA Expert members (see LICENSE). (c) David Daly Ndiaye\n\n")
        raise SystemExit(3)
    os.environ["_YTA_LICENSE_OK"] = "1"          # child processes (renders etc.) inherit the result
    return p


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    try:
        if cmd == "install":
            # accepts a .key file OR the licence code itself (the one-line text members receive by email / DM)
            src = " ".join(sys.argv[2:]).strip().strip('"')
            text = open(src, encoding="utf-8").read() if os.path.exists(src) else src
            import re
            m = re.search(r"[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{40,}", text)      # find the code inside a pasted message
            text = m.group(0) if m else text.replace("YTA-LICENSE:", "").strip()
            p = verify(text)
            open(KEY_FILE, "w", encoding="utf-8").write(text.strip() + "\n")
        else:
            p = check()
        print(f"LICENSE OK - {p.get('name')} ({p.get('member')}), licence {p.get('id')}, "
              f"valid until {p.get('expires') or 'no expiry'}")
    except LicenseError as e:
        print("LICENSE INVALID - " + str(e))
        sys.exit(1)
