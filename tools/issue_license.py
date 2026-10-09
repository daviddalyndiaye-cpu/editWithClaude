"""OWNER ONLY - issue a personal licence file for a YTA Expert member.

The private signing key lives OUTSIDE the repo (default %USERPROFILE%\\.yta_license\\signing_key.pem) and must never be
shared or committed: whoever has it can create licences.

  python tools/issue_license.py init                                    (once: create the signing key, prints the public key)
  python tools/issue_license.py issue "Jane Doe" jane@mail.com [--days 365] [--github janedoe]
        -> licenses/issued/<id>_<name>.key   (send this file to the member; they save it as yta-license.key)
  python tools/issue_license.py revoke <id> [reason]                    (adds the id to licenses/revoked.txt)
  python tools/issue_license.py sync <skool_members.csv> [--days N]
        -> issues a licence for every member email not licensed yet, revokes licences whose email is no longer in the
           export, and writes licenses/issued/to_send.csv (first name, email, licence code) for the new ones.
"""
import base64, datetime as dt, json, os, re, sys, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_DIR = os.path.join(os.path.expanduser("~"), ".yta_license")
PRIV = os.path.join(KEY_DIR, "signing_key.pem")
OUT = os.path.join(ROOT, "licenses", "issued")
LOG = os.path.join(KEY_DIR, "issued_log.csv")


def b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def load_priv():
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(open(PRIV, "rb").read(), password=None)


def init():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if os.path.exists(PRIV):
        sys.exit(f"signing key already exists: {PRIV} (never overwrite it - every issued licence depends on it)")
    os.makedirs(KEY_DIR, exist_ok=True)
    k = Ed25519PrivateKey.generate()
    open(PRIV, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print("private key:", PRIV, "\npublic key :", b64(pub))
    return b64(pub)


def issue(name, member, days=None, github=""):
    lid = uuid.uuid4().hex[:12]
    payload = {"product": "auto-broll-studio", "id": lid, "name": name, "member": member, "github": github,
               "issued": dt.date.today().isoformat(),
               "expires": (dt.date.today() + dt.timedelta(days=days)).isoformat() if days else None,
               "terms": "YTA Expert Community License v1.0 - personal use by this member only. (c) David Daly Ndiaye"}
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = b64(load_priv().sign(body.encode()))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{lid}_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.key")
    open(path, "w", encoding="utf-8").write(body + "." + sig + "\n")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{lid},{name},{member},{github},{payload['issued']},{payload['expires']}\n")
    print("issued:", path)
    return path, body + "." + sig


def revoke(lid, reason=""):
    p = os.path.join(ROOT, "licenses", "revoked.txt")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{lid}  # {dt.date.today()} {reason}\n")
    print("revoked", lid, "- push licenses/revoked.txt so members' copies pick it up on their next update")


def sync(csv_path, days=None):
    import csv
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8-sig")) if (r.get("Email") or "").strip()]
    members = {r["Email"].strip().lower(): r for r in rows}
    issued = {}
    if os.path.exists(LOG):
        for line in open(LOG, encoding="utf-8"):
            f = line.rstrip("\n").split(",")
            if len(f) >= 3:
                issued.setdefault(f[2].strip().lower(), f[0])
    rev_p = os.path.join(ROOT, "licenses", "revoked.txt")
    revoked = {l.split("#")[0].strip() for l in open(rev_p, encoding="utf-8")} if os.path.exists(rev_p) else set()
    new, gone = [], []
    for email, r in members.items():
        if email not in issued or issued[email] in revoked:
            name = f'{r.get("FirstName", "").strip()} {r.get("LastName", "").strip()}'.strip()
            path, code = issue(name, email, days)
            new.append((r.get("FirstName", "").strip(), email, code))
    for email, lid in issued.items():
        if email not in members and lid not in revoked and "@" in email and email != "owner@yta-expert":
            revoke(lid, f"left the community ({email})"); gone.append(email)
    out = os.path.join(OUT, "to_send.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f); w.writerow(["FirstName", "Email", "LicenceCode"]); w.writerows(new)
    print(f"[sync] {len(new)} new licences, {len(gone)} revoked -> {out}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "init":
        init()
    elif a[0] == "issue":
        days = int(a[a.index("--days") + 1]) if "--days" in a else None
        gh = a[a.index("--github") + 1] if "--github" in a else ""
        issue(a[1], a[2], days, gh)
    elif a[0] == "sync":
        sync(a[1], int(a[a.index("--days") + 1]) if "--days" in a else None)
    elif a[0] == "revoke":
        revoke(a[1], " ".join(a[2:]))
