import re
from flask import Flask, render_template, request, flash, redirect, url_for
from network_lookup import find_mac, find_port_description
from nornir import InitNornir
from nornir.core.filter import F  # Needed for filtering
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure
from network_lookup import expand_interface
from nornir_netmiko.tasks import netmiko_send_command
from nornir_netmiko.tasks import netmiko_send_config
nr = InitNornir(config_file="config.yaml")


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
        "snmp_location": "",
        "available_vlans": [],
        "available_interfaces": []
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
                "snmp_location": result.get("snmp_location", ""),
                "available_vlans": result.get("available_vlans", []),
                "available_interfaces": result.get("available_interfaces", [])
            })
            flash(f"MAC found on {result['host']} {result['interface']}", "success")
        else:
            flash("MAC address not found.", "error")

    else:
        matches = find_port_description(query)
        if matches:
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



@app.route("/change_vlan", methods=["POST"])
def change_vlan():
    host = request.form.get("host")
    interface = request.form.get("interface")
    new_vlan = request.form.get("new_vlan")

    fields = {
        "host": host,
        "interface": interface,
        "mac_address": "",
        "vlan": new_vlan,
        "description": "",
        "snmp_location": "",
        "available_vlans": []
    }

    if not all([host, interface, new_vlan]):
        flash("Missing data for VLAN change.", "error")
        return render_template("index.html", fields=fields)

    # Filter to the specific host
    target = nr.filter(F(name=host))

    # Build interface command (Cisco syntax)
    intf_full = expand_interface(interface)
    cmds = [
        f"interface {intf_full}",
        f"switchport access vlan {new_vlan}",
        "exit"
    ]

    result = target.run(task=netmiko_send_config, config_commands=cmds)
    task = list(result.values())[0]

    if task.failed:
        flash(f"Failed to change VLAN: {task.result}", "error")
    else:
        flash(f"Successfully changed {intf_full} to VLAN {new_vlan} on {host}", "success")

    return render_template("index.html", fields=fields)


if __name__ == "__main__":
    app.secret_key = "supersecret"
    app.run(debug=True, port=5000)
