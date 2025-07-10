import logging
from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get
import re
from nornir_netmiko.tasks import netmiko_send_config, netmiko_send_command
nr = InitNornir(config_file="config.yaml")
# Set up logging
logging.basicConfig(
    filename="network_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

nr = InitNornir(config_file="config.yaml")

INTERFACE_MAP = {
    "Gi": "GigabitEthernet",
    "Fa": "FastEthernet",
    "Te": "TenGigabitEthernet",
    "Vl": "Vlan",
    "Eth": "Ethernet"
}


def expand_interface(short_name):
    # Avoid expanding if already expanded
    if any(short_name.startswith(long) for long in INTERFACE_MAP.values()):
        return short_name  # already expanded

    for short, long in INTERFACE_MAP.items():
        if short_name.lower().startswith(short.lower()):
            return short_name.replace(short, long, 1)

    return short_name




def get_interface_vlan_from_vlans(interface, vlan_info):
    """
    Given an interface name and the get_vlans() result,
    return the VLAN ID (as string) that includes this interface.
    """
    for vlan_id, vlan_data in vlan_info.items():
        if interface in vlan_data.get("interfaces", []):
            return str(vlan_id)
    return ""


def get_interface_details(host, interface):
    logging.debug(f"Getting interface details for {host} - {interface}")
    filtered = nr.filter(name=host)

    try:
        # Get data from both Napalm and Netmiko
        result = filtered.run(
            task=napalm_get,
            getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"]
        )

        result_values = list(result.values())
        if not result_values:
            logging.error(f"No result returned for host: {host}")
            raise ValueError("Empty Nornir result")

        task_result = result_values[0].result
        if not isinstance(task_result, dict):
            logging.error(f"Unexpected task_result type: {type(task_result)} - {task_result}")
            raise TypeError("task_result is not a dictionary")

        interfaces = task_result.get("interfaces", {})
        vlan_info = task_result.get("get_vlans", {})

        # Run Netmiko show interfaces switchport to find trunks
        switchport_output = filtered.run(
            task=netmiko_send_command,
            command_string="show interfaces switchport"
        )
        switchport_raw = list(switchport_output.values())[0].result

        # Parse out trunk interfaces
        trunk_interfaces = []
        current_iface = None
        for line in switchport_raw.splitlines():
            if line.startswith("Name:"):
                current_iface = line.split("Name:")[1].strip()
            elif "Administrative Mode:" in line and "trunk" in line.lower():
                if current_iface:
                    trunk_interfaces.append(current_iface)

        # Filter interfaces to exclude trunks
        available_interfaces = [
            iface for iface in interfaces.keys()
            if iface not in trunk_interfaces
        ]

        mac_entry = next(
            (entry for entry in task_result.get("mac_address_table", [])
             if entry["interface"] == interface),
            None
        )

        iface_details = interfaces.get(interface, {})
        vlan = get_interface_vlan_from_vlans(interface, vlan_info)

        return {
            "host": host,
            "interface": interface,
            "mac_address": mac_entry["mac"] if mac_entry else "",
            "vlan": vlan,
            "available_vlans": [str(v) for v in vlan_info.keys()],
            "available_interfaces": available_interfaces,
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
                logging.warning(f"Unexpected result type on {host}: {type(result_data)}")
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
        result_values = list(result.values())
        if not result_values:
            logging.error(f"No data returned for host: {hostname}")
            return {}

        task_result = result_values[0].result
        if not isinstance(task_result, dict):
            logging.error(f"Unexpected result format for host {hostname}: {type(task_result)}")
            return {}

        interfaces = task_result.get("interfaces", {})
        vlan_info = task_result.get("get_vlans", {})

        # Run Netmiko to find trunk interfaces
        switchport_output = filtered.run(
            task=netmiko_send_command,
            command_string="show interfaces switchport"
        )
        switchport_raw = list(switchport_output.values())[0].result

        trunk_interfaces = []
        current_iface = None
        for line in switchport_raw.splitlines():
            if line.startswith("Name:"):
                current_iface = line.split("Name:")[1].strip()
            elif "Administrative Mode:" in line and "trunk" in line.lower():
                if current_iface:
                    trunk_interfaces.append(current_iface)

        available_interfaces = [
            iface for iface in interfaces.keys()
            if iface not in trunk_interfaces
        ]

        return {
            "host": hostname,
            "available_vlans": list(vlan_info.keys()),
            "available_interfaces": available_interfaces,
            "snmp_location": task_result.get("get_snmp_information", {}).get("location", "")
        }

    except Exception as e:
        logging.exception(f"Error looking up host: {hostname}")
        return {}
