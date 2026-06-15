"""Phase 0: device-code sign-in to the user's OneDrive + a quick Graph smoke test.
Prints the user code, waits for sign-in, then creates the folder, uploads a test
file, lists it, and saves the refresh token. Run in the background."""
import httpx, time, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"  # Microsoft Graph CLI (public client)
TENANT = "common"
SCOPE = "Files.ReadWrite offline_access User.Read"
FOLDER = "WhatsApp Files"
base = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"

with httpx.Client(timeout=30) as c:
    r = c.post(base + "/devicecode", data={"client_id": CLIENT_ID, "scope": SCOPE})
    f = r.json()
    if "user_code" not in f:
        print("DEVICECODE ERROR:", f); raise SystemExit
    print("USERCODE:", f["user_code"])
    print("URL:", f["verification_uri"])
    print("---waiting for sign-in (you have ~15 min)---", flush=True)
    device_code = f["device_code"]
    interval = f.get("interval", 5)
    deadline = time.time() + f.get("expires_in", 900)
    tok = None
    while time.time() < deadline:
        time.sleep(interval)
        tr = c.post(base + "/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": CLIENT_ID, "device_code": device_code,
        })
        j = tr.json()
        if "access_token" in j:
            tok = j; break
        err = j.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5; continue
        print("AUTH ERROR:", err, "|", (j.get("error_description") or "")[:240]); raise SystemExit
    if not tok:
        print("TIMED OUT — no sign-in"); raise SystemExit

    json.dump(tok, open(os.path.join(os.environ["TEMP"], "od_token.json"), "w"))
    print("HAS_REFRESH_TOKEN:", bool(tok.get("refresh_token")))
    at = tok["access_token"]
    g = httpx.Client(timeout=40, headers={"Authorization": f"Bearer {at}"})
    me = g.get("https://graph.microsoft.com/v1.0/me").json()
    print("SIGNED IN AS:", me.get("userPrincipalName") or me.get("displayName") or me)
    cr = g.post("https://graph.microsoft.com/v1.0/me/drive/root/children",
                json={"name": FOLDER, "folder": {}, "@microsoft.graph.conflictBehavior": "replace"})
    print("create folder:", cr.status_code)
    up = g.put(f"https://graph.microsoft.com/v1.0/me/drive/root:/{FOLDER}/hello_from_assistant.txt:/content",
               content=b"hello from your study assistant! if you see this in your OneDrive, it works.",
               headers={"Content-Type": "text/plain"})
    print("upload:", up.status_code)
    ls = g.get(f"https://graph.microsoft.com/v1.0/me/drive/root:/{FOLDER}:/children").json()
    print("files in folder:", [it.get("name") for it in ls.get("value", [])])
    print("PHASE0_OK" if up.status_code in (200, 201) else "PHASE0_FAILED")
