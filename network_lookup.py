from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command

nr = InitNornir(config_file="config.yaml")

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

def find_mac(mac_address):
    mac_address_search = mac_address.lower()
    result = nr.run(task=napalm_get, getters=["mac_address_table", "interfaces", "get_snmp_information", "get_vlans"])
    
    for host, task_result in result.items():
        mac_table = task_result.result.get("mac_address_table", [])
        interfaces = task_result.result.get("interfaces", {})
        snmp_info = task_result.result.get("get_snmp_information", {})
        vlan_info = task_result.result.get("get_vlans", {})
        snmp_location = snmp_info.get("location", "")

        available_interfaces = list(interfaces.keys())

        matches = [entry for entry in mac_table if mac_address_search in entry["mac"].lower()]
        if matches:
            short_name = matches[0]['interface']
            long_name = expand_interface(short_name)
            description = interfaces.get(long_name, {}).get('description', '')
            vlan = matches[0].get('vlan', '')
            available_vlans = list(vlan_info.keys())
        
        # Return BOTH short and long interface names
        return {
            "host": host,
            "interface": short_name,  # Keep short name for display consistency
            "interface_long": long_name,  # Add long name for backend
            "mac_address": mac_address,
            "vlan": vlan,
            "available_vlans": available_vlans,
            "description": description,
            "snmp_location": snmp_location,
            "available_interfaces": available_interfaces  # ADD THIS LINE
        }
    return {}

def find_port_description(description_search):
    """
    Search for interfaces with matching descriptions across all devices.
    Returns a list of dicts: {host, interface, description}
    """
    result = nr.run(task=napalm_get, getters=["get_interfaces"])
    matches = []
    for host, task_result in result.items():
        if not task_result.failed:
            interfaces = task_result.result.get("get_interfaces", {})
            for iface, data in interfaces.items():
                desc = data.get('description', '')
                if desc and description_search.lower() in desc.lower():
                    matches.append({
                        "host": host,
                        "interface": iface,
                        "description": desc
                    })
    return matches

def get_full_details_for_interface(host, interface):
    """
    Given a host and interface, returns (mac_address, vlan, snmp_location).
    """
    result = nr.filter(name=host).run(task=napalm_get, getters=["mac_address_table", "interfaces", "get_snmp_information"])
    mac_address = ""
    vlan = ""
    snmp_location = ""
    for _, task_result in result.items():
        mac_table = task_result.result.get("mac_address_table", [])
        snmp_info = task_result.result.get("get_snmp_information", {})
        snmp_location = snmp_info.get("location", "")
        for entry in mac_table:
            if entry["interface"] == interface:
                mac_address = entry["mac"]
                vlan = entry.get("vlan", "")
                break
    return mac_address, vlan, snmp_location
