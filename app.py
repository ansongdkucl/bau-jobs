from flask import Flask, render_template, request, redirect, url_for, flash
from network_lookup import find_mac, change_vlan_on_interface

app = Flask(__name__)
app.secret_key = "supersecret"  # Needed for flash messages

@app.route("/", methods=["GET", "POST"])
def index():
    fields = {
        "mac_address": "",
        "host": "",
        "interface": "",
        "long_interface": "",
        "vlan": "",
        "description": "",
        "router": "",
        "ip_address": "",
        "snmp_location": "",
        "interfaces_list": [],
        "vlans_list": []
    }
    error = None

    if request.method == "POST":
        mac_address = request.form.get("mac_address", "").strip()
        fields["mac_address"] = mac_address
        if not mac_address:
            error = "Please enter a MAC address."
        else:
            result = find_mac(mac_address)
            if result:
                fields.update(result)
            else:
                error = "MAC address not found."

    return render_template("index.html", fields=fields, error=error)

@app.route("/change_vlan", methods=["POST"])
def change_vlan():
    hostname = request.form.get("host")
    interface = request.form.get("long_interface")
    vlan_id = request.form.get("vlan")
    success, message = change_vlan_on_interface(hostname, interface, vlan_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)
