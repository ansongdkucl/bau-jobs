from flask import Flask, render_template, request, flash, redirect, url_for
from network_lookup import expand_interface, get_interface_details, find_mac, find_port_description, find_host
import re

app = Flask(__name__)
app.secret_key = "supersecret"

MAC_REGEX = r"^([0-9A-Fa-f]{2}([:\-\.]?)){5}[0-9A-Fa-f]{2}$"

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", fields={
        "host": "", "interface": "", "mac_address": "", "vlan": "",
        "description": "", "snmp_location": "", "available_vlans": [],
        "available_interfaces": []
    })

@app.route("/search", methods=["POST"])
def search():
    query = request.form.get("query", "").strip()
    fields = {
        "host": "", "interface": "", "mac_address": "", "vlan": "",
        "description": "", "snmp_location": "", "available_vlans": [],
        "available_interfaces": []
    }

    if not query:
        flash("Please enter a search value.", "error")
        return render_template("index.html", fields=fields)

    # Hostname search
    if query.lower() in [h.lower() for h in find_host.__globals__['nr'].inventory.hosts.keys()]:
        result = find_host(query)
        if result:
            fields = {
                "host": result.get("host", ""),
                "interface": "",
                "mac_address": "",
                "vlan": "",
                "description": "",
                "snmp_location": result.get("snmp_location", ""),
                "available_vlans": result.get("available_vlans", []),
                "available_interfaces": result.get("available_interfaces", [])
            }
            flash(f"Hostname found: {result['host']}", "success")
        else:
            flash("Hostname not found.", "error")
        return render_template("index.html", fields=fields)

    # MAC address search
    if re.match(MAC_REGEX, query):
        result = find_mac(query)
        if result:
            fields.update(result)
            flash(f"MAC found on {result['host']} {result['interface']}", "success")
        else:
            flash("MAC address not found.", "error")
        return render_template("index.html", fields=fields)

    # Port description search
    matches = find_port_description(query)
    if matches:
        details = get_interface_details(matches[0]['host'], matches[0]['interface'])
        fields.update(details)
        flash(f"Description found: {matches[0]['host']} ({matches[0]['interface']}): {matches[0]['description']}", "success")
    else:
        flash("No matching port description found.", "error")

    return render_template("index.html", fields=fields)

@app.route("/change_vlan", methods=["POST"])
def change_vlan():
    host = request.form.get("host")
    interface_short = request.form.get("interface")
    new_vlan = request.form.get("new_vlan")
    current_vlan = request.form.get("current_vlan")
    requested_interface = interface_short  # For template rendering

    interface = expand_interface(interface_short)

    # If the VLAN change button was NOT pressed, this is just an interface change
    if "change_vlan" not in request.form:
        fields = get_interface_details(host, interface)
        if fields:
            # Set the VLAN in the dropdown to match the interface's current VLAN
            new_vlan = fields.get('vlan', '')
            flash(f"Showing details for interface {interface_short}", "success")
            return render_template(
                "index.html",
                fields=fields,
                requested_interface=interface_short,
                requested_vlan=new_vlan
            )
        else:
            flash(f"Could not get details for interface {interface_short}", "error")
            return redirect(url_for('index'))

    # If the VLAN change button WAS pressed, proceed with VLAN change logic
    fields = get_interface_details(host, interface)

    if not all([host, interface_short, new_vlan]):
        flash("Missing data for VLAN change.", "error")
        return render_template("index.html", fields=fields)

    # If confirmation is not present, prompt for confirmation
    confirm = request.form.get("confirm")
    if not confirm:
        confirmation_message = (
            f"You have requested to change VLAN for host <b>{host}</b> "
            f"on interface <b>{interface_short}</b> to VLAN <b>{new_vlan}</b>."
        )
        return render_template(
            "index.html",
            fields=fields,
            confirmation_message=confirmation_message,
            requested_vlan=new_vlan,
            requested_interface=interface_short
        )

    # If confirmation is present, perform the VLAN change
    from nornir.core.filter import F
    from nornir_netmiko.tasks import netmiko_send_config
    target = find_host.__globals__['nr'].filter(F(name=host))
    cmds = [
        f"interface {interface}",
        f"switchport access vlan {new_vlan}",
        "exit"
    ]
    result = target.run(task=netmiko_send_config, config_commands=cmds)
    task = list(result.values())[0]
    print(f"Task result: {task.result}")

    if task.failed:
        print(f"Failed to change VLAN: {task.result}")
        flash(f"Failed to change VLAN: {task.result}", "error")
        return render_template("index.html", fields=fields)

    # Refresh actual data from device
    updated_fields = get_interface_details(host, interface)
    success_message = (
        f"You have successfully changed host <b>{host}</b> "
        f"on interface <b>{interface_short}</b> to VLAN <b>{new_vlan}</b>."
    )
    return render_template(
        "index.html",
        fields=updated_fields,
        success_message=success_message
    )

if __name__ == "__main__":
    app.run(debug=True, port=5005)
