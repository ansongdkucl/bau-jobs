from flask import Flask, render_template, request
import logging
from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get

app = Flask(__name__)

# Initialize Nornir once
try:
    nr = InitNornir(config_file="config.yaml")
except Exception as e:
    logging.error(f"Failed to initialize Nornir: {e}")
    nr = None

def expand_interface(short_name):
    mapping = {
        "Gi": "GigabitEthernet",
        "Fa": "FastEthernet",
        "Te": "TenGigabitEthernet",
        "Vl": "Vlan",
        "Eth": "Ethernet",
    }
    for short, long in mapping.items():
        if short_name.startswith(short):
            return short_name.replace(short, long, 1)
    return short_name

def mac_to_dotted(mac):
    mac = mac.lower().replace(':', '').replace('-', '').replace('.', '')
    mac = mac.zfill(12)
    return f"{mac[0:4]}.{mac[4:8]}.{mac[8:12]}"

def find_ip_on_router(task, mac_address):
    mac_dotted = mac_to_dotted(mac_address)
    r = task.run(task=napalm_get, getters=["get_arp_table"])
    arp_table = r.result.get("get_arp_table", [])
    for entry in arp_table:
        if entry["mac"].lower() == mac_dotted:
            return entry["ip"]
    return "Not found"

def find_mac(task, mac_address):
    r = task.run(task=napalm_get, getters=["mac_address_table", "interfaces", "get_snmp_information"])
    mac_table = r.result.get("mac_address_table", [])
    interfaces = r.result.get("interfaces", {})
    snmp_info = r.result.get("get_snmp_information", {})
    snmp_location = snmp_info.get("location", "n/a")
    
    matches = [entry for entry in mac_table if mac_address.lower() in entry["mac"].lower()]
    if matches:
        short_name = matches[0]['interface']
        long_name = expand_interface(short_name)
        description = interfaces.get(long_name, {}).get('description', 'n/a')
        router_name = task.host.data.get("router", "Unknown")
        
        # Lookup IP on router
        router_nr = nr.filter(name=router_name)
        arp_result = router_nr.run(task=find_ip_on_router, mac_address=mac_address)
        ip_address = "Not found"
        for host, res in arp_result.items():
            ip_address = res.result
        
        return {
            "host": task.host.name,
            "interface": short_name,
            "long_interface": long_name,
            "vlan": matches[0].get('vlan', 'n/a'),
            "description": description,
            "router": router_name,
            "ip_address": ip_address,
            "snmp_location": snmp_location,
        }
    return {}

def lookup_mac(mac_address):
    if not nr:
        return {}
    try:
        result = nr.run(task=find_mac, mac_address=mac_address)
        for host, task_result in result.items():
            if task_result.result:
                return task_result.result
        return {}
    except Exception as e:
        logging.error(f"Lookup failed: {e}")
        return {}

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
        "snmp_location": ""
    }
    error = None

    if request.method == "POST":
        mac_address = request.form.get("mac_address", "").strip()
        fields["mac_address"] = mac_address
        if not mac_address:
            error = "Please enter a MAC address."
        else:
            result = lookup_mac(mac_address)
            if result:
                fields.update(result)
            else:
                error = "MAC address not found."

    return render_template("index.html", fields=fields, error=error)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
