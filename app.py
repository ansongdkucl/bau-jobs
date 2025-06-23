import re
from flask import Flask, render_template, request, flash, redirect, url_for
from network_lookup import find_mac, find_port_description

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    # You can set up a default empty fields dict
    fields = {
        "host": "",
        "interface": "",
        "mac_address": "",
        "vlan": "",
        "description": "",
        "snmp_location": ""
    }
    return render_template("index.html", fields=fields)


@app.route("/search", methods=["POST"])
def search():
    query = request.form.get("query", "").strip()
    fields = {
        "host": "",
        "interface": "",
        "mac_address": "",
        "vlan": "",
        "description": "",
        "snmp_location": ""
    }
    if not query:
        flash("Please enter a search value.", "error")
        return render_template("index.html", fields=fields)
    mac_regex = r"^([0-9A-Fa-f]{2}([:\-\.]?)){5}[0-9A-Fa-f]{2}$"
    if re.match(mac_regex, query):
        result = find_mac(query)
        if result:
            fields.update({
                "host": result.get("host", ""),
                "interface": result.get("interface", ""),
                "mac_address": query,
                "vlan": result.get("vlan", ""),
                "description": result.get("description", ""),
                "snmp_location": result.get("snmp_location", "")
            })
            flash(f"MAC found on {result['host']} {result['interface']}", "success")
        else:
            flash("MAC address not found.", "error")
    else:
        matches = find_port_description(query)
        if matches:
            # Show the first match, or handle as you wish
            m = matches[0]
            fields.update({
                "host": m.get("host", ""),
                "interface": m.get("interface", ""),
                "mac_address": "",
                "vlan": "",
                "description": m.get("description", ""),
                "snmp_location": ""
            })
            flash(f"Description found: {m['host']} ({m['interface']}): {m['description']}", "success")
        else:
            flash("No matching port description found.", "error")
    return render_template("index.html", fields=fields)

if __name__ == "__main__":
    app.secret_key = "supersecret"
    app.run(debug=True, port=5000)
