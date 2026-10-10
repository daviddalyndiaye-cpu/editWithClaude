"""OWNER ONLY - email every member their personal licence code through Gmail.

Needs two lines in .env (never committed):
    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=abcd efgh ijkl mnop      (a Gmail "App password", not your normal password)

  python tools/send_licenses.py --dry-run     show who would get an email + the first message, send nothing
  python tools/send_licenses.py --test        send ONE sample email to your own GMAIL_ADDRESS
  python tools/send_licenses.py               send to everyone in licenses/issued/to_send.csv

Already-sent addresses are recorded in licenses/issued/sent.csv and skipped on reruns, so it is safe to run again.
"""
import csv, os, smtplib, ssl, sys, time
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TO_SEND = os.path.join(ROOT, "licenses", "issued", "to_send.csv")
SENT = os.path.join(ROOT, "licenses", "issued", "sent.csv")
EXCLUDE_FILE = os.path.join(ROOT, "licenses", "issued", "exclude.txt")   # private: one email per line, never emailed
EXCLUDE = {l.strip().lower() for l in open(EXCLUDE_FILE, encoding="utf-8")} if os.path.exists(EXCLUDE_FILE) else set()
SUBJECT = "Your Auto B-Roll Studio licence (YTA Expert)"


def env():
    vals = {}
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); vals[k.strip()] = v.strip().strip('"')
    return vals


def body(first, code):
    return (f"Hi {first},\n\n"
            "Your personal licence for Auto B-Roll Studio (YTA Expert) is below. Keep it private: it's tied to your name, "
            "and a shared licence gets revoked.\n\n"
            f"YTA-LICENSE: {code}\n\n"
            "To activate it: open Claude in the tool's folder and paste this whole message (or just the line starting with "
            "YTA-LICENSE). Claude installs it and you're ready.\n\n"
            "Reminder: the tool is licensed for your own personal use as a YTA Expert member only. Reselling it or sharing it "
            "outside the community is prohibited.\n\nDavid")


def main():
    args = set(sys.argv[1:])
    rows = list(csv.DictReader(open(TO_SEND, encoding="utf-8")))
    sent = {l.split(",")[0].strip().lower() for l in open(SENT, encoding="utf-8")} if os.path.exists(SENT) else set()
    todo = [r for r in rows if r["Email"].lower() not in EXCLUDE | sent]
    print(f"{len(rows)} licences, {len(sent)} already sent, {len(rows) - len(todo) - len(sent & {r['Email'].lower() for r in rows})} excluded "
          f"-> {len(todo)} to send")
    if "--dry-run" in args:
        if todo:
            print("\n--- first message ---\nTo:", todo[0]["Email"], "\n" + body(todo[0]["FirstName"], todo[0]["LicenceCode"])[:500])
        return
    e = env()
    user, pw = e.get("GMAIL_ADDRESS"), e.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not user or not pw:
        sys.exit("Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to .env first (see the top of this file).")
    if "--test" in args:
        todo = [dict(todo[0] if todo else rows[0], Email=user)]
    try:
        import truststore; truststore.inject_into_ssl()      # use the Windows certificate store (antivirus / proxy certs)
    except ImportError:
        pass
    # port 587 + STARTTLS: port 465 gets cut off on this PC during login
    s = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
    s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
    try:
        s.login(user, pw)
    except smtplib.SMTPAuthenticationError:
        sys.exit("Gmail refused the login: check GMAIL_ADDRESS is the account where you created the App Password, "
                 "and that GMAIL_APP_PASSWORD is the 16-letter app password (not your normal password).")
    for n, r in enumerate(todo, 1):
        m = EmailMessage(); m["From"] = f"David Daly Ndiaye <{user}>"; m["To"] = r["Email"]; m["Subject"] = SUBJECT
        m.set_content(body(r["FirstName"], r["LicenceCode"]))
        try:
            s.send_message(m)
        except smtplib.SMTPException as ex:
            print(f"  FAILED {r['Email']}: {ex}"); continue
        print(f"  [{n}/{len(todo)}] sent to {r['Email']}")
        if "--test" not in args:
            with open(SENT, "a", encoding="utf-8") as f:
                f.write(f"{r['Email']},{time.strftime('%Y-%m-%d %H:%M')}\n")
        time.sleep(3)                                  # gentle pace so Gmail doesn't flag the burst
    s.quit()
    print("done" if "--test" not in args else f"test email sent to {user} - check your inbox, then run without --test")


if __name__ == "__main__":
    main()
