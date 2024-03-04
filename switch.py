#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

root_bridge_id = 0

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bpdu(root_id=0, own_id=0, cost=0):
    dest_mac = b'\x01\x80\xc2\00\00\00'
    source_mac = get_switch_mac()
    return struct.pack("6s6siii", dest_mac, source_mac, root_id, own_id, cost)


def send_bdpu_every_sec(own_bridge_id):
    global root_bridge_ID
    while True:
        # TODO Send BDPU every second if necessary
        if root_bridge_ID == own_bridge_id:
            for i in range(0,4):
                data = create_bpdu(own_bridge_id, own_bridge_id, 0)
                send_to_link(i, data, 24)
        time.sleep(1)

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]

    global root_bridge_ID

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    # Printing interface names

    mac_table = dict()
    vlan = dict()
    prio = 0

    if switch_id == "0":
        prio = 14
        vlan["r-0"] = 1
        vlan["r-1"] = 2  
        vlan["rr-0-1"] = 0
        vlan["rr-0-2"] = 0  
    elif switch_id == "1":
        prio = 10
        vlan["r-0"] = 1
        vlan["r-1"] = 1
        vlan["rr-0-1"] = 0
        vlan["rr-1-2"] = 0
    elif switch_id == "2":
        prio = 19
        vlan["r-0"] = 2
        vlan["r-1"] = 1
        vlan["rr-1-2"] = 0
        vlan["rr-0-2"] = 0

    port_state = dict()
    port_type = dict()

    # STATE :                              
    # BLOCKING = 0                              
    # LISTENING = 1
    for i in interfaces:
        if vlan[get_interface_name(i)] == 0: # verific daca interfata este trunk
            port_state[get_interface_name(i)] = 0 # setez starea tuturor porturilor trunk pe Blocking
        else:
            port_state[get_interface_name(i)] = 1 # celelate portuei (acces) sunt setate pe Listening

    # switch-ul crede ca este root bridge
    own_bridge_ID =  prio
    root_bridge_ID = own_bridge_ID
    root_path_cost = 0

    # TYPE : BP = 0, DP = 1, RP = 2
    # setam toate porturile pe designated
    if own_bridge_ID == root_bridge_ID:
        for i in interfaces:
            port_type[get_interface_name(i)] = 1
            port_state[get_interface_name(i)] = 1
    

    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec, args=(own_bridge_ID,))
    t.start()

    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)
        mac_address = "01:80:c2:00:00:00"
     #   print(dest_mac, " ", type(dest_mac))
     #   print(bytes.fromhex(mac_address.replace(":", "")))

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        print("am primit pe interfata ", get_interface_name(interface), " de lungime ", length, " de la ", src_mac, " catre ", dest_mac)
        for i in interfaces:
            print("port state = ", port_state[get_interface_name(i)], " port type ", port_type[get_interface_name(i)])

     #   print(get_switch_mac())

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]

        
        # TODO: Implement VLAN support
        mac_table[src_mac] = interface
        if dest_mac == "ff:ff:ff:ff:ff:ff":
            if port_state[get_interface_name(interface)] != 0: # port is not blocking 
                print("BROADCAST")
                if vlan_id == -1: # vine de pe ACCES
                    for i in interfaces:
                        if i != interface:
                            if vlan[get_interface_name(i)] == 0: # trimit pe TRUNK
                                send_to_link(i, data[0:12] + create_vlan_tag(vlan[get_interface_name(interface)]) + data[12:], length + 4)
                            elif vlan[get_interface_name(interface)] == vlan[get_interface_name(i)]: # trimit tot pe ACCES
                                send_to_link(i, data, length)
                else: # vine de pe TRUNK
                    for i in interfaces:
                        if i != interface:
                            if vlan[get_interface_name(i)] == 0: # trimit tot pe TRUNK
                                send_to_link(i, data, length) # trimit pachetul identic
                            else: # trimit pe ACCES
                                if vlan[get_interface_name(i)] == vlan_id:
                                    send_to_link(i, data[0:12] + data[16:], length - 4) 
        elif dest_mac != "01:80:c2:00:00:00": # unicast
            if port_state[get_interface_name(interface)] != 0: # port is not blocking
                print("unicast")

                if vlan_id == -1: # vine de pe ACCES

                    if dest_mac in mac_table: # nu trebuie sa fac broadcast

                        new_interface = mac_table[dest_mac] # interfata de pe care se va face forward
                        if vlan[get_interface_name(new_interface)] == 0: # new_interface este TRUNK
                
                            send_to_link(new_interface, data[0:12] + create_vlan_tag(vlan[get_interface_name(interface)]) + data[12:], length + 4)
                        elif vlan[get_interface_name(new_interface)] == vlan[get_interface_name(interface)]: # new_interface este ACCES
                        
                            send_to_link(new_interface, data, length) # trimit identic
                    else: # trebuie sa fac broadcast
                
                        for i in interfaces:
                            if i != interface:
                                if vlan[get_interface_name(i)] == 0: # trimit pe TRUNK
                                
                                    send_to_link(i, data[0:12] + create_vlan_tag(vlan[get_interface_name(interface)]) + data[12:], length + 4)
                                else: # trimit tot pe ACCES
                                    if vlan[get_interface_name(interface)] == vlan[get_interface_name(i)]:
                                
                                        send_to_link(i, data, length)
                else: # vine de pe TRUNK
                
                    if dest_mac in mac_table: # se afla in tabela
                        new_interface = mac_table[dest_mac]
                    
                        if vlan[get_interface_name(new_interface)] == 0: # trimit pe TRUNK
                        
                            send_to_link(new_interface, data, length) # trimit identic
                        elif vlan_id == vlan[get_interface_name(new_interface)]: # trimit pe ACCES
                        
                            send_to_link(new_interface, data[0:12] + data[16:], length - 4)
                    else: # nu se afla in tabela => facem broadcast
                    
                        for i in interfaces:
                            if i != interface:
                                if vlan[get_interface_name(i)] == 0: # trimit tot pe TRUNK
                                
                                    send_to_link(i, data, length)
                                else: # trimit pe ACCES
                                    if vlan_id == vlan[get_interface_name(i)]:
                                    
                                        send_to_link(i, data[0:12] + data[16:], length-4)
                
        else: # port is blocking
            if dest_mac == "01:80:c2:00:00:00": # check if bpdu
                print("bpdu")
                received_data = struct.unpack("6s6siii", data)
                bpdu_root_ID = received_data[2]
                bpdu_sender_ID = received_data[3]
                bpdu_sender_path_cost = received_data[4]
                print("bpdu_root_id = ", bpdu_root_ID, " bpdu_sender_id = ", bpdu_sender_ID, " cost = ", bpdu_sender_path_cost)
                previous_root = own_bridge_ID == root_bridge_ID
                if bpdu_root_ID < root_bridge_ID:
                    root_bridge_ID = bpdu_root_ID
                    root_path_cost = bpdu_sender_path_cost + 10
                    port_type[get_interface_name(interface)] = 2 # setez portul care a primit acest bpdu ca root

                    if previous_root:
                        for i in interfaces:
                            if i != interface:
                                if vlan[get_interface_name(i)] == 0: # doar interfetele trunk
                                    if port_type[get_interface_name(i)] != 2: # not root
                                        port_state[get_interface_name(i)] = 0 # set to blocking
                    
                    if port_state[get_interface_name(interface)] == 0: # if root port state is blocking
                        port_state[get_interface_name(interface)] = 1 # set to listening
                    
                    new_bpdu = create_bpdu(bpdu_root_ID, own_bridge_ID, root_path_cost)
                    for i in interfaces:
                        if i != interface and vlan[get_interface_name(i)] == 0:
                            send_to_link(i, new_bpdu, 24)

                elif bpdu_root_ID == root_bridge_ID:
                    if port_type[get_interface_name(interface)] == 2 and bpdu_sender_path_cost + 10 < root_path_cost:
                        root_path_cost = bpdu_sender_path_cost + 10

                    else:
                        if bpdu_sender_path_cost > root_path_cost:
                            if port_type[get_interface_name(interface)] != 1: # if not designated
                                port_type[get_interface_name(interface)] = 1
                                port_state[get_interface_name(interface)] = 1 # set to listening

                elif bpdu_sender_ID == own_bridge_ID:
                    port_state[get_interface_name(interface)] = 0 # set to blocking

                if root_bridge_ID == own_bridge_ID:
                    for i in interfaces:
                        if vlan[get_interface_name(i)] == 0:
                            port_type[get_interface_name(i)] = 1 # set to designated


        # TODO: Implement STP support


        # data is of type bytes.
        # send_to_link(i, data, length)

if __name__ == "__main__":
    main()