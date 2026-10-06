"""Mirror Mozilla's released translation models into a kdchat GitHub release (maintainer tool).

    uv run python tools/mirror_models.py 2026.10            # download, verify, write manifest.json into build/models-2026.10
    uv run python tools/mirror_models.py 2026.10 --upload   # ... and create / fill the GitHub release models-2026.10

Source: the Firefox Translations model registry (MPL-2.0, https://github.com/mozilla/translations). For every language
pair that Firefox ships on desktop (release status "Release" / "Release Desktop") the best architecture is taken
(base > base-memory > tiny). Every model is a direction X -> English or English -> X; kdchat pivots through English.
The release holds the gzip files as Mozilla publishes them (asset name "<pair>__<file>.gz") plus manifest.json with
sizes and SHA-256 sums (of the gzip file and of its content); kdchat downloads from there and checks both.
"""
import argparse, gzip, hashlib, json, os, subprocess, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

REGISTRY = "https://storage.googleapis.com/moz-fx-translations-data--303e-prod-translations-data/db/models.json"
ARCH = {"base": 0, "base-memory": 1, "tiny": 2}
REPO = "kurashizu/kdchat"
KINDS = {"model": "model", "lexicalShortlist": "lex", "vocab": "vocab", "srcVocab": "srcvocab", "trgVocab": "trgvocab"}


def pick(registry):
    out = {}
    for pair, lst in sorted(registry["models"].items()):
        ok = [x for x in lst if x.get("releaseStatus") in ("Release", "Release Desktop")]
        if ok:
            out[pair] = min(ok, key=lambda x: ARCH.get(x["architecture"], 9))
    return out


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--only", nargs="*", help="language pairs (e.g. zh-en en-zh)")
    a = ap.parse_args()
    reg = json.loads(fetch(REGISTRY))
    base = reg["baseUrl"]
    models = pick(reg)
    if a.only:
        models = {k: v for k, v in models.items() if k in a.only}
    out = os.path.join("build", f"models-{a.version}")
    os.makedirs(out, exist_ok=True)
    manifest = {"version": a.version, "tag": f"models-{a.version}",
                "source": "Mozilla Firefox Translations (https://github.com/mozilla/translations), MPL-2.0",
                "registry_generated": reg.get("generated"), "models": {}}

    def one(item):
        pair, x = item
        files = {}
        for kind, f in x["files"].items():
            k = KINDS[kind]
            gz_name = f"{pair}__{os.path.basename(f['path'])}"
            path = os.path.join(out, gz_name)
            if not os.path.exists(path):
                data = fetch(f"{base}/{f['path']}")
                open(path + ".part", "wb").write(data)
                os.replace(path + ".part", path)
            data = open(path, "rb").read()
            raw = gzip.decompress(data)
            if f.get("uncompressedHash"):
                assert hashlib.sha256(raw).hexdigest() == f["uncompressedHash"], (pair, kind)
            files[k] = {"asset": gz_name, "name": os.path.basename(f["path"])[:-3], "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(), "raw_size": len(raw),
                        "raw_sha256": hashlib.sha256(raw).hexdigest()}
        model_name = files["model"]["name"]
        return pair, {"from": x["sourceLanguage"], "to": x["targetLanguage"], "architecture": x["architecture"],
                      "gemm": "int8shiftAll" if model_name.endswith("intgemm8.bin") else "int8shiftAlphaAll",
                      "size": sum(v["size"] for v in files.values()), "files": files}

    with ThreadPoolExecutor(8) as ex:
        for pair, entry in ex.map(one, models.items()):
            manifest["models"][pair] = entry
            print(f"{pair:12s} {entry['architecture']:12s} {entry['size'] / 1e6:6.1f} MB", flush=True)
    total = sum(m["size"] for m in manifest["models"].values())
    print(f"{len(manifest['models'])} models, {total / 1e9:.2f} GB")
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    if a.upload:
        tag = manifest["tag"]
        notes = (f"Translation models for kdchat's translation feature (version {a.version}).\n\n"
                 "Mirrored unchanged from Mozilla's Firefox Translations models (MPL-2.0, "
                 "https://github.com/mozilla/translations; source code of the engine: "
                 "https://github.com/mozilla/translations/tree/main/inference). kdchat downloads only the languages you "
                 "pick; manifest.json lists every file with its size and SHA-256.")
        lic = os.path.join(out, "LICENSE-MPL-2.0.txt")
        if not os.path.exists(lic):
            open(lic, "wb").write(fetch("https://raw.githubusercontent.com/mozilla/translations/main/LICENSE"))
        have = subprocess.run(["gh", "release", "view", tag, "-R", REPO, "--json", "assets", "-q", ".assets[].name"],
                              capture_output=True, text=True)
        if have.returncode != 0:
            subprocess.run(["gh", "release", "create", tag, "-R", REPO, "--title", f"Translation models {a.version}",
                            "--notes", notes, "--latest=false"], check=True)
            names = set()
        else:
            names = set(have.stdout.split())
        files = sorted(n for n in os.listdir(out) if not n.endswith(".part"))
        todo = [n for n in files if n not in names or n == "manifest.json"]
        for i in range(0, len(todo), 20):
            chunk = [os.path.join(out, n) for n in todo[i:i + 20]]
            subprocess.run(["gh", "release", "upload", tag, "-R", REPO, "--clobber"] + chunk, check=True)
            print(f"uploaded {min(i + 20, len(todo))}/{len(todo)}", flush=True)


if __name__ == "__main__":
    main()
