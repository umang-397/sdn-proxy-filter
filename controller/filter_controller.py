
import os
import socket
import threading

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls
)
from ryu.ofproto import ofproto_v1_3


class ProxyFilterController(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ProxyFilterController, self).__init__(
            *args, **kwargs
        )

        self.datapaths = {}
        self.dynamic_drops = set()

        self.socket_path = "/tmp/sdn_ctrl.sock"

        self.logger.info("Proxy Filter Controller initialized")

        threading.Thread(
        target=self.socket_server,
        daemon=True
        ).start()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath

        self.datapaths[datapath.id] = datapath

        self.logger.info(
            "Switch connected: %s",
            datapath.id
        )

        self.install_default_rules(datapath)

    def add_flow(self, datapath, priority, match, actions=None):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        instructions = []

        if actions:
            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    actions
                )
            ]

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )

        datapath.send_msg(flow_mod)


    def install_default_rules(self, datapath):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Allow ARP so hosts can discover each other's MAC addresses
        match = parser.OFPMatch(
            eth_type=0x0806
        )

        actions = [
            parser.OFPActionOutput(ofproto.OFPP_NORMAL)
        ]

        self.add_flow(datapath, 100, match, actions)

        # Define permitted communication pairs
        allowed_pairs = [
            # Clients -> Proxy
            ("10.0.0.1", "10.0.0.10"),
            ("10.0.0.2", "10.0.0.10"),
            ("10.0.0.3", "10.0.0.10"),

            # Proxy -> Clients
            ("10.0.0.10", "10.0.0.1"),
            ("10.0.0.10", "10.0.0.2"),
            ("10.0.0.10", "10.0.0.3"),

            # Proxy -> Services
            ("10.0.0.10", "10.0.0.21"),
            ("10.0.0.10", "10.0.0.22"),

            # Services -> Proxy
            ("10.0.0.21", "10.0.0.10"),
            ("10.0.0.22", "10.0.0.10")
        ]

        for src, dst in allowed_pairs:
            match = parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src=src,
                ipv4_dst=dst
            )

            actions = [
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]

            self.add_flow(
                datapath,
                100,
                match,
                actions
            )

        # Drop all other traffic by default
        match = parser.OFPMatch()

        self.add_flow(
            datapath,
            0,
            match,
            []
        )

        self.logger.info("Default network rules installed")


    def add_drop_rule(self, datapath, src, dst):
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src=src,
            ipv4_dst=dst
        )

        self.add_flow(
            datapath,
            200,
            match,
            []
        )

        self.dynamic_drops.add((src, dst))

        self.logger.info(
            "DROP rule installed: %s -> %s",
            src,
            dst
        )

    def remove_drop_rule(self, datapath, src, dst):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src=src,
            ipv4_dst=dst
        )

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=200,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match
        )

        datapath.send_msg(flow_mod)

        self.dynamic_drops.discard((src, dst))

        self.logger.info(
            "DROP rule removed: %s -> %s",
            src,
            dst
        )


    def socket_server(self):
        # Remove an old socket file if one exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        server = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM
        )

        server.bind(self.socket_path)
        server.listen(5)

        self.logger.info(
            "Controller socket listening at %s",
            self.socket_path
        )

        while True:
            conn, _ = server.accept()

            try:
                command = conn.recv(1024).decode().strip()
                response = self.process_command(command)
                conn.sendall((response + "\n").encode())

            except Exception as e:
                self.logger.error("Socket error: %s", e)
                conn.sendall(("ERR " + str(e) + "\n").encode())

            finally:
                conn.close()

    def process_command(self, command):
        parts = command.split()

        if len(parts) != 3:
            return "ERR invalid command format"

        action, src, dst = parts

        if action == "DROP":
            for datapath in self.datapaths.values():
                self.add_drop_rule(datapath, src, dst)

            return "OK DROP installed"

        elif action == "ALLOW":
            for datapath in self.datapaths.values():
                self.remove_drop_rule(datapath, src, dst)

            return "OK DROP removed"

        else:
            return "ERR unknown command"
