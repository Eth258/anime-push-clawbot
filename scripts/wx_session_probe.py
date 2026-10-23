import base64, glob, json, os, random, time
import requests

LOG = "/var/log/wx_session.log"
VER = (2 << 16) | (4 << 8) | 10


def headers(token):
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str(VER),
        "X-WECHAT-UIN": base64.b64encode(str(random.randint(1, 2 ** 32 - 1)).encode()).decode(),
        "Authorization": "Bearer " + token,
    }


def main():
    try:
        ctxp = sorted(glob.glob("/root/.openclaw/openclaw-weixin/accounts/*.context-tokens.json"),
                      key=lambda p: os.stat(p).st_mtime, reverse=True)[0]
        acc = json.load(open(ctxp.replace(".context-tokens.json", ".json")))
        ctx = json.load(open(ctxp)).get(acc["userId"], "")
        r = requests.post(acc["baseUrl"].rstrip("/") + "/ilink/bot/getconfig",
                          json={"ilink_user_id": acc["userId"], "context_token": ctx,
                                "base_info": {"channel_version": "2.4.10", "bot_agent": "openclaw"}},
                          headers=headers(acc["token"]), timeout=15)
        body = r.json() if r.text.strip().startswith("{") else {}
        line = "OK" if not body.get("errcode") else "FAIL errcode=%s %s" % (body.get("errcode"), body.get("errmsg", ""))
    except Exception as e:
        line = "EXC " + str(e)[:70]
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    print(line)


if __name__ == "__main__":
    main()
