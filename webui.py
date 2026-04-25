from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import json
import requests
from urllib.parse import quote

CFG_PATH = "config.json"

def load_cfg():
    with open(CFG_PATH, "r") as f:
        return json.load(f)

def save_cfg(cfg: dict):
    with open(CFG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def agent_client(cfg):
    base = cfg["host_agent"]["base_url"].rstrip("/")
    headers = {"X-Widgets-Token": cfg["host_agent"]["token"]}
    return base, headers

def agent_get(cfg, path):
    base, headers = agent_client(cfg)
    r = requests.get(f"{base}{path}", headers=headers, timeout=6)
    r.raise_for_status()
    return r.json()

def agent_post(cfg, path, body):
    base, headers = agent_client(cfg)
    r = requests.post(f"{base}{path}", headers=headers, json=body, timeout=8)
    r.raise_for_status()
    return r.json()

def nav():
    return """
    <div style="margin-bottom:12px;">
      <a href="/">Home</a> | <a href="/setup">Setup</a>
    </div>
    """

def html_page(title: str, body: str):
    return f"""
    <html>
      <head>
        <title>{title}</title>
        <style>
          body {{ font-family: Arial, sans-serif; }}
          table {{ border-collapse: collapse; }}
          th, td {{ padding: 6px 10px; }}
          .ok {{ color: green; }}
          .err {{ color: red; }}
          .small {{ font-size: 12px; color: #444; }}
          .banner {{ padding: 10px; border: 1px solid #ccc; background: #f7f7f7; margin: 10px 0; white-space: pre-wrap; }}
          .danger {{ color: #b00020; }}
        </style>
      </head>
      <body>
        <h1>{title}</h1>
        {nav()}
        {body}
      </body>
    </html>
    """

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
def index():
    cfg = load_cfg()
    zones = cfg.get("zones", {})

    health_line = ""
    try:
        health = agent_get(cfg, "/health")
        health_line = f"<p class='ok'>Host Agent Health: {health}</p>"
    except Exception as e:
        health_line = f"<p class='err'>Host Agent Health ERROR: {e}</p>"

    rows = []
    for zid, zcfg in zones.items():
        err = None
        try:
            st = agent_get(cfg, f"/zones/{zid}/status")
            active = st.get("zone_active", "?")
            mute = st.get("mute", "?")
            vol = st.get("volume", "?")
            svc = st.get("active_service", "") or "None"
        except Exception as e:
            err = str(e)
            active = mute = vol = "ERR"
            svc = "None"

        rows.append(f"""
        <tr>
          <td>
            <a href="/zone/{zid}">{zcfg.get("display_name", zid)}</a>
            <div class="small">{zcfg.get("savant_zone_name","")}</div>
          </td>
          <td>{active}</td>
          <td>{mute}</td>
          <td>{vol}</td>
          <td style="max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{svc}</td>
          <td>
            <a href="/action/{zid}/power?return=/">Power</a> |
            <a href="/action/{zid}/mute?return=/">Mute</a> |
            <a href="/action/{zid}/vu?return=/">Vol+</a> |
            <a href="/action/{zid}/vd?return=/">Vol-</a>
            <span class="small">|</span>
            <a class="danger" href="/zone/{zid}/delete">Delete</a>
          </td>
        </tr>
        """)

    body = f"""
      {health_line}
      <table border="1">
        <tr>
          <th>Zone</th><th>Active</th><th>Muted</th><th>Vol</th><th>Active Service</th><th>Actions</th>
        </tr>
        {''.join(rows)}
      </table>
      <p class="small">If a zone shows ERR, the host agent likely doesn't recognize that zone_id yet (mapping needed).</p>
    """
    return html_page("Widgets Remote Hub", body)

@app.get("/setup", response_class=HTMLResponse)
def setup():
    cfg = load_cfg()
    zones_cfg = cfg.get("zones", {})

    available = []
    err = None
    try:
        available = agent_get(cfg, "/savant/userzones").get("zones", [])
    except Exception as e:
        err = str(e)

    def to_id(name: str) -> str:
        return name.strip().lower().replace(" ", "_").replace("-", "_")

    options = ""
    for z in available:
        zid = to_id(z)
        mark = " (already added)" if zid in zones_cfg else ""
        options += f'<option value="{z}">{z}{mark}</option>'

    err_html = f"<div class='banner err'>Discovery error: {err}</div>" if err else ""

    existing = "".join([
        f'<li><a href="/zone/{zid}">{zcfg.get("display_name", zid)}</a> '
        f'<span class="small">({zcfg.get("savant_zone_name","")})</span> '
        f' <a class="danger" href="/zone/{zid}/delete">Delete</a></li>'
        for zid, zcfg in zones_cfg.items()
    ])

    body = f"""
      {err_html}
      <h2>Add Zone</h2>
      <form method="post" action="/save_zone">
        <label>Savant Zone Name:</label><br/>
        <select name="savant_zone_name">{options}</select><br/><br/>
        <label>Zone ID (internal / URLs):</label><br/>
        <input name="zone_id" placeholder="e.g. se_living"/><br/><br/>
        <label>Display Name:</label><br/>
        <input name="display_name" placeholder="e.g. SE Living"/><br/><br/>
        <button type="submit">Add / Update Zone</button>
      </form>

      <h2>Existing Zones</h2>
      <ul>{existing}</ul>
    """
    return html_page("Setup", body)

@app.post("/save_zone")
def save_zone(
    savant_zone_name: str = Form(...),
    zone_id: str = Form(...),
    display_name: str = Form(...)
):
    cfg = load_cfg()
    cfg.setdefault("zones", {})

    cfg["zones"][zone_id] = {
        "display_name": display_name.strip(),
        "savant_zone_name": savant_zone_name.strip(),
        "service_on_token": cfg["zones"].get(zone_id, {}).get("service_on_token", ""),
        "power_off_token": cfg["zones"].get(zone_id, {}).get("power_off_token", f"{savant_zone_name.strip()}-----PowerOff"),
    }
    save_cfg(cfg)
    return RedirectResponse(url=f"/zone/{zone_id}", status_code=303)

@app.get("/zone/{zone_id}", response_class=HTMLResponse)
def zone_page(zone_id: str, msg: str = ""):
    cfg = load_cfg()
    z = cfg.get("zones", {}).get(zone_id)
    if not z:
        return HTMLResponse(html_page("Unknown Zone", f"<p>Unknown zone {zone_id}</p>"), status_code=404)

    savant_zone = z.get("savant_zone_name", "")
    services = []
    err = None
    try:
        services = agent_get(cfg, f"/savant/services?zone={quote(savant_zone)}").get("services", [])
    except Exception as e:
        err = str(e)

    svc_opts = "".join([f'<option value="{s}">{s}</option>' for s in services])
    err_html = f"<div class='banner err'>Service discovery error: {err}</div>" if err else ""
    msg_html = f"<div class='banner'>{msg}</div>" if msg else ""

    body = f"""
      {msg_html}
      <h2>{z.get("display_name", zone_id)}</h2>
      <div class="small">zone_id: <b>{zone_id}</b> | savant_zone_name: <b>{savant_zone}</b></div>
      <p><a class="danger" href="/zone/{zone_id}/delete">Delete this zone</a></p>

      <h3>Saved Tokens</h3>
      <p><b>PowerOff token:</b> {z.get("power_off_token","")}</p>
      <p><b>ServiceOn token:</b> {z.get("service_on_token","")}</p>

      <h3>Quick Actions</h3>
      <p>
        <a href="/action/{zone_id}/power?return=/zone/{zone_id}">Power</a> |
        <a href="/action/{zone_id}/mute?return=/zone/{zone_id}">Mute</a> |
        <a href="/action/{zone_id}/vu?return=/zone/{zone_id}">Vol+</a> |
        <a href="/action/{zone_id}/vd?return=/zone/{zone_id}">Vol-</a>
      </p>

      <h3>Set ServiceOn Token</h3>
      {err_html}
      <form method="post" action="/save_tokens">
        <input type="hidden" name="zone_id" value="{zone_id}"/>

        <label>Pick a service (helper):</label><br/>
        <select name="service_pick">
          <option value="">-- choose --</option>
          {svc_opts}
        </select>
        <div class="small">If ServiceOn token is blank, we auto-build it by appending <b>-PowerOn</b>.</div>
        <br/>

        <label>ServiceOn token (optional override):</label><br/>
        <input name="service_on_token" style="width:900px;"
               value="{z.get("service_on_token","")}"
               placeholder="Leave blank to auto-build from dropdown"/><br/><br/>

        <label>PowerOff token:</label><br/>
        <input name="power_off_token" style="width:900px;" value="{z.get("power_off_token","")}" /><br/><br/>

        <button type="submit">Save Tokens</button>
      </form>
    """
    return html_page("Zone", body)

@app.post("/save_tokens")
def save_tokens(
    zone_id: str = Form(...),
    service_on_token: str = Form(""),
    power_off_token: str = Form(""),
    service_pick: str = Form("")
):
    cfg = load_cfg()
    z = cfg.get("zones", {}).get(zone_id)
    if not z:
        return RedirectResponse(url="/setup", status_code=303)

    service_on_token = (service_on_token or "").strip()
    service_pick = (service_pick or "").strip()

    if not service_on_token and service_pick:
        service_on_token = service_pick if service_pick.endswith("-PowerOn") else (service_pick + "-PowerOn")

    z["service_on_token"] = service_on_token
    if power_off_token:
        z["power_off_token"] = power_off_token.strip()

    cfg["zones"][zone_id] = z
    save_cfg(cfg)
    return RedirectResponse(url=f"/zone/{zone_id}", status_code=303)

@app.get("/zone/{zone_id}/delete", response_class=HTMLResponse)
def delete_confirm(zone_id: str):
    cfg = load_cfg()
    z = cfg.get("zones", {}).get(zone_id)
    if not z:
        return RedirectResponse(url="/setup", status_code=303)

    body = f"""
      <div class="banner">
        <b class="danger">Confirm delete</b><br/><br/>
        Zone ID: <b>{zone_id}</b><br/>
        Display: <b>{z.get("display_name","")}</b><br/>
        Savant Zone: <b>{z.get("savant_zone_name","")}</b><br/><br/>
        This will remove it from <code>config.json</code>.
      </div>

      <form method="post" action="/zone/{zone_id}/delete">
        <button class="danger" type="submit">Yes, delete it</button>
        <a style="margin-left:12px;" href="/zone/{zone_id}">Cancel</a>
      </form>
    """
    return html_page("Delete Zone", body)

@app.post("/zone/{zone_id}/delete")
def delete_do(zone_id: str):
    cfg = load_cfg()
    zones = cfg.get("zones", {})
    if zone_id in zones:
        del zones[zone_id]
        cfg["zones"] = zones
        save_cfg(cfg)
    return RedirectResponse(url="/setup", status_code=303)

@app.get("/action/{zone_id}/{cmd}")
def do_action(zone_id: str, cmd: str, return_url: str = "/"):
    cfg = load_cfg()
    z = cfg.get("zones", {}).get(zone_id)
    if not z:
        return RedirectResponse(url=return_url, status_code=303)

    # NOTE: these calls REQUIRE the host agent to recognize zone_id.
    if cmd == "power":
        st = agent_get(cfg, f"/zones/{zone_id}/status")
        zone_active = str(st.get("zone_active", "0")) == "1"
        token = z.get("power_off_token") if zone_active else z.get("service_on_token")
        if token:
            agent_post(cfg, "/savant/testtoken", {"token": token})
    elif cmd == "mute":
        st = agent_get(cfg, f"/zones/{zone_id}/status")
        is_muted = str(st.get("mute", "0")) == "1"
        action = "mute_off" if is_muted else "mute_on"
        agent_post(cfg, f"/zones/{zone_id}/action", {"action": action})
    elif cmd == "vu":
        agent_post(cfg, f"/zones/{zone_id}/action", {"action": "vol_up"})
    elif cmd == "vd":
        agent_post(cfg, f"/zones/{zone_id}/action", {"action": "vol_down"})

    return RedirectResponse(url=return_url, status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webui:app", host="0.0.0.0", port=8080, log_level="info")
