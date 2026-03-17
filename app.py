#!/usr/bin/env python3
import os, sqlite3, hashlib, hmac, secrets, json
from datetime import datetime
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server
import cgi

DB_PATH = os.environ.get('DENT_TROOPER_DB', 'dent_trooper.db')
UPLOAD_DIR = os.environ.get('DENT_TROOPER_UPLOAD_DIR', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

LEAD_STATUSES = ['new','contacted','estimate sent','scheduled','lost']
JOB_STATUSES = ['scheduled','in progress','completed','paid','cancelled']
INVOICE_STATUSES = ['draft','sent','paid','unpaid']


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
    return f'{salt}${digest}'


def verify_password(password, stored):
    salt, digest = stored.split('$', 1)
    check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
    return hmac.compare_digest(digest, check)


def init_db():
    conn = db(); c = conn.cursor()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, role TEXT, name TEXT);
    CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT);
    CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT, address TEXT, notes TEXT, flagged INTEGER DEFAULT 0, flagged_reason TEXT);
    CREATE TABLE IF NOT EXISTS vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER, year TEXT, make TEXT, model TEXT, vin TEXT, color TEXT, plate TEXT, notes TEXT);
    CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT, email TEXT, address TEXT, vehicle_year TEXT, make TEXT, model TEXT, damage_summary TEXT, preferred_timing TEXT, lead_source TEXT, notes TEXT, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, lead_id INTEGER, customer_id INTEGER, vehicle_id INTEGER, service_address TEXT, scheduled_at TEXT, status TEXT, damage_summary TEXT, internal_notes TEXT, estimate_amount REAL, invoice_amount REAL, payment_status TEXT, mileage REAL, created_at TEXT);
    CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, entity_type TEXT, entity_id INTEGER, content TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS job_photos (id INTEGER PRIMARY KEY, job_id INTEGER, kind TEXT, file_path TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS estimates (id INTEGER PRIMARY KEY, lead_id INTEGER, job_id INTEGER, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS estimate_line_items (id INTEGER PRIMARY KEY, estimate_id INTEGER, description TEXT, quantity REAL, unit_price REAL);
    CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY, estimate_id INTEGER, job_id INTEGER, status TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS invoice_line_items (id INTEGER PRIMARY KEY, invoice_id INTEGER, description TEXT, quantity REAL, unit_price REAL);
    CREATE TABLE IF NOT EXISTS message_templates (id INTEGER PRIMARY KEY, type TEXT, title TEXT, content TEXT);
    CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY, job_id INTEGER, event TEXT, created_at TEXT);
    ''')
    conn.commit()
    u = c.execute('SELECT COUNT(*) as n FROM users').fetchone()['n']
    if u == 0:
        c.execute('INSERT INTO users (email,password_hash,role,name) VALUES (?,?,?,?)', ('admin@denttrooper.local', hash_password('changeme123'), 'admin', 'Dent Admin'))
        c.execute('INSERT INTO customers (name,phone,email,address,notes,flagged,flagged_reason) VALUES (?,?,?,?,?,?,?)',
                  ('Maya Chen','555-1010','maya@example.com','21 South St','VIP fleet contact',0,''))
        customer_id = c.lastrowid
        c.execute('INSERT INTO vehicles (customer_id,year,make,model,vin,color,plate,notes) VALUES (?,?,?,?,?,?,?,?)',
                  (customer_id,'2022','Toyota','Camry','','White','8XYZ100','Front fender dent history'))
        vehicle_id = c.lastrowid
        c.execute('INSERT INTO leads (customer_name,phone,email,address,vehicle_year,make,model,damage_summary,preferred_timing,lead_source,notes,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  ('Jordan Brooks','555-2020','jordan@example.com','44 Pine Ave','2019','Honda','Civic','Hail dents on hood','This week AM','Google','Needs fast turnaround','new',datetime.utcnow().isoformat()))
        lead_id = c.lastrowid
        sched = datetime.utcnow().replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
        c.execute('INSERT INTO jobs (lead_id,customer_id,vehicle_id,service_address,scheduled_at,status,damage_summary,internal_notes,estimate_amount,invoice_amount,payment_status,mileage,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (lead_id,customer_id,vehicle_id,'21 South St',sched,'scheduled','Door ding on passenger side','Bring glue pull kit',250,0,'unpaid',12.5,datetime.utcnow().isoformat()))
        job_id = c.lastrowid
        c.execute('INSERT INTO activity_logs (job_id,event,created_at) VALUES (?,?,?)', (job_id, 'Job created from seed data', datetime.utcnow().isoformat()))
        c.execute('INSERT INTO message_templates (type,title,content) VALUES (?,?,?)', ('reminder','Appointment Reminder','Hi {{name}}, reminder for your dent repair on {{date}}.'))
        c.execute('INSERT INTO estimates (lead_id,job_id,status,created_at) VALUES (?,?,?,?)', (lead_id, job_id, 'draft', datetime.utcnow().isoformat()))
    conn.commit(); conn.close()


def parse_cookies(environ):
    raw = environ.get('HTTP_COOKIE', '')
    cookies = {}
    for item in raw.split(';'):
        if '=' in item:
            k, v = item.strip().split('=', 1); cookies[k] = v
    return cookies


def get_user(environ):
    sid = parse_cookies(environ).get('session_id')
    if not sid: return None
    conn = db(); c = conn.cursor()
    row = c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=?', (sid,)).fetchone()
    conn.close()
    return row


def require_auth(environ):
    return get_user(environ) is not None


def html_page(title, body, user=None):
    nav = '' if not user else '''<nav class="bottom-nav">
        <a href="/dashboard"><span>🏠</span><small>Dashboard</small></a>
        <a href="/leads"><span>🎯</span><small>Leads</small></a>
        <a href="/jobs"><span>🛠️</span><small>Jobs</small></a>
        <a href="/customers"><span>👥</span><small>Customers</small></a>
        <a href="/billing"><span>💵</span><small>Billing</small></a>
    </nav>'''
    top = '' if not user else f'''<header class="topbar"><div><p class="eyebrow">The Dent Trooper</p><h1>{title}</h1></div><a class="logout" href="/logout">Log out</a></header>'''
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"/><title>{title}</title><link rel="stylesheet" href="/static/app.css"></head><body><main>{top}<section class="view">{body}</section></main>{nav}</body></html>'''.encode()


def redirect(start_response, location, cookie=None):
    headers=[('Location', location)]
    if cookie: headers.append(('Set-Cookie', cookie))
    start_response('302 Found', headers)
    return [b'']


def parse_post(environ):
    try:
        size = int(environ.get('CONTENT_LENGTH', 0))
    except: size = 0
    data = environ['wsgi.input'].read(size)
    return {k: v[0] for k, v in parse_qs(data.decode()).items()}


def has_conflict(conn, scheduled_at, job_id=None):
    q='SELECT id FROM jobs WHERE scheduled_at=? AND status NOT IN ("cancelled","paid")'
    args=[scheduled_at]
    if job_id:
        q += ' AND id != ?'; args.append(job_id)
    return conn.execute(q,args).fetchone() is not None


def app(environ, start_response):
    init_db()
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD','GET')
    user = get_user(environ)

    if path.startswith('/static/'):
        fp = path.lstrip('/')
        if os.path.exists(fp):
            start_response('200 OK', [('Content-Type','text/css')]); return [open(fp,'rb').read()]
        start_response('404 Not Found',[]); return [b'']
    if path.startswith('/uploads/'):
        fp = path.lstrip('/')
        if os.path.exists(fp):
            start_response('200 OK', [('Content-Type','image/jpeg')]); return [open(fp,'rb').read()]
        start_response('404 Not Found',[]); return [b'']

    if path == '/':
        return redirect(start_response, '/dashboard' if user else '/login')

    if path == '/login' and method == 'GET':
        body='''<h1>The Dent Trooper</h1><form method="post"><input name="email" placeholder="Email" required><input name="password" type="password" placeholder="Password" required><button>Log in</button><p>Demo: admin@denttrooper.local / changeme123</p></form>'''
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Login', body)]

    if path == '/login' and method == 'POST':
        data = parse_post(environ)
        conn=db(); c=conn.cursor(); row = c.execute('SELECT * FROM users WHERE email=?',(data.get('email',''),)).fetchone()
        if row and verify_password(data.get('password',''), row['password_hash']):
            sid = secrets.token_hex(24)
            c.execute('INSERT INTO sessions (id,user_id,created_at) VALUES (?,?,?)',(sid,row['id'],datetime.utcnow().isoformat())); conn.commit(); conn.close()
            return redirect(start_response,'/dashboard',f'session_id={sid}; HttpOnly; Path=/; SameSite=Lax')
        conn.close(); start_response('401 Unauthorized',[('Content-Type','text/html')]); return [html_page('Login','<p>Invalid credentials</p><a href="/login">Try again</a>')]

    if path == '/logout':
        return redirect(start_response,'/login','session_id=; expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/')

    if not require_auth(environ):
        return redirect(start_response,'/login')

    conn = db(); c = conn.cursor()

    if path == '/dashboard':
        counts = {
            'leads': c.execute('SELECT COUNT(*) n FROM leads').fetchone()['n'],
            'jobs': c.execute('SELECT COUNT(*) n FROM jobs').fetchone()['n'],
            'customers': c.execute('SELECT COUNT(*) n FROM customers').fetchone()['n'],
            'invoices': c.execute('SELECT COUNT(*) n FROM invoices').fetchone()['n'],
        }
        upcoming = c.execute('SELECT j.id,j.scheduled_at,j.status,coalesce(cu.name,l.customer_name) as customer FROM jobs j LEFT JOIN customers cu ON cu.id=j.customer_id LEFT JOIN leads l ON l.id=j.lead_id ORDER BY scheduled_at LIMIT 5').fetchall()
        cards=''.join([f'<a class="card" href="/{k}"><h3>{k.title()}</h3><p>{v}</p></a>' for k,v in counts.items()])
        up=''.join([f'<li><a href="/jobs/{r["id"]}">{r["customer"]} - {r["scheduled_at"]} ({r["status"]})</a></li>' for r in upcoming])
        body=f'<h1>Dashboard</h1><section class="grid">{cards}<a class="card" href="/calendar"><h3>Calendar</h3></a></section><h2>Upcoming jobs</h2><ul>{up or "<li>No jobs yet</li>"}</ul>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Dashboard',body,user)]

    if path == '/leads':
        if method == 'POST':
            d=parse_post(environ)
            c.execute('INSERT INTO leads (customer_name,phone,email,address,vehicle_year,make,model,damage_summary,preferred_timing,lead_source,notes,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (d.get('customer_name'),d.get('phone'),d.get('email'),d.get('address'),d.get('vehicle_year'),d.get('make'),d.get('model'),d.get('damage_summary'),d.get('preferred_timing'),d.get('lead_source'),d.get('notes'),d.get('status','new'),datetime.utcnow().isoformat()))
            conn.commit(); return redirect(start_response,'/leads')
        leads = c.execute('SELECT * FROM leads ORDER BY id DESC').fetchall()
        rows=''.join([f'<li><a href="/leads/{r["id"]}">{r["customer_name"]} - {r["status"]}</a></li>' for r in leads])
        form='''<h2>New lead</h2><form method="post" class="stack">'''+''.join([f'<input name="{f}" placeholder="{f.replace("_"," ").title()}">' for f in ['customer_name','phone','email','address','vehicle_year','make','model','preferred_timing','lead_source']])+'''<textarea name="damage_summary" placeholder="Damage summary"></textarea><textarea name="notes" placeholder="Internal notes"></textarea><select name="status">'''+''.join([f'<option>{s}</option>' for s in LEAD_STATUSES])+'''</select><button>Create lead</button></form>'''
        body=f'<h1>Leads</h1><ul>{rows or "<li>No leads</li>"}</ul>{form}'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Leads',body,user)]

    if path.startswith('/leads/') and path.endswith('/convert') and method == 'POST':
        lead_id = int(path.split('/')[2])
        l = c.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
        if not l: start_response('404 Not Found',[]); return [b'']
        c.execute('INSERT INTO customers (name,phone,email,address,notes,flagged,flagged_reason) VALUES (?,?,?,?,?,?,?)', (l['customer_name'],l['phone'],l['email'],l['address'],l['notes'],0,''))
        cid = c.lastrowid
        c.execute('INSERT INTO vehicles (customer_id,year,make,model,vin,color,plate,notes) VALUES (?,?,?,?,?,?,?,?)', (cid,l['vehicle_year'],l['make'],l['model'],'','','',l['damage_summary']))
        vid = c.lastrowid
        c.execute('INSERT INTO jobs (lead_id,customer_id,vehicle_id,service_address,scheduled_at,status,damage_summary,internal_notes,estimate_amount,invoice_amount,payment_status,mileage,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (lead_id,cid,vid,l['address'],'','scheduled',l['damage_summary'],l['notes'],0,0,'unpaid',0,datetime.utcnow().isoformat()))
        jid = c.lastrowid
        c.execute('UPDATE leads SET status=? WHERE id=?', ('scheduled', lead_id))
        c.execute('INSERT INTO activity_logs (job_id,event,created_at) VALUES (?,?,?)', (jid,'Converted from lead',datetime.utcnow().isoformat()))
        conn.commit(); return redirect(start_response,f'/jobs/{jid}')

    if path.startswith('/leads/'):
        lead_id=int(path.split('/')[2]); l=c.execute('SELECT * FROM leads WHERE id=?',(lead_id,)).fetchone()
        body=f'<h1>Lead #{lead_id}</h1><p>{l["customer_name"]} | {l["phone"]}</p><p>{l["damage_summary"]}</p><form method="post" action="/leads/{lead_id}/convert"><button>Convert to job</button></form>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Lead detail',body,user)]

    if path == '/customers':
        if method == 'POST':
            d=parse_post(environ); c.execute('INSERT INTO customers (name,phone,email,address,notes,flagged,flagged_reason) VALUES (?,?,?,?,?,?,?)',
            (d.get('name'),d.get('phone'),d.get('email'),d.get('address'),d.get('notes'),1 if d.get('flagged') else 0,d.get('flagged_reason'))); conn.commit(); return redirect(start_response,'/customers')
        rows=c.execute('SELECT * FROM customers ORDER BY id DESC').fetchall()
        lst=''.join([f'<li><a href="/customers/{r["id"]}">{"🚩" if r["flagged"] else ""}{r["name"]}</a></li>' for r in rows])
        body='<h1>Customers</h1><ul>'+ (lst or '<li>No customers</li>') + '</ul><h2>New customer</h2><form method="post" class="stack"><input name="name" required placeholder="Name"><input name="phone" placeholder="Phone"><input name="email" placeholder="Email"><input name="address" placeholder="Address"><textarea name="notes" placeholder="Internal notes"></textarea><label><input type="checkbox" name="flagged"> Flagged customer</label><input name="flagged_reason" placeholder="Flag reason"><button>Create customer</button></form>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Customers',body,user)]

    if path.startswith('/customers/'):
        cid=int(path.split('/')[2]); cu=c.execute('SELECT * FROM customers WHERE id=?',(cid,)).fetchone(); veh=c.execute('SELECT * FROM vehicles WHERE customer_id=?',(cid,)).fetchall(); jobs=c.execute('SELECT * FROM jobs WHERE customer_id=?',(cid,)).fetchall()
        warning = f'<p class="flag">⚠️ {cu["flagged_reason"]}</p>' if cu['flagged'] else ''
        body=f'<h1>{cu["name"]}</h1>{warning}<p>{cu["phone"]} · {cu["email"]}</p><h2>Vehicles</h2><ul>'+''.join([f'<li>{v["year"]} {v["make"]} {v["model"]}</li>' for v in veh])+'</ul><h2>Jobs</h2><ul>'+''.join([f'<li><a href="/jobs/{j["id"]}">Job #{j["id"]} {j["status"]}</a></li>' for j in jobs])+'</ul>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Customer detail',body,user)]

    if path == '/jobs':
        if method == 'POST':
            d=parse_post(environ)
            if d.get('scheduled_at') and has_conflict(conn,d.get('scheduled_at')):
                start_response('400 Bad Request',[('Content-Type','text/html')]); return [html_page('Jobs','<p>Schedule conflict detected.</p><a href="/jobs">Back</a>',user)]
            c.execute('INSERT INTO jobs (customer_id,vehicle_id,service_address,scheduled_at,status,damage_summary,internal_notes,estimate_amount,invoice_amount,payment_status,mileage,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (d.get('customer_id') or None,d.get('vehicle_id') or None,d.get('service_address'),d.get('scheduled_at'),d.get('status','scheduled'),d.get('damage_summary'),d.get('internal_notes'),float(d.get('estimate_amount') or 0),float(d.get('invoice_amount') or 0),d.get('payment_status','unpaid'),float(d.get('mileage') or 0),datetime.utcnow().isoformat()))
            jid=c.lastrowid; c.execute('INSERT INTO activity_logs (job_id,event,created_at) VALUES (?,?,?)',(jid,'Job created manually',datetime.utcnow().isoformat())); conn.commit(); return redirect(start_response,f'/jobs/{jid}')
        jobs=c.execute('SELECT j.*, coalesce(cu.name,l.customer_name,"Unknown") cname FROM jobs j LEFT JOIN customers cu ON cu.id=j.customer_id LEFT JOIN leads l ON l.id=j.lead_id ORDER BY j.id DESC').fetchall()
        customers=c.execute('SELECT id,name FROM customers').fetchall(); vehicles=c.execute('SELECT id,year,make,model FROM vehicles').fetchall()
        body='<h1>Jobs</h1><ul>'+''.join([f'<li><a href="/jobs/{j["id"]}">#{j["id"]} {j["cname"]} - {j["status"]}</a></li>' for j in jobs])+'</ul><h2>New job</h2><form method="post" class="stack"><input name="service_address" placeholder="Service address"><input type="datetime-local" name="scheduled_at"><select name="customer_id"><option value="">Customer</option>'+''.join([f'<option value="{r["id"]}">{r["name"]}</option>' for r in customers])+'</select><select name="vehicle_id"><option value="">Vehicle</option>'+''.join([f'<option value="{v["id"]}">{v["year"]} {v["make"]} {v["model"]}</option>' for v in vehicles])+'</select><select name="status">'+''.join([f'<option>{s}</option>' for s in JOB_STATUSES])+'</select><textarea name="damage_summary" placeholder="Damage summary"></textarea><textarea name="internal_notes" placeholder="Internal notes"></textarea><input name="estimate_amount" type="number" step="0.01" placeholder="Estimate amount"><input name="invoice_amount" type="number" step="0.01" placeholder="Invoice amount"><input name="mileage" type="number" step="0.1" placeholder="Mileage"><button>Create job</button></form>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Jobs',body,user)]

    if path.startswith('/jobs/') and path.endswith('/photo') and method == 'POST':
        jid=int(path.split('/')[2])
        form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ, keep_blank_values=True)
        kind=form.getvalue('kind') or 'before'; upload=form['photo'] if 'photo' in form else None
        if upload is not None and getattr(upload,'filename',None):
            ext = os.path.splitext(upload.filename)[1] or '.jpg'
            fname=f'{jid}_{int(datetime.utcnow().timestamp())}_{secrets.token_hex(4)}{ext}'
            full=os.path.join(UPLOAD_DIR,fname)
            with open(full,'wb') as f: f.write(upload.file.read())
            c.execute('INSERT INTO job_photos (job_id,kind,file_path,created_at) VALUES (?,?,?,?)',(jid,kind,f'/{UPLOAD_DIR}/{fname}',datetime.utcnow().isoformat())); conn.commit()
        return redirect(start_response,f'/jobs/{jid}')

    if path.startswith('/jobs/') and path.endswith('/note') and method == 'POST':
        jid=int(path.split('/')[2]); d=parse_post(environ)
        c.execute('INSERT INTO notes (entity_type,entity_id,content,created_at) VALUES (?,?,?,?)',('job',jid,d.get('content',''),datetime.utcnow().isoformat())); conn.commit()
        return redirect(start_response,f'/jobs/{jid}')

    if path.startswith('/jobs/'):
        jid=int(path.split('/')[2]); j=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone();
        if method=='POST':
            d=parse_post(environ)
            scheduled=d.get('scheduled_at')
            if scheduled and has_conflict(conn,scheduled,jid):
                start_response('400 Bad Request',[('Content-Type','text/html')]); return [html_page('Job','<p>Schedule conflict detected.</p>',user)]
            c.execute('UPDATE jobs SET service_address=?,scheduled_at=?,status=?,damage_summary=?,internal_notes=?,estimate_amount=?,invoice_amount=?,payment_status=?,mileage=? WHERE id=?',
            (d.get('service_address'),scheduled,d.get('status'),d.get('damage_summary'),d.get('internal_notes'),float(d.get('estimate_amount') or 0),float(d.get('invoice_amount') or 0),d.get('payment_status'),float(d.get('mileage') or 0),jid))
            c.execute('INSERT INTO activity_logs (job_id,event,created_at) VALUES (?,?,?)',(jid,'Job updated',datetime.utcnow().isoformat())); conn.commit(); return redirect(start_response,f'/jobs/{jid}')
        photos=c.execute('SELECT * FROM job_photos WHERE job_id=? ORDER BY id DESC',(jid,)).fetchall(); logs=c.execute('SELECT * FROM activity_logs WHERE job_id=? ORDER BY id DESC',(jid,)).fetchall(); notes=c.execute('SELECT * FROM notes WHERE entity_type="job" AND entity_id=? ORDER BY id DESC',(jid,)).fetchall()
        phtml=''.join([f'<img src="{p["file_path"]}" class="thumb" alt="photo">' for p in photos])
        nhtml=''.join([f'<li>{n["content"]}</li>' for n in notes])
        lhtml=''.join([f'<li>{a["created_at"]}: {a["event"]}</li>' for a in logs])
        body=f'<h1>Job #{jid}</h1><form method="post" class="stack"><input name="service_address" value="{j["service_address"] or ""}" placeholder="Service address"><input name="scheduled_at" value="{j["scheduled_at"] or ""}" placeholder="ISO datetime"><select name="status">'+''.join([f'<option {"selected" if j["status"]==s else ""}>{s}</option>' for s in JOB_STATUSES])+f'</select><textarea name="damage_summary">{j["damage_summary"] or ""}</textarea><textarea name="internal_notes">{j["internal_notes"] or ""}</textarea><input name="estimate_amount" type="number" step="0.01" value="{j["estimate_amount"] or 0}"><input name="invoice_amount" type="number" step="0.01" value="{j["invoice_amount"] or 0}"><input name="payment_status" value="{j["payment_status"] or ""}" placeholder="Payment status"><input name="mileage" type="number" step="0.1" value="{j["mileage"] or 0}"><button>Save</button></form><h2>Photos</h2><form method="post" action="/jobs/{jid}/photo" enctype="multipart/form-data" class="stack"><select name="kind"><option>before</option><option>after</option></select><input type="file" name="photo" accept="image/*" capture="environment"><button>Upload photo</button></form><div class="photos">{phtml}</div><h2>Internal notes</h2><form method="post" action="/jobs/{jid}/note"><textarea name="content"></textarea><button>Add note</button></form><ul>{nhtml}</ul><h2>Activity</h2><ul>{lhtml}</ul><a class="btn" href="/estimates/new?job_id={jid}">Create estimate</a>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Job detail',body,user)]

    if path == '/calendar':
        jobs = c.execute('SELECT id,scheduled_at,status FROM jobs WHERE scheduled_at != "" ORDER BY scheduled_at').fetchall()
        body='<h1>Schedule</h1><h2>Day/Upcoming</h2><ul>'+''.join([f'<li><a href="/jobs/{j["id"]}">{j["scheduled_at"]} - {j["status"]}</a></li>' for j in jobs])+'</ul>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Calendar',body,user)]

    if path == '/billing':
        est=c.execute('SELECT * FROM estimates ORDER BY id DESC').fetchall(); inv=c.execute('SELECT * FROM invoices ORDER BY id DESC').fetchall()
        body='<h1>Estimates & Invoices</h1><a class="btn" href="/estimates/new">New estimate</a><h2>Estimates</h2><ul>'+''.join([f'<li><a href="/estimates/{e["id"]}">Estimate #{e["id"]} ({e["status"]})</a></li>' for e in est])+'</ul><h2>Invoices</h2><ul>'+''.join([f'<li><a href="/invoices/{i["id"]}">Invoice #{i["id"]} ({i["status"]})</a></li>' for i in inv])+'</ul>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Billing',body,user)]

    if path == '/estimates/new':
        qs=parse_qs(environ.get('QUERY_STRING','')); job_id=(qs.get('job_id',[''])[0] or None)
        if method=='POST':
            d=parse_post(environ); c.execute('INSERT INTO estimates (lead_id,job_id,status,created_at) VALUES (?,?,?,?)',(None,d.get('job_id') or None,'draft',datetime.utcnow().isoformat())); eid=c.lastrowid
            for desc,qty,price in zip(d.get('desc','').split('|'), d.get('qty','').split('|'), d.get('price','').split('|')):
                if desc.strip(): c.execute('INSERT INTO estimate_line_items (estimate_id,description,quantity,unit_price) VALUES (?,?,?,?)',(eid,desc.strip(),float(qty or 1),float(price or 0)))
            conn.commit(); return redirect(start_response,f'/estimates/{eid}')
        body=f'<h1>New Estimate</h1><form method="post" class="stack"><input name="job_id" value="{job_id or ""}" placeholder="Job ID"><p>Line items as pipe-delimited for MVP</p><input name="desc" placeholder="Dent removal|Panel finishing"><input name="qty" placeholder="1|1"><input name="price" placeholder="200|50"><button>Create estimate</button></form>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('New estimate',body,user)]

    if path.startswith('/estimates/'):
        eid=int(path.split('/')[2]); e=c.execute('SELECT * FROM estimates WHERE id=?',(eid,)).fetchone(); items=c.execute('SELECT * FROM estimate_line_items WHERE estimate_id=?',(eid,)).fetchall(); total=sum(i['quantity']*i['unit_price'] for i in items)
        if method=='POST':
            c.execute('INSERT INTO invoices (estimate_id,job_id,status,created_at) VALUES (?,?,?,?)',(eid,e['job_id'],'draft',datetime.utcnow().isoformat())); iid=c.lastrowid
            for i in items: c.execute('INSERT INTO invoice_line_items (invoice_id,description,quantity,unit_price) VALUES (?,?,?,?)',(iid,i['description'],i['quantity'],i['unit_price']))
            conn.commit(); return redirect(start_response,f'/invoices/{iid}')
        rows=''.join([f'<li>{i["description"]}: {i["quantity"]} x ${i["unit_price"]}</li>' for i in items])
        body=f'<article class="printable"><h1>Estimate #{eid}</h1><ul>{rows}</ul><h3>Total: ${total:.2f}</h3><button onclick="window.print()">Print / PDF</button><form method="post"><button>Convert to invoice</button></form></article>'
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Estimate',body,user)]

    if path.startswith('/invoices/'):
        iid=int(path.split('/')[2]); inv=c.execute('SELECT * FROM invoices WHERE id=?',(iid,)).fetchone(); items=c.execute('SELECT * FROM invoice_line_items WHERE invoice_id=?',(iid,)).fetchall(); total=sum(i['quantity']*i['unit_price'] for i in items)
        if method=='POST':
            d=parse_post(environ); c.execute('UPDATE invoices SET status=? WHERE id=?',(d.get('status','draft'),iid)); conn.commit(); return redirect(start_response,f'/invoices/{iid}')
        rows=''.join([f'<li>{i["description"]}: {i["quantity"]} x ${i["unit_price"]}</li>' for i in items])
        body=f'<article class="printable"><h1>Invoice #{iid}</h1><ul>{rows}</ul><h3>Total: ${total:.2f}</h3><form method="post"><select name="status">'+''.join([f'<option {"selected" if inv["status"]==s else ""}>{s}</option>' for s in INVOICE_STATUSES])+'''</select><button>Update status</button></form><button onclick="window.print()">Print / PDF</button></article>'''
        start_response('200 OK',[('Content-Type','text/html')]); return [html_page('Invoice',body,user)]

    start_response('404 Not Found',[('Content-Type','text/plain')]); return [b'Not found']


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', '8000'))
    print(f'The Dent Trooper running on http://localhost:{port}')
    make_server('0.0.0.0', port, app).serve_forever()
