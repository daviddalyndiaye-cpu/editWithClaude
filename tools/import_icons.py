"""Import a sticker pack (transparent PNGs named by concept) into library/icons/ + library/icons/icons.json.

    python tools/import_icons.py <folder>

The renderer pops a sticker in when the narrator says one of its trigger words (see hf_build.auto_icons).
Edit MAP to add or rename; files not in MAP are ignored (backgrounds, bars, blank frames, unclear names).
"""
import json, os, sys
from PIL import Image

# source file stem -> (clean name, trigger words; a trailing * means prefix match, a space means a phrase)
MAP = {
    "1 minute": ("stopwatch", ["minute", "minutes", "seconds"]),
    "1hr": ("clock", ["hour", "hours"]),
    "50 euro": ("cash", ["euros", "euro", "cash"]),
    "150 euro": ("cash-hand", ["paid", "payment*", "salary", "paycheck"]),
    "accelerate": ("rocket-man", ["accelerat*", "faster"]),
    "attract": ("magnet", ["attract*", "magnet*", "leads"]),
    "automate": ("automation", ["automat*", "autopilot"]),
    "balance": ("scales", ["lawsuit*", "court", "legal", "lawyer*"]),
    "bank break": ("piggy-break", ["bankrupt*", "debt", "debts"]),
    "begin": ("launch", ["launch*", "startup", "startups"]),
    "better-health": ("health-heart", ["health", "healthy", "fitness"]),
    "buy": ("buy-cash", ["bought", "purchase", "purchased"]),
    "call": ("phone-call", ["call", "calls", "calling"]),
    "capcut": ("capcut", ["capcut"]),
    "check": ("checklist", ["checklist", "requirements"]),
    "clos": ("closed", ["closed", "shutdown", "shut down"]),
    "coin": ("bitcoin", ["bitcoin", "btc"]),
    "coins": ("coins", ["coins", "pennies", "cents"]),
    "comment": ("comments", ["comment*", "messages"]),
    "company": ("company", ["company", "companies", "corporation*"]),
    "confuse": ("confused", ["confus*", "complicated"]),
    "crwon": ("crown", ["king", "crown", "luxury", "empire"]),
    "crypto": ("crypto", ["crypto*", "blockchain"]),
    "decisn": ("decision", ["decision", "decisions"]),
    "document": ("tax-doc", ["tax", "taxes", "irs"]),
    "ear": ("ear", ["listening", "listen"]),
    "earning": ("money-growth", ["earning*", "income", "profit*", "revenue"]),
    "email": ("email", ["email*", "inbox", "newsletter*"]),
    "emergency": ("warning", ["emergency", "warning", "danger*", "risky"]),
    "expenses": ("expenses", ["expense*", "spending"]),
    "food": ("restaurant", ["food", "restaurant*"]),
    "free": ("free-delivery", ["free shipping", "shipping"]),
    "freedom": ("freedom", ["freedom", "escape"]),
    "games": ("gamepad", ["game", "games", "gaming", "gamer*"]),
    "GIFT": ("gift", ["gift", "gifts", "bonus"]),
    "give": ("donate", ["donat*", "charity"]),
    "grew": ("growth", ["grew", "growth", "skyrocket*"]),
    "habit save": ("savings-jar", ["savings", "saving"]),
    "hadnshk": ("handshake", ["deal", "deals", "partnership*", "agreement", "contract"]),
    "health care": ("healthcare", ["healthcare", "medical", "doctor*", "hospital*"]),
    "heart": ("heart", ["love", "loved", "loves"]),
    "high-five": ("high-five", ["teamwork", "high five"]),
    "home": ("home", ["house", "houses", "mortgage", "real estate"]),
    "ideas": ("ideas", ["idea", "ideas", "creativity"]),
    "insta": ("instagram", ["instagram"]),
    "interview": ("interview", ["interview*", "hiring", "hired"]),
    "invest": ("invest", ["invest", "invested", "investor*", "investing"]),
    "investment": ("investment", ["investment*", "portfolio", "stocks"]),
    "jar": ("money-jar", ["emergency fund", "fund", "funds"]),
    "life-insurance": ("insurance", ["insurance", "insured"]),
    "linkd": ("linkedin", ["linkedin"]),
    "low tax": ("tax-down", ["tax-free", "deduct*", "write-off"]),
    "lucky": ("lucky", ["luck", "lucky"]),
    "money": ("money-hand", ["money", "dollars"]),
    "mouth": ("shout", ["scream*", "shout*", "yell*"]),
    "music": ("music", ["music", "song", "songs"]),
    "no money": ("no-money", ["poor", "poverty", "broke"]),
    "oops": ("oops", ["oops", "mistake", "mistakes"]),
    "pain": ("pain", ["pain", "painful"]),
    "perc": ("percent-up", ["percent", "percentage", "interest"]),
    "phon": ("phone", ["phone", "smartphone", "iphone"]),
    "present": ("presentation", ["presentation*", "pitch", "meeting*"]),
    "q": ("question", ["question", "questions"]),
    "reels": ("reels", ["reels"]),
    "resume": ("resume", ["resume", "cv", "career"]),
    "sad": ("crying", ["sad", "crying", "depress*"]),
    "save money": ("save-money", ["save money", "budget*"]),
    "saving": ("piggy-bank", ["piggy", "savings account"]),
    "scale": ("scale-up", ["scale", "scaling", "scaled"]),
    "search (1)": ("search", ["search*", "google", "googled"]),
    "see": ("eyes", ["notice*", "watching"]),
    "share": ("share", ["share", "shared", "sharing"]),
    "short": ("shorts", ["shorts"]),
    "stop": ("stop-hand", ["quit", "quitting"]),
    "stop (1)": ("stop-sign", ["avoid", "forbidden", "banned"]),
    "strong": ("strong", ["strength", "powerful"]),
    "support": ("support", ["support*"]),
    "teach": ("teacher", ["teach", "teaching", "course", "courses"]),
    "team": ("team", ["employee*", "staff", "workers"]),
    "think": ("thinking", ["think", "thinking", "wonder*"]),
    "tik": ("tiktok", ["tiktok"]),
    "timme": ("hourglass", ["patience", "patient", "long-term"]),
    "track": ("target", ["target*", "goal", "goals"]),
    "trend": ("chart-up", ["trend*", "chart", "statistic*"]),
    "unexpectd": ("surprise", ["unexpected*", "surpris*", "shock*"]),
    "upload": ("upload", ["upload", "uploaded", "uploading"]),
    "video": ("video", ["editing", "edited"]),
    "viral": ("viral", ["viral", "views"]),
    "wave": ("wave", ["hello", "welcome", "goodbye"]),
    "website": ("website", ["website", "websites", "internet"]),
    "wp": ("whatsapp", ["whatsapp"]),
    "wrong": ("cross", ["failure", "failed"]),
    "yt": ("youtube", ["youtube", "subscribe*", "subscribers"]),
    "economy": ("economy", ["economy", "economic*"]),
    "family2": ("family", ["family", "kids", "children", "parents"]),
    "friend": ("friends", ["friend", "friends"]),
    "leader": ("boss", ["ceo", "manager"]),
}


def main(src, dst="library/icons"):
    os.makedirs(dst, exist_ok=True)
    index = []
    for stem, (name, words) in MAP.items():
        f = os.path.join(src, stem + ".png")
        if not os.path.exists(f):
            print("missing", stem)
            continue
        im = Image.open(f).convert("RGBA")
        bb = im.getchannel("A").getbbox()
        if bb:
            im = im.crop(bb)
        im.thumbnail((520, 520))
        im.save(os.path.join(dst, name + ".png"))
        index.append({"file": name + ".png", "words": words})
    json.dump(index, open(os.path.join(dst, "icons.json"), "w"), indent=1)
    print(f"{len(index)} stickers -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:])
