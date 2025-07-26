import logging
from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command
import re

nr = InitNornir(config_file="config.yaml")

logging.basicConfig(
    filename="network_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

INTERFACE_MAP = {
    "Gi": "GigabitEthernet",
    "Fa": "FastEthernet",
    "Te": "TenGigabitEthernet",
    "Vl": "Vlan",
    "Eth": "Ethernet"
}

def expand_interface(short_name):
    if any(short_name.startswith(long) for long in INTERFACE_MAP.values()):
        return short_name
    for short, long in INTERFACE_MAP.items():
        if short_name.lower().startswith(short.lower()):
            return short_name.replace(short, long, 1)
    return short_name

def get_interface_vlan_from_vlans(interface, vlan_info):
    for vlan_id, vlan_data in vlan_info.items():
        if interface in vlan_data.get("interfaces", []):
            return str(vlan_id)
    return ""

def find_mac(mac_address):
    logging.debug(f"Searching for MAC address: {mac_address}")
    mac_search = mac_address.lower()
    try:
        results = nr.run(
            task=napalm_get,
            getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"]
        )
        for host, task_result in results.items():
            result_data = task_result.result
            if not isinstance(result_data, dict):
                continue

            mac_table = result_data.get("mac_address_table", [])
            matches = [entry for entry in mac_table if mac_search in entry["mac"].lower()]
            if matches:
                interface_short = matches[0]['interface']
                interface_long = expand_interface(interface_short)
                interfaces = result_data.get("interfaces", {})
                return {
                    "host": host,
                    "interface": interface_long,
                    "mac_address": mac_address,
                    "vlan": matches[0].get("vlan", ""),
                    "available_vlans": list(result_data.get("get_vlans", {}).keys()),
                    "available_interfaces": list(interfaces.keys()),
                    "description": interfaces.get(interface_long, {}).get("description", ""),
                    "snmp_location": result_data.get("get_snmp_information", {}).get("location", "")
                }
    except Exception as e:
        logging.exception("Error during MAC address search")
    return {}

def find_port_description(search_term):
    logging.debug(f"Searching port descriptions for term: {search_term}")
    matches = []
    try:
        results = nr.run(task=napalm_get, getters=["interfaces"])
        for host, task_result in results.items():
            result_data = task_result.result
            if not isinstance(result_data, dict):
                continue
            interfaces = result_data.get("interfaces", {})
            for iface, data in interfaces.items():
                if search_term.lower() in data.get('description', '').lower():
                    matches.append({
                        "host": host,
                        "interface": iface,
                        "description": data.get('description', '')
                    })
    except Exception as e:
        logging.exception("Error during port description search")
    return matches

def find_host(hostname):
    logging.debug(f"Looking up host: {hostname}")
    if hostname not in nr.inventory.hosts:
        logging.warning(f"Host not found in inventory: {hostname}")
        return {}

    try:
        filtered = nr.filter(name=hostname)
        result = filtered.run(
            task=napalm_get,
            getters=["interfaces", "get_snmp_information", "get_vlans"]
        )
        task_result = list(result.values())[0].result

        interfaces = task_result.get("interfaces", {})
        vlan_info = task_result.get("get_vlans", {})

        switchport_output = filtered.run(
            task=netmiko_send_command,
            command_string="show interfaces switchport"
        )
        switchport_raw = list(switchport_output.values())[0].result

        valid_interfaces = []
        current_iface = None
        mode = None

        for line in switchport_raw.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                current_iface = line.split("Name:")[1].strip()
                mode = None
            elif "Operational Mode:" in line and current_iface:
                mode = line.split("Operational Mode:")[1].strip().lower()
                if current_iface.lower().startswith("po") or mode == "trunk":
                    logging.debug(f"Skipping interface {current_iface} (trunk or port-channel)")
                    current_iface = None
                    continue
                valid_interfaces.append(current_iface)
                current_iface = None

        return {
            "host": hostname,
            "available_vlans": list(vlan_info.keys()),
            "available_interfaces": valid_interfaces,
            "snmp_location": task_result.get("get_snmp_information", {}).get("location", "")
        }

    except Exception as e:
        logging.exception(f"Error looking up host: {hostname}")
        return {}

def get_interface_details(host, interface):
    logging.debug(f"Getting interface details for {host} - {interface}")
    filtered = nr.filter(name=host)

    try:
        result = filtered.run(
            task=napalm_get,
            getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"]
        )
        task_result = list(result.values())[0].result

        interfaces = task_result.get("interfaces", {})
        vlan_info = task_result.get("get_vlans", {})

        switchport_output = filtered.run(
            task=netmiko_send_command,
            command_string="show interfaces switchport"
        )
        switchport_raw = list(switchport_output.values())[0].result

        valid_interfaces = []
        current_iface = None
        mode = None

        for line in switchport_raw.splitlines():
            line = line.strip()
            if line.startswith("Name:"):
                current_iface = line.split("Name:")[1].strip()
                mode = None
            elif "Operational Mode:" in line and current_iface:
                mode = line.split("Operational Mode:")[1].strip().lower()
                if current_iface.lower().startswith("po") or mode == "trunk":
                    logging.debug(f"Skipping interface {current_iface} (trunk or port-channel)")
                    current_iface = None
                    continue
                valid_interfaces.append(current_iface)
                current_iface = None

        # Try to match MAC address based on interface
        mac_entry = None
        interface_normalized = interface.replace("GigabitEthernet", "Gi").lower()

        for entry in task_result.get("mac_address_table", []):
            entry_iface = expand_interface(entry["interface"].strip())
            entry_normalized = entry_iface.replace("GigabitEthernet", "Gi").lower()

            if entry_normalized == interface_normalized:
                mac_entry = entry
                logging.debug(f"Matched MAC {mac_entry['mac']} to interface {interface}")
                break

        if not mac_entry:
            logging.debug(f"No MAC found for interface {interface} on host {host}")

        iface_details = interfaces.get(interface, {})
        vlan = get_interface_vlan_from_vlans(interface, vlan_info)

        return {
            "host": host,
            "interface": interface,
            "mac_address": mac_entry["mac"] if mac_entry else "",
            "vlan": vlan,
            "available_vlans": [str(v) for v in vlan_info.keys()],
            "available_interfaces": valid_interfaces,
            "description": iface_details.get("description", ""),
            "snmp_location": task_result.get("get_snmp_information", {}).get("location", "")
        }
    
    except Exception as e:
        logging.exception(f"Failed to get interface details for {host} - {interface}")
        return {
            "host": host,
            "interface": interface,
            "mac_address": "",
            "vlan": "",
            "available_vlans": [],
            "available_interfaces": [],
            "description": "",
            "snmp_location": "",
            "error": str(e)
        }