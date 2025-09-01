from flask import Flask, render_template, request, flash
from network_lookup import (
    expand_interface,
    get_interface_details,
    find_mac,
    find_port_description,
    find_host,
    nr,
    INTERFACE_MAP
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
    requested_interface = ""

    if not query:
        flash("Please enter a search value.", "error")
        return render_template("index.html", fields=fields)

    # Hostname search
    if query.lower() in [h.lower() for h in nr.inventory.hosts.keys()]:
        result = find_host(query)
        if result:
            fields.update(result)
            flash(f"Hostname found: {result['host']}", "success")
        else:
            flash("Hostname not found.", "error")
        # This path has a return, which is good.
        return render_template("index.html", fields=fields)

    # MAC Address search
    if re.match(MAC_REGEX, query):
        result = find_mac(query)
        if result:
            long_name = result['interface']
            requested_interface = long_name
            for short, long_val in INTERFACE_MAP.items():
                if long_name.lower().startswith(long_val.lower()):
                    # Use .replace() on the original case string but with lowercased search terms
                    requested_interface = long_name.replace(long_val, short, 1)
                    break
            fields.update(result)
            flash(f"MAC found on {result['host']} {result['interface']}", "success")
        else:
            flash("MAC address not found.", "error")
        # This path also has a return, which is good.
        return render_template("index.html", fields=fields, requested_interface=requested_interface)

    # --- THIS IS THE CORRECTED SECTION ---
    # Default to port description search
    matches = find_port_description(query)
    if matches:
        first_match = matches[0]
        details = get_interface_details(first_match['host'], first_match['interface'])
        
        long_name = first_match['interface']
        requested_interface = long_name
        for short, long_val in INTERFACE_MAP.items():
            if long_name.lower().startswith(long_val.lower()):
                requested_interface = long_name.replace(long_val, short, 1)
                break

        fields.update(details)
        flash(f"Description found: {first_match['host']} ({first_match['interface']}): {first_match['description']}", "success")
    else:
        flash("No matching port description found.", "error")

    # THIS RETURN STATEMENT IS CRITICAL. It handles the return for the port
    # description search path, whether a match was found or not.
    return render_template("index.html", fields=fields, requested_interface=requested_interface)


@app.route("/change_vlan", methods=["POST"])
def change_vlan():
    host = request.form.get("host")
    interface_short = request.form.get("interface")
    new_vlan = request.form.get("new_vlan")
    current_vlan = request.form.get("current_vlan")
    confirm = request.form.get("confirm")
    new_description = request.form.get("new_description", "").strip()

    interface = expand_interface(interface_short)
    fields = get_interface_details(host, interface)

    # Always maintain the original interface selection
    fields["interface"] = interface
    requested_interface = interface_short

    if not request.form.get("change_vlan"):
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=requested_interface,
            requested_vlan=new_vlan or fields.get('vlan', ''),
            requested_description=new_description
        )

    if not new_vlan or new_vlan not in [str(v) for v in fields.get('available_vlans', [])]:
        flash("Invalid VLAN selection", "error")
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=requested_interface,
            requested_vlan=new_vlan or fields.get('vlan', ''),
            requested_description=new_description
        )

    if not confirm:
        confirmation_message = (
            f"You have requested to change VLAN for host <b>{host}</b> "
            f"on interface <b>{interface_short}</b> from VLAN <b>{current_vlan}</b> "
            f"to VLAN <b>{new_vlan}</b>."
        )
        if new_description:
            confirmation_message += f"<br>You also requested to change the description to: <b>{new_description}</b>"

        return render_template(
            "index.html",
            fields=fields,
            confirmation_message=confirmation_message,
            requested_interface=requested_interface,
            requested_vlan=new_vlan,
            requested_description=new_description
        )

    try:
        target = nr.filter(F(name=host))
        app.logger.info(f"Changing VLAN on {host} {interface} from {current_vlan} to {new_vlan}")
        if new_description:
            app.logger.info(f"Updating description to: {new_description}")

        cmds = [
            f"interface {interface}",
            f"switchport access vlan {new_vlan}"
        ]
        if new_description:
            cmds.append(f"description {new_description}")
        cmds.append("end")

        config_result = target.run(task=netmiko_send_config, config_commands=cmds)
        task = list(config_result.values())[0]

        if task.failed:
            flash(f"Failed to change VLAN: {task.result}", "error")
            return render_template(
                "index.html",
                fields=fields,
                requested_interface=requested_interface,
                requested_vlan=new_vlan,
                requested_description=new_description
            )

        # Refresh updated fields
        updated_fields = get_interface_details(host, interface)
        updated_fields["interface"] = interface

        show_cmd = f"show run interface {interface}"
        show_result = target.run(task=netmiko_send_command, command_string=show_cmd)
        show_output = list(show_result.values())[0].result

        success_message = (
            f"Successfully changed VLAN on {host} interface {interface_short} "
            f"from {current_vlan} to {new_vlan}."
        )
        if new_description:
            success_message += f"<br>New description: <b>{new_description}</b>"
        success_message += (
            f"<br><b>Config output:</b><br><pre>{task.result}</pre>"
            f"<b>Verification output:</b><br><pre>{show_output}</pre>"
        )

        return render_template(
            "index.html",
            fields=updated_fields,
            success_message=success_message,
            requested_interface=requested_interface,
            requested_vlan=new_vlan
        )

    except Exception as e:
        app.logger.error(f"VLAN change error: {str(e)}")
        flash(f"VLAN change failed: {str(e)}", "error")
        return render_template(
            "index.html",
            fields=fields,
            requested_interface=requested_interface,
            requested_vlan=new_vlan,
            requested_description=new_description
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



#
if __name__ == "__main__":
    app.run(debug=True, port=5008)




#flask run --host=0.0.0.0 --port=5000

#docker build -t flask-app .
#docker run -p 5000:5000 flask-app
