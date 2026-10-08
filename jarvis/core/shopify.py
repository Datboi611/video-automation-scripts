"""Shopify (Admin API) con un token de app personalizada: ventas, pedidos e inventario."""
import datetime as dt
import logging
import time

import requests

log = logging.getLogger("jarvis")
VERSION = "2025-07"
PUERTO_OAUTH = 8788
REDIRECCION = f"http://localhost:{PUERTO_OAUTH}/shopify"
ALCANCES = "read_orders,read_products,read_inventory,read_customers"


class Shopify:
    def __init__(self, tienda, token=None, client_id=None, client_secret=None):
        self.tienda = (tienda or "").replace("https://", "").strip("/ ")
        if self.tienda and "." not in self.tienda:
            self.tienda += ".myshopify.com"
        self.token = (token or "").strip()
        self.client_id, self.client_secret = (client_id or "").strip(), (client_secret or "").strip()
        self._vence = 0

    @property
    def listo(self):
        return bool(self.tienda and (self.token or (self.client_id and self.client_secret)))

    def _renovar(self):
        """Apps del Dev Dashboard: token por 'client credentials' (dura ~24 h); se renueva solo."""
        if not (self.client_id and self.client_secret) or time.time() < self._vence:
            return
        if self.token.startswith("shpat_"):
            return  # token permanente ya obtenido
        r = requests.post(f"https://{self.tienda}/admin/oauth/access_token", timeout=20,
                          data={"grant_type": "client_credentials", "client_id": self.client_id,
                                "client_secret": self.client_secret})
        r.raise_for_status()
        d = r.json()
        self.token = d["access_token"]
        self._vence = time.time() + int(d.get("expires_in", 86399)) - 300

    def autorizar(self, timeout=300):
        """Si 'client credentials' no está permitido (app de distribución personalizada), se usa el flujo
        normal de Shopify: se abre el navegador, el dueño aprueba y se obtiene un token permanente (shpat_)."""
        import http.server
        import secrets
        import urllib.parse
        import webbrowser
        estado, resultado = secrets.token_hex(8), {}

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                if q.get("state") == estado and q.get("code"):
                    resultado["code"] = q["code"]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>Listo. JARVIS ya tiene acceso a Shopify; puede cerrar esta pestaña.</h2>".encode())

        srv = http.server.HTTPServer(("127.0.0.1", PUERTO_OAUTH), H)
        srv.timeout = 2
        webbrowser.open(f"https://{self.tienda}/admin/oauth/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id, "scope": ALCANCES, "redirect_uri": REDIRECCION, "state": estado}))
        fin = time.time() + timeout
        while "code" not in resultado and time.time() < fin:
            srv.handle_request()
        srv.server_close()
        if "code" not in resultado:
            raise RuntimeError("No se aprobó el acceso en el navegador a tiempo.")
        r = requests.post(f"https://{self.tienda}/admin/oauth/access_token", timeout=20, json={
            "client_id": self.client_id, "client_secret": self.client_secret, "code": resultado["code"]})
        r.raise_for_status()
        self.token = r.json()["access_token"]
        self._vence = float("inf")  # token permanente
        return self.token

    def _gql(self, query, variables=None):
        self._renovar()
        r = requests.post(f"https://{self.tienda}/admin/api/{VERSION}/graphql.json", timeout=25,
                          headers={"X-Shopify-Access-Token": self.token, "Content-Type": "application/json"},
                          json={"query": query, "variables": variables or {}})
        r.raise_for_status()
        d = r.json()
        if d.get("errors"):
            raise RuntimeError(str(d["errors"])[:300])
        return d["data"]

    def _pedidos(self, desde, n=100):
        q = """query($q:String!,$n:Int!){orders(first:$n,query:$q,sortKey:CREATED_AT,reverse:true){edges{node{
               name createdAt displayFinancialStatus displayFulfillmentStatus
               totalPriceSet{shopMoney{amount currencyCode}} customer{displayName}
               lineItems(first:5){edges{node{title quantity}}}}}}}"""
        d = self._gql(q, {"q": f"created_at:>={desde}", "n": n})
        return [e["node"] for e in d["orders"]["edges"]]

    def ventas(self, dias=1):
        desde = (dt.date.today() - dt.timedelta(days=max(1, int(dias)) - 1)).isoformat()
        ps = self._pedidos(desde)
        if not ps:
            return f"Sin pedidos desde {desde}."
        total = sum(float(p["totalPriceSet"]["shopMoney"]["amount"]) for p in ps)
        mon = ps[0]["totalPriceSet"]["shopMoney"]["currencyCode"]
        pend = sum(1 for p in ps if p["displayFulfillmentStatus"] in ("UNFULFILLED", "PARTIALLY_FULFILLED"))
        return (f"{'Hoy' if int(dias) <= 1 else f'Últimos {dias} días'}: {len(ps)} pedidos, {total:,.2f} {mon} "
                f"(promedio {total / len(ps):,.2f}). Sin enviar: {pend}.")

    def pedidos(self, n=5):
        ps = self._pedidos((dt.date.today() - dt.timedelta(days=30)).isoformat(), int(n))
        if not ps:
            return "Sin pedidos en los últimos 30 días."
        return "\n".join(
            f"{p['name']} · {(p.get('customer') or {}).get('displayName', 'cliente')} · "
            f"{p['totalPriceSet']['shopMoney']['amount']} {p['totalPriceSet']['shopMoney']['currencyCode']} · "
            f"{p['displayFinancialStatus']}/{p['displayFulfillmentStatus']} · "
            + ", ".join(f"{e['node']['quantity']}x {e['node']['title']}" for e in p["lineItems"]["edges"])
            for p in ps)

    def inventario(self, busqueda=""):
        q = """query($q:String){products(first:10,query:$q){edges{node{title status totalInventory
               variants(first:5){edges{node{title inventoryQuantity price}}}}}}}"""
        d = self._gql(q, {"q": busqueda or None})
        ps = [e["node"] for e in d["products"]["edges"]]
        if not ps:
            return f"No encontré productos con '{busqueda}'."
        return "\n".join(f"{p['title']} ({p['status']}): {p['totalInventory']} en stock — "
                         + ", ".join(f"{v['node']['title']}: {v['node']['inventoryQuantity']} a {v['node']['price']}"
                                     for v in p["variants"]["edges"]) for p in ps)
