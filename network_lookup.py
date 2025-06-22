# network_lookup.py

from nornir import InitNornir
from nornir_napalm.plugins.tasks import napalm_get, napalm_configure
from nornir_utils.plugins.functions import print_result

# Initialize Nornir only once
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

def mac_to_dotted(mac):
    mac = mac.lower().replace(':', '').replace('-', '').replace('.', '')
    mac = mac.zfill(12)
    return f"{mac[0:4]}.{mac[4:8]}.{mac[8:12]}"

def get_device_interfaces(hostname):
    result = nr.filter(name=hostname).run(task=napalm_get, getters=["get_interfaces"])
    interfaces = []
    for host, task_result in result.items():
        interfaces = list(task_result.result.get("get_interfaces", {}).keys())
    return interfaces

def get_device_vlans(hostname):
    result = nr.filter(name=hostname).run(task=napalm_get, getters=["get_vlans"])
    vlans = []
    for host, task_result in result.items():
        vlan_dict = task_result.result.get("get_vlans", {})
        vlans = [str(vlan_id) for vlan_id in vlan_dict.keys()]
    return vlans

def find_ip_on_router(task, mac_address):
    mac_dotted = mac_to_dotted(mac_address)
    r = task.run(task=napalm_get, getters=["get_arp_table"])
    arp_table = r.result.get("get_arp_table", [])
    for entry in arp_table:
        if entry["mac"].lower() == mac_dotted:
            return entry["ip"]
    return "Not found"

def find_mac(mac_address):
    mac_address_search = mac_address.lower()
    result = nr.run(task=napalm_get, getters=["mac_address_table", "interfaces", "get_snmp_information"])
    for host, task_result in result.items():
        mac_table = task_result.result.get("mac_address_table", [])
        interfaces = task_result.result.get("interfaces", {})
        snmp_info = task_result.result.get("get_snmp_information", {})
        snmp_location = snmp_info.get("location", "n/a")
        matches = [entry for entry in mac_table if mac_address_search in entry["mac"].lower()]
        if matches:
            short_name = matches[0]['interface']
            long_name = expand_interface(short_name)
            description = interfaces.get(long_name, {}).get('description', 'n/a')
            router_name = task_result.host.data.get("router", "Unknown")
            # Get available interfaces and VLANs for dropdowns
            interfaces_list = get_device_interfaces(host)
            vlans_list = get_device_vlans(host)
            # Lookup IP on router
            router_nr = nr.filter(name=router_name)
            arp_result = router_nr.run(task=find_ip_on_router, mac_address=mac_address)
            ip_address = "Not found"
            for _, res in arp_result.items():
                ip_address = res.result
            return {
                "host": host,
                "interface": short_name,
                "long_interface": long_name,
                "vlan": matches[0].get('vlan', 'n/a'),
                "description": description,
                "router": router_name,
                "ip_address": ip_address,
                "snmp_location": snmp_location,
                "interfaces_list": interfaces_list,
                "vlans_list": vlans_list,
            }
    return {}

def change_vlan_on_interface(hostname, interface, vlan_id):
    """
    Change the VLAN of the given interface on the given device.
    This is a template for Cisco IOS-like devices. Adjust as needed for your environment.
    """
    config_commands = [
        f"configure terminal",
        f"interface {interface}",
        f"switchport access vlan {vlan_id}",
        "exit"
    ]
    result = nr.filter(name=hostname).run(
        task=napalm_configure,
        configuration="\n".join(config_commands)
    )
    # Check for errors or success
    for host, task_result in result.items():
        if task_result.failed:
            return False, f"Failed to change VLAN: {task_result.exception}"
    return True, f"Changed {interface} to VLAN {vlan_id} on {hostname}"

