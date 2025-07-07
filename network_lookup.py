from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get

nr = InitNornir(config_file="config.yaml")

INTERFACE_MAP = {
    "Gi": "GigabitEthernet",
    "Fa": "FastEthernet",
    "Te": "TenGigabitEthernet",
    "Vl": "Vlan",
    "Eth": "Ethernet"
}

def expand_interface(short_name):
    for short, long in INTERFACE_MAP.items():
        if short_name.startswith(short):
            return short_name.replace(short, long, 1)
    return short_name

def get_interface_vlan_from_vlans(interface, vlan_info):
    for vlan_id, vlan_data in vlan_info.items():
        if interface in vlan_data.get("interfaces", []):
            return str(vlan_id)
    return ""

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
    filtered = nr.filter(name=host)
    result = filtered.run(
        task=napalm_get,
        getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"]
    )
    result_values = list(result.values())
    if not result_values:
        return {
            "host": host,
            "interface": interface,
            "mac_address": "",
            "vlan": "",
            "available_vlans": [],
            "available_interfaces": [],
            "description": "",
            "snmp_location": "",
            "error": f"No Nornir result for host '{host}'."
        }
    task_result = result_values[0].result
    interfaces = task_result.get("interfaces", {})
    vlan_info = task_result.get("get_vlans", {})
    mac_entry = next(
        (entry for entry in task_result.get("mac_address_table", [])
         if entry["interface"] == interface),
        None
    )
    iface_details = interfaces.get(interface, {})
    # Use VLAN mapping from get_vlans()
    vlan = get_interface_vlan_from_vlans(interface, vlan_info)
    return {
        "host": host,
        "interface": interface,
        "mac_address": mac_entry["mac"] if mac_entry else "",
        "vlan": vlan,
        "available_vlans": [str(v) for v in vlan_info.keys()],
        "available_interfaces": list(interfaces.keys()),
        "description": iface_details.get("description", ""),
        "snmp_location": task_result.get("get_snmp_information", {}).get("location", "")
    }




def find_mac(mac_address):
    mac_search = mac_address.lower()
    for host, task_result in nr.run(
        task=napalm_get,
        getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"]
    ).items():
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
    return {}

def find_port_description(search_term):
    matches = []
    for host, task_result in nr.run(task=napalm_get, getters=["interfaces"]).items():
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
    return matches

def find_host(hostname):
    if hostname not in nr.inventory.hosts:
        return {}
    result = nr.filter(name=hostname).run(
        task=napalm_get,
        getters=["interfaces", "get_snmp_information", "get_vlans"]
    )
    result_values = list(result.values())
    if not result_values:
        return {}
    task_result = result_values[0].result
    if not isinstance(task_result, dict):
        return {}
    return {
        "host": hostname,
        "available_vlans": list(task_result.get("get_vlans", {}).keys()),
        "available_interfaces": list(task_result.get("interfaces", {}).keys()),
        "snmp_location": task_result.get("get_snmp_information", {}).get("location", "")
    }
