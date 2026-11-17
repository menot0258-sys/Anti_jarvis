"""Google Workspace for Jarvis (stdlib only): OAuth loopback + PKCE, and builders for
Slides, Sheets, Docs, Forms, Calendar, Drive, Gmail and a generic *.googleapis.com proxy."""
import json, os, time, base64, hashlib, secrets, re, uuid, mimetypes, datetime, urllib.request, urllib.parse, urllib.error
from email.message import EmailMessage

D = os.path.dirname(os.path.abspath(__file__)); AUTH = os.path.join(D, "google_auth.json")
SC = "https://www.googleapis.com/auth/"
SCOPES = ["openid", SC + "userinfo.email", SC + "drive", SC + "documents", SC + "spreadsheets", SC + "presentations", SC + "forms.body",
          SC + "forms.responses.readonly", SC + "calendar", SC + "gmail.modify", SC + "tasks", SC + "contacts.readonly"]
PENDING = {}

class GErr(Exception): pass

def _b64u(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def load():
    try: return json.load(open(AUTH, encoding="utf8"))
    except Exception: return {}
def save(d):
    with open(AUTH, "w", encoding="utf8") as f: json.dump(d, f)
    try: os.chmod(AUTH, 0o600)
    except Exception: pass
def _send(method, url, headers=None, data=None, timeout=40):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()

# ---------- OAuth ----------
def status():
    d = load()
    return {"ok": True, "configured": bool(d.get("client_id") and d.get("client_secret")), "client_id": (d.get("client_id") or "")[:14],
            "connected": bool(d.get("refresh_token")), "email": d.get("email", "")}
def auth_url(redirect, cid=None, sec=None):
    d = load()
    if cid: d["client_id"] = cid.strip()
    if sec: d["client_secret"] = sec.strip()
    save(d)
    if not (d.get("client_id") and d.get("client_secret")): raise GErr("Paste your Client ID and Client secret first.")
    for k in [k for k, v in PENDING.items() if time.time() - v["t"] > 600]: PENDING.pop(k, None)
    ver = secrets.token_urlsafe(64); state = secrets.token_urlsafe(16); PENDING[state] = {"v": ver, "r": redirect, "t": time.time()}
    q = {"client_id": d["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES), "state": state,
         "code_challenge": _b64u(hashlib.sha256(ver.encode()).digest()), "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q)
def _tok(form):
    st, b = _send("POST", "https://oauth2.googleapis.com/token", {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(form).encode())
    j = json.loads(b.decode() or "{}")
    if st != 200: raise GErr(j.get("error_description") or j.get("error") or "Google rejected the sign-in (HTTP %s)" % st)
    return j
def finish(code, state):
    p = PENDING.pop(state, None)
    if not p: raise GErr("Unknown or expired sign-in attempt. Press Connect again.")
    d = load()
    j = _tok({"code": code, "client_id": d["client_id"], "client_secret": d["client_secret"], "redirect_uri": p["r"], "grant_type": "authorization_code", "code_verifier": p["v"]})
    d.update(access_token=j["access_token"], expires_at=time.time() + j.get("expires_in", 3600) - 30)
    if j.get("refresh_token"): d["refresh_token"] = j["refresh_token"]
    try:
        st, b = _send("GET", "https://www.googleapis.com/oauth2/v3/userinfo", {"Authorization": "Bearer " + j["access_token"]})
        d["email"] = json.loads(b.decode()).get("email", "")
    except Exception: pass
    save(d); return d.get("email", "")
def disconnect():
    d = load()
    try:
        if d.get("refresh_token"): _send("POST", "https://oauth2.googleapis.com/revoke?token=" + urllib.parse.quote(d["refresh_token"]), {"Content-Type": "application/x-www-form-urlencoded"}, b"")
    except Exception: pass
    for k in ("refresh_token", "access_token", "expires_at", "email"): d.pop(k, None)
    save(d)
def token():
    d = load()
    if not d.get("refresh_token"): raise GErr("Google isn't connected. Open Settings > Google Workspace and press Connect Google.")
    if d.get("access_token") and d.get("expires_at", 0) > time.time() + 30: return d["access_token"]
    j = _tok({"client_id": d["client_id"], "client_secret": d["client_secret"], "refresh_token": d["refresh_token"], "grant_type": "refresh_token"})
    d.update(access_token=j["access_token"], expires_at=time.time() + j.get("expires_in", 3600) - 30); save(d); return d["access_token"]

# ---------- REST helper ----------
OKHOST = re.compile(r"^https://([a-z0-9-]+\.googleapis\.com|www\.googleapis\.com)/")
def api(method, url, body=None, raw=None, headers=None):
    if not OKHOST.match(url): raise GErr("Only https://*.googleapis.com URLs are allowed.")
    h = {"Authorization": "Bearer " + token(), **(headers or {})}; data = raw
    if body is not None: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    st, b = _send(method, url, h, data); txt = b.decode("utf8", "replace")
    try: j = json.loads(txt) if txt.strip() else {}
    except Exception: j = {"text": txt}
    if st >= 400:
        e = j.get("error") if isinstance(j, dict) else None; m = (e.get("message") if isinstance(e, dict) else str(e or "")) or txt[:200]
        hint = " Enable this API in Google Cloud Console > APIs & Services > Library." if st == 403 and ("has not been used" in m or "disabled" in m) else ""
        raise GErr("Google API %s: %s%s" % (st, m, hint))
    return j
def rgb(h, default="#000000"):
    h = (h or default).lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h): h = default.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}
def upload(name, gmime, data, mime, parents=None):
    meta = {"name": name}
    if gmime: meta["mimeType"] = gmime
    if parents: meta["parents"] = parents
    b = "jv" + secrets.token_hex(8)
    body = ("--%s\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n%s\r\n--%s\r\nContent-Type: %s\r\n\r\n" % (b, json.dumps(meta), b, mime)).encode() + data + ("\r\n--%s--" % b).encode()
    return api("POST", "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,webViewLink", raw=body, headers={"Content-Type": "multipart/related; boundary=" + b})

# ---------- Slides ----------
THEMES = {"dark": {"bg": "#0f172a", "title": "#ffffff", "text": "#cbd5e1"}, "midnight": {"bg": "#1e1b4b", "title": "#ffffff", "text": "#c7d2fe"},
          "ocean": {"bg": "#0c4a6e", "title": "#ffffff", "text": "#bae6fd"}, "forest": {"bg": "#14532d", "title": "#ffffff", "text": "#bbf7d0"},
          "sunset": {"bg": "#7c2d12", "title": "#fff7ed", "text": "#fed7aa"}, "light": {"bg": "#ffffff", "title": "#111827", "text": "#374151"}}
def slides(spec, tz=None, res=None):
    title = spec.get("title") or "Presentation"; items = spec.get("slides") or []; th = spec.get("theme")
    th = THEMES.get(th) if isinstance(th, str) else th
    pres = api("POST", "https://slides.googleapis.com/v1/presentations", {"title": title}); pid = pres["presentationId"]; first = pres["slides"][0]["objectId"]
    reqs, notes = [], []
    def text(oid, t, color=None, cell=None, bold=False):
        if t in (None, ""): return
        r = {"insertText": {"objectId": oid, "text": str(t), "insertionIndex": 0}}
        if cell: r["insertText"]["cellLocation"] = cell
        reqs.append(r)
        st, f = {}, []
        if color: st["foregroundColor"] = {"opaqueColor": {"rgbColor": rgb(color)}}; f.append("foregroundColor")
        if bold: st["bold"] = True; f.append("bold")
        if st:
            u = {"objectId": oid, "textRange": {"type": "ALL"}, "style": st, "fields": ",".join(f)}
            if cell: u["cellLocation"] = cell
            reqs.append({"updateTextStyle": u})
    for i, s in enumerate(items):
        sid = "slide%d" % (i + 1)
        t = (s.get("type") or ("table" if s.get("table") else "image" if s.get("image") else "bullets" if (s.get("bullets") or s.get("body")) else "title" if i == 0 else "section")).lower()
        lay, maps = {"title": ("TITLE", [("CENTERED_TITLE", "t"), ("SUBTITLE", "s")]), "section": ("SECTION_HEADER", [("TITLE", "t")]),
                     "bullets": ("TITLE_AND_BODY", [("TITLE", "t"), ("BODY", "b")])}.get(t, ("TITLE_ONLY", [("TITLE", "t")]))
        reqs.append({"createSlide": {"objectId": sid, "slideLayoutReference": {"predefinedLayout": lay},
                     "placeholderIdMappings": [{"layoutPlaceholder": {"type": ty, "index": 0}, "objectId": "%s_%s" % (sid, k)} for ty, k in maps]}})
        if th and th.get("bg"):
            reqs.append({"updatePageProperties": {"objectId": sid, "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": rgb(th["bg"])}}}}, "fields": "pageBackgroundFill.solidFill.color"}})
        tc, xc = (th or {}).get("title"), (th or {}).get("text")
        text(sid + "_t", s.get("title"), tc)
        if t == "title": text(sid + "_s", s.get("subtitle"), xc)
        if t == "bullets":
            b = s.get("bullets") or s.get("body") or []; text(sid + "_b", "\n".join(map(str, b)) if isinstance(b, list) else b, xc)
        if t == "table":
            rows = [[("" if c is None else str(c)) for c in r] for r in (s.get("table") or [])]
            if rows:
                nc = max(len(r) for r in rows); tid = sid + "_tbl"
                reqs.append({"createTable": {"objectId": tid, "rows": len(rows), "columns": nc, "elementProperties": {"pageObjectId": sid,
                             "size": {"width": {"magnitude": 8229600, "unit": "EMU"}, "height": {"magnitude": 300000 * len(rows), "unit": "EMU"}},
                             "transform": {"scaleX": 1, "scaleY": 1, "translateX": 457200, "translateY": 1450000, "unit": "EMU"}}}})
                for ri, r in enumerate(rows):
                    for ci, c in enumerate(r): text(tid, c, xc, {"rowIndex": ri, "columnIndex": ci}, bold=(ri == 0))
        if t == "image" and s.get("image"):
            reqs.append({"createImage": {"objectId": sid + "_img", "url": s["image"], "elementProperties": {"pageObjectId": sid,
                         "size": {"width": {"magnitude": 4800000, "unit": "EMU"}, "height": {"magnitude": 3000000, "unit": "EMU"}},
                         "transform": {"scaleX": 1, "scaleY": 1, "translateX": 2172000, "translateY": 1500000, "unit": "EMU"}}}})
        if s.get("notes"): notes.append((sid, s["notes"]))
    if items: reqs.append({"deleteObject": {"objectId": first}})
    if reqs: api("POST", "https://slides.googleapis.com/v1/presentations/%s:batchUpdate" % pid, {"requests": reqs})
    if notes:
        p = api("GET", "https://slides.googleapis.com/v1/presentations/%s?fields=slides(objectId,slideProperties(notesPage(notesProperties(speakerNotesObjectId))))" % pid)
        ids = {x["objectId"]: x.get("slideProperties", {}).get("notesPage", {}).get("notesProperties", {}).get("speakerNotesObjectId") for x in p.get("slides", [])}
        nr = [{"insertText": {"objectId": ids[sid], "text": str(n), "insertionIndex": 0}} for sid, n in notes if ids.get(sid)]
        if nr: api("POST", "https://slides.googleapis.com/v1/presentations/%s:batchUpdate" % pid, {"requests": nr})
    return {"ok": True, "url": "https://docs.google.com/presentation/d/%s/edit" % pid, "title": title, "slides": len(items), "summary": "Created %d slides" % len(items)}

# ---------- Sheets ----------
def sheets(spec, tz=None, res=None):
    title = spec.get("title") or "Spreadsheet"
    shs = spec.get("sheets") or [{"name": "Sheet1", "rows": spec.get("rows") or []}]
    names = [(x.get("name") or "Sheet%d" % (i + 1))[:90] for i, x in enumerate(shs)]
    ss = api("POST", "https://sheets.googleapis.com/v4/spreadsheets", {"properties": {"title": title}, "sheets": [{"properties": {"title": n}} for n in names]})
    sid = ss["spreadsheetId"]; ids = [x["properties"]["sheetId"] for x in ss["sheets"]]; data, reqs = [], []
    for x, n, shid in zip(shs, names, ids):
        rows = [["" if c is None else c for c in r] for r in (x.get("rows") or [])]
        if not rows: continue
        nr, nc = len(rows), max(len(r) for r in rows)
        data.append({"range": "'%s'!A1" % n.replace("'", "''"), "majorDimension": "ROWS", "values": rows})
        if x.get("header", True):
            reqs += [{"repeatCell": {"range": {"sheetId": shid, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": nc},
                      "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "foregroundColor": rgb("#ffffff")}}}, "fields": "userEnteredFormat.textFormat"}},
                     {"updateSheetProperties": {"properties": {"sheetId": shid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
                     {"addBanding": {"bandedRange": {"range": {"sheetId": shid, "startRowIndex": 0, "endRowIndex": nr, "startColumnIndex": 0, "endColumnIndex": nc},
                      "rowProperties": {"headerColor": rgb("#1a73e8"), "firstBandColor": rgb("#ffffff"), "secondBandColor": rgb("#e8f0fe")}}}}]
        reqs.append({"autoResizeDimensions": {"dimensions": {"sheetId": shid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": nc}}})
        ch = x.get("chart")
        if ch and nr > 1 and nc > 1:
            def src(c0, c1): return {"sources": [{"sheetId": shid, "startRowIndex": 0, "endRowIndex": nr, "startColumnIndex": c0, "endColumnIndex": c1}]}
            dcol = int(ch.get("x", 0)); scols = [int(c) for c in (ch.get("series") or [c for c in range(nc) if c != dcol])]
            ty = (ch.get("type") or "COLUMN").upper()
            if ty == "PIE": spec_ = {"title": ch.get("title", ""), "pieChart": {"legendPosition": "RIGHT_LEGEND", "domain": {"sourceRange": src(dcol, dcol + 1)}, "series": {"sourceRange": src(scols[0], scols[0] + 1)}}}
            else: spec_ = {"title": ch.get("title", ""), "basicChart": {"chartType": ty if ty in ("COLUMN", "BAR", "LINE", "AREA", "SCATTER") else "COLUMN", "legendPosition": "BOTTOM_LEGEND",
                           "headerCount": 1, "domains": [{"domain": {"sourceRange": src(dcol, dcol + 1)}}],
                           "series": [{"series": {"sourceRange": src(c, c + 1)}, "targetAxis": "LEFT_AXIS"} for c in scols]}}
            reqs.append({"addChart": {"chart": {"spec": spec_, "position": {"overlayPosition": {"anchorCell": {"sheetId": shid, "rowIndex": 1, "columnIndex": nc + 1}, "widthPixels": 600, "heightPixels": 371}}}}})
    if data: api("POST", "https://sheets.googleapis.com/v4/spreadsheets/%s/values:batchUpdate" % sid, {"valueInputOption": "USER_ENTERED", "data": data})
    if reqs: api("POST", "https://sheets.googleapis.com/v4/spreadsheets/%s:batchUpdate" % sid, {"requests": reqs})
    return {"ok": True, "url": ss.get("spreadsheetUrl") or "https://docs.google.com/spreadsheets/d/%s/edit" % sid, "title": title, "summary": "Created a spreadsheet with %d sheet(s)" % len(shs)}

# ---------- Docs / Forms ----------
def doc(spec, tz=None, res=None):
    title = spec.get("title") or "Document"; h = spec.get("html") or "<p>%s</p>" % re.sub(r"[<>&]", "", spec.get("text", ""))
    r = upload(title, "application/vnd.google-apps.document", ("<html><head><meta charset='utf-8'></head><body>%s</body></html>" % h).encode("utf8"), "text/html")
    return {"ok": True, "url": "https://docs.google.com/document/d/%s/edit" % r["id"], "title": title, "summary": "Created a Google Doc"}
def form(spec, tz=None, res=None):
    title = spec.get("title") or "Form"; quiz = bool(spec.get("quiz"))
    f = api("POST", "https://forms.googleapis.com/v1/forms", {"info": {"title": title, "documentTitle": title}}); fid = f["formId"]; reqs = []
    if spec.get("description"): reqs.append({"updateFormInfo": {"info": {"description": spec["description"]}, "updateMask": "description"}})
    if quiz: reqs.append({"updateSettings": {"settings": {"quizSettings": {"isQuiz": True}}, "updateMask": "quizSettings.isQuiz"}})
    for i, q in enumerate(spec.get("questions") or []):
        t = (q.get("type") or "text").lower(); qt = q.get("title") or q.get("question") or "Question %d" % (i + 1)
        if t in ("section", "page"): item = {"title": qt, "pageBreakItem": {}}
        elif t in ("info", "textblock", "description"): item = {"title": qt, "textItem": {}}
        else:
            qq = {"required": bool(q.get("required", False))}
            if t in ("paragraph", "long"): qq["textQuestion"] = {"paragraph": True}
            elif t in ("choice", "radio", "mcq", "multiple_choice", "checkbox", "checkboxes", "dropdown", "select"):
                ty = "CHECKBOX" if t.startswith("checkbox") else "DROP_DOWN" if t in ("dropdown", "select") else "RADIO"
                qq["choiceQuestion"] = {"type": ty, "options": [{"value": str(o)} for o in (q.get("options") or [])], "shuffle": bool(q.get("shuffle", False))}
            elif t == "scale":
                qq["scaleQuestion"] = {"low": int(q.get("low", 1)), "high": int(q.get("high", 5))}
                if q.get("lowLabel"): qq["scaleQuestion"]["lowLabel"] = q["lowLabel"]
                if q.get("highLabel"): qq["scaleQuestion"]["highLabel"] = q["highLabel"]
            elif t == "date": qq["dateQuestion"] = {"includeYear": True}
            elif t == "time": qq["timeQuestion"] = {}
            else: qq["textQuestion"] = {"paragraph": False}
            if quiz and q.get("correct") is not None and t not in ("date", "time", "scale"):
                ans = q["correct"] if isinstance(q["correct"], list) else [q["correct"]]
                qq["grading"] = {"pointValue": int(q.get("points", 1)), "correctAnswers": {"answers": [{"value": str(a)} for a in ans]}}
            item = {"title": qt, "questionItem": {"question": qq}}
        if q.get("description"): item["description"] = q["description"]
        reqs.append({"createItem": {"item": item, "location": {"index": i}}})
    if reqs: api("POST", "https://forms.googleapis.com/v1/forms/%s:batchUpdate" % fid, {"requests": reqs})
    return {"ok": True, "url": "https://docs.google.com/forms/d/%s/edit" % fid, "share_link": f.get("responderUri"), "title": title, "summary": "Created a form with %d question(s)" % len(spec.get("questions") or [])}

# ---------- Calendar ----------
def _dt(s, tz):
    s = str(s).strip()
    if re.fullmatch(r"\d{4}-\d\d-\d\d", s): return {"date": s}
    if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d", s): s += ":00"
    o = {"dateTime": s}
    if not re.search(r"(Z|[+-]\d\d:\d\d)$", s): o["timeZone"] = tz or "UTC"
    return o
def cal(spec, tz=None, res=None):
    a = spec.get("action", "create"); tz = spec.get("timezone") or tz or "UTC"; B = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    if a == "list":
        now = datetime.datetime.now(datetime.timezone.utc); days = int(spec.get("days", 7))
        q = urllib.parse.urlencode({"timeMin": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeMax": (now + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"), "singleEvents": "true", "orderBy": "startTime", "maxResults": 50})
        r = api("GET", B + "?" + q)
        ev = [{"id": e.get("id"), "summary": e.get("summary"), "start": e.get("start"), "end": e.get("end"), "location": e.get("location"), "meet": e.get("hangoutLink")} for e in r.get("items", [])]
        return {"ok": True, "events": ev, "summary": "%d event(s)" % len(ev)}
    if a == "delete":
        api("DELETE", B + "/" + urllib.parse.quote(spec["id"])); return {"ok": True, "summary": "Event deleted"}
    st = _dt(spec["start"], tz)
    if spec.get("end"): en = _dt(spec["end"], tz)
    elif "date" in st: en = {"date": (datetime.date.fromisoformat(st["date"]) + datetime.timedelta(days=1)).isoformat()}
    else:
        en = dict(st)
        try: en["dateTime"] = (datetime.datetime.fromisoformat(st["dateTime"].replace("Z", "+00:00")) + datetime.timedelta(hours=1)).isoformat()
        except Exception: pass
    ev = {"summary": spec.get("summary") or spec.get("title") or "Event", "start": st, "end": en}
    for k in ("description", "location"):
        if spec.get(k): ev[k] = spec[k]
    if spec.get("attendees"): ev["attendees"] = [{"email": e} for e in spec["attendees"]]
    if spec.get("meet"): ev["conferenceData"] = {"createRequest": {"requestId": uuid.uuid4().hex, "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
    if spec.get("reminders"): ev["reminders"] = {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(m)} for m in spec["reminders"]]}
    if spec.get("recurrence"): ev["recurrence"] = spec["recurrence"] if isinstance(spec["recurrence"], list) else [spec["recurrence"]]
    r = api("POST", B + "?conferenceDataVersion=1&sendUpdates=all", ev)
    return {"ok": True, "url": r.get("htmlLink"), "id": r.get("id"), "meet": r.get("hangoutLink"), "summary": "Event created"}

# ---------- Drive ----------
def drive(spec, tz=None, res=None):
    a = spec.get("action", "list"); F = "https://www.googleapis.com/drive/v3/files"
    if a in ("list", "search"):
        q = spec.get("q") or ""
        if not q:
            qs = ["trashed=false"]
            if spec.get("query"): qs.append("name contains '%s'" % str(spec["query"]).replace("'", "\\'"))
            if spec.get("folder"): qs.append("'%s' in parents" % spec["folder"])
            q = " and ".join(qs)
        r = api("GET", F + "?" + urllib.parse.urlencode({"q": q, "pageSize": int(spec.get("limit", 20)), "orderBy": "modifiedTime desc", "fields": "files(id,name,mimeType,webViewLink,modifiedTime,size)"}))
        return {"ok": True, "files": r.get("files", []), "summary": "%d file(s)" % len(r.get("files", []))}
    if a == "mkdir":
        r = api("POST", F + "?fields=id,name,webViewLink", {"name": spec.get("name") or "New folder", "mimeType": "application/vnd.google-apps.folder", **({"parents": [spec["folder"]]} if spec.get("folder") else {})})
        return {"ok": True, "url": r.get("webViewLink"), "id": r.get("id"), "summary": "Folder created"}
    if a == "upload":
        p = res(spec.get("path", "")) if res else None
        if not p or not os.path.isfile(p): raise GErr("Local file not found inside the apps folder: %s" % spec.get("path"))
        conv = {"sheet": "application/vnd.google-apps.spreadsheet", "doc": "application/vnd.google-apps.document", "slides": "application/vnd.google-apps.presentation"}.get(spec.get("convert"))
        r = upload(spec.get("name") or os.path.basename(p), conv, open(p, "rb").read(), mimetypes.guess_type(p)[0] or "application/octet-stream", [spec["folder"]] if spec.get("folder") else None)
        return {"ok": True, "url": r.get("webViewLink"), "id": r.get("id"), "summary": "Uploaded " + r.get("name", "")}
    fid = urllib.parse.quote(spec.get("id", ""))
    if a == "share":
        perm = {"role": spec.get("role", "reader"), "type": "anyone"} if spec.get("anyone") else {"role": spec.get("role", "reader"), "type": "user", "emailAddress": spec.get("email")}
        api("POST", F + "/" + fid + "/permissions?sendNotificationEmail=true", perm)
        r = api("GET", F + "/" + fid + "?fields=webViewLink"); return {"ok": True, "url": r.get("webViewLink"), "summary": "Shared"}
    if a == "read":
        m = api("GET", F + "/" + fid + "?fields=mimeType,name")
        if m.get("mimeType", "").startswith("application/vnd.google-apps"):
            r = api("GET", F + "/" + fid + "/export?mimeType=" + ("text/csv" if "spreadsheet" in m["mimeType"] else "text/plain"))
        else: r = api("GET", F + "/" + fid + "?alt=media")
        return {"ok": True, "name": m.get("name"), "text": (r.get("text") if isinstance(r, dict) and "text" in r else json.dumps(r))[:6000], "summary": "Read " + str(m.get("name"))}
    if a == "trash":
        api("PATCH", F + "/" + fid, {"trashed": True}); return {"ok": True, "summary": "Moved to trash"}
    raise GErr("Unknown drive action: %s" % a)

# ---------- Gmail ----------
def gmail(spec, tz=None, res=None):
    a = spec.get("action", "list"); B = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
    if a == "send":
        body = spec.get("body", ""); m = EmailMessage(); m["To"] = spec["to"]; m["Subject"] = spec.get("subject", "")
        m.set_content(re.sub(r"<[^>]+>", "", body))
        if "<" in body: m.add_alternative(body, subtype="html")
        api("POST", B + "/send", {"raw": _b64u(m.as_bytes())}); return {"ok": True, "summary": "Email sent to " + spec["to"]}
    if a == "read":
        r = api("GET", B + "/" + urllib.parse.quote(spec["id"]) + "?format=full"); txt = ""
        def walk(p):
            nonlocal txt
            if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"): txt += base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf8", "replace")
            for c in p.get("parts", []) or []: walk(c)
        walk(r.get("payload", {})); hd = {h["name"]: h["value"] for h in r.get("payload", {}).get("headers", [])}
        return {"ok": True, "from": hd.get("From"), "subject": hd.get("Subject"), "date": hd.get("Date"), "text": txt[:5000], "summary": "Read email"}
    r = api("GET", B + "?" + urllib.parse.urlencode({"q": spec.get("query", ""), "maxResults": min(int(spec.get("limit", 5)), 10)})); out = []
    for m in r.get("messages", []):
        x = api("GET", B + "/" + m["id"] + "?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date")
        hd = {h["name"]: h["value"] for h in x.get("payload", {}).get("headers", [])}
        out.append({"id": m["id"], "from": hd.get("From"), "subject": hd.get("Subject"), "date": hd.get("Date"), "snippet": x.get("snippet")})
    return {"ok": True, "emails": out, "summary": "%d email(s)" % len(out)}

def generic(spec, tz=None, res=None):
    r = api((spec.get("method") or "GET").upper(), spec["url"], spec.get("body"))
    return {"ok": True, "data": json.loads(json.dumps(r)[:12000]) if len(json.dumps(r)) <= 12000 else json.dumps(r)[:12000], "summary": "Done"}

KINDS = {"gslides": slides, "gsheets": sheets, "gdoc": doc, "gform": form, "gcal": cal, "gdrive": drive, "gmail": gmail, "google": generic}
def run(kind, spec, tz=None, res=None):
    try:
        if kind not in KINDS: raise GErr("Unknown Google action: %s" % kind)
        return KINDS[kind](spec, tz, res)
    except GErr as e: return {"ok": False, "error": str(e)}
    except KeyError as e: return {"ok": False, "error": "Missing field in the %s block: %s" % (kind, e)}
    except Exception as e: return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
