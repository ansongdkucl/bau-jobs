from flask import Flask, render_template, request, flash
from network_lookup import (
    expand_interface,
    get_interface_details,
    find_mac,
    find_port_description,
    find_host,
    nr
)
from nornir_netmiko.tasks import netmiko_send_config, netmiko_send_command
from nornir.core.filter import F
import logging
import sys
from logging.handlers import RotatingFileHandler
import re

app = Flask(__name__)
app.secret_key = "supersecret"

log_file = "network_debug.log"
handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.setLevel(logging.DEBUG)

class StreamToLogger:
    def __init__(self, logger, level):
        self.logger = logger
        self.level = level
        self.linebuf = ''

    def write(self, message):
        if message.strip() != "":
            self.logger.log(self.level, message.strip())

    def flush(self):
        pass

sys.stdout = StreamToLogger(app.logger, logging.INFO)
sys.stderr = StreamToLogger(app.logger, logging.ERROR)

MAC_REGEX = r"^([0-9A-Fa-f]{2}([:\-\.]?)){5}[0-9A-Fa-f]{2}$"

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", fields={
        "host": "", 
        "interface": "", 
        "mac_address": "", 
        "vlan": "",
        "description": "", 
        "snmp_location": "", 
        "available_vlans": [],
        "available_interfaces": []
    })

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

    if query.lower() in [h.lower() for h in nr.inventory.hosts.keys()]:
        result = find_host(query)
        if result:
            fields.update(result)
            flash(f"Hostname found: {result['host']}", "success")
        else:
            flash("Hostname not found.", "error")
        return render_template("index.html", fields=fields)

    if re.match(MAC_REGEX, query):
        result = find_mac(query)
        if result:
            fields.update(result)
            flash(f"MAC found on {result['host']} {result['interface']}", "success")
        else:
            flash("MAC address not found.", "error")
        return render_template("index.html", fields=fields)

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
    confirm = request.form.get("confirm")

    interface = expand_interface(interface_short)
    fields = get_interface_details(host, interface)
    fields["interface"] = interface

    requested_vlan = new_vlan or fields.get('vlan', '')

    if not request.form.get("change_vlan"):
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=interface_short,
            requested_vlan=requested_vlan
        )

    if not new_vlan or new_vlan not in [str(v) for v in fields.get('available_vlans', [])]:
        flash("Invalid VLAN selection", "error")
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=interface_short,
            requested_vlan=requested_vlan
        )

    if not confirm:
        confirmation_message = (
            f"You have requested to change VLAN for host <b>{host}</b> "
            f"on interface <b>{interface_short}</b> from VLAN <b>{current_vlan}</b> "
            f"to VLAN <b>{new_vlan}</b>."
        )
        return render_template(
            "index.html",
            fields=fields,
            confirmation_message=confirmation_message,
            requested_interface=interface_short,
            requested_vlan=requested_vlan
        )

    try:
        target = nr.filter(F(name=host))
        app.logger.info(f"Changing VLAN on {host} {interface} from {current_vlan} to {new_vlan}")

        cmds = [
            f"interface {interface}",
            f"switchport access vlan {new_vlan}",
            "end"
        ]

        config_result = target.run(task=netmiko_send_config, config_commands=cmds)
        task = list(config_result.values())[0]

        if task.failed:
            flash(f"Failed to change VLAN: {task.result}", "error")
            return render_template(
                "index.html",
                fields=fields,
                requested_interface=interface_short,
                requested_vlan=requested_vlan
            )

        show_cmd = f"show interfaces {interface} switchport"
        show_result = target.run(task=netmiko_send_command, command_string=show_cmd)
        show_output = list(show_result.values())[0].result

        updated_fields = get_interface_details(host, interface)
        updated_fields["interface"] = interface

        success_message = (
            f"Successfully changed VLAN on {host} interface {interface_short} "
            f"from {current_vlan} to {new_vlan}.<br>"
            f"<b>Config output:</b><br><pre>{task.result}</pre>"
            f"<b>Verification output:</b><br><pre>{show_output}</pre>"
        )

        return render_template(
            "index.html",
            fields=updated_fields,
            success_message=success_message,
            netmiko_output=task.result,
            requested_interface=interface_short,
            requested_vlan=requested_vlan
        )

    except Exception as e:
        app.logger.error(f"VLAN change error: {str(e)}")
        flash(f"VLAN change failed: {str(e)}", "error")
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=interface_short,
            requested_vlan=requested_vlan
        )

@app.route("/refresh-interface", methods=["POST"])
def refresh_interface():
    host = request.form.get("host")
    interface_short = request.form.get("interface")
    interface = expand_interface(interface_short)

    fields = get_interface_details(host, interface)
    fields["interface"] = interface

    return render_template(
        "index.html",
        fields=fields,
        requested_interface=interface_short,
        requested_vlan=fields.get("vlan")
    )

if __name__ == "__main__":
    app.run(debug=True, port=5001)
