"""Shopify (Admin API) con un token de app personalizada: ventas, pedidos e inventario."""
import datetime as dt
import logging

import requests

log = logging.getLogger("jarvis")
VERSION = "2025-07"


class Shopify:
    def __init__(self, tienda, token):
        self.tienda = (tienda or "").replace("https://", "").strip("/ ")
        if self.tienda and "." not in self.tienda:
            self.tienda += ".myshopify.com"
        self.token = (token or "").strip()

    @property
    def listo(self):
        return bool(self.tienda and self.token)

    def _gql(self, query, variables=None):
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
