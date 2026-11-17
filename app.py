import os, json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template, request, jsonify

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv('DATABASE_PATH', str(BASE_DIR / 'price_radar.db'))
REVIEW_WEBHOOK = os.getenv('N8N_REVIEW_WEBHOOK_URL', '').strip()
ALERT_WEBHOOK = os.getenv('N8N_PRICE_ALERT_WEBHOOK_URL', '').strip()
EMAIL_WEBHOOK = os.getenv('N8N_EMAIL_WEBHOOK_URL', '').strip()
app = Flask(__name__)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, marketplace TEXT NOT NULL,
          product_url TEXT, current_price REAL NOT NULL, target_price REAL,
          drop_amount REAL, alert_mode TEXT NOT NULL DEFAULT 'target',
          previous_price REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL,
          price REAL NOT NULL, source TEXT NOT NULL, checked_at TEXT NOT NULL,
          FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS product_listings (
          id TEXT PRIMARY KEY, product_id TEXT NOT NULL, marketplace TEXT NOT NULL,
          product_url TEXT NOT NULL, current_price REAL, previous_price REAL, source_status TEXT NOT NULL DEFAULT 'link_only',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL,
          message TEXT NOT NULL, price REAL NOT NULL, created_at TEXT NOT NULL,
          read INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(product_id) REFERENCES products(id)
        );
        ''')


        # Lightweight migrations keep existing databases usable.
        listing_columns = {r['name'] for r in con.execute('PRAGMA table_info(product_listings)')}
        if 'previous_price' not in listing_columns:
            con.execute('ALTER TABLE product_listings ADD COLUMN previous_price REAL')
        con.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('notification_email','')")


def rowdict(row):
    return dict(row) if row else None


def send_alert_to_n8n(payload):
    if not ALERT_WEBHOOK:
        return {'connected': False, 'reason': 'N8N_PRICE_ALERT_WEBHOOK_URL is not configured'}
    try:
        import requests
        response = requests.post(ALERT_WEBHOOK, json=payload, timeout=20)
        response.raise_for_status()
        try:
            return {'connected': True, 'response': response.json()}
        except ValueError:
            return {'connected': True, 'response': response.text[:500]}
    except Exception as exc:
        return {'connected': False, 'reason': str(exc)}


def evaluate_alert(product, previous_price, current_price, already_notified=False):
    # A target is a ceiling: any current price at or below it qualifies.
    # The caller deduplicates repeat alerts at the exact same observed price.
    target_hit = (
        product['target_price'] is not None
        and current_price <= float(product['target_price'])
        and not already_notified
    )
    drop_hit = (
        previous_price is not None and product['drop_amount'] is not None
        and (float(previous_price) - current_price) >= float(product['drop_amount'])
    )
    if product['alert_mode'] == 'target':
        return bool(target_hit), 'Target price reached'
    if product['alert_mode'] == 'drop':
        return bool(drop_hit), 'Price dropped by your selected amount'
    return bool(target_hit or drop_hit), 'Your price alert condition was met'


def already_target_notified(con, product_id, current_price):
    # Deduplicate the same alert at the same price, but allow a fresh notification
    # when the observed price changes while still satisfying the target.
    row = con.execute("SELECT 1 FROM notifications WHERE product_id=? AND ABS(price-?) < 0.005 LIMIT 1", (product_id, current_price)).fetchone()
    return row is not None


def local_review_analysis(reviews, product_name):
    """Calculate dependable metrics from supplied ratings and derive evidence-led aspects."""
    ratings = [int(r.get('rating', 0)) for r in reviews if str(r.get('rating', '')).isdigit() and 1 <= int(r.get('rating')) <= 5]
    total = len(ratings)
    positive = sum(x >= 4 for x in ratings)
    negative = sum(x <= 2 for x in ratings)
    neutral = total - positive - negative
    pct = lambda n: round(n * 100 / total) if total else 0
    aspects = {
        'Performance': (['performance','fast','smooth','multitask','boot','processor','lag'], 'positive'),
        'Display / Screen': (['display','screen'], 'positive'),
        'Heating': (['heat','heating','hot','overheat'], 'negative'),
        'Battery life': (['battery','drain','backup'], 'negative'),
        'Build quality': (['build','solid','premium'], 'positive'),
        'Keyboard': (['keyboard'], 'positive'),
        'Customer support': (['support','customer service'], 'negative'),
        'Speakers': (['speaker','audio'], 'mixed'),
        'Value for money': (['value for money','worth the price','value'], 'positive'),
    }
    aspect_rows=[]
    for name,(terms,direction) in aspects.items():
        matching=[r for r in reviews if any(t in (r.get('text') or '').lower() for t in terms)]
        if matching:
            aspect_rows.append({'aspect':name,'mentions':len(matching),'observation':
                ('Mostly positive mentions' if direction=='positive' else 'Recurring concern' if direction=='negative' else 'Mentioned as an area to assess') + f' across {len(matching)} of the supplied reviews.',
                'sentiment':direction})
    aspect_rows.sort(key=lambda x:x['mentions'], reverse=True)
    strengths=[f"{x['aspect']}: {x['observation']}" for x in aspect_rows if x['sentiment']=='positive']
    weaknesses=[f"{x['aspect']}: {x['observation']}" for x in aspect_rows if x['sentiment']=='negative']
    verdict=(f"Across {total} supplied reviews, feedback is mixed: {positive} positive, {neutral} neutral and {negative} negative. "
             + ("Check the recurring battery and heating complaints before buying." if any(x['aspect'] in ('Battery life','Heating') for x in aspect_rows) else "Consider the aspect-level feedback alongside your needs.")) if total else 'No valid rated reviews were available to analyse.'
    return {'product':product_name,'total_reviews':total,'sentiment':{
        'positive':{'count':positive,'percent':pct(positive)},'neutral':{'count':neutral,'percent':pct(neutral)},'negative':{'count':negative,'percent':pct(negative)}},
        'average_rating':round(sum(ratings)/total,1) if total else None,'strengths':strengths,'weaknesses':weaknesses,
        'aspect_analysis':aspect_rows,'common_topics':[{'topic':x['aspect'],'mentions':x['mentions']} for x in aspect_rows],
        'verdict':verdict,'summary':verdict}


@app.get('/health')
def health():
    return jsonify({'status': 'healthy', 'application': 'Price Radar AI'}), 200


@app.get('/')
def home():
    return render_template('index.html', review_ready=bool(REVIEW_WEBHOOK), alert_ready=bool(ALERT_WEBHOOK))


@app.get('/api/state')
def state():
    with db() as con:
        products = [dict(r) for r in con.execute('SELECT * FROM products ORDER BY created_at DESC')]
        notices = [dict(r) for r in con.execute('''SELECT n.*, p.name AS product_name FROM notifications n
                      JOIN products p ON p.id=n.product_id ORDER BY n.id DESC LIMIT 20''')]
        history = [dict(r) for r in con.execute('''SELECT h.*, p.name AS product_name FROM price_history h
                      JOIN products p ON p.id=h.product_id ORDER BY h.id DESC LIMIT 30''')]
        listings = [dict(r) for r in con.execute('SELECT * FROM product_listings ORDER BY created_at DESC')]
        email_row = con.execute("SELECT value FROM app_settings WHERE key='notification_email'").fetchone()
    return jsonify({'products': products, 'notifications': notices, 'history': history,
                    'review_n8n_ready': bool(REVIEW_WEBHOOK), 'alert_n8n_ready': bool(ALERT_WEBHOOK), 'email_n8n_ready': bool(EMAIL_WEBHOOK),
                    'notification_email': email_row['value'] if email_row else '', 'listings': listings})


@app.get('/api/products/<product_id>/history')
def product_history(product_id):
    with db() as con:
        exists = con.execute('SELECT id FROM products WHERE id=?', (product_id,)).fetchone()
        if not exists:
            return jsonify({'error': 'Tracked product not found.'}), 404
        rows = [dict(r) for r in con.execute('SELECT id,price,source,checked_at FROM price_history WHERE product_id=? ORDER BY checked_at ASC', (product_id,))]
    return jsonify({'history': rows})


@app.post('/api/products/<product_id>/listings')
def add_listing(product_id):
    data = request.get_json(force=True)
    marketplace = (data.get('marketplace') or '').strip()
    url = (data.get('product_url') or '').strip()
    if not marketplace or not url.startswith(('https://','http://')):
        return jsonify({'error': 'Enter a store name and a valid product URL.'}), 400
    try:
        price = float(data['current_price']) if data.get('current_price') not in (None, '') else None
        if price is not None and price <= 0: raise ValueError()
    except (TypeError, ValueError):
        return jsonify({'error': 'Listing price must be a positive number.'}), 400
    stamp, lid = now(), str(uuid.uuid4())
    with db() as con:
        if not con.execute('SELECT id FROM products WHERE id=?', (product_id,)).fetchone():
            return jsonify({'error': 'Tracked product not found.'}), 404
        con.execute('INSERT INTO product_listings(id,product_id,marketplace,product_url,current_price,previous_price,source_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (lid,product_id,marketplace,url,price,None,'link_only' if price is None else 'manual_observation',stamp,stamp))
    if price is not None:
        with db() as con:
            con.execute('INSERT INTO price_history(product_id,price,source,checked_at) VALUES(?,?,?,?)', (product_id,price,'Marketplace listing: '+marketplace,stamp))
    return jsonify({'ok': True, 'id': lid})


@app.post('/api/listings/<listing_id>/price')
def update_listing_price(listing_id):
    data = request.get_json(force=True)
    try: price = float(data.get('current_price'))
    except (TypeError, ValueError): return jsonify({'error': 'Enter a valid listing price.'}), 400
    if price <= 0: return jsonify({'error': 'Price must be greater than zero.'}), 400
    stamp = now()
    with db() as con:
        listing = con.execute('SELECT * FROM product_listings WHERE id=?', (listing_id,)).fetchone()
        if not listing: return jsonify({'error': 'Store listing not found.'}), 404
        product_row = con.execute('SELECT * FROM products WHERE id=?', (listing['product_id'],)).fetchone()
        product = dict(product_row)
        previous = float(listing['current_price']) if listing['current_price'] is not None else None
        triggered, reason = evaluate_alert(product, previous, price, already_target_notified(con, listing['product_id'], price))
        con.execute("UPDATE product_listings SET previous_price=current_price, current_price=?, source_status='manual_observation', updated_at=? WHERE id=?", (price,stamp,listing_id))
        con.execute('INSERT INTO price_history(product_id,price,source,checked_at) VALUES(?,?,?,?)', (listing['product_id'],price,'Marketplace listing: '+listing['marketplace'],stamp))
        if triggered:
            message = f"{product['name']} at {listing['marketplace']}: {reason}. Price is now ₹{price:,.2f}."
            con.execute('INSERT INTO notifications(product_id,message,price,created_at) VALUES(?,?,?,?)', (listing['product_id'],message,price,stamp))
        recipient_row = con.execute("SELECT value FROM app_settings WHERE key='notification_email'").fetchone()
        recipient = recipient_row['value'] if recipient_row else ''
    email_result = send_email_alert({'to': recipient, 'product': product['name'], 'marketplace': listing['marketplace'],
        'current_price': price, 'previous_price': previous, 'reason': reason, 'product_url': listing['product_url']}) if triggered else {'sent': False, 'reason': 'No alert triggered'}
    return jsonify({'ok': True, 'alert_triggered': triggered, 'email': email_result})


@app.delete('/api/listings/<listing_id>')
def delete_listing(listing_id):
    with db() as con: con.execute('DELETE FROM product_listings WHERE id=?', (listing_id,))
    return jsonify({'ok': True})


@app.post('/api/settings/email')
def save_email_setting():
    import re
    email = (request.get_json(force=True).get('email') or '').strip()
    if email and not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({'error': 'Enter a valid email address.'}), 400
    with db() as con:
        con.execute("INSERT INTO app_settings(key,value) VALUES('notification_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (email,))
    return jsonify({'ok': True, 'email': email, 'email_webhook_ready': bool(EMAIL_WEBHOOK)})


def send_email_alert(payload):
    if not EMAIL_WEBHOOK or not payload.get('to'):
        return {'sent': False, 'reason': 'Email webhook or recipient is not configured'}
    try:
        import requests
        response = requests.post(EMAIL_WEBHOOK, json=payload, timeout=20)
        response.raise_for_status()
        return {'sent': True}
    except Exception as exc:
        return {'sent': False, 'reason': str(exc)}


@app.post('/api/products')
def add_product():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    marketplace = (data.get('marketplace') or 'Other').strip()
    url = (data.get('product_url') or '').strip()
    try:
        price = float(data['current_price']) if data.get('current_price') not in (None, '') else 0.0
        target = float(data['target_price']) if data.get('target_price') not in (None, '') else None
        drop = float(data['drop_amount']) if data.get('drop_amount') not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter valid numeric prices.'}), 400
    mode = data.get('alert_mode', 'target')
    if not name or price < 0 or mode not in ('target', 'drop', 'either'):
        return jsonify({'error': 'Product name and a valid alert type are required. Starting price must be positive if supplied.'}), 400
    if mode in ('target', 'either') and (target is None or target <= 0):
        return jsonify({'error': 'Enter a valid target price for this alert type.'}), 400
    if mode in ('drop', 'either') and (drop is None or drop <= 0):
        return jsonify({'error': 'Enter a positive drop amount for this alert type.'}), 400
    pid, stamp = str(uuid.uuid4()), now()
    with db() as con:
        con.execute('''INSERT INTO products(id,name,marketplace,product_url,current_price,target_price,drop_amount,alert_mode,previous_price,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (pid,name,marketplace,url,price,target,drop,mode,None,stamp,stamp))
        if price > 0:
            con.execute('INSERT INTO price_history(product_id,price,source,checked_at) VALUES(?,?,?,?)', (pid,price,'Initial recorded price',stamp))
        initial_trigger = price > 0 and target is not None and price <= target and mode in ('target','either')
        recipient_row = con.execute("SELECT value FROM app_settings WHERE key='notification_email'").fetchone()
        recipient = recipient_row['value'] if recipient_row else ''
        if initial_trigger:
            msg = f"{name}: Target price reached. Current price is ₹{price:,.2f}."
            con.execute('INSERT INTO notifications(product_id,message,price,created_at) VALUES(?,?,?,?)',(pid,msg,price,stamp))
    email_result = send_email_alert({'to':recipient,'product':name,'marketplace':marketplace,'current_price':price,'previous_price':None,'reason':'Target price already met when added','product_url':url}) if initial_trigger else {'sent':False,'reason':'No initial target condition met'}
    return jsonify({'ok': True, 'id': pid, 'alert_triggered': initial_trigger, 'email':email_result})


@app.post('/api/price-update')
def price_update():
    data = request.get_json(force=True)
    pid = data.get('product_id')
    try:
        current = float(data.get('current_price'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Enter a valid current price.'}), 400
    if current <= 0:
        return jsonify({'error': 'Price must be greater than zero.'}), 400
    source = (data.get('source') or 'Demo price update').strip()
    with db() as con:
        product = con.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
        if not product:
            return jsonify({'error': 'Tracked product not found.'}), 404
        p = dict(product)
        previous = float(p['current_price'])
        triggered, reason = evaluate_alert(p, previous, current, already_target_notified(con, pid, current))
        stamp = now()
        con.execute('UPDATE products SET previous_price=?, current_price=?, updated_at=? WHERE id=?', (previous,current,stamp,pid))
        con.execute('INSERT INTO price_history(product_id,price,source,checked_at) VALUES(?,?,?,?)', (pid,current,source,stamp))
        if triggered:
            message = f"{p['name']}: {reason}. Price is now ₹{current:,.2f} (previously ₹{previous:,.2f})."
            con.execute('INSERT INTO notifications(product_id,message,price,created_at) VALUES(?,?,?,?)', (pid,message,current,stamp))
        recipient_row = con.execute("SELECT value FROM app_settings WHERE key='notification_email'").fetchone()
        recipient = recipient_row['value'] if recipient_row else ''
    payload = {'product_id': pid, 'product': p['name'], 'marketplace': p['marketplace'],
               'previous_price': previous, 'current_price': current, 'target_price': p['target_price'],
               'drop_amount': p['drop_amount'], 'alert_mode': p['alert_mode'],
               'alert_triggered': triggered, 'alert_reason': reason if triggered else None}
    n8n = send_alert_to_n8n(payload) if triggered else {'connected': False, 'reason': 'No alert triggered'}
    email_result = send_email_alert({'to': recipient, 'product': p['name'], 'marketplace': p['marketplace'],
        'current_price': current, 'previous_price': previous, 'reason': reason, 'product_url': p['product_url']}) if triggered else {'sent': False, 'reason': 'No alert triggered'}
    return jsonify({'ok': True, 'alert_triggered': triggered, 'reason': reason if triggered else None,
                    'n8n': n8n, 'email': email_result, 'message': payload['alert_reason']})


@app.post('/api/analyze/<product_id>')
def analyze_product(product_id):
    import csv
    path = BASE_DIR / 'sample_reviews.csv'
    reviews=[]
    with path.open(newline='',encoding='utf-8') as f:
        for idx,item in enumerate(csv.DictReader(f),1):
            reviews.append({'review_number':idx,'rating':int(item['rating']),'text':item['review'].strip(),'source':item.get('source','Sample dataset')})
    with db() as con:
        product=con.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
    if not product: return jsonify({'error':'Tracked product not found.'}),404
    p=dict(product)
    # Deterministic metrics and numbered review records are always returned;
    # the AI workflow is an optional enrichment, not a dependency for correctness.
    analysis=local_review_analysis(reviews,p['name'])
    mode='local-evidence-analysis'
    if REVIEW_WEBHOOK:
        try:
            import requests
            response=requests.post(REVIEW_WEBHOOK,json={'product':p['name'],'marketplace':p['marketplace'],'reviews':reviews,
                'source_note':'Bundled synthetic demonstration reviews; not live marketplace reviews.'},timeout=90)
            response.raise_for_status()
            body=response.json()
            ai=body.get('analysis',body) if isinstance(body,dict) else body
            if isinstance(ai,str):
                try: ai=json.loads(ai)
                except json.JSONDecodeError: ai={}
            if isinstance(ai,dict):
                # Only enrich narrative/aspect text. Never let AI overwrite calculated counts/percentages.
                for key in ('strengths','weaknesses','aspect_analysis','common_topics'):
                    if isinstance(ai.get(key), list): analysis[key]=ai[key]
                for key in ('verdict','summary'):
                    if isinstance(ai.get(key), str) and ai[key].strip(): analysis[key]=ai[key]
                mode='n8n-ai-enriched'
        except Exception:
            # A temporary n8n/model failure should not blank a useful report.
            mode='local-evidence-analysis (AI unavailable)'
    return jsonify({'mode':mode,'source':'Bundled synthetic sample reviews; not live marketplace reviews.','result':analysis,'reviews':reviews})


@app.post('/api/demo/run/<scenario>')
def run_demo_scenario(scenario):
    """Run isolated, illustrative scenarios without writing to the user's watchlist."""
    scenarios = {
        'target': {
            'title': 'Target price reached', 'product': 'Wireless headphones',
            'marketplace': 'Illustrative example', 'previous_price': 8000,
            'current_price': 6500, 'target_price': 6800, 'drop_amount': None,
            'alert_mode': 'target', 'alert_triggered': True,
            'reason': 'The new price is below your target of ₹6,800.'
        },
        'drop': {
            'title': 'Significant price drop', 'product': 'Smartphone',
            'marketplace': 'Illustrative example', 'previous_price': 30000,
            'current_price': 26500, 'target_price': None, 'drop_amount': 3000,
            'alert_mode': 'drop', 'alert_triggered': True,
            'reason': 'The price dropped by ₹3,500, exceeding your ₹3,000 threshold.'
        }
    }
    if scenario in scenarios:
        result = dict(scenarios[scenario])
        result['notice'] = 'Illustrative values only. This scenario does not change your watchlist or database.'
        # Demonstration-only: do not send synthetic scenarios to a real notification workflow.
        return jsonify({'type': 'price', 'result': result})
    if scenario == 'reviews':
        import csv
        path = BASE_DIR / 'sample_reviews.csv'
        reviews = []
        with path.open(newline='', encoding='utf-8') as f:
            for item in csv.DictReader(f):
                reviews.append({'rating': int(item['rating']), 'text': item['review'], 'source': item.get('source', 'Illustrative sample')})
        source_note = 'Illustrative sample review set. These are not live marketplace reviews.'
        if REVIEW_WEBHOOK:
            try:
                import requests
                response = requests.post(REVIEW_WEBHOOK, json={'product': 'Laptop review example', 'marketplace': 'Illustrative example', 'reviews': reviews, 'source_note': source_note}, timeout=90)
                response.raise_for_status()
                body = response.json()
                analysis = body.get('analysis', body) if isinstance(body, dict) else body
                if isinstance(analysis, str):
                    try: analysis = json.loads(analysis)
                    except json.JSONDecodeError: analysis = {'summary': analysis, 'verdict': analysis}
                return jsonify({'type': 'review', 'mode': 'n8n-ai-agent', 'source': source_note, 'result': analysis})
            except Exception as exc:
                return jsonify({'error': f'Review AI workflow could not complete: {exc}'}), 502
        # A transparent local preview keeps the demo usable without spending AI credits.
        ratings = [r['rating'] for r in reviews]
        positive = sum(1 for x in ratings if x >= 4)
        negative = sum(1 for x in ratings if x <= 2)
        neutral = len(ratings) - positive - negative
        total = max(1, len(ratings))
        analysis = {
            'product': 'Laptop review example', 'total_reviews': len(ratings),
            'sentiment': {
                'positive': {'count': positive, 'percent': round(positive * 100 / total)},
                'neutral': {'count': neutral, 'percent': round(neutral * 100 / total)},
                'negative': {'count': negative, 'percent': round(negative * 100 / total)}
            },
            'average_rating': round(sum(ratings) / total, 1),
            'strengths': ['Performance and everyday usability are recurring positive themes in this sample.'],
            'weaknesses': ['Battery life and heat are recurring points to check in the sample feedback.'],
            'verdict': 'Preview only: use the source reviews and a connected AI workflow for a fuller evidence-based assessment.',
            'summary': 'A local preview was generated from the bundled illustrative review set.'
        }
        return jsonify({'type': 'review', 'mode': 'local-preview', 'source': source_note, 'result': analysis})
    return jsonify({'error': 'Unknown demo scenario.'}), 404


@app.get('/api/demo/smartphone')
def demo_smartphone():
    from datetime import timedelta
    # Six months of simulated weekly observations, clearly isolated from user data.
    today=datetime.now(timezone.utc).date()
    prices=[32999,32499,31999,31499,30999,31499,30499,29999,29499,29999,28999,28499,27999,
            28499,27499,26999,27499,26499,25999,26499,25499,24999,25499,24499,24999,23999]
    history=[]
    for i,value in enumerate(prices):
        day=today-timedelta(days=(len(prices)-1-i)*7)
        history.append({'date':day.isoformat(),'price':value})
    current=prices[-1]
    demo_reviews=[
      {'review_number':1,'rating':5,'text':'Very smooth everyday performance, bright display and fast app loading.','source':'Synthetic demo review'},
      {'review_number':2,'rating':4,'text':'Camera and screen are good. Battery comfortably lasts most of the day.','source':'Synthetic demo review'},
      {'review_number':3,'rating':2,'text':'Phone warms up during long gaming sessions and heavy camera use.','source':'Synthetic demo review'},
      {'review_number':4,'rating':5,'text':'Premium build, responsive interface and excellent display for videos.','source':'Synthetic demo review'},
      {'review_number':5,'rating':3,'text':'Good phone overall, but charging could be faster.','source':'Synthetic demo review'},
      {'review_number':6,'rating':2,'text':'Battery drains faster when using 5G and navigation for long periods.','source':'Synthetic demo review'},
      {'review_number':7,'rating':4,'text':'Performance is reliable and multitasking feels smooth.','source':'Synthetic demo review'},
      {'review_number':8,'rating':3,'text':'Camera is decent, although low-light photos could be improved.','source':'Synthetic demo review'},
      {'review_number':9,'rating':5,'text':'Great screen, solid construction and good value at a discounted price.','source':'Synthetic demo review'},
      {'review_number':10,'rating':4,'text':'Fast and easy to use; speakers are average.','source':'Synthetic demo review'}]
    review_result=local_review_analysis(demo_reviews,'Nova X Pro Smartphone')
    return jsonify({'product':{'name':'Nova X Pro Smartphone','brand':'Nova','specs':['256 GB storage','AMOLED display','5G connectivity','Fast charging'],
        'current_price':current,'currency':'INR'},'history':history,'retailers':[
        {'store':'Amazon (illustrative)','price':current,'url':'https://www.amazon.in/'},
        {'store':'Flipkart (illustrative)','price':current+500,'url':'https://www.flipkart.com/'},
        {'store':'Brand store (illustrative)','price':current+1000,'url':'https://www.example.com/'}],
        'review_result':review_result,'reviews':demo_reviews,'review_source':'Synthetic demo reviews; not real customer feedback.',
        'notice':'SIMULATED DEMO DATA — six months of illustrative weekly prices, sample retailer prices and sample reviews. Not live marketplace data.'})


@app.get('/api/notifications')
def notifications():
    with db() as con:
        rows = [dict(r) for r in con.execute('''SELECT n.*, p.name AS product_name FROM notifications n
                    JOIN products p ON p.id=n.product_id ORDER BY n.id DESC LIMIT 50''')]
    return jsonify(rows)


@app.post('/api/notifications/<int:notice_id>/read')
def mark_read(notice_id):
    with db() as con:
        con.execute('UPDATE notifications SET read=1 WHERE id=?', (notice_id,))
    return jsonify({'ok': True})


@app.delete('/api/products/<product_id>')
def delete_product(product_id):
    with db() as con:
        con.execute('DELETE FROM product_listings WHERE product_id=?', (product_id,))
        con.execute('DELETE FROM notifications WHERE product_id=?', (product_id,))
        con.execute('DELETE FROM price_history WHERE product_id=?', (product_id,))
        con.execute('DELETE FROM products WHERE id=?', (product_id,))
    return jsonify({'ok': True})


init_db()
if __name__ == '__main__':
    app.run(host=os.getenv('APP_HOST', '0.0.0.0'), port=int(os.getenv('APP_PORT', '5000')), debug=os.getenv('FLASK_DEBUG', '0') == '1')
