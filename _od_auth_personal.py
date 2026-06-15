"""Re-auth to the PERSONAL OneDrive (yutabanishky@gmail.com) — the one synced to
the laptop. Device-code flow against 'consumers'. Saves the refresh token and
smoke-tests Documents/whatsapp."""
import httpx, time, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
TENANT = "consumers"  # personal Microsoft accounts
SCOPE = "Files.ReadWrite offline_access User.Read"
FOLDER = "Documents/whatsapp"
base = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"

with httpx.Client(timeout=30) as c:
    f = c.post(base + "/devicecode", data={"client_id": CLIENT_ID, "scope": SCOPE}).json()
    if "user_code" not in f:
        print("DEVICECODE ERROR:", f); raise SystemExit
    print("USERCODE:", f["user_code"])
    print("URL:", f["verification_uri"])
    print("---SIGN IN WITH yutabanishky@gmail.com (your personal account)---", flush=True)
    device_code = f["device_code"]; interval = f.get("interval", 5)
    deadline = time.time() + f.get("expires_in", 900); tok = None
    while time.time() < deadline:
        time.sleep(interval)
        j = c.post(base + "/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": CLIENT_ID, "device_code": device_code}).json()
        if "access_token" in j:
            tok = j; break
        if j.get("error") == "authorization_pending":
            continue
        if j.get("error") == "slow_down":
            interval += 5; continue
        print("AUTH ERROR:", j.get("error"), "|", (j.get("error_description") or "")[:200]); raise SystemExit
    if not tok:
        print("TIMED OUT"); raise SystemExit

    json.dump(tok, open(os.path.join(os.environ["TEMP"], "od_personal.json"), "w"))
    g = httpx.Client(timeout=40, headers={"Authorization": f"Bearer {tok['access_token']}"})
    me = g.get("https://graph.microsoft.com/v1.0/me").json()
    print("SIGNED IN AS:", me.get("userPrincipalName") or me.get("displayName"))
    dr = g.get("https://graph.microsoft.com/v1.0/me/drive").json()
    print("drive type:", dr.get("driveType"))
    # ensure Documents/whatsapp exists (Documents already exists on personal OneDrive)
    chk = g.get("https://graph.microsoft.com/v1.0/me/drive/root:/Documents/whatsapp")
    if chk.status_code != 200:
        g.post("https://graph.microsoft.com/v1.0/me/drive/root:/Documents:/children",
               json={"name": "whatsapp", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
    up = g.put("https://graph.microsoft.com/v1.0/me/drive/root:/Documents/whatsapp/welcome.txt:/content",
               content=b"your whatsapp file folder is connected!", headers={"Content-Type": "text/plain"})
    print("folder+upload:", up.status_code)
    print("HAS_REFRESH_TOKEN:", bool(tok.get("refresh_token")))
    print("PERSONAL_OK" if up.status_code in (200, 201) else "FAILED")
